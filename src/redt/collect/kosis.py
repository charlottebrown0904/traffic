"""KOSIS 통계목록 탐색 — 시군구 인구·사업체 표를 **찾아서** 씁니다.

가설3 에 필요한 두 가지가 KOSIS 에 있습니다.

    시군구 인구      주민등록인구현황
    사업체·종사자    전국사업체조사

문제는 **어느 통계표인지** 입니다. KOSIS 에서 자료를 받으려면 orgId(기관)와
tblId(표) 를 알아야 하는데, 그 값은 목록을 훑어야 나옵니다. 추측해서 적어
넣으면 틀린 표의 숫자를 받아놓고도 맞는 줄 압니다 — RTMS 시군구 코드에서
이미 같은 일을 겪었습니다(잘못된 코드에 오류가 아니라 0건이 옵니다).

그래서 목록 API 로 트리를 내려가며 **이름으로 후보를 찾아 보여줍니다.**
사람이 보고 고르면, 그 ID 로 자료를 받습니다.

    https://kosis.kr/openapi/statisticsList.do?method=getList

요청변수 (사용자 제공 명세)
    apiKey    발급 키          필수 — 중계기가 채웁니다
    vwCd      서비스뷰 코드     필수 (MT_ZTITLE=국내통계 주제별 …)
    parentId  시작목록 ID       필수
    format    결과 유형(json)   필수
    content   헤더 유형         선택
"""
from __future__ import annotations

import json

from .http import get

LIST_URL = "https://kosis.kr/openapi/statisticsList.do"

# 서비스뷰. 주제별이 기본이고, 시군구 단위 지표는 e-지방지표에도 있다.
VIEWS = {
    "주제별": "MT_ZTITLE",
    "기관별": "MT_OTITLE",
    "지방지표_주제": "MT_GTITLE01",
    "지방지표_지역": "MT_GTITLE02",
}

# 우리가 찾는 것. 이름에 이 말이 들어간 항목을 눈에 띄게 표시한다.
WANTED = ("주민등록", "인구", "사업체", "종사자", "세대")


def _rows(payload) -> list[dict]:
    """응답에서 행 목록을 꺼낸다. 모양이 여러 가지라 방어적으로 본다."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("List", "list", "row", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        # 오류는 dict 하나로 온다 — 그대로 돌려주면 호출 측이 보고 판단한다.
        return [payload]
    return []


def browse(parent_id: str, vw_cd: str = "MT_ZTITLE") -> list[dict]:
    """목록 한 단계를 가져온다."""
    resp = get(LIST_URL, {
        "method": "getList",
        "apiKey": "",            # 중계기가 채운다
        "vwCd": vw_cd,
        "parentId": parent_id,
        "format": "json",
        "content": "json",
    })
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        head = resp.text[:300].replace("\n", " ")
        raise RuntimeError(f"JSON 이 아닙니다: {head}") from None
    return _rows(payload)


def _label(row: dict) -> str:
    for k in ("LIST_NM", "TBL_NM", "listNm", "tblNm", "NM", "name"):
        if row.get(k):
            return str(row[k])
    return ""


def _ident(row: dict) -> str:
    parts = []
    for k in ("LIST_ID", "listId", "TBL_ID", "tblId", "ORG_ID", "orgId"):
        if row.get(k):
            parts.append(f"{k}={row[k]}")
    return " ".join(parts)


def is_table(row: dict) -> bool:
    """표(잎)인가 폴더(가지)인가. 표에는 TBL_ID 가 붙는다."""
    return bool(row.get("TBL_ID") or row.get("tblId"))


def walk(parent_id: str, vw_cd: str = "MT_ZTITLE", depth: int = 2,
         _level: int = 0, _seen: set | None = None) -> list[dict]:
    """트리를 depth 만큼 내려가며 표를 모은다.

    폭이 넓으면 호출이 금방 늘어난다. depth 는 작게 두고, 이름이 맞는
    가지만 더 파고드는 편이 싸다.
    """
    _seen = _seen if _seen is not None else set()
    if parent_id in _seen or _level > depth:
        return []
    _seen.add(parent_id)

    try:
        rows = browse(parent_id, vw_cd)
    except Exception as exc:                          # noqa: BLE001
        print(f"{'  ' * _level}  ⚠ {parent_id} 조회 실패: {exc}")
        return []

    found = []
    for row in rows:
        name = _label(row)
        ident = _ident(row)
        if not name and not ident:
            # 오류 응답일 수 있다. 통째로 보여준다 — 삼키면 원인을 못 찾는다.
            print(f"{'  ' * _level}  ? {json.dumps(row, ensure_ascii=False)[:200]}")
            continue
        hit = any(w in name for w in WANTED)
        mark = "★" if hit else " "
        kind = "표" if is_table(row) else "폴더"
        print(f"{'  ' * _level}  {mark} [{kind}] {name}  ({ident})")
        if is_table(row):
            found.append(row)
        elif hit or _level < depth:
            child = row.get("LIST_ID") or row.get("listId")
            if child:
                found += walk(str(child), vw_cd, depth, _level + 1, _seen)
    return found
