-- 회원 등급 (2026-09-11 지시) — admin / A / B / C
--
--   admin  모든 권한. 등급 변경 권한 포함.
--   A      제한 없음 (프리미엄 포함). 결제 없이 열어 주는 계정.
--   B      유료 프리미엄 — 현재 가치·미래 가치 조회 가능. grade_until 이 있으면 그날까지.
--   C      무료 회원 — 프리미엄은 못 본다. 누르면 가입·결제 안내 (안내 문구는 미확정).
--
-- role(user/broker/admin) 은 그대로 둔다 — 중개사 여부는 등급과 다른 축이다.
-- 승인(status) 도 그대로다. 등급은 **승인된 사람 안에서** 무엇을 더 볼 수 있는가다.
--
-- 진짜 자물쇠는 여기(RLS·트리거·함수)다. 화면(app.js)의 가림은 편의다 —
-- 다만 현재 가치의 숫자 원천(valuation.json·표준지 조각)은 아직 정적 파일이라
-- 주소를 알면 받을 수 있다. 그것을 API 뒤로 옮기는 일이 다음 단계다
-- (docs/membership-grades.md).
--
-- 실행: Supabase 대시보드 → SQL Editor → 붙여넣기 → Run (또는 MCP apply_migration)

alter table public.profile
  add column if not exists grade text not null default 'C'
    check (grade in ('admin', 'A', 'B', 'C')),
  add column if not exists grade_until timestamptz,
  add column if not exists grade_note text;

-- 이미 관리자인 계정은 admin 등급으로.
update public.profile set grade = 'admin' where role = 'admin' and grade <> 'admin';

-- 누가 언제 누구의 등급을 바꿨나. 결제가 붙으면 여기에 결제 건이 이어진다.
create table if not exists public.grade_log (
  id           bigserial primary key,
  user_id      uuid not null references auth.users(id) on delete cascade,
  old_grade    text,
  new_grade    text not null,
  grade_until  timestamptz,
  note         text,
  changed_by   uuid references auth.users(id),
  changed_at   timestamptz not null default now()
);
alter table public.grade_log enable row level security;
drop policy if exists grade_log_admin_read on public.grade_log;
create policy grade_log_admin_read on public.grade_log
  for select using (public.is_admin());

-- 관리자 판정: role 이 admin 이거나 grade 가 admin.
create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.profile
    where id = auth.uid() and (role = 'admin' or grade = 'admin')
  );
$$;

-- 본인은 자기 등급·역할·상태를 못 바꾼다.
-- profile_self_write 정책이 본인 행의 update 를 통째로 허용해서, 그대로 두면
-- REST 로 status='approved' 나 grade='A' 를 스스로 쓸 수 있었다. 열 단위
-- 제한은 정책으로 못 하므로 트리거로 막는다. auth.uid() 가 없는 호출
-- (SQL Editor·service_role)은 통과한다 — 대시보드에서 손보는 길은 남긴다.
create or replace function public.profile_guard()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then
    return new;
  end if;
  if (new.grade is distinct from old.grade
      or new.grade_until is distinct from old.grade_until
      or new.grade_note is distinct from old.grade_note
      or new.role is distinct from old.role
      or new.status is distinct from old.status)
     and not public.is_admin() then
    raise exception '등급·역할·상태는 관리자만 바꿀 수 있습니다' using errcode = '42501';
  end if;
  return new;
end;
$$;
drop trigger if exists profile_guard on public.profile;
create trigger profile_guard before update on public.profile
  for each row execute function public.profile_guard();
-- 트리거 함수는 REST 로 부를 일이 없다 (advisor 0028/0029).
revoke all on function public.profile_guard() from public, anon, authenticated;

-- 관리자는 누구의 프로필이든 고칠 수 있다 (승인·등급).
drop policy if exists profile_admin_write on public.profile;
create policy profile_admin_write on public.profile
  for update using (public.is_admin()) with check (public.is_admin());

-- 등급 변경은 이 함수로만 — 기록이 남는다.
create or replace function public.set_grade(target uuid, new_grade text,
                                            until timestamptz default null, note text default null)
returns void language plpgsql security definer set search_path = public as $$
declare
  old_grade text;
begin
  if not public.is_admin() then
    raise exception '관리자만 등급을 바꿀 수 있습니다' using errcode = '42501';
  end if;
  if new_grade not in ('admin', 'A', 'B', 'C') then
    raise exception '등급은 admin·A·B·C 중 하나입니다';
  end if;
  select grade into old_grade from public.profile where id = target;
  if old_grade is null then
    raise exception '프로필이 없습니다';
  end if;
  update public.profile
     set grade = new_grade, grade_until = until, grade_note = note
   where id = target;
  insert into public.grade_log (user_id, old_grade, new_grade, grade_until, note, changed_by)
  values (target, old_grade, new_grade, until, note, auth.uid());
end;
$$;
revoke all on function public.set_grade(uuid, text, timestamptz, text) from public, anon;
grant execute on function public.set_grade(uuid, text, timestamptz, text) to authenticated;

-- 지금 로그인한 사람이 프리미엄을 볼 수 있는가. 서버가 자물쇠를 걸 때 이것을 쓴다.
create or replace function public.premium_ok()
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((
    select status = 'approved'
       and (grade in ('admin', 'A')
            or (grade = 'B' and (grade_until is null or grade_until > now())))
    from public.profile where id = auth.uid()
  ), false);
$$;
revoke all on function public.premium_ok() from public, anon;
grant execute on function public.premium_ok() to authenticated;
