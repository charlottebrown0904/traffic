"""국토교통부 실거래가(RTMS) OpenAPI 수집.

조회 단위가 (시군구 5자리 × 계약년월)이라 호출 수가 많다.
중단/재개는 db.collect_log 가 담당한다.

응답 필드는 **영문 camelCase** 이며 물건 종류마다 다르다.
(data.go.kr 각 오퍼레이션 문서 및 실응답 기준)
"""
from __future__ import annotations

import hashlib
import re

import pandas as pd

from ..config import keys
from .http import ApiError, get_xml, polite_sleep, text_of

BASE = "https://apis.data.go.kr/1613000"

# kind → (서비스/오퍼레이션, data.go.kr 데이터셋 번호)
ENDPOINTS = {
    "land":       ("RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade", "15126466"),
    "factory":    ("RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade", "15126470"),
    "house":      ("RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",     "15126465"),
    "commercial": ("RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",   "15126463"),
}

# 면적 필드는 물건 종류마다 의미가 다르다. ㎡당 단가의 분모로 무엇을 쓸지가 핵심.
#   land       : dealArea      (거래면적 = 토지면적)
#   factory    : plottageAr    (대지면적) — 건물면적은 헤도닉 통제변수로 별도 보관
#   commercial : plottageAr    (대지면적), 없으면 buildingAr
#   house      : plottageAr    (대지면적), 없으면 totalFloorAr
AREA_FIELDS = {
    "land":       ["dealArea", "거래면적"],
    "factory":    ["plottageAr", "대지면적", "buildingAr"],
    "commercial": ["plottageAr", "대지면적", "buildingAr"],
    "house":      ["plottageAr", "대지면적", "totalFloorAr", "연면적"],
}

ALIASES = {
    "umd":         ["umdNm", "법정동"],
    "jibun":       ["jibun", "지번"],
    "price":       ["dealAmount", "거래금액"],
    "year":        ["dealYear", "년"],
    "month":       ["dealMonth", "월"],
    "day":         ["dealDay", "일"],
    "jimok":       ["jimok", "지목"],
    "land_use":    ["landUse", "용도지역"],
    "building_ar": ["buildingAr", "totalFloorAr", "건축면적", "연면적"],
    "building_use": ["buildingUse", "buildingType", "주용도", "유형"],
    "build_year":  ["buildYear", "건축년도"],
    "share":       ["shareDealingType", "지분구분"],
    "deal_type":   ["dealingGbn", "거래유형"],
    "cancel_type": ["cdealType", "해제여부"],
    "cancel_day":  ["cdealDay", "해제사유발생일"],
    "sigungu":     ["sggNm", "시군구"],
    "sigungu_cd":  ["sggCd"],
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
    """dealAmount 는 '  1,234' 형태의 **만원** 단위 문자열."""
    manwon = _to_float(value)
    return int(manwon * 10_000) if manwon is not None else None


def fetch_page(kind: str, sigungu_cd: str, deal_ymd: str, page: int = 1,
               rows: int = 1000) -> tuple[list[dict], int]:
    if kind not in ENDPOINTS:
        raise ValueError(f"알 수 없는 물건 종류: {kind} (가능: {list(ENDPOINTS)})")
    root = get_xml(
        f"{BASE}/{ENDPOINTS[kind][0]}",
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
    price = _price_to_krw(_pick(item, ALIASES["price"]))
    area = _to_float(_pick(item, AREA_FIELDS[kind]))
    year = _to_float(_pick(item, ALIASES["year"]))
    month = _to_float(_pick(item, ALIASES["month"]))
    if price is None or year is None or month is None:
        return None

    umd = _pick(item, ALIASES["umd"])
    jibun = _pick(item, ALIASES["jibun"])
    build_year = _to_float(_pick(item, ALIASES["build_year"]))
    building_ar = _to_float(_pick(item, ALIASES["building_ar"]))

    key = f"{kind}|{sigungu_cd}|{umd}|{jibun}|{int(year)}|{int(month)}|{price}|{area}"
    return {
        "trade_id": hashlib.sha1(key.encode("utf-8")).hexdigest(),
        "kind": kind,
        "sigungu_cd": _pick(item, ALIASES["sigungu_cd"]) or sigungu_cd,
        "sido": "",                       # 응답에 없음 — 지오코딩 시 시군구명으로 충분
        "sigungu": _pick(item, ALIASES["sigungu"]),
        "umd": umd,
        "jibun": jibun,
        "deal_year": int(year),
        "deal_month": int(month),
        "area_m2": area,
        "price_krw": price,
        "price_per_m2": (price / area) if area else None,
        "jimok": _pick(item, ALIASES["jimok"]),
        "land_use": _pick(item, ALIASES["land_use"]),
        "building_area_m2": building_ar,
        "building_use": _pick(item, ALIASES["building_use"]),
        "build_year": int(build_year) if build_year else None,
        "is_share_deal": "지분" in _pick(item, ALIASES["share"]),
        # cdealType 이 'O' 면 해제된 계약 — 실제 거래가 아니므로 분석에서 제외해야 한다
        "is_cancelled": _pick(item, ALIASES["cancel_type"]).strip().upper() == "O",
        "deal_type": _pick(item, ALIASES["deal_type"]),   # 중개거래 / 직거래
        "lat": None,
        "lon": None,
        "geocode_level": None,
    }


def fetch_month(kind: str, sigungu_cd: str, deal_ymd: str) -> pd.DataFrame:
    """한 시군구·한 달치 전체(페이지네이션 포함)."""
    records, total = fetch_page(kind, sigungu_cd, deal_ymd, page=1)
    page = 1
    while len(records) < total and records:
        page += 1
        polite_sleep()
        more, total = fetch_page(kind, sigungu_cd, deal_ymd, page=page)
        if not more:
            break
        records.extend(more)
    return pd.DataFrame(records)
