"""매물·중개사 저장소 (SQLite).

분석용 DuckDB 와 분리한다. DuckDB 는 대량 집계에 강하지만 동시 쓰기가 잦은
운영 데이터에는 맞지 않는다. 매물은 전형적인 OLTP 라 SQLite 를 쓴다.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..config import PROCESSED

DB_PATH = PROCESSED / "listings.sqlite"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS broker (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    NOT NULL UNIQUE,
    password_hash  TEXT    NOT NULL,
    password_salt  TEXT    NOT NULL,
    office_name    TEXT    NOT NULL,   -- 중개사무소 명칭
    office_address TEXT    NOT NULL,   -- 사무소 소재지
    license_no     TEXT    NOT NULL,   -- 등록번호
    agent_name     TEXT    NOT NULL,   -- 개업공인중개사 성명
    phone          TEXT    NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'pending',  -- pending/verified/suspended
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    token_hash TEXT PRIMARY KEY,
    broker_id  INTEGER NOT NULL REFERENCES broker(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_broker ON session(broker_id);

CREATE TABLE IF NOT EXISTS listing (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_id     INTEGER NOT NULL REFERENCES broker(id) ON DELETE CASCADE,
    kind          TEXT    NOT NULL,   -- land/factory/house/commercial
    deal_type     TEXT    NOT NULL,   -- sale/lease  (표시·광고 명시사항)
    address       TEXT    NOT NULL,
    lat           REAL,
    lon           REAL,
    area_m2       REAL    NOT NULL,
    price_manwon  INTEGER NOT NULL,
    jimok         TEXT,
    land_use      TEXT,
    memo          TEXT,
    contact_phone TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending_payment',
    paid_until    TEXT,
    -- 등록 시점에 계산해 저장 (영업소 좌표가 바뀌어도 매물 표시는 안정적으로)
    nearest_tollgate_id TEXT,
    nearest_name        TEXT,
    nearest_km          REAL,
    band                TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_listing_status ON listing(status);
CREATE INDEX IF NOT EXISTS idx_listing_broker ON listing(broker_id);
CREATE INDEX IF NOT EXISTS idx_listing_tollgate ON listing(nearest_tollgate_id);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@contextmanager
def transaction(con: sqlite3.Connection):
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
