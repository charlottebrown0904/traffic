-- 운영자 전용 버킷 (2026-09-19, 실거래 지번 추정의 연도별 신뢰도)
--
-- 지시: "연도에 대한 신뢰도는 저희만 조회합니다(Admin 탭). 실거래 지번에 대한
-- 정확도는 절대 유저에게 보여주지 않습니다."
--
-- 'premium' 버킷은 이제 **승인 회원 전부**가 읽는다(0009). 그래서 거기 두면
-- 회원이 다 본다. 운영자만 보는 자리가 따로 필요하다.
--
-- 왜 '숨김' 이 아니라 '못 읽음' 이어야 하나 — 화면에서 감추는 것은 자물쇠가
-- 아니다. /admin 의 JS 는 주소를 알면 누구나 받고, 그 안에 주소가 적혀 있으면
-- 파일도 같이 받힌다. 내려받기 정책이 is_admin() 을 물어야 실제로 막힌다.
--
-- 올리는 쪽은 러너(service_role)이고, 정책을 거치지 않는다.
--
-- 실행: Supabase 대시보드 → SQL Editor (또는 MCP apply_migration).

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('ops', 'ops', false, 10485760, array['application/json'])
on conflict (id) do update set public = false;

drop policy if exists ops_read on storage.objects;
create policy ops_read on storage.objects
  for select to authenticated
  using (bucket_id = 'ops' and public.is_admin());
