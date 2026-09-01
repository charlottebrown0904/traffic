"""한국도로공사 영업소 마스터(좌표 포함) 수집.

data.ex.co.kr 응답 필드명이 버전에 따라 다르므로 후보 키를 순차 탐색한다.
API 접근이 막히면 data/raw/tollgate.csv 를 직접 넣어도 된다.
"""
from __future__ import annotations

import pandas as pd

from ..config import RAW, keys
from ..ids import canon_series
from .http import get, polite_sleep

EX_BASE = "https://data.ex.co.kr/openapi"

# 서울 경유 탐색으로 확인한 실제 경로 (2026-08-31).
# 포털의 API 목록이 자바스크립트로 그려져 문서에서 읽을 수 없어, 이름을 훑어 찾았다.
#   locationinfo/locationinfoUnit  영업소 590곳  unitCode·unitName·xValue·yValue
#   locationinfo/locationinfoIc    IC 위치       icCode·icName
#   locationinfo/locationinfoRest  휴게소 203곳
# 예전에 쓰던 business/curBusinessInfo 는 존재하지 않는 경로였다.
UNIT_INFO = f"{EX_BASE}/locationinfo/locationinfoUnit"
IC_INFO = f"{EX_BASE}/locationinfo/locationinfoIc"

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
    seen_first: str | None = None
    for page in range(1, max_pages + 1):
        resp = get(
            UNIT_INFO,
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
        # pageNo 를 무시하고 같은 페이지를 되돌려주는 API 가 있다. 그대로 두면
        # 같은 행을 max_pages 만큼 쌓고 뒤에서 조용히 합쳐진다.
        first = str(items[0])
        if seen_first is not None and first == seen_first:
            print(f"  {page}페이지가 이전과 동일 — 페이지네이션 미지원으로 보고 중단")
            break
        seen_first = first
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

    # unitCode 는 "065 " 처럼 뒤에 공백이 붙어 온다. 이대로 두면 교통량 쪽
    # 영업소코드와 조인이 어긋난다.
    # fillna 를 먼저 해야 한다. NaN 은 .str 접근자를 그대로 통과해
    # 아래 빈값 검사를 빠져나간다.
    # 교통량 파일은 코드를 정수로(11), API 는 세 자리 문자열로("011 ") 준다.
    # 같은 규칙으로 접지 않으면 100 미만 코드 25개가 조인에서 통째로 빠진다.
    out["tollgate_id"] = canon_series(out["tollgate_id"]).fillna("")
    out["name"] = out["name"].fillna("").astype(str).str.strip()
    out["sigungu_cd"] = None
    out["is_open_type"] = None

    # 같은 영업소가 노선·방향별로 여러 줄 올 수 있어 코드 기준으로 합친다.
    # 몇 건이 합쳐졌는지 밝혀두지 않으면 "590건 받았는데 86건 저장"처럼
    # 조용히 줄어든 것을 나중에 알아채기 어렵다.
    bad = out["tollgate_id"].isin(["", "None", "nan", "NaN", "<NA>"])
    if bad.any():
        print(f"  영업소코드 없음 {int(bad.sum())}건 제외")
        out = out[~bad].copy()
    before = len(out)
    out = out.drop_duplicates(subset=["tollgate_id"])
    if before != len(out):
        print(f"  중복 영업소코드 {before - len(out)}건 병합 ({before} → {len(out)})")
    # 교통량 파일과 조인이 어긋나면 패널이 조용히 빈다. 어떤 모양의 코드가
    # 저장됐는지 남겨두면 로그만 보고 표기 차이를 알아챌 수 있다.
    print(f"  코드 예시: {sorted(out['tollgate_id'])[:8]}")
    return out


def load_from_csv(path=None) -> pd.DataFrame:
    """API 대신 수동으로 받은 CSV 사용."""
    return normalize(pd.read_csv(path or (RAW / "tollgate.csv")))
