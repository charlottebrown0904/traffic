"""국토교통부 실거래가(RTMS) OpenAPI 수집.

조회 단위가 (시군구 5자리 × 계약년월)이라 호출 수가 많다.
중단/재개가 가능하도록 이미 수집된 (kind, sigungu, ym)은 건너뛴다.
"""
from __future__ import annotations

import hashlib
import re

import pandas as pd

from ..config import keys
from .http import ApiError, get_xml, polite_sleep, text_of

BASE = "https://apis.data.go.kr/1613000"

ENDPOINTS = {
    "land": "RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
    "factory": "RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
    "house": "RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
    "commercial": "RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
}

# RTMS 는 오퍼레이션마다 태그명이 조금씩 다르다. 후보를 순서대로 시도한다.
FIELD_ALIASES = {
    "umd": ["법정동", "umdNm", "법정동명"],
    "jibun": ["지번", "jibun"],
    "area": ["거래면적", "대지면적", "연면적", "건축면적", "dealArea", "totalFloorAr", "plottageAr"],
    "price": ["거래금액", "dealAmount"],
    "year": ["년", "dealYear"],
    "month": ["월", "dealMonth"],
    "day": ["일", "dealDay"],
    "land_use": ["지목", "용도지역", "jimok", "useAreaNm", "구분"],
    "share": ["지분구분", "shareDealingType", "거래구분"],
    "build_year": ["건축년도", "buildYear"],
    "sigungu": ["시군구", "sggNm"],
    "sido": ["시도", "sidoNm"],
}


def _pick(node, aliases: list[str]) -> str:
    for tag in aliases:
        value = text_of(node, tag)
        if value:
            return value
    return ""


def _to_float(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", value or "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _price_to_krw(value: str) -> int | None:
    """'  1,234' (만원 단위) → 12,340,000 원."""
    manwon = _to_float(value)
    return int(manwon * 10_000) if manwon is not None else None


def fetch_page(kind: str, sigungu_cd: str, deal_ymd: str, page: int = 1,
               rows: int = 1000) -> tuple[list[dict], int]:
    """한 페이지 조회. (레코드 리스트, 전체 건수) 반환."""
    if kind not in ENDPOINTS:
        raise ValueError(f"알 수 없는 물건 종류: {kind}")
    root = get_xml(
        f"{BASE}/{ENDPOINTS[kind]}",
        {
            "serviceKey": keys().require("data_go_kr"),
            "LAWD_CD": sigungu_cd,
            "DEAL_YMD": deal_ymd,
            "pageNo": page,
            "numOfRows": rows,
        },
    )
    code = text_of(root, ".//resultCode") or text_of(root, ".//returnReasonCode")
    if code and code not in ("00", "000"):
        msg = text_of(root, ".//resultMsg") or text_of(root, ".//returnAuthMsg")
        raise ApiError(f"RTMS 오류 {code}: {msg} ({kind}/{sigungu_cd}/{deal_ymd})")

    total = int(text_of(root, ".//totalCount", "0") or 0)
    records = [_parse_item(item, kind, sigungu_cd) for item in root.findall(".//item")]
    return [r for r in records if r], total


def _parse_item(item, kind: str, sigungu_cd: str) -> dict | None:
    price = _price_to_krw(_pick(item, FIELD_ALIASES["price"]))
    area = _to_float(_pick(item, FIELD_ALIASES["area"]))
    year = _to_float(_pick(item, FIELD_ALIASES["year"]))
    month = _to_float(_pick(item, FIELD_ALIASES["month"]))
    if price is None or year is None or month is None:
        return None

    umd = _pick(item, FIELD_ALIASES["umd"])
    jibun = _pick(item, FIELD_ALIASES["jibun"])
    share_raw = _pick(item, FIELD_ALIASES["share"])
    build_year = _to_float(_pick(item, FIELD_ALIASES["build_year"]))

    key = f"{kind}|{sigungu_cd}|{umd}|{jibun}|{int(year)}|{int(month)}|{price}|{area}"
    return {
        "trade_id": hashlib.sha1(key.encode("utf-8")).hexdigest(),
        "kind": kind,
        "sigungu_cd": sigungu_cd,
        "sido": _pick(item, FIELD_ALIASES["sido"]),
        "sigungu": _pick(item, FIELD_ALIASES["sigungu"]),
        "umd": umd,
        "jibun": jibun,
        "deal_year": int(year),
        "deal_month": int(month),
        "area_m2": area,
        "price_krw": price,
        "price_per_m2": (price / area) if area else None,
        "land_use": _pick(item, FIELD_ALIASES["land_use"]),
        "build_year": int(build_year) if build_year else None,
        # '지분' 이라는 글자가 들어가면 지분거래로 간주 (㎡단가 왜곡 방지)
        "is_share_deal": "지분" in share_raw,
        "lat": None,
        "lon": None,
    }


def fetch_month(kind: str, sigungu_cd: str, deal_ymd: str) -> pd.DataFrame:
    """한 시군구·한 달치 전체(페이지네이션 포함)."""
    records, total = fetch_page(kind, sigungu_cd, deal_ymd, page=1)
    fetched = len(records)
    page = 1
    while fetched < total and records:
        page += 1
        polite_sleep()
        more, total = fetch_page(kind, sigungu_cd, deal_ymd, page=page)
        if not more:
            break
        records.extend(more)
        fetched = len(records)
    return pd.DataFrame(records)
