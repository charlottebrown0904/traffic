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
    src         VARCHAR          -- ex(도로공사 API) / poi(이름검색) / csv
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
"""


# 이미 만들어진 DB 는 CREATE TABLE IF NOT EXISTS 로는 컬럼이 늘지 않는다.
# 캐시로 되살린 DB 에 새 컬럼을 붙일 때 필요하다.
MIGRATIONS = [
    "ALTER TABLE tollgate ADD COLUMN IF NOT EXISTS src VARCHAR",
    "ALTER TABLE zone_event ADD COLUMN IF NOT EXISTS sigungu_cd VARCHAR",
    "ALTER TABLE zone_event ADD COLUMN IF NOT EXISTS source VARCHAR",
    "ALTER TABLE zone_event ADD COLUMN IF NOT EXISTS geocode_level VARCHAR",
]


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    ensure_dirs()
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
        for stmt in MIGRATIONS:
            con.execute(stmt)
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, df) -> int:
    """DataFrame 을 테이블에 병합. PK 충돌 시 기존 행을 대체한다."""
    if df is None or len(df) == 0:
        return 0
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    df = df.reindex(columns=cols)
    con.register("_incoming", df)
    con.execute(f"INSERT OR REPLACE INTO {table} SELECT {', '.join(cols)} FROM _incoming")
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
