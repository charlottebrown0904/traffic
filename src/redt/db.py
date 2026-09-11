"""DuckDB 연결과 스키마."""
from __future__ import annotations

import duckdb

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS tollgate (
    tollgate_id VARCHAR PRIMARY KEY,
    name        VARCHAR,
    route_no    VARCHAR,
    lat         DOUBLE,
    lon         DOUBLE,
    sido        VARCHAR,
    sigungu     VARCHAR,
    sigungu_cd  VARCHAR,
    is_open_type BOOLEAN,
    src         VARCHAR,         -- ex(도로공사 API) / poi(이름검색) / master(명부) / csv
    -- 도로공사 명부의 '고속도로운영기관구분코드'. 이 칸이 교통량 결측을
    -- 설명한다 — 아래 traffic_source 주석 참고.
    operator_cd VARCHAR
);

-- 교통량은 출처가 여러 개이고 성격이 다르다. source 를 키에 포함해 섞이지 않게 한다.
--   tcs  : 영업소 진출입 교통량 (그 IC 로 실제 나가고 들어온 통행) ← 지역 수요 지표
--   aadt : 본선 지점 연평균일교통량 (통과 교통 포함)              ← 장기 시계열 확보용
CREATE TABLE IF NOT EXISTS traffic (
    tollgate_id  VARCHAR,
    year         INTEGER,
    vehicle_type INTEGER,          -- 0 = 차종 미구분 합계
    direction    VARCHAR,          -- in / out / all
    volume       BIGINT,           -- 연간 누적 (일평균 자료는 ×365 아님, avg_daily 참조)
    avg_daily    DOUBLE,           -- 일평균 (AADT 계열은 이쪽이 원값)
    source       VARCHAR,          -- tcs / aadt / <파일명>
    unit_type    VARCHAR,          -- tollgate / point(본선지점 → 최근접 영업소로 매핑)
    match_km     DOUBLE,           -- point 를 영업소에 매핑한 거리 (tollgate 면 0)
    PRIMARY KEY (tollgate_id, year, vehicle_type, direction, source)
);

-- 일별 원시 교통량. 연 집계를 나중에 다시 할 수 있도록 원본 해상도를 보존한다.
-- 결측일을 세야 '교통량 감소'와 '수집 누락'을 구분할 수 있다.
CREATE TABLE IF NOT EXISTS traffic_daily (
    tollgate_id  VARCHAR,
    sum_date     DATE,
    vehicle_type INTEGER,
    direction    VARCHAR,          -- in / out / all
    hipass       VARCHAR,          -- tcs(현금) / hipass / all
    volume       BIGINT,
    PRIMARY KEY (tollgate_id, sum_date, vehicle_type, direction, hipass)
);

CREATE TABLE IF NOT EXISTS traffic_fetch_log (
    sum_date  DATE PRIMARY KEY,
    n_rows    INTEGER,
    status    VARCHAR,             -- ok / empty / error
    message   VARCHAR
);

CREATE TABLE IF NOT EXISTS trade (
    trade_id      VARCHAR PRIMARY KEY,
    kind          VARCHAR,
    sigungu_cd    VARCHAR,
    sido          VARCHAR,
    sigungu       VARCHAR,
    umd           VARCHAR,
    jibun         VARCHAR,
    deal_year     INTEGER,
    deal_month    INTEGER,
    area_m2       DOUBLE,           -- 단가 분모 (토지=거래면적, 공장/상업=대지면적)
    price_krw     BIGINT,
    price_per_m2  DOUBLE,
    jimok            VARCHAR,       -- 지목 (전/답/대/임야/공장용지...)
    land_use         VARCHAR,       -- 용도지역 (계획관리/생산녹지/공업...)
    building_area_m2 DOUBLE,        -- 건물면적 (헤도닉 통제변수)
    building_use     VARCHAR,
    build_year    INTEGER,
    is_share_deal BOOLEAN,          -- 지분거래 → ㎡단가 왜곡
    is_cancelled  BOOLEAN,          -- 계약 해제 → 실제 거래 아님, 분석에서 제외
    deal_type     VARCHAR,          -- 중개거래 / 직거래
    lat           DOUBLE,
    lon           DOUBLE,
    geocode_level VARCHAR           -- parcel(지번) / umd(법정동 중심) / NULL
);

-- 가설3 이벤트형: 산업단지·택지지구처럼 '언제 어디서' 가 있는 개발 사건.
--
-- IC 개통과 같은 방식으로 전후를 가르는 데 쓰고, 동시에 IC 효과의 **교란**
-- 으로도 쓴다. IC 가 뚫린 그 해에 옆에 산단이 지정됐다면, 산단이 만든 상승을
-- IC 공으로 돌리게 된다.
CREATE TABLE IF NOT EXISTS zone_event (
    zone_id          VARCHAR PRIMARY KEY,
    name             VARCHAR,
    type             VARCHAR,          -- 산업단지 / 택지지구 / 도시개발
    lat              DOUBLE,
    lon              DOUBLE,
    area_m2          DOUBLE,
    designated_date  DATE,
    sigungu_cd       VARCHAR,
    source           VARCHAR,          -- 어느 데이터셋에서 왔는지
    geocode_level    VARCHAR           -- parcel / umd / sigungu(시군구 중심)
);

-- 가설3 패널형: 시군구 × 연도 규모 지표.
--
-- 인구가 늘어서 오른 것을 교통량이 늘어서 오른 것으로 읽지 않으려면, 같은
-- 회귀에 넣어야 한다. 값 종류를 행으로 두어 새 지표가 생겨도 스키마를
-- 안 바꾼다.
CREATE TABLE IF NOT EXISTS region_year (
    sigungu_cd  VARCHAR,
    year        INTEGER,
    metric      VARCHAR,              -- population / households / businesses / employees
    value       DOUBLE,
    source      VARCHAR,
    PRIMARY KEY (sigungu_cd, year, metric)
);

-- 읍·면·동 인구 (KOSIS DT_1B04005N, 2011년~).
--
-- **행정동이지 법정동이 아니다.** 받은 10자리 코드는 행정동 코드고,
-- 우리 실거래에는 법정동 이름만 있다. 그래서 코드로 못 잇고 이름으로
-- 잇는다 — 읍·면은 거의 맞고 도시의 동은 자주 어긋난다.
--
-- adm_cd 를 함께 남기는 것은 나중에 행정동 → 법정동 대조표를 구했을 때
-- 다시 이을 수 있게 하기 위해서다. 이름만 남기면 그때 처음부터 받아야 한다.
CREATE TABLE IF NOT EXISTS umd_pop (
    adm_cd      VARCHAR,          -- 행정동 코드 10자리
    sigungu_cd  VARCHAR,          -- 앞 5자리
    umd         VARCHAR,          -- 행정동 이름
    year        INTEGER,
    pop         BIGINT,
    PRIMARY KEY (adm_cd, year)
);

-- 전국 법정동 명부 (행정안전부 행정표준코드 행정구역코드).
--
-- **왜 따로 두는가.** 우리 자료는 실거래에서 나왔다. 그래서 거래가
-- 있었던 동네만 안다. 거래가 없던 곳은 이름조차 몰라 지도에서 통째로
-- 빠졌다 (보고된 문제 2026-09-09: "거래가 없는 동 이름이 다 안나오네요").
--
-- 이 표에는 **좌표가 없다** — 표준코드가 안 준다. lat/lon 은 뒤이어
-- 브이월드 지오코더로 채운다. 채우기 전에는 NULL 이고, NULL 인 줄은
-- 지도에 못 올린다 (이름표는 좌표 위에 놓인다).
CREATE TABLE IF NOT EXISTS region_umd (
    region_cd   VARCHAR PRIMARY KEY,  -- 법정동코드 10자리
    sigungu_cd  VARCHAR,              -- 앞 5자리
    sigungu     VARCHAR,              -- 시군구 이름 (세종은 빈 값)
    umd         VARCHAR,              -- '금남면 국곡리' — trade.umd 와 같은 꼴
    level       VARCHAR,              -- 'umd'(읍·면·동) | 'ri'(리)
    full_nm     VARCHAR,              -- 시도부터의 전체 주소
    lat         DOUBLE,
    lon         DOUBLE
);

-- 거래 ↔ 개발사건 공간 조인. trade_tollgate_link 와 같은 모양이다.
CREATE TABLE IF NOT EXISTS trade_zone_link (
    trade_id    VARCHAR,
    zone_id     VARCHAR,
    distance_km DOUBLE,
    band        VARCHAR,
    is_nearest  BOOLEAN,
    PRIMARY KEY (trade_id, zone_id)
);

CREATE TABLE IF NOT EXISTS trade_tollgate_link (
    trade_id    VARCHAR,
    tollgate_id VARCHAR,
    distance_km DOUBLE,
    band        VARCHAR,
    is_nearest  BOOLEAN,
    PRIMARY KEY (trade_id, tollgate_id)
);

-- 필지 특성 — 도로접·형상·지세. 브이월드 토지특성(dt_d194).
--
-- 요구사항(2026-09-07): "도로를 접하는 가가 제일 중요합니다."
-- 실측(남이천·안성)으로 확인한 것: 차가 들어가느냐가 값을 +66~67% 가른다.
-- 그 변수를 헤도닉이 안 쓰고 있어서, 전·답·임야 잔차가 통째로 남아
-- 교통량 계수를 덮고 있었다.
--
-- **도형은 저장하지 않는다.** 필지 도형은 무겁고(전국이면 수백만 개),
-- 우리가 쓰는 것은 '이 거래가 어느 필지인가' 하나뿐이다. 받는 그 자리
-- 에서 점-다각형으로 맞춰 trade_parcel 에 남기고 도형은 버린다.
CREATE TABLE IF NOT EXISTS parcel (
    pnu            VARCHAR PRIMARY KEY,   -- 19자리 필지 식별자
    sigungu_cd     VARCHAR,
    jimok          VARCHAR,               -- lndcgr_code_nm
    land_use       VARCHAR,               -- prpos_area_1_nm 용도지역
    use_situation  VARCHAR,               -- lad_use_sittn_nm 토지이용상황
    area_m2        DOUBLE,                -- lndpcl_ar
    road_side      VARCHAR,               -- road_side_code_nm 도로접면
    shape          VARCHAR,               -- tpgrph_frm_code_nm 형상
    slope          VARCHAR,               -- tpgrph_hg_code_nm 지세
    official_price DOUBLE,                -- pblntf_pclnd 공시지가 원/㎡
    stdr_year      INTEGER
);

-- 거래가 어느 필지에 떨어졌는가. 점-다각형으로 맞춘다.
--
-- 지번으로 맞추는 길도 재 봤는데 두 곳 다 0% 였다 — 저쪽은 읍면동을
-- 숫자 코드로 주고 우리는 이름으로 갖고 있어서다. 좌표는 100% 붙는다.
CREATE TABLE IF NOT EXISTS trade_parcel (
    trade_id VARCHAR PRIMARY KEY,
    pnu      VARCHAR
);

-- 관청(도청·시청·군청·구청) 위치.
--
-- 요구사항(2026-09-07): "인구 표시 원의 중심은 도청/시청/구청/군청
-- 소재지가 중심이 되도록." 그 전까지 원의 중심은 우리 거래 좌표에서
-- 만든 대표점이었다 — 거래가 없는 동네가 많은 시군구는 그만큼 끌려간다.
--
-- **시도 이름도 여기서 온다.** 실거래 API 응답에 시도가 없어서
-- trade.sido 는 늘 빈 값이다(collect/rtms.py). 관청 도로명주소의 첫
-- 마디가 그 시군구의 시도 이름이고, 그것이 우리가 가진 유일한 출처다.
CREATE TABLE IF NOT EXISTS office (
    level      VARCHAR,    -- 'sido' | 'si' | 'gu'
    key        VARCHAR,    -- gu 는 시군구코드, 나머지는 행정구역 이름
    label      VARCHAR,    -- 화면에 쓰는 행정구역 이름 (수원시 장안구 …)
    name       VARCHAR,    -- 검색이 준 관청 이름 (장안구청 …)
    category   VARCHAR,    -- 지방행정기관 > 구청 …
    sido       VARCHAR,    -- 도로명주소의 첫 마디
    road_addr  VARCHAR,
    lat        DOUBLE,
    lon        DOUBLE,
    -- 대표점과 몇 km 떨어졌는가. 같은 이름의 구가 여럿이라 엉뚱한 곳을
    -- 집을 수 있는데, 그때 조용히 틀리지 않고 이 숫자가 커진다.
    dist_km    DOUBLE,
    source     VARCHAR,
    fetched_at TIMESTAMP,
    PRIMARY KEY (level, key)
);

-- 어느 칸을 이미 훑었는가. 없으면 재개할 때마다 처음부터 다시 받는다.
CREATE TABLE IF NOT EXISTS parcel_tile (
    tile_key   VARCHAR PRIMARY KEY,   -- "w,s,e,n" 소수 4자리로 반올림
    n_parcels  INTEGER,
    n_matched  INTEGER,
    truncated  BOOLEAN,               -- 한도에 닿아 쪼갠 칸인가
    fetched_at TIMESTAMP,
    -- **어느 범위로 훑었는가.** 이것이 없으면 대상을 넓혀도 이미 훑은
    -- 칸은 영영 건너뛴다. run 44 가 그랬다 — 붙일 거래가 148만인데
    -- 칸 7,520개 중 1,168개만 안 훑은 것으로 잡혀서, 나머지 115만 건이
    -- 이미 훑은 칸 안에 갇혔다. 필지 도형은 저장하지 않으므로 다시
    -- 받지 않으면 맞출 방법이 없다.
    scope      VARCHAR                -- core ⊂ land ⊂ all
);

-- 감정평가서 (요구사항 2026-09-10 — '현재 가치' 프리미엄).
--
-- ## 왜 실거래가 아니라 감정평가서인가
--
-- 실거래는 **팔린 땅**만 말해 준다. 안 팔린 땅이 얼마인지는 말이 없다.
-- 감정평가서는 팔리지 않은 땅에도 값을 매긴 기록이라 그 빈칸을 메운다.
-- 게다가 값 하나만 있는 것이 아니라 **어떻게 그 값에 이르렀는지**가
-- 적혀 있다 (감정평가에 관한 규칙 §14 공시지가기준법).
--
--   토지가액 = 비교표준지 공시지가
--            × 시점수정 × 지역요인 × 개별요인 × 그 밖의 요인 보정
--
-- 우리가 배우려는 것은 마지막 두 개다.
--
--   개별요인       가로·접근·환경·획지(면적/형상/지세)·행정(용도지역/규제)
--                  → 요구사항에 적힌 칸들이 여기 그대로 들어 있다
--   그 밖의 요인   공시지가와 시장가치의 벌어진 폭 (보통 1.2~2.5배)
--                  → 지역마다 크게 다르고, 어디에도 공표되지 않는다
--
-- ## ratio_official 이 학습 목표다
--
-- 우리는 이미 **모든 필지의 개별공시지가**를 갖고 있다 (브이월드
-- 토지특성, parcel.official_price). 그래서
--
--   현재 가치 = 개별공시지가 × 예측배율
--
-- 로 낼 수 있고, 예측배율을 (지역 × 용도지역 × 지목 × 도로접 × 형상 ×
-- 지세 × 면적) 로 회귀하는 것이 이 표의 쓰임이다. 평가액을 통째로
-- 예측하려 들면 표본이 몇백 건일 때 지역 차이만 학습하고 끝난다.
--
-- ## 원본은 저장소에 두지 않는다
--
-- 감정평가서에는 소유자·채무자 이름이 적혀 있다. 이 저장소는 **공개**다.
-- 원본 PDF 는 구글 드라이브(개인 계정)에만 두고, 이 표에는
-- 사람 이름이 들어가는 칸을 아예 만들지 않는다.
CREATE TABLE IF NOT EXISTS appraisal (
    appraisal_id  VARCHAR PRIMARY KEY,  -- 사건번호-물건번호-일련
    source        VARCHAR,              -- court(법원경매) / onbid(공매) / manual
    case_no       VARCHAR,              -- 2024타경12345
    item_no       VARCHAR,              -- 물건번호
    base_date     DATE,                 -- 기준시점 (가격시점)
    report_date   DATE,                 -- 작성일

    -- 대상 토지. parcel 표와 같은 이름·같은 값으로 둔다 — 다르게 적으면
    -- 대입할 때 사전을 하나 더 만들어야 하고, 그 사전이 곧 어긋난다.
    pnu           VARCHAR,
    addr          VARCHAR,
    sigungu_cd    VARCHAR,
    jimok         VARCHAR,
    land_use      VARCHAR,              -- 용도지역
    land_use2     VARCHAR,              -- 둘째 용도지역 (겹칠 때)
    zone_txt      VARCHAR,              -- 지구·구역 원문 (농업진흥구역, 개발제한구역 …)
    use_situation VARCHAR,              -- 이용상황
    road_side     VARCHAR,              -- 도로접면
    shape         VARCHAR,              -- 형상
    slope         VARCHAR,              -- 지세
    area_m2       DOUBLE,

    -- 산식의 각 마디. 하나라도 비면 검산이 안 되므로 다 받는다.
    official_price     DOUBLE,          -- 대상 개별공시지가 원/㎡
    std_pnu            VARCHAR,         -- 비교표준지
    std_price          DOUBLE,          -- 비교표준지 공시지가 원/㎡
    f_time             DOUBLE,          -- 시점수정
    f_region           DOUBLE,          -- 지역요인
    f_indiv            DOUBLE,          -- 개별요인 (곱한 값)
    f_other            DOUBLE,          -- 그 밖의 요인 보정
    appraised_per_m2   DOUBLE,          -- 감정평가액 원/㎡
    appraised_krw      BIGINT,          -- 토지 평가액 (건물 제외)

    -- 학습 목표. 평가액 ÷ 대상 개별공시지가.
    ratio_official DOUBLE,

    src_file   VARCHAR,                 -- 원본 파일명 (내용은 저장소 밖)
    parsed_by  VARCHAR,                 -- 어느 판독기가 읽었는지
    parsed_at  TIMESTAMP
);

-- 개별요인 격차율의 **속**. 평가사가 가로·접근·환경·획지·행정 항목마다
-- 대상과 표준지를 견줘 몇 %로 봤는지가 여기 남는다.
--
-- 이것이 이 프로젝트에서 가장 값진 칸이다 — 우리 다섯 축(도로·모양·
-- 지세·용도)이 값을 얼마나 가르는지를, 우리가 추정한 것이 아니라
-- **평가사가 직접 매긴 숫자**로 알 수 있다.
CREATE TABLE IF NOT EXISTS appraisal_factor (
    appraisal_id VARCHAR,
    group_nm     VARCHAR,   -- 가로조건 / 접근조건 / 환경조건 / 획지조건 / 행정적조건 / 기타조건
    item_nm      VARCHAR,   -- 도로폭 / 형상 / 지세 / 면적 / 용도지역 …
    subject      VARCHAR,   -- 대상 토지의 값
    comp         VARCHAR,   -- 비교표준지의 값
    ratio        DOUBLE,    -- 격차율 (1.00 = 같음)
    PRIMARY KEY (appraisal_id, group_nm, item_nm)
);

-- 표준지공시지가 (collect/stdland). '현재 가치' 2판의 첫 마디.
-- 원천 셋(파일·odcloud·브이월드)을 같은 열로 접는다. 사람 이름은 없다.
CREATE TABLE IF NOT EXISTS std_land (
    std_id        VARCHAR PRIMARY KEY,   -- pnu-연도 (pnu 가 없으면 법정동코드-지번-연도)
    pnu           VARCHAR,
    ld_code       VARCHAR,               -- 법정동코드 10자리
    ld_name       VARCHAR,
    special       VARCHAR,               -- 특수지 구분 (일반/산)
    jibun         VARCHAR,
    std_no        VARCHAR,               -- 표준지 일련번호
    year          INTEGER,               -- 기준연도
    month         VARCHAR,
    price         DOUBLE,                -- 공시지가 원/㎡
    jimok         VARCHAR,
    area_m2       DOUBLE,
    land_use      VARCHAR,
    land_use2     VARCHAR,
    district      VARCHAR,               -- 용도지구 1
    district2     VARCHAR,
    use_situation VARCHAR,
    surroundings  VARCHAR,               -- 주위환경
    road_side     VARCHAR,
    road_dist     VARCHAR,               -- 도로거리 (비준표 항목)
    slope         VARCHAR,
    shape         VARCHAR,
    cnflc_rt      VARCHAR,               -- 도시계획시설 저촉률
    notice_date   VARCHAR,
    lon           DOUBLE,
    lat           DOUBLE,
    sigungu_cd    VARCHAR,
    source        VARCHAR,               -- file / odcloud / vworld
    -- 원천의 코드 열. 이름이 빈 행을 코드로 채우고, 코드표를 배우는 재료.
    land_use_code  VARCHAR,
    land_use2_code VARCHAR,
    use_code       VARCHAR,
    road_side_code VARCHAR,
    road_dist_code VARCHAR,
    slope_code     VARCHAR,
    shape_code     VARCHAR
);
"""


# 이미 만들어진 DB 는 CREATE TABLE IF NOT EXISTS 로는 컬럼이 늘지 않는다.
# 캐시로 되살린 DB 에 새 컬럼을 붙일 때 필요하다.
MIGRATIONS = [
    "ALTER TABLE tollgate ADD COLUMN IF NOT EXISTS src VARCHAR",
    "ALTER TABLE tollgate ADD COLUMN IF NOT EXISTS operator_cd VARCHAR",
    "ALTER TABLE zone_event ADD COLUMN IF NOT EXISTS sigungu_cd VARCHAR",
    "ALTER TABLE zone_event ADD COLUMN IF NOT EXISTS source VARCHAR",
    "ALTER TABLE zone_event ADD COLUMN IF NOT EXISTS geocode_level VARCHAR",
    # 예전에 담긴 칸은 전부 core 범위로 훑은 것이다. 빈 값을 그렇게 읽는다.
    "ALTER TABLE parcel_tile ADD COLUMN IF NOT EXISTS scope VARCHAR",
    # 표준지 표는 2026-09-11 첫 적재 시도 뒤 열이 늘었다.
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS district VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS district2 VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS road_dist VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS cnflc_rt VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS land_use_code VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS land_use2_code VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS use_code VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS road_side_code VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS road_dist_code VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS slope_code VARCHAR",
    "ALTER TABLE std_land ADD COLUMN IF NOT EXISTS shape_code VARCHAR",
]


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    ensure_dirs()
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
        for stmt in MIGRATIONS:
            con.execute(stmt)
    return con


def _primary_key(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    row = con.execute("""
        SELECT constraint_column_names FROM duckdb_constraints()
        WHERE constraint_type = 'PRIMARY KEY' AND table_name = ?
    """, [table]).fetchone()
    return list(row[0]) if row else []


def upsert(con: duckdb.DuckDBPyConnection, table: str, df,
           preserve: list[str] | None = None) -> int:
    """DataFrame 을 테이블에 병합. PK 충돌 시 기존 행을 대체한다.

    preserve 에 적은 칸은 **들어온 값이 비어 있으면 기존 값을 지키지
    않는다** — 지운다. 그것이 기본 동작(INSERT OR REPLACE)이고, 다음
    사고를 냈다.

      1) 거래 T 를 수집한다            lat = NULL
      2) 지오코딩으로 좌표를 붙인다     lat = 37.1   ← 하루 4,000건짜리 호출
      3) 같은 거래를 다시 수집한다      lat = NULL   ← 방금 산 것이 날아간다

    API 응답에 좌표 칸이 없는 것은 '좌표가 없어졌다' 가 아니라 '그 API 가
    좌표를 모른다' 는 뜻이다. 그것을 지움으로 받아들이면, 이 프로젝트에서
    가장 비싼 자원(지오코딩·영업소 좌표 보충)이 재수집할 때마다 사라진다.
    예외도 경고도 없이 표만 얇아지므로 몇 주 뒤에나 알게 된다.

    preserve 에 적은 칸은 들어온 값이 NULL 일 때 기존 값을 남긴다.
    들어온 값이 있으면 그것으로 덮는다(갱신은 정상 동작이다).
    """
    if df is None or len(df) == 0:
        return 0
    described = con.execute(f"DESCRIBE {table}").fetchall()
    cols = [r[0] for r in described]
    types = {r[0]: r[1] for r in described}
    df = df.reindex(columns=cols)
    con.register("_incoming", df)

    keep = [c for c in (preserve or []) if c in cols]
    pk = _primary_key(con, table) if keep else []
    if keep and not pk:
        # PK 를 모르면 어느 행과 합칠지 알 수 없다. 조용히 옛 동작으로
        # 돌아가면 지키라고 적어둔 칸이 지워지므로, 말하고 멈춘다.
        raise ValueError(
            f"{table} 에 기본키가 없어 {keep} 를 지킬 수 없습니다")

    if keep:
        on = " AND ".join(f"i.{c} IS NOT DISTINCT FROM t.{c}" for c in pk)
        # 값이 전부 비어 있는 칸을 pandas 는 DOUBLE(NaN) 으로 준다. 문자
        # 칸과 coalesce 하면 타입이 안 맞아 터지므로, 테이블이 선언한
        # 타입으로 맞춰 넣는다. 좌표가 다 빈 재수집이 바로 이 경우다.
        sel = ", ".join(
            f"coalesce(CAST(i.{c} AS {types[c]}), t.{c}) AS {c}"
            if c in keep else f"i.{c} AS {c}"
            for c in cols)
        sql = (f"INSERT OR REPLACE INTO {table} SELECT {sel} "
               f"FROM _incoming i LEFT JOIN {table} t ON {on}")
    else:
        sql = f"INSERT OR REPLACE INTO {table} SELECT {', '.join(cols)} FROM _incoming"
    con.execute(sql)
    con.unregister("_incoming")
    return len(df)


COLLECT_LOG = """
CREATE TABLE IF NOT EXISTS collect_log (
    kind       VARCHAR,
    sigungu_cd VARCHAR,
    deal_ymd   VARCHAR,
    n_rows     INTEGER,
    status     VARCHAR,          -- ok / empty / error
    message    VARCHAR,
    PRIMARY KEY (kind, sigungu_cd, deal_ymd)
);
"""


def done_cells(con, kind: str) -> set[tuple[str, str]]:
    """이미 성공적으로 수집한 (시군구, 년월) 집합 — 재개용."""
    con.execute(COLLECT_LOG)
    rows = con.execute(
        "SELECT sigungu_cd, deal_ymd FROM collect_log WHERE kind = ? AND status <> 'error'",
        [kind],
    ).fetchall()
    return {(r[0], r[1]) for r in rows}


def log_cell(con, kind: str, sigungu_cd: str, deal_ymd: str,
             n_rows: int, status: str, message: str = "") -> None:
    con.execute(COLLECT_LOG)
    con.execute(
        "INSERT OR REPLACE INTO collect_log VALUES (?, ?, ?, ?, ?, ?)",
        [kind, sigungu_cd, deal_ymd, n_rows, status, message[:500]],
    )
