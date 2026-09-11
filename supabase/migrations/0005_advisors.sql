-- 0005 — Supabase 어드바이저 정리 (2026-09-11)
--
-- 보안·성능 어드바이저가 든 것을 한 번에 정리한다. 무엇이 왜인지:
--
--   ERROR  profile_public 이 SECURITY DEFINER 뷰
--          → 뷰 대신 **표**(id·nickname)를 두고 트리거로 맞춘다. RLS + select
--            정책이 걸린 평범한 표라 우회가 없다. 화면(board.js)은 이름이 같아
--            그대로 읽는다.
--   WARN   handle_new_user · is_admin · is_approved 를 anon 이 부를 수 있다
--          → handle_new_user 는 auth 관리자만. is_admin·is_approved 는 authenticated
--            만. anon 이 못 부르려면 **anon 이 평가하는 정책에서 이 함수를 쓰지
--            말아야** 한다 — 그래서 정책마다 역할을 못 박고(to authenticated),
--            anon 에게는 매물 공개 읽기 하나만 따로 준다.
--   WARN   touch_updated_at 의 search_path 가 열려 있다 → 고정, 앱 역할은 못 부름.
--   WARN   정책이 auth.uid() 를 행마다 다시 평가한다 → (select auth.uid()) 로.
--   WARN   같은 역할·동작에 허용 정책이 둘 (comment_write ALL + comment_read 등)
--          → ALL 을 insert/update/delete 로 쪼개고, profile_admin_write 는
--            profile_write 가 이미 품고 있어 지운다.
--   INFO   외래키에 인덱스 없음 8곳 → 만든다.
--   INFO   appraisal_case·appraisal_factor 는 RLS 만 켜고 정책이 없다 → **그대로**
--          둔다. service key 로만 읽는 비공개 원장이라 정책이 없는 것이 맞다.
--
-- 남는 경고 (의도한 것):
--   authenticated 가 SECURITY DEFINER 함수(is_admin·is_approved·premium_ok·
--   set_grade·bump_place_view)를 부를 수 있다 — 정책과 화면이 쓰는 것이라
--   그래야 한다. 넷은 호출자 자신에 대해서만 답하고, set_grade 는 안에서
--   is_admin 을 다시 본다.
--   '유출된 비밀번호 보호 꺼짐' 은 대시보드 설정이다 (Authentication →
--   Providers → Email → Leaked password protection).
--
-- 덤: profile 에 profile_guard 트리거가 둘(profile_guard · profile_guard_trg)
-- 걸려 있었다. 같은 함수를 두 번 돌리던 것이라 하나를 지운다.

-- ── 1. 중복 트리거 ──────────────────────────────────────────────
drop trigger if exists profile_guard_trg on public.profile;

-- ── 2. 함수 권한 ────────────────────────────────────────────────
alter function public.touch_updated_at() set search_path = public;
revoke all on function public.touch_updated_at() from public, anon, authenticated;

revoke all on function public.handle_new_user() from public, anon, authenticated;
grant execute on function public.handle_new_user() to supabase_auth_admin;

revoke all on function public.is_admin() from public, anon;
grant execute on function public.is_admin() to authenticated, service_role;
revoke all on function public.is_approved() from public, anon;
grant execute on function public.is_approved() to authenticated, service_role;

-- ── 3. 정책 — 역할을 못 박고 auth.uid() 는 한 번만 ─────────────────
-- profile
drop policy if exists profile_self_read on public.profile;
drop policy if exists profile_write on public.profile;
drop policy if exists profile_admin_write on public.profile;
create policy profile_self_read on public.profile for select to authenticated
  using (id = (select auth.uid()) or (select public.is_admin()));
create policy profile_write on public.profile for update to authenticated
  using (id = (select auth.uid()) or (select public.is_admin()))
  with check (id = (select auth.uid()) or (select public.is_admin()));

-- broker
drop policy if exists broker_self_insert on public.broker;
drop policy if exists broker_self_read on public.broker;
drop policy if exists broker_self_update on public.broker;
create policy broker_self_insert on public.broker for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy broker_self_read on public.broker for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()));
create policy broker_self_update on public.broker for update to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()))
  with check ((select public.is_admin()) or status = 'pending');

-- listing — anon 은 공개된 것만, 함수 호출 없이
drop policy if exists listing_public_read on public.listing;
drop policy if exists listing_owner_write on public.listing;
drop policy if exists listing_anon_read on public.listing;
drop policy if exists listing_owner_insert on public.listing;
drop policy if exists listing_owner_update on public.listing;
drop policy if exists listing_owner_delete on public.listing;
create policy listing_anon_read on public.listing for select to anon
  using (status = 'published');
create policy listing_public_read on public.listing for select to authenticated
  using (status = 'published' or (select public.is_admin())
         or broker_id in (select id from public.broker where user_id = (select auth.uid())));
create policy listing_owner_insert on public.listing for insert to authenticated
  with check (broker_id in (select id from public.broker
                            where user_id = (select auth.uid()) and status = 'verified')
              or (select public.is_admin()));
create policy listing_owner_update on public.listing for update to authenticated
  using (broker_id in (select id from public.broker where user_id = (select auth.uid()))
         or (select public.is_admin()))
  with check (broker_id in (select id from public.broker
                            where user_id = (select auth.uid()) and status = 'verified')
              or (select public.is_admin()));
create policy listing_owner_delete on public.listing for delete to authenticated
  using (broker_id in (select id from public.broker where user_id = (select auth.uid()))
         or (select public.is_admin()));

-- favorite
drop policy if exists favorite_self on public.favorite;
create policy favorite_self on public.favorite for all to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- inquiry
drop policy if exists inquiry_insert on public.inquiry;
drop policy if exists inquiry_read on public.inquiry;
create policy inquiry_insert on public.inquiry for insert to authenticated
  with check ((select auth.uid()) is not null);
create policy inquiry_read on public.inquiry for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin())
         or listing_id in (select l.id from public.listing l
                           join public.broker b on b.id = l.broker_id
                           where b.user_id = (select auth.uid())));

-- report
drop policy if exists report_insert on public.report;
drop policy if exists report_read on public.report;
create policy report_insert on public.report for insert to authenticated
  with check ((select auth.uid()) is not null);
create policy report_read on public.report for select to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()));

-- post
drop policy if exists post_read on public.post;
drop policy if exists post_insert on public.post;
drop policy if exists post_update on public.post;
create policy post_read on public.post for select to authenticated
  using ((is_deleted = false and (select public.is_approved()))
         or user_id = (select auth.uid()) or (select public.is_admin()));
create policy post_insert on public.post for insert to authenticated
  with check (user_id = (select auth.uid()) and (select public.is_approved())
              and (category <> 'notice' or (select public.is_admin())));
create policy post_update on public.post for update to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()))
  with check (user_id = (select auth.uid()) or (select public.is_admin()));

-- comment — ALL 을 셋으로
drop policy if exists comment_read on public.comment;
drop policy if exists comment_write on public.comment;
drop policy if exists comment_insert on public.comment;
drop policy if exists comment_update on public.comment;
drop policy if exists comment_delete on public.comment;
create policy comment_read on public.comment for select to authenticated
  using ((is_deleted = false and (select public.is_approved()))
         or user_id = (select auth.uid()) or (select public.is_admin()));
create policy comment_insert on public.comment for insert to authenticated
  with check (user_id = (select auth.uid()) and (select public.is_approved()));
create policy comment_update on public.comment for update to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()))
  with check (user_id = (select auth.uid()) and (select public.is_approved()));
create policy comment_delete on public.comment for delete to authenticated
  using (user_id = (select auth.uid()) or (select public.is_admin()));

-- grade_log
drop policy if exists grade_log_admin_read on public.grade_log;
create policy grade_log_admin_read on public.grade_log for select to authenticated
  using ((select public.is_admin()));

-- ── 4. 외래키 인덱스 ────────────────────────────────────────────
create index if not exists idx_comment_user       on public.comment (user_id);
create index if not exists idx_favorite_listing   on public.favorite (listing_id);
create index if not exists idx_grade_log_changed  on public.grade_log (changed_by);
create index if not exists idx_grade_log_user     on public.grade_log (user_id);
create index if not exists idx_inquiry_user       on public.inquiry (user_id);
create index if not exists idx_post_user          on public.post (user_id);
create index if not exists idx_report_listing     on public.report (listing_id);
create index if not exists idx_report_user        on public.report (user_id);

-- ── 5. profile_public — 뷰에서 표로 ─────────────────────────────
-- 두 컬럼만 담는 것은 0002 와 같다. ⚠ 컬럼을 늘리면 그만큼 공개된다.
drop view if exists public.profile_public;
create table if not exists public.profile_public (
  id       uuid primary key references public.profile (id) on delete cascade,
  nickname text
);
insert into public.profile_public (id, nickname)
  select id, nickname from public.profile
  on conflict (id) do update set nickname = excluded.nickname;

create or replace function public.profile_public_sync()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profile_public (id, nickname) values (new.id, new.nickname)
  on conflict (id) do update set nickname = excluded.nickname;
  return new;
end;
$$;
revoke all on function public.profile_public_sync() from public, anon, authenticated;
drop trigger if exists profile_public_sync on public.profile;
create trigger profile_public_sync after insert or update of nickname on public.profile
  for each row execute function public.profile_public_sync();

alter table public.profile_public enable row level security;
drop policy if exists profile_public_read on public.profile_public;
create policy profile_public_read on public.profile_public for select to anon, authenticated
  using (true);
revoke all on public.profile_public from anon, authenticated;
grant select on public.profile_public to anon, authenticated;
