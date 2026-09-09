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
import re

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


def loads_lenient(text: str):
    """KOSIS 응답을 읽는다. **엄격한 JSON 이 아니다.**

    format=json 을 줘도 이렇게 옵니다 — 키에 따옴표가 없습니다.

        [{LIST_NM:"인구",LIST_ID:"A",VW_NM:"국내통계 주제별"}]

    자바스크립트 객체 표기이지 JSON 이 아니라서 json.loads 가 거부합니다.
    첫 실행에서 자료는 멀쩡히 왔는데 '조회 실패' 로 찍혔습니다.

    먼저 정식으로 시도하고, 실패하면 **맨앞 키에만** 따옴표를 채워 다시
    시도합니다. `{` 나 `,` 바로 뒤의 ASCII 식별자 + 콜론만 건드리므로
    한글 값이나 값 속의 콜론은 손대지 않습니다.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    return json.loads(_quote_bare_keys(text))


def _quote_bare_keys(text: str) -> str:
    """따옴표 **밖에** 있는 맨 키에만 따옴표를 채운다.

    정규식 한 줄로 하려다 값을 깨뜨렸다. `{A:"x, y:z"}` 에서 값 안의
    `, y:` 를 키로 보고 `,"y":` 로 바꿔 문자열을 갈라놓는다. 실제 자료에
    쉼표와 콜론이 든 이름이 있으면 그때 조용히 틀어진다.

    그래서 문자열 안팎을 세어가며 훑는다.
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:      # 이스케이프는 통째로 넘긴다
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch in "{,":
            out.append(ch)
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            k = j
            while k < n and (text[k].isalnum() or text[k] == "_"):
                k += 1
            # 식별자 뒤가 콜론일 때만 키로 본다.
            m = k
            while m < n and text[m].isspace():
                m += 1
            if k > j and m < n and text[m] == ":" and not text[j].isdigit():
                out.append(text[i + 1:j])
                out.append('"' + text[j:k] + '"')
                i = k
                continue
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


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
        payload = loads_lenient(resp.text)
    except json.JSONDecodeError:
        head = resp.text[:300].replace("\n", " ")
        raise RuntimeError(f"읽을 수 없는 응답: {head}") from None
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


SEARCH_URL = "https://kosis.kr/openapi/statisticsSearch.do"


def raw(url: str, params: dict) -> tuple[int, str]:
    """응답을 그대로 돌려준다. 진단용."""
    from .http import get_once
    resp = get_once(url, params)
    return resp.status_code, resp.text


def diagnose() -> None:
    """parentId 가 실제로 먹히는지, 어느 뷰가 답하는지 사실만 확인한다.

    두 번 헛돌았습니다. 한 번은 응답이 JSON 이 아니어서, 한 번은 트리가
    안 내려가서. 추측으로 한 번씩 더 돌리는 대신, 한 실행에서 필요한
    사실을 모두 확인합니다.

      1. parentId 를 바꾸면 응답이 달라지는가 (안 달라지면 무시되는 것)
      2. 어느 서비스뷰가 답하는가
      3. 검색 엔드포인트가 있는가 — 있으면 트리를 안 타도 된다
    """
    print("=" * 60)
    print("1. parentId 가 먹히는가 — 두 값의 응답을 비교합니다")
    print("=" * 60)
    bodies = {}
    for pid in ("A", "B", "F"):
        try:
            code, text = raw(LIST_URL, {
                "method": "getList", "apiKey": "", "vwCd": "MT_ZTITLE",
                "parentId": pid, "format": "json", "content": "json"})
        except Exception as exc:                       # noqa: BLE001
            print(f"  parentId={pid}  호출 실패: {exc}")
            continue
        bodies[pid] = text
        print(f"  parentId={pid}  HTTP {code} · {len(text):,}자 · 앞부분: {text[:120]}")
    uniq = len(set(bodies.values()))
    if len(bodies) > 1:
        print(f"\n  → 서로 다른 응답 {uniq}종 / 시도 {len(bodies)}개")
        if uniq == 1:
            print("     **parentId 가 무시되고 있습니다.** 트리를 이 방법으로는 못 내려갑니다.")
        else:
            print("     parentId 가 먹힙니다. 트리 탐색을 이어가면 됩니다.")

    print()
    print("=" * 60)
    print("2. 어느 서비스뷰가 답하는가")
    print("=" * 60)
    for name, code_ in VIEWS.items():
        try:
            code, text = raw(LIST_URL, {
                "method": "getList", "apiKey": "", "vwCd": code_,
                "parentId": "A", "format": "json", "content": "json"})
            n = len(_rows(loads_lenient(text))) if text.strip() else 0
            print(f"  {name:14s} {code_:14s} HTTP {code} · 항목 {n}개 · {text[:90]}")
        except Exception as exc:                       # noqa: BLE001
            print(f"  {name:14s} {code_:14s} 실패: {exc}")

    print()
    print("=" * 60)
    print("3. 검색 엔드포인트 — 있으면 트리를 안 타도 됩니다")
    print("=" * 60)
    for term in ("주민등록인구", "사업체"):
        try:
            code, text = raw(SEARCH_URL, {
                "method": "getList", "apiKey": "", "searchNm": term,
                "format": "json", "jsonVD": "Y"})
            print(f"  '{term}'  HTTP {code} · {len(text):,}자")
            print(f"    {text[:400]}")
        except Exception as exc:                       # noqa: BLE001
            print(f"  '{term}'  실패: {exc}")


def search(term: str, rows: int = 100) -> list[dict]:
    """이름으로 통계표를 찾는다. **트리를 안 타도 됩니다.**

    statisticsList.do 는 parentId 를 무시하고 늘 최상위만 돌려줬습니다.
    statisticsSearch.do 는 ORG_ID·TBL_ID 를 바로 줍니다 — 우리에게 필요한
    것이 정확히 그 둘입니다. 게다가 응답이 정식 JSON 입니다.
    """
    code, text = raw(SEARCH_URL, {
        "method": "getList", "apiKey": "", "searchNm": term,
        "format": "json", "jsonVD": "Y"})
    if code != 200:
        raise RuntimeError(f"검색 실패 HTTP {code}: {text[:200]}")
    return _rows(loads_lenient(text))


def sido_codes() -> list[tuple[str, str]]:
    """현재 시도 코드를 KOSIS 에서 가져온다.

    e-지방지표(지역별)의 최상위 LIST_ID 가 시도 코드입니다. 손으로 적어둔
    목록은 행정구역이 개편되면 조용히 낡습니다 — 전북 45→52 를 이미
    그렇게 놓칠 뻔했고, 광주(29)·전남(46)이 0건인 것도 같은 이유일 수
    있습니다.
    """
    rows = browse("A", "MT_GTITLE02")
    out = []
    for r in rows:
        code = r.get("LIST_ID") or r.get("listId")
        name = _label(r)
        if code and name:
            out.append((str(code), name))
    return out


# 검색으로 확인한 표. **추측이 아니라 관측입니다** (kosis-find 로 확인).
#
#   DT_1B040A3  1992~2026  행정구역(시군구)별, 성별 인구수
#               우리 창(2006~2025)을 완전히 덮고 시군구 단위입니다.
#   DT_1B040B3  1992~2026  행정구역(시군구)별 주민등록세대수
#
# 사업체는 시군구 단위로 여러 해를 주는 표를 아직 못 찾았습니다. 검색에
# 나온 것은 시도 단위(DT_1K52F01, 2020~2024)뿐입니다. 찾으면 여기 적습니다.
TABLES = {
    "population": {"orgId": "101", "tblId": "DT_1B040A3",
                   "name": "행정구역(시군구)별 성별 인구수"},
    "households": {"orgId": "101", "tblId": "DT_1B040B3",
                   "name": "행정구역(시군구)별 주민등록세대수"},
}

DATA_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


class KosisError(RuntimeError):
    """KOSIS 가 HTTP 200 에 오류 본문을 실어 보낸 것.

    **200 을 성공으로 읽으면 안 된다.** KOSIS 는 필수 변수가 빠져도,
    셀 한도를 넘겨도 200 으로 답하고 본문에 err 를 담는다. 그것을 그냥
    파싱하면 '한 행이 왔다' 가 되어 '자료가 거의 없구나' 로 오해한다 —
    탐침 3절이 실제로 그렇게 보였다 (1행 · 코드 자릿수 [0]).
    """


def _err(body) -> str | None:
    if isinstance(body, dict) and body.get("err"):
        return f"[{body['err']}] {body.get('errMsg', '')}".strip()
    return None


def fetch_meta(org_id: str, tbl_id: str, kind: str = "OBJ") -> list[dict]:
    """통계표의 **분류축·항목 목록**을 받는다.

    읍면동 표는 분류축이 둘 이상이라(지역 × 5세별) objL1 만 보내면
    '필수요청변수값이 누락되었습니다 (objL)' 로 막힌다. 그렇다고 축
    이름을 기억으로 적으면 안 된다 — 표마다 다르다. **물어본다.**

      kind="OBJ"  분류축과 그 코드
      kind="ITM"  항목 (총인구수·남자·여자 …)
      kind="TBL"  표 자체 (기간 등)
    """
    code, text = raw(DATA_URL, {
        "method": "getMeta", "apiKey": "", "format": "json", "jsonVD": "Y",
        "orgId": org_id, "tblId": tbl_id, "type": kind,
    })
    if code != 200:
        raise RuntimeError(f"메타 조회 실패 HTTP {code}: {text[:160]}")
    body = loads_lenient(text)
    msg = _err(body)
    if msg:
        raise KosisError(msg)
    return _rows(body)


def fetch_table(org_id: str, tbl_id: str, start: str, end: str,
                prd_se: str = "Y", obj_l1: str = "ALL",
                itm_id: str = "ALL", *, obj: dict | None = None,
                quiet: bool = False) -> list[dict]:
    """통계표 하나를 연 단위로 받는다.

    obj 로 분류축을 더 준다 — {"objL2": "ALL"} 처럼. 축이 둘인 표는
    이것을 안 주면 200 에 err 20 이 실려 온다.
    """
    params = {
        "method": "getList", "apiKey": "", "format": "json", "jsonVD": "Y",
        "orgId": org_id, "tblId": tbl_id,
        "prdSe": prd_se, "startPrdDe": start, "endPrdDe": end,
        "objL1": obj_l1, "itmId": itm_id,
    }
    params.update(obj or {})
    code, text = raw(DATA_URL, params)
    if not quiet:
        print(f"  HTTP {code} · {len(text):,}자")
        print(f"  앞부분: {text[:400]}")
    if code != 200:
        raise RuntimeError(f"자료 조회 실패 HTTP {code}")
    body = loads_lenient(text)
    # **200 에 실려 온 오류를 성공으로 읽지 않는다.**
    msg = _err(body)
    if msg:
        raise KosisError(msg)
    return _rows(body)
