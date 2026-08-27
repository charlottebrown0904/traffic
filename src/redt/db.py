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
    area_m2       DOUBLE,
    price_krw     BIGINT,
    price_per_m2  DOUBLE,
    land_use      VARCHAR,
    build_year    INTEGER,
    is_share_deal BOOLEAN,
    lat           DOUBLE,
    lon           DOUBLE
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
