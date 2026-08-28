"""한국도로공사 영업소 마스터(좌표 포함) 수집.

data.ex.co.kr 응답 필드명이 버전에 따라 다르므로 후보 키를 순차 탐색한다.
API 접근이 막히면 data/raw/tollgate.csv 를 직접 넣어도 된다.
"""
from __future__ import annotations

import pandas as pd

from ..config import RAW, keys
from .http import get, polite_sleep

EX_BASE = "https://data.ex.co.kr/openapi"
BUSINESS_INFO = f"{EX_BASE}/business/curBusinessInfo"

ALIASES = {
    "tollgate_id": ["unitCode", "unitcode", "tcsUnitCode", "icCode", "영업소코드"],
    "name": ["unitName", "unitname", "tcsUnitName", "icName", "영업소명"],
    "route_no": ["routeNo", "routeNm", "노선번호"],
    "lat": ["yValue", "yvalue", "lat", "latitude", "위도"],
    "lon": ["xValue", "xvalue", "lon", "lng", "longitude", "경도"],
    "sido": ["sidoName", "sido", "시도"],
    "sigungu": ["sigunguName", "sigungu", "시군구"],
}


def _pick(row: dict, aliases: list[str]):
    for key in aliases:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def fetch_tollgates(rows_per_page: int = 500, max_pages: int = 20) -> pd.DataFrame:
    """영업소 목록 전체를 페이지네이션으로 수집."""
    collected: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = get(
            BUSINESS_INFO,
            {
                "key": keys().require("ex"),
                "type": "json",
                "numOfRows": rows_per_page,
                "pageNo": page,
            },
        )
        payload = resp.json()
        # 응답 래퍼 키가 버전마다 달라 리스트를 담은 첫 키를 찾는다
        items = next(
            (v for v in payload.values() if isinstance(v, list) and v and isinstance(v[0], dict)),
            [],
        )
        if not items:
            break
        collected.extend(items)
        if len(items) < rows_per_page:
            break
        polite_sleep()

    return normalize(pd.DataFrame(collected))


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=list(ALIASES) + ["sigungu_cd", "is_open_type"])

    records = raw.to_dict("records")
    out = pd.DataFrame(
        [{field: _pick(row, aliases) for field, aliases in ALIASES.items()} for row in records]
    )
    for col in ("lat", "lon"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    # 한반도 범위를 벗어난 좌표는 오염된 값으로 보고 버린다
    valid = out["lat"].between(33, 39) & out["lon"].between(124, 132)
    dropped = int((~valid).sum())
    if dropped:
        print(f"  좌표 이상치 {dropped}건 제외")
    out = out[valid].copy()

    out["tollgate_id"] = out["tollgate_id"].astype(str)
    out["sigungu_cd"] = None
    out["is_open_type"] = None
    return out.drop_duplicates(subset=["tollgate_id"])


def load_from_csv(path=None) -> pd.DataFrame:
    """API 대신 수동으로 받은 CSV 사용."""
    return normalize(pd.read_csv(path or (RAW / "tollgate.csv")))
