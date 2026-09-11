-- 0006 — 지역 태그 조회수를 24시간 굴림으로 · 가입(승인)일 (2026-09-11 지시)
--
-- 1. place_view: 날 단위(day) → **시간 단위(hour)**.
--    지시: "24시간 동안 보는 사람 누적 (1시간마다 옛 한 시간 누적을 삭제)".
--    한 시간 칸에 쌓고, bump 때마다 24시간 지난 칸을 지운다 — 표는 태그 수 ×
--    24 를 넘지 않는다 (#43 '오래된 날짜 지우기' 도 이것으로 끝).
--    옛 day 칸은 버린다 — 오늘·주간 수는 더 이상 쓰지 않는다.
-- 2. profile.approved_at: 승인된 날. 신청일(created_at)과 따로 적어 관리자
--    회원 목록이 '신청일 · 가입일' 을 둘 다 보인다.

-- ── 1. 24시간 조회수 ─────────────────────────────────────────────
drop function if exists public.place_view_stats(text[]);
drop table if exists public.place_view;

create table public.place_view (
  place_key text        not null,
  hour      timestamptz not null,
  n         bigint      not null default 0,
  primary key (place_key, hour)
);
create index place_view_hour_idx on public.place_view (hour);
alter table public.place_view enable row level security;
drop policy if exists place_view_select on public.place_view;
create policy place_view_select on public.place_view for select to authenticated using (true);

create or replace function public.bump_place_view(k text)
returns bigint language plpgsql security definer set search_path = public as $$
declare
  h timestamptz := date_trunc('hour', now());
  total bigint;
begin
  -- 열쇠 모양을 여기서 막는다. 화면이 보내는 것만 받는다.
  if k is null or k !~ '^[ugs]:[^\n\r\t]{1,60}$' then
    raise exception '지역 열쇠 모양이 아닙니다';
  end if;
  -- 24시간 지난 칸은 지운다. 표가 작아 매번 해도 싸다.
  delete from public.place_view where hour < now() - interval '24 hours';
  insert into public.place_view (place_key, hour, n) values (k, h, 1)
  on conflict (place_key, hour) do update set n = public.place_view.n + 1;
  select coalesce(sum(n), 0) into total from public.place_view
   where place_key = k and hour >= now() - interval '24 hours';
  return total;   -- 이 태그의 24시간 누적
end;
$$;
revoke all on function public.bump_place_view(text) from public, anon;
grant execute on function public.bump_place_view(text) to authenticated, service_role;

-- 보이는 태그의 24시간 누적을 한 번에. 호출자 권한(RLS select)으로 돈다.
create function public.place_view_stats(keys text[])
returns table (place_key text, n24 bigint)
language sql stable set search_path = public as $$
  select v.place_key, coalesce(sum(v.n), 0)::bigint
  from public.place_view v
  where v.place_key = any (keys[1:200])
    and v.hour >= now() - interval '24 hours'
  group by v.place_key;
$$;
revoke all on function public.place_view_stats(text[]) from public, anon;
grant execute on function public.place_view_stats(text[]) to authenticated, service_role;

-- ── 2. 가입(승인)일 ──────────────────────────────────────────────
alter table public.profile add column if not exists approved_at timestamptz;
update public.profile set approved_at = coalesce(approved_at, created_at) where status = 'approved';

create or replace function public.profile_stamp()
returns trigger language plpgsql as $$
begin
  if new.status = 'approved' and old.status is distinct from 'approved' then
    new.approved_at := now();
  end if;
  return new;
end;
$$;
revoke all on function public.profile_stamp() from public, anon, authenticated;
drop trigger if exists profile_stamp on public.profile;
create trigger profile_stamp before update of status on public.profile
  for each row execute function public.profile_stamp();
