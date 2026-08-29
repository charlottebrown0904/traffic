"""매물 API 서버.

  POST /api/brokers          중개사 가입
  POST /api/auth/login       로그인 → 토큰
  POST /api/auth/logout      로그아웃
  GET  /api/me               내 정보
  GET  /api/listings         매물 목록 (공개: 활성 매물만 / 로그인: 내 매물 포함)
  POST /api/listings         매물 등록 (인증)
  PATCH  /api/listings/{id}  수정 (본인만)
  DELETE /api/listings/{id}  삭제 (본인만, 소프트 삭제)
  POST /api/listings/{id}/publish  결제 후 게시 — 지금은 결제 미연동 모의 처리
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.staticfiles import StaticFiles

from ..config import ROOT, band_label
from . import security as sec
from . import store
from .models import (BrokerPublic, BrokerSignup, ListingCreate, ListingPublic,
                     ListingUpdate, LoginRequest, TokenResponse)

FEE_KRW = 30_000
LISTING_DAYS = 90

# 로그인 무차별 대입 방어. 프로세스 메모리라 재시작하면 초기화되고
# 여러 워커로 띄우면 워커별로 센다. 단일 프로세스 운영 기준의 최소 방어이며,
# 다중화하면 Redis 같은 공유 저장소로 옮겨야 한다.
MAX_FAILURES = 8
LOCKOUT = timedelta(minutes=15)
_failures: dict[str, list[datetime]] = {}


def _throttle_key(request: Request, email: str) -> str:
    client = request.client.host if request.client else "?"
    return f"{client}|{email}"


def check_throttle(key: str) -> None:
    cutoff = datetime.now(timezone.utc) - LOCKOUT
    recent = [t for t in _failures.get(key, []) if t > cutoff]
    _failures[key] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "로그인 시도가 너무 많습니다. 15분 후 다시 시도하세요")


def record_failure(key: str) -> None:
    _failures.setdefault(key, []).append(datetime.now(timezone.utc))

_con: sqlite3.Connection | None = None
_tollgates: list[dict] = []


# ─────────────────────────── 수명주기 ───────────────────────────
def get_con() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = store.connect()
    return _con


def load_tollgates() -> list[dict]:
    """영업소 좌표를 메모리에 올린다. 분석 DB 가 없어도 서버는 떠야 한다."""
    global _tollgates
    try:
        from .. import db as analytics_db
        with analytics_db.connect(read_only=True) as con:
            rows = con.execute(
                "SELECT tollgate_id, name, lat, lon FROM tollgate "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
        _tollgates = [{"id": r[0], "name": r[1], "lat": r[2], "lon": r[3]} for r in rows]
    except Exception as exc:
        print(f"영업소 좌표를 불러오지 못했습니다 ({exc}). 매물의 IC 거리 계산은 생략됩니다.")
        _tollgates = []
    return _tollgates


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_con()
    load_tollgates()
    print(f"매물 API 시작 — 영업소 {len(_tollgates)}개 로드")
    yield


app = FastAPI(title="IC 스크리닝 매물 API", version="0.1.0", lifespan=lifespan)


# ─────────────────────────── 인증 ───────────────────────────
def current_broker(request: Request, con=Depends(get_con)) -> dict:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다")
    row = con.execute(
        "SELECT b.*, s.expires_at FROM session s JOIN broker b ON b.id = s.broker_id "
        "WHERE s.token_hash = ?", (sec.token_hash(header[7:].strip()),)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 유효하지 않습니다")
    if row["expires_at"] < sec.now_iso():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "세션이 만료되었습니다")
    if row["status"] == "suspended":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "정지된 계정입니다")
    return dict(row)


def optional_broker(request: Request, con=Depends(get_con)) -> dict | None:
    try:
        return current_broker(request, con)
    except HTTPException:
        return None


# ─────────────────────────── 공간 계산 ───────────────────────────
def nearest_tollgate(lat: float, lon: float) -> dict | None:
    if not _tollgates:
        return None
    best, best_km = None, float("inf")
    for tg in _tollgates:
        dlat = math.radians(tg["lat"] - lat)
        dlon = math.radians(tg["lon"] - lon)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(tg["lat"]))
             * math.sin(dlon / 2) ** 2)
        km = 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, a)))
        if km < best_km:
            best, best_km = tg, km
    return {"id": best["id"], "name": best["name"], "km": round(best_km, 3),
            "band": band_label(best_km)}


# ─────────────────────────── 직렬화 ───────────────────────────
def to_public(row: sqlite3.Row) -> ListingPublic:
    data = dict(row)
    area = data.get("area_m2") or 0
    data["price_per_m2"] = round(data["price_manwon"] * 10_000 / area, 1) if area else None
    return ListingPublic(**{k: data.get(k) for k in ListingPublic.model_fields})


def broker_public(row) -> BrokerPublic:
    return BrokerPublic(**{k: dict(row)[k] for k in BrokerPublic.model_fields})


# ─────────────────────────── 중개사 ───────────────────────────
@app.post("/api/brokers", response_model=TokenResponse, status_code=201)
def signup(payload: BrokerSignup, con=Depends(get_con)):
    pw_hash, salt = sec.hash_password(payload.password)
    try:
        with store.transaction(con):
            cur = con.execute(
                "INSERT INTO broker (email, password_hash, password_salt, office_name,"
                " office_address, license_no, agent_name, phone, status, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,'pending',?)",
                (payload.email, pw_hash, salt, payload.office_name, payload.office_address,
                 payload.license_no, payload.agent_name, payload.phone, sec.now_iso()))
            broker_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다")
    return _issue_token(con, broker_id)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, con=Depends(get_con)):
    email = payload.email.strip().lower()
    key = _throttle_key(request, email)
    check_throttle(key)

    row = con.execute("SELECT * FROM broker WHERE email = ?", (email,)).fetchone()
    # 계정 존재 여부를 노출하지 않도록 메시지를 하나로 통일한다
    if row is None or not sec.verify_password(payload.password, row["password_hash"],
                                              row["password_salt"]):
        record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "이메일 또는 비밀번호가 올바르지 않습니다")
    _failures.pop(key, None)
    return _issue_token(con, row["id"])


def _issue_token(con, broker_id: int) -> TokenResponse:
    token, hashed, expires = sec.new_token()
    with store.transaction(con):
        con.execute("DELETE FROM session WHERE expires_at < ?", (sec.now_iso(),))
        con.execute("INSERT INTO session VALUES (?,?,?,?)",
                    (hashed, broker_id, sec.now_iso(), expires))
    row = con.execute("SELECT * FROM broker WHERE id = ?", (broker_id,)).fetchone()
    return TokenResponse(token=token, expires_at=expires, broker=broker_public(row))


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, con=Depends(get_con), broker=Depends(current_broker)):
    header = request.headers.get("authorization", "")
    with store.transaction(con):
        con.execute("DELETE FROM session WHERE token_hash = ?",
                    (sec.token_hash(header[7:].strip()),))
    return Response(status_code=204)


@app.get("/api/me", response_model=BrokerPublic)
def me(broker=Depends(current_broker)):
    return BrokerPublic(**{k: broker[k] for k in BrokerPublic.model_fields})


# ─────────────────────────── 매물 ───────────────────────────
LISTING_SELECT = """
SELECT l.*, b.office_name, b.office_address, b.license_no, b.agent_name
FROM listing l JOIN broker b ON b.id = l.broker_id
"""


@app.get("/api/listings", response_model=list[ListingPublic])
def list_listings(
    con=Depends(get_con), broker=Depends(optional_broker),
    kind: str | None = None,
    tollgate_id: str | None = None,
    mine: bool = False,
    limit: int = Query(200, ge=1, le=1000),
):
    # 공개 목록에는 게시중인 매물만. 본인 매물은 결제 전 것도 보인다.
    where = ["l.status != 'removed'"]
    params: list = []
    if mine:
        if not broker:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다")
        where.append("l.broker_id = ?")
        params.append(broker["id"])
    elif broker:
        where.append("(l.status = 'active' OR l.broker_id = ?)")
        params.append(broker["id"])
    else:
        where.append("l.status = 'active'")

    if kind:
        where.append("l.kind = ?")
        params.append(kind)
    if tollgate_id:
        where.append("l.nearest_tollgate_id = ?")
        params.append(tollgate_id)

    params.append(limit)
    rows = con.execute(
        f"{LISTING_SELECT} WHERE {' AND '.join(where)} "
        f"ORDER BY l.created_at DESC LIMIT ?", params).fetchall()
    return [to_public(r) for r in rows]


@app.post("/api/listings", response_model=ListingPublic, status_code=201)
def create_listing(payload: ListingCreate, con=Depends(get_con),
                   broker=Depends(current_broker)):
    near = (nearest_tollgate(payload.lat, payload.lon)
            if payload.lat is not None and payload.lon is not None else None)
    now = sec.now_iso()
    with store.transaction(con):
        cur = con.execute(
            "INSERT INTO listing (broker_id, kind, deal_type, address, lat, lon, area_m2,"
            " price_manwon, jimok, land_use, memo, contact_phone, status,"
            " nearest_tollgate_id, nearest_name, nearest_km, band, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'pending_payment',?,?,?,?,?,?)",
            (broker["id"], payload.kind, payload.deal_type, payload.address,
             payload.lat, payload.lon, payload.area_m2, payload.price_manwon,
             payload.jimok, payload.land_use, payload.memo, payload.contact_phone,
             near["id"] if near else None, near["name"] if near else None,
             near["km"] if near else None, near["band"] if near else None, now, now))
        listing_id = cur.lastrowid
    return to_public(_fetch(con, listing_id))


@app.patch("/api/listings/{listing_id}", response_model=ListingPublic)
def update_listing(listing_id: int, payload: ListingUpdate, con=Depends(get_con),
                   broker=Depends(current_broker)):
    row = _fetch_owned(con, listing_id, broker["id"])
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return to_public(row)

    sets = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values())

    # 좌표가 바뀌면 최근접 영업소를 다시 계산한다
    lat = fields.get("lat", row["lat"])
    lon = fields.get("lon", row["lon"])
    if ("lat" in fields or "lon" in fields) and lat is not None and lon is not None:
        near = nearest_tollgate(lat, lon)
        if near:
            sets += ", nearest_tollgate_id = ?, nearest_name = ?, nearest_km = ?, band = ?"
            values += [near["id"], near["name"], near["km"], near["band"]]

    values += [sec.now_iso(), listing_id]
    with store.transaction(con):
        con.execute(f"UPDATE listing SET {sets}, updated_at = ? WHERE id = ?", values)
    return to_public(_fetch(con, listing_id))


@app.post("/api/listings/{listing_id}/publish", response_model=ListingPublic)
def publish_listing(listing_id: int, con=Depends(get_con), broker=Depends(current_broker)):
    """결제 완료 처리 자리.

    ⚠️ 결제(PG)가 아직 연동되지 않았다. 지금은 결제 없이 게시 상태로 바꾼다.
       실제 연동 시 이 함수는 '결제 검증 성공' 콜백에서만 호출되어야 한다.
    """
    _fetch_owned(con, listing_id, broker["id"])
    until = (datetime.now(timezone.utc) + timedelta(days=LISTING_DAYS)).isoformat(
        timespec="seconds")
    with store.transaction(con):
        con.execute("UPDATE listing SET status='active', paid_until=?, updated_at=? "
                    "WHERE id = ?", (until, sec.now_iso(), listing_id))
    return to_public(_fetch(con, listing_id))


@app.delete("/api/listings/{listing_id}", status_code=204)
def delete_listing(listing_id: int, con=Depends(get_con), broker=Depends(current_broker)):
    _fetch_owned(con, listing_id, broker["id"])
    # 실제 삭제 대신 상태만 바꾼다 — 광고 이력은 분쟁 대비로 남겨야 한다
    with store.transaction(con):
        con.execute("UPDATE listing SET status='removed', updated_at=? WHERE id = ?",
                    (sec.now_iso(), listing_id))
    return Response(status_code=204)


@app.get("/api/fees")
def fees():
    return {"listing_fee_krw": FEE_KRW, "listing_days": LISTING_DAYS,
            "payment_connected": False,
            "notice": "결제(PG)가 연동되지 않아 게시는 모의 처리됩니다."}


def _fetch(con, listing_id: int):
    row = con.execute(f"{LISTING_SELECT} WHERE l.id = ?", (listing_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "매물을 찾을 수 없습니다")
    return row


def _fetch_owned(con, listing_id: int, broker_id: int):
    row = _fetch(con, listing_id)
    if row["broker_id"] != broker_id:
        # 남의 매물이 '존재한다'는 사실도 알려주지 않는다
        raise HTTPException(status.HTTP_404_NOT_FOUND, "매물을 찾을 수 없습니다")
    return row


# ─────────────────────────── 정적 파일 ───────────────────────────
WEB_DIR = ROOT / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
