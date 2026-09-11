-- 프리미엄 자료 버킷 (2026-09-11, 회원 등급 A 단계 "진짜 자물쇠")
--
-- 현재 가치의 숫자 원천 둘 — 격차율 표(valuation.json)와 표준지 조각
-- (stdland-NNNNN.json 252개) — 은 공개 저장소·Vercel·CDN 에 있으면 주소를
-- 아는 누구나 받는다. 여기 비공개 버킷에 두고, 내려받기 정책이 premium_ok()
-- (승인 + admin/A/B 기한 안)를 묻는다. 화면(app.js premiumFetch)은 로그인
-- 토큰으로 이 버킷에서 받는다. 올리는 쪽은 러너(service_role)다.
--
-- 실행: Supabase 대시보드 → SQL Editor (또는 MCP apply_migration). 2026-09-11 적용.

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('premium', 'premium', false, 52428800, array['application/json'])
on conflict (id) do update set public = false;

drop policy if exists premium_read on storage.objects;
create policy premium_read on storage.objects
  for select to authenticated
  using (bucket_id = 'premium' and public.premium_ok());
