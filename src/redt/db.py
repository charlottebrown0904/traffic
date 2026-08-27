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
    is_open_type BOOLEAN
);

CREATE TABLE IF NOT EXISTS traffic (
    tollgate_id  VARCHAR,
    year         INTEGER,
    vehicle_type INTEGER,
    direction    VARCHAR,
    volume       BIGINT,
    PRIMARY KEY (tollgate_id, year, vehicle_type, direction)
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

CREATE TABLE IF NOT EXISTS zone_event (
    zone_id          VARCHAR PRIMARY KEY,
    name             VARCHAR,
    type             VARCHAR,
    lat              DOUBLE,
    lon              DOUBLE,
    area_m2          DOUBLE,
    designated_date  DATE
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


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    ensure_dirs()
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
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
