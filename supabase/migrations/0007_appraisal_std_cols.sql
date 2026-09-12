-- 0007 — 감정평가 원장에 표준지 특성 열 (2026-09-11, 2차 164건 적재)
--
-- 그 밖의 요인(f_other)은 **비교표준지** 기준 배율이다. 1차 원장은 대상 필지의
-- 지목·이용상황만 적어 칸(지목군)을 대상 기준으로 갈랐다. 2차부터 표준지의
-- 지목·이용상황·용도지역·지세를 같이 적어 칸을 표준지 기준으로 가른다
-- (화면 otherFactorOf 가 이미 표준지 지목군으로 찾는다 — 산출 쪽을 맞춘다).
--
-- 다필지 평가서는 필지마다 한 행이다. file_id 는 첫 필지가 드라이브 파일 ID,
-- 둘째부터 '<파일ID>#<일련번호>'. 사람 이름 칸은 여전히 없다.
alter table public.appraisal_case
  add column if not exists jibun             text,   -- 대상 지번 (본번-부번, 산 포함)
  add column if not exists official_year     int,    -- 개별공시지가 연도
  add column if not exists zone_txt          text,   -- 지구·구역 원문 요약
  add column if not exists std_addr          text,   -- 비교표준지 소재지(읍면동 지번)
  add column if not exists std_jimok         text,
  add column if not exists std_use_situation text,
  add column if not exists std_land_use      text,
  add column if not exists std_slope         text,
  add column if not exists other_basis       text,   -- 그 밖의 요인 산출 근거 한 줄
  add column if not exists batch             smallint default 1;  -- 1차 52건 = 1, 2차 = 2
comment on column public.appraisal_case.batch is '적재 회차. 1=2026-09-10 52건, 2=2026-09-11 164파일';
