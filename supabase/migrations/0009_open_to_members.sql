-- 0009 — 등급 장벽을 뺀다: 가입(승인)하면 전부 열린다 (2026-09-12 방향 전환)
--
-- 회의 결론: "호갱노노·밸류맵도 결국 광고와 매물 수익 구조. 개인 유료 결제는
-- 기대하기 어렵다. 등급·가입 장벽 없이 회원 가입 시 전면 무료 공개 → 광고,
-- 매물 등록 기반으로 간다."
--
-- premium_ok() 는 비공개 버킷(premium — 격차율 표·표준지 조각) 읽기 정책이
-- 묻는 함수다. 예전에는 admin·A·기한 안의 B 만 참이었다. 이제 **승인된
-- 회원이면** 참이다.
--
-- 바뀌지 않는 것:
--   * 버킷은 여전히 비공개다. 로그인하지 않은 사람은 못 받는다 — 주소를
--     아는 누구나 받는 공개 폴더로 되돌리는 것이 아니다.
--   * 등급 칸(grade·grade_until)과 관리자 화면은 그대로 둔다. 다시 잠글 수
--     있어야 하고, 관리자가 회원을 그 칸으로 본다.
--   * 감정평가서 원장(appraisal_case·appraisal_factor)은 그대로 잠겨 있다.
--     집계만 관리자에게 나간다 (0008).
--
-- 되돌리려면 0003 의 premium_ok() 본문(grade in ('admin','A') or B 기한)을
-- 다시 넣으면 된다. 화면 쪽은 public/lib/access.js 의 `open` 한 줄이다.
create or replace function public.premium_ok()
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((
    select status = 'approved' from public.profile where id = auth.uid()
  ), false);
$$;
revoke all on function public.premium_ok() from public, anon;
grant execute on function public.premium_ok() to authenticated;
