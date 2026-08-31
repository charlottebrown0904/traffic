-- 게시판에 작성자 이름을 보이기 위한 최소 공개면
--
-- profile 테이블 자체는 계속 잠가둔다. 거기엔 전화번호와 권한이 함께
-- 들어 있어서, 남의 행을 읽게 열어주면 그것까지 새어 나간다. RLS 는 행
-- 단위라 "닉네임 컬럼만 공개" 를 정책으로 표현할 수 없다.
--
-- 그래서 닉네임만 담은 뷰를 따로 두고 그 뷰에만 읽기 권한을 준다.
-- security_invoker = off 라 이 뷰는 소유자 권한으로 돌아가고, 곧 profile
-- 의 RLS 를 우회한다. 우회해도 안전한 근거는 단 하나 — 뷰가 id 와
-- nickname 두 컬럼만 내보낸다는 것이다.
--
--   ⚠ 이 뷰에 컬럼을 추가하는 순간 그 근거가 깨진다. 컬럼을 늘려야 할
--     일이 생기면 뷰를 고치지 말고 새 뷰를 만들 것.
--
-- 실행: Supabase 대시보드 → SQL Editor → 붙여넣기 → Run

create or replace view public.profile_public
  with (security_invoker = off)
as
  select id, nickname from public.profile;

revoke all on public.profile_public from anon, authenticated;
grant select on public.profile_public to anon, authenticated;
