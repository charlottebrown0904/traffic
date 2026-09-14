"""지역 지표 원천 탐침 — 허가 → 가동 → 소득 세 마디.

2026-09-14 지시. 법인지방소득세 · 산업용 전력 · 건축허가 면적 셋을 한 번에
잡아 선행 시차를 본다 (docs/future-value-indicators.md §5).

**엔드포인트는 추측하지 않는다.** ECOS 에서 표 코드를 추측해 틀렸던 것과
같은 일을 세 번 되풀이하지 않으려면, 먼저 두 길로 찾는다.

  1. 공공데이터포털 **검색 페이지**를 중계기로 읽어 데이터셋 번호와 유형
     (API / 파일)을 뽑는다. 사람이 브라우저로 하는 일을 러너가 한다.
  2. 이미 알고 있는 후보 엔드포인트는 **직접 두드려** 무엇이 오는지 본다 —
     키가 없어 거절되는 것과 주소가 틀린 것은 다른 답이 온다.

둘의 결과를 한 JSON 에 남기고, 다음 판에서 그것을 보고 적재기를 쓴다.
"""
from __future__ import annotations

import html
import re
import threading
import time

from . import http

PORTAL_SEARCH = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"

# 무엇을 찾는가. 검색어는 포털 제목에 실제로 쓰이는 말로 둔다.
KEYWORDS = {
    "electric":  ["계약종별 전력사용량", "지역별 전력사용량", "전력사용량 시군구"],
    "permit":    ["건축인허가", "건축허가 현황", "건축HUB"],
    "local_tax": ["지방세 징수", "법인지방소득세", "지방재정 세입"],
}

# 직접 두드려 볼 후보. 키가 필요한 곳은 자리표를 두고 중계기가 채운다
# (없으면 상류가 '키 없음' 을 말해 준다 — 그것도 답이다).
CANDIDATES = [
    # 국토부 건축HUB 건축인허가 — 기본개요. 시군구·법정동 코드로 묻는다.
    # 허가일(pmsDay)·착공일(stcnsDay)·연면적(totArea)·주용도(mainPurpsCdNm)가
    # 온다고 알고 있다 — 이번 판에서 확인한다.
    {"name": "건축HUB 기본개요",
     "url": "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo",
     "params": {"sigunguCd": "41550", "bjdongCd": "25300", "numOfRows": "3",
                "pageNo": "1", "_type": "json"}},
    # 한전 빅데이터 플랫폼 — 시군구 × 계약종별 × 월 전력사용량.
    # 키는 한전 쪽에서 따로 받는다 (KEPCO_KEY). 없으면 거절 메시지가 온다.
    {"name": "한전 계약종별 전력사용량",
     "url": "https://bigdata.kepco.co.kr/openapi/v1/powerUsage/contractType.do",
     "params": {"year": "2024", "month": "01", "metroCd": "41", "cityCd": "41550",
                "apiKey": http.VIA_RELAY, "returnType": "json"}},
    # 4차(run 34806432813)에서 건축HUB 가 NORMAL SERVICE 로 열렸다 — 활용신청이
    # 반영된 것이다. 안성 25300 은 0건이었으니, 자료가 있는 동으로 한 건 받아
    # **항목 열쇠**를 보고, 법정동 없이 시군구만으로 되는지도 본다 — 그것이
    # 전국을 훑는 호출 수(250 vs 3,500+)를 정한다.
    {"name": "건축HUB 강남·역삼 (열쇠 보기)",
     "url": "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo",
     "params": {"sigunguCd": "11680", "bjdongCd": "10300", "numOfRows": "2",
                "pageNo": "1", "_type": "json"}},
    # 5차: 법정동 없이는 {"body":{}} — 빈 몸통. 법정동별로 불러야 한다. 그러면
    # 전국이 3,500+ 법정동 × 쪽수다. 쪽 크기 한도(1000 이 되는가)와 허가일
    # 필터(startDate·endDate 가 먹는가)가 그 수를 정한다. 개포동 전체 건수도 본다.
    {"name": "건축HUB 개포동 1000줄 (쪽 한도·건수)",
     "url": "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo",
     "params": {"sigunguCd": "11680", "bjdongCd": "10300", "numOfRows": "1000",
                "pageNo": "1", "_type": "json"}},
    {"name": "건축HUB 개포동 2024년만 (날짜 필터)",
     "url": "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo",
     "params": {"sigunguCd": "11680", "bjdongCd": "10300", "numOfRows": "5",
                "pageNo": "1", "_type": "json", "startDate": "20240101", "endDate": "20241231"}},
    # 행안부 통계연보 — 상세 화면에서 주소와 운영 이름이 나왔다 (15107410).
    # 한전: 시군구(cityCd) 없이 시도만 주면 시도 전체가 오는가 — 그러면 전국이
    # 17 시도 × 12 월 × 연수 호출로 끝난다.
    {"name": "한전 계약종별 · 시군구 없이 (시도 전체?)",
     "url": "https://bigdata.kepco.co.kr/openapi/v1/powerUsage/contractType.do",
     "params": {"year": "2024", "month": "01", "metroCd": "41",
                "apiKey": http.VIA_RELAY, "returnType": "json"}},
    {"name": "통계연보 지방세 징수실적",
     "url": "https://apis.data.go.kr/1741000/RecordLocalTaxCollectionYear/getRecordLocalTaxCollectionYear",
     "params": {"pageNo": "1", "numOfRows": "3", "type": "json"}},
]


def search_portal(keyword: str, timeout: int = 40) -> list[dict]:
    """포털 검색 결과에서 (번호, 유형, 제목) 을 뽑는다.

    포털 화면의 HTML 구조를 모르고 시작한다. 그래서 '/data/번호/유형.do'
    링크만 믿고, 제목은 그 링크 안의 글자에서 태그를 벗겨 얻는다. 하나도
    못 뽑으면 화면 앞부분을 그대로 남겨 다음 판에서 구조를 본다.
    """
    resp = http.get(PORTAL_SEARCH, {"keyword": keyword}, timeout=timeout)
    page = resp.text
    out = []
    seen = set()
    for m in re.finditer(
            r'href="(?:https?://www\.data\.go\.kr)?/data/(\d+)/(openapi|fileData|standard)\.do[^"]*"'
            r'[^>]*>(.*?)</a>', page, re.I | re.S):
        num, kind, inner = m.group(1), m.group(2), m.group(3)
        title = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        title = re.sub(r"\s+", " ", title).strip()
        key = (num, kind)
        if key in seen or not title:
            continue
        seen.add(key)
        out.append({"id": num, "kind": kind, "title": title})
    return out if out else [{"_raw_head": page[:1500], "_len": len(page)}]


def knock(cand: dict, timeout: int = 40) -> dict:
    """후보 하나를 두드려 상태와 본문 머리를 돌려준다. 죽지 않는다.

    **get_once 를 쓴다.** 첫 판에서 get() 을 썼더니 403·400 을 일시 장애로
    보고 네 번 다시 불렀고, 예외로 올라와 **본문을 못 봤다** — 상류가 무슨
    말로 거절했는지가 답인데 그 답을 버린 셈이다. 틀린 주소는 다시 불러도
    틀린 주소고, 거절 메시지는 성공 응답만큼 값진 자료다.
    """
    try:
        resp = http.get_once(cand["url"], dict(cand["params"]), timeout=timeout)
        head = resp.text[:800]
        return {"name": cand["name"], "url": cand["url"], "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "head": head, "keys": _top_keys(resp.text),
                "total": _total_count(resp.text), "n_items": _n_items(resp.text)}
    except Exception as exc:                          # noqa: BLE001
        return {"name": cand["name"], "url": cand["url"], "error": f"{type(exc).__name__}: {exc}"[:400]}


PORTAL_DETAIL = "https://www.data.go.kr/data/{id}/{kind}.do"


def detail(dataset_id: str, kind: str = "openapi", timeout: int = 40) -> dict:
    """데이터셋 상세 화면에서 **실제로 부를 것**을 뽑는다.

    검색으로 번호는 알아도 주소는 상세 화면에만 있다.
    - API 형(openapi·standard): 'apis.data.go.kr/…' 모양의 주소와 운영 이름
      (get… 낱말) — 명세서 없이 첫 호출을 만들 수 있게.
    - 파일 형(fileData): 내려받기 링크(fileDownload.do?atchFileId=…)와 파일
      이름·크기 — 러너가 대신 받을 수 있는지 보려고.
    화면 어디에 있든 모양으로 찍어 낸다. 구조를 알고 시작하지 않는다.
    """
    url = PORTAL_DETAIL.format(id=dataset_id, kind=kind)
    try:
        resp = http.get_once(url, {}, timeout=timeout)
    except Exception as exc:                          # noqa: BLE001
        return {"id": dataset_id, "kind": kind, "error": f"{type(exc).__name__}: {exc}"[:300]}
    page = html.unescape(resp.text)
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    out = {"id": dataset_id, "kind": kind, "status": resp.status_code,
           "title": re.sub(r"\s+", " ", title.group(1)).strip()[:120] if title else ""}
    # 2차(run 34805702626)에서 운영 이름은 잡혔는데 주소는 하나도 안 잡혔다.
    # 화면이 'http://' 없이 쓰거나 입력칸(value=)에 넣어 둔 것이다. 스킴을
    # 선택으로 두고, 못 잡으면 주소가 있을 법한 낱말 둘레를 그대로 남긴다.
    out["endpoints"] = sorted(set(re.findall(
        r"(?:https?://)?(?:apis\.data\.go\.kr|api\.odcloud\.kr|api\.data\.go\.kr)/[A-Za-z0-9_./\-{}]+",
        page)))[:20]
    # 3차에서 '활용신청' 발췌가 앞을 다 차지해 주소 발췌가 밀렸다. 주소가 먼저다.
    out["excerpts"] = _around(page, ("apis.data.go.kr", "End Point", "endPoint", "요청주소",
                                     "서비스URL", "fn_fileDataDown"), width=320, limit=8)
    # 4차: 15101360 · 15138716 의 주소는 발췌에 안 나왔다 — <script> 안에 있는
    # 것이다 (_around 는 스크립트를 벗긴다). 스크립트를 살려 한 번 더 본다.
    out["excerpts_raw"] = _around(page, ("apis.data.go.kr", "fileDetailSn"),
                                  width=360, limit=6, keep_script=True)
    out["operations"] = sorted(set(re.findall(r"\b(get[A-Z][A-Za-z0-9]+)\b", page)))[:40]
    out["downloads"] = sorted(set(re.findall(
        r"fileDownload\.do\?[^\"'<>\s]*atchFileId=[^\"'<>\s]+", page)))[:10]
    # 파일 이름은 .csv/.xlsx/.zip 로 끝나는 글자에서, 크기는 'MB'·'KB' 앞 숫자에서
    out["files"] = sorted(set(re.findall(
        r"[\w가-힣()\-_. ]{3,80}\.(?:csv|xlsx|xls|zip|txt)", page, re.I)))[:10]
    out["sizes"] = re.findall(r"\d[\d,.]*\s*(?:MB|KB|GB)", page)[:6]
    if not (out["endpoints"] or out["operations"] or out["downloads"]):
        out["_raw_head"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))[:600]
    return out


def _around(page: str, words: tuple, width: int = 260, limit: int = 6,
            keep_script: bool = False) -> list[str]:
    """낱말 둘레의 글자를 태그 벗겨 남긴다 — 구조를 모를 때의 실마리."""
    body = page if keep_script else re.sub(r"<script.*?</script>", " ", page, flags=re.S | re.I)
    flat = re.sub(r"\s+", " ", body)
    out = []
    for w in words:
        for m in re.finditer(re.escape(w), flat):
            a, b = max(0, m.start() - width // 2), m.end() + width // 2
            snip = re.sub(r"<[^>]+>", " ", flat[a:b])
            snip = re.sub(r"\s+", " ", snip).strip()
            if snip and snip not in out:
                out.append(f"[{w}] …{snip}…")
            if len(out) >= limit:
                return out
    return out


def _decode_table(raw: bytes) -> str | None:
    """CSV 바이트를 글자로. 한국 공공 파일은 cp949 가 흔하다."""
    for enc in ("utf-8-sig", "cp949", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def fetch_head(url: str, timeout: int = 60) -> dict:
    """파일 내려받기가 **로그인 없이** 되는지 — 머리만 받아 본다.

    3차(run 34806071394)에서 셋 다 200 이 왔는데 머리가 base64 글자였다.
    중계기가 텍스트 아닌 content-type 은 base64 로 감싸 보내기 때문이다
    (api/relay.js · x-relay-encoding). 그 머리표를 보고 풀어 읽는다.
    x-relay-bytes 가 진짜 크기다 — 중계기 함수는 큰 몸통을 못 넘기므로
    이 값이 '중계기로 받을 수 있는가' 를 정한다.
    """
    try:
        resp = http.get_once(url, {}, timeout=timeout)
    except Exception as exc:                          # noqa: BLE001
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"[:300]}
    raw = resp.content
    relayed_b64 = resp.headers.get("x-relay-encoding") == "base64"
    if relayed_b64:
        import base64
        try:
            raw = base64.b64decode(raw)
        except Exception:                             # noqa: BLE001
            pass
    text = _decode_table(raw[:6000])
    lines = text.splitlines() if text else []
    first = lines[0] if lines else ""
    return {"url": url, "status": resp.status_code,
            "content_type": resp.headers.get("x-relay-content-type") or resp.headers.get("content-type", ""),
            "relayed_base64": relayed_b64,
            "bytes": resp.headers.get("x-relay-bytes") or resp.headers.get("content-length", ""),
            "header": first[:400],
            "rows": [ln[:200] for ln in lines[1:4]],
            "looks_like": ("html" if (text or "").lstrip().lower().startswith(("<!doctype", "<html"))
                           else "table" if "," in first or "\t" in first
                           else "binary" if text is None else "other")}


def fetch_portal_file(url: str, timeout: int = 90) -> bytes:
    """포털 파일을 **중계기로** 받는다 — 러너 직접은 러너마다 막힌다.

    4차에서 직접 받기가 200 이었는데 5차(run 34806782924)에서는 셋 다
    ConnectTimeout 이었다. 해외 IP 차단이 러너에 따라 다르게 걸린다. 중계기
    경유는 두 번 다 200 이었고, 파일이 2.5MB 이하라 중계기 한도(약 4.5MB,
    base64 로 1.33배 불어도 3.4MB) 안이다. 그 길이 믿을 만하다.
    """
    import base64
    resp = http.get(url, {}, timeout=timeout)
    raw = resp.content
    if resp.headers.get("x-relay-encoding") == "base64":
        raw = base64.b64decode(raw)
    return raw


def profile_file(url: str, timeout: int = 90, limit: int = 30_000_000) -> dict:
    """파일을 **통째로** 러너가 직접 받아 무엇이 들었는지 본다.

    4차에서 셋이 0.4~2.5MB 로 작고 미국에서 200 이 왔다. 적재기를 쓰기 전에
    기간이 어디서 어디까지인지, 시군구가 몇인지, 업종 값이 무엇인지 알아야
    한다 — 머리 세 줄로는 '2016-10' 이 시작인지 유일한 달인지 모른다.
    """
    import io
    import pandas as pd
    try:
        raw = fetch_portal_file(url, timeout=timeout)
    except Exception as exc:                          # noqa: BLE001
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]}
    text = _decode_table(raw)
    if text is None:
        return {"url": url, "bytes": len(raw), "error": "글자로 못 읽음"}
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str)
    except Exception as exc:                          # noqa: BLE001
        return {"url": url, "bytes": len(raw), "error": f"CSV 파싱: {exc}"[:200]}
    out = {"url": url, "bytes": len(raw), "rows": int(len(df)), "columns": list(df.columns)[:12]}
    cols = {c: c for c in df.columns}
    # 기간 칸 — 이름에 기간·년·월·일자가 든 것
    for c in df.columns:
        if re.search(r"기간|년도|연도|년|월|일자|date", c, re.I):
            vals = df[c].dropna().astype(str)
            if not vals.empty:
                out.setdefault("periods", {})[c] = {"min": vals.min(), "max": vals.max(),
                                                    "n": int(vals.nunique())}
    for c in df.columns:
        if re.search(r"시군구|시도|법정동|계약종|용도|업종|산업", c):
            vals = df[c].dropna().astype(str)
            out.setdefault("dims", {})[c] = {"n": int(vals.nunique()),
                                             "sample": sorted(vals.unique())[:14]}
    return out


def fetch_direct(url: str, timeout: int = 20, limit: int = 65536) -> dict:
    """중계기 **없이** 러너에서 바로 받아 본다 — 큰 파일을 위해.

    중계기(Vercel 함수)는 몸통 크기에 한도가 있어 수십 MB 파일은 못 넘긴다.
    포털 파일 내려받기가 해외 IP 에도 열려 있으면 러너가 직접 받는 길이
    생긴다. 열려 있는지는 두드려 봐야 안다 — API 는 막혔지만 파일은
    다를 수 있다.
    """
    try:
        resp = http._sess().get(url, stream=True, timeout=timeout,
                                headers={"User-Agent": "redt-research/0.1"})
        chunk = b""
        for part in resp.iter_content(16384):
            chunk += part
            if len(chunk) >= limit:
                break
        resp.close()
        text = _decode_table(chunk[:4000])
        first = (text or "").splitlines()[0] if text else ""
        return {"url": url, "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "length": resp.headers.get("content-length", ""),
                "got": len(chunk), "header": first[:300],
                "looks_like": ("html" if (text or "").lstrip().lower().startswith(("<!doctype", "<html"))
                               else "table" if "," in first else "other")}
    except Exception as exc:                          # noqa: BLE001
        return {"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]}


def _total_count(text: str):
    """포털 봉투의 body.totalCount — 한 법정동에 몇 건인가."""
    import json
    try:
        body = json.loads(text)["response"]["body"]
        return body.get("totalCount")
    except Exception:                                 # noqa: BLE001
        return None


def _n_items(text: str):
    import json
    try:
        item = json.loads(text)["response"]["body"]["items"]["item"]
        return len(item) if isinstance(item, list) else (1 if item else 0)
    except Exception:                                 # noqa: BLE001
        return None


def _top_keys(text: str) -> list[str]:
    """JSON 이면 맨 위 열쇠들 — 무엇이 왔는지 한눈에 보려고."""
    import json
    try:
        obj = json.loads(text)
    except ValueError:
        return []
    if isinstance(obj, dict):
        keys = list(obj)[:8]
        # 포털 표준 봉투(response.body.items)는 한 겹 더 벗겨 보인다.
        body = (obj.get("response") or {}).get("body") if isinstance(obj.get("response"), dict) else None
        if isinstance(body, dict):
            keys += [f"body.{k}" for k in list(body)[:6]]
            items = body.get("items")
            if isinstance(items, dict):
                item = items.get("item")
                if isinstance(item, list) and item and isinstance(item[0], dict):
                    keys += [f"item.{k}" for k in list(item[0])[:60]]
        return keys
    return []


LOFIN_PAGES = [
    # 지방재정365 Open API 안내가 어디 있는지 모른다. 첫 화면과 흔한 경로를
    # 읽어 'api' 가 든 링크를 모은다 — 주소를 추측해 두드리는 대신 화면이
    # 가리키는 곳으로 간다.
    "https://www.lofin365.go.kr/",
    "https://www.lofin365.go.kr/portal/main.do",
    "https://lofin365.go.kr/",
]


def lofin_links(timeout: int = 40) -> list[dict]:
    """지방재정365 화면에서 API 관련 링크와 글귀를 모은다."""
    out = []
    for url in LOFIN_PAGES:
        try:
            resp = http.get_once(url, {}, timeout=timeout)
        except Exception as exc:                      # noqa: BLE001
            out.append({"url": url, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        page = html.unescape(resp.text)
        links = sorted(set(re.findall(r'href="([^"]*(?:api|API|openapi|Openapi|OpenAPI)[^"]*)"', page)))[:20]
        words = _around(page, ("Open API", "오픈API", "인증키", "openapi"), width=200, limit=6)
        out.append({"url": url, "status": resp.status_code, "len": len(page),
                    "links": links, "excerpts": words})
        if links:
            break
    return out


def probe(timeout: int = 40) -> dict:
    """세 마디 모두 — 포털 검색 + 후보 두드리기."""
    found = {}
    for group, words in KEYWORDS.items():
        found[group] = {}
        for w in words:
            try:
                found[group][w] = search_portal(w, timeout=timeout)
            except Exception as exc:                  # noqa: BLE001
                found[group][w] = [{"_error": f"{type(exc).__name__}: {exc}"[:300]}]
    knocked = [knock(c, timeout=timeout) for c in CANDIDATES]

    # 검색에서 나온 것 중 우리 셋과 이름이 맞는 것만 상세를 본다.
    # 시군구 하나짜리('○○시_지방세 징수현황')는 전국 패널에 못 쓰므로 뺀다.
    # 1차 결과(run 34805269914)에서 전력은 **전부 파일**, 건축인허가는 API 와
    # 파일 둘 다, 지방세는 통계연보 API 와 재정연감(결산) 파일이 나왔다.
    # 3차: 2차에서 새로 보인 한전 **API**(15101360)와 동단위 전력 파일
    # (15101533·15104908), 지방재정365 지방세 징수실적 API(15138716)를 더한다.
    want_api = re.compile(r"건축인\s*허가|건축인허가|기본정보표준|지방세 징수실적|"
                          r"계약종별 전력사용량|지방재정\s*365_?\s*(우리 지자체|세입|재정\s*자립도)", re.I)
    want_file = re.compile(r"시군구별\s*(계약종별|용도업종별)\s*전력|건축인허가 기본개요|"
                           r"재정\s*연감\(결산\)|동단위|법정동별 전력", re.I)
    skip = re.compile(r"(시|군|구|특별자치시)_", re.I)
    picked: list[tuple[str, str]] = []
    for by_word in found.values():
        for rows in by_word.values():
            for r in rows:
                t, k, i = r.get("title", ""), r.get("kind"), r.get("id")
                if not i or skip.search(t) or any(i == pi for pi, _ in picked):
                    continue
                if k in ("openapi", "standard") and want_api.search(t):
                    picked.append((i, k))
                elif k == "fileData" and want_file.search(t):
                    picked.append((i, k))
    details = [detail(i, k, timeout=timeout) for i, k in picked[:16]]

    # 상세에서 나온 내려받기 링크는 머리만 실제로 받아 본다 — 로그인 없이
    # 되는지가 '러너가 대신 받을 수 있는가' 를 정한다.
    downloads, direct, profiles = [], [], []
    for d in details:
        for u in d.get("downloads", [])[:1]:
            full = "https://www.data.go.kr/cmm/cmm/" + u.lstrip("/")
            got = fetch_head(full, timeout=timeout)
            got["dataset"] = d["id"]
            downloads.append(got)
            dd = fetch_direct(full)
            dd["dataset"] = d["id"]
            direct.append(dd)
            # 5차: 직접 받기는 러너마다 막힌다. 중계기 경유가 200 이면 프로파일한다.
            if got.get("status") == 200:
                pf = profile_file(full)
                pf["dataset"] = d["id"]
                pf["title"] = d.get("title", "")[:60]
                profiles.append(pf)
    return {"portal": found, "candidates": knocked, "details": details,
            "downloads": downloads, "direct": direct, "profiles": profiles,
            "lofin": lofin_links(timeout=timeout)}


def describe(result: dict) -> str:
    """사람이 읽는 요약. 0 은 소리를 내야 한다."""
    lines = []
    for group, by_word in result["portal"].items():
        lines.append(f"\n── 포털 검색 · {group} ──")
        for w, rows in by_word.items():
            real = [r for r in rows if "id" in r]
            if real:
                lines.append(f"  '{w}' → {len(real)}건")
                for r in real[:8]:
                    lines.append(f"     {r['id']:>8}  {r['kind']:<9} {r['title'][:70]}")
            elif rows and "_raw_head" in rows[0]:
                lines.append(f"  '{w}' → 링크를 못 뽑았습니다 (화면 {rows[0]['_len']:,}자 — "
                             f"구조가 다릅니다. JSON 에 앞부분을 남겼습니다)")
            else:
                lines.append(f"  '{w}' → {rows[0].get('_error', '?')}")
    lines.append("\n── 상세 화면에서 뽑은 주소 ──")
    for d in result.get("details", []):
        if "error" in d:
            lines.append(f"  ✗ {d['id']}  {d['error']}")
            continue
        lines.append(f"  {d['id']} [{d.get('kind', '')}]  {d.get('title', '')[:70]}")
        for u in d.get("endpoints", [])[:8]:
            lines.append(f"       {u}")
        if d.get("operations"):
            lines.append(f"       운영: {', '.join(d['operations'][:12])}")
        for u in d.get("downloads", [])[:4]:
            lines.append(f"       받기: {u[:120]}")
        if d.get("files"):
            lines.append(f"       파일: {' · '.join(f.strip() for f in d['files'][:5])}")
        if d.get("sizes"):
            lines.append(f"       크기: {' · '.join(d['sizes'][:4])}")
        for x in d.get("excerpts", [])[:3]:
            lines.append(f"       발췌 {x[:230]}")
        for x in d.get("excerpts_raw", [])[:3]:
            lines.append(f"       스크립트 {x[:300]}")
        if "_raw_head" in d:
            lines.append(f"       (주소를 못 뽑았습니다) {d['_raw_head'][:200]}")
    lines.append("\n── 내려받기 시험 · 중계기 경유 (로그인 없이 되는가) ──")
    for g in result.get("downloads", []):
        if "error" in g:
            lines.append(f"  ✗ {g.get('dataset')}  {g['error']}")
            continue
        lines.append(f"  {g['status']} {g.get('dataset')}  {g['looks_like']:<6} "
                     f"{g['content_type'][:40]}  {g['bytes']}바이트"
                     f"{'  (base64 풀었음)' if g.get('relayed_base64') else ''}")
        lines.append(f"       머리: {g['header'][:300]}")
        for r in g.get("rows", [])[:2]:
            lines.append(f"       행:   {r[:200]}")
    lines.append("\n── 내려받기 시험 · 러너 직접 (미국에서 열려 있는가) ──")
    for g in result.get("direct", []):
        if "error" in g:
            lines.append(f"  ✗ {g.get('dataset')}  {g['error']}")
            continue
        lines.append(f"  {g['status']} {g.get('dataset')}  {g['looks_like']:<6} "
                     f"{g['content_type'][:40]}  길이 {g['length'] or '?'} · 받은 {g['got']:,}")
        if g.get("header"):
            lines.append(f"       머리: {g['header'][:200]}")
    lines.append("\n── 지방재정365 — API 안내가 어디 있나 ──")
    for g in result.get("lofin", []):
        if "error" in g:
            lines.append(f"  ✗ {g['url']}  {g['error']}")
            continue
        lines.append(f"  {g['status']} {g['url']}  ({g['len']:,}자)")
        for u in g.get("links", [])[:12]:
            lines.append(f"       링크: {u[:140]}")
        for x in g.get("excerpts", [])[:4]:
            lines.append(f"       발췌 {x[:200]}")
    lines.append("\n── 파일 프로파일 (통째로 받아서) ──")
    for pf in result.get("profiles", []):
        if "error" in pf:
            lines.append(f"  ✗ {pf.get('dataset')}  {pf['error']}")
            continue
        lines.append(f"  {pf.get('dataset')}  {pf.get('title', '')}")
        lines.append(f"       {pf['rows']:,}행 · {pf['bytes']:,}바이트 · 열: {', '.join(pf['columns'])}")
        for c, v in pf.get("periods", {}).items():
            lines.append(f"       기간 {c}: {v['min']} ~ {v['max']} ({v['n']}개)")
        for c, v in pf.get("dims", {}).items():
            lines.append(f"       {c}: {v['n']}개 — {' · '.join(v['sample'][:10])}")
    lines.append("\n── 후보 두드리기 ──")
    for k in result["candidates"]:
        if "error" in k:
            lines.append(f"  ✗ {k['name']:<24} {k['error']}")
            continue
        keys = ", ".join(k["keys"]) if k["keys"] else "(JSON 아님)"
        extra = ""
        if k.get("total") is not None:
            extra = f"  전체 {k['total']}건 · 이 쪽 {k.get('n_items')}건"
        lines.append(f"  {k['status']} {k['name']:<24} {k['content_type'][:30]}{extra}")
        lines.append(f"       열쇠: {keys[:900]}")
        head = re.sub(r"\s+", " ", k["head"])[:220]
        lines.append(f"       머리: {head}")
    return "\n".join(lines)


# ── 파일 적재 — 전력 셋 → region_series ─────────────────────────────
#
# 4차(run 34806432813)에서 셋이 러너 직접 200 · 0.4~2.5MB 로 확정됐다.
# 파일은 **이름**으로 온다 (시도·시군구·법정동). 코드가 없다. 그래서
# region_umd(법정동코드·시군구 이름·전체 주소)로 대조표를 만들어 잇는다.
# 못 이은 이름은 **반드시 세어 말한다** — 이름이 안 맞아 빠진 시군구는
# 오류를 안 내고 조용히 사라지기 때문이다.

POWER_FILES = {
    # 데이터셋 번호: (파일 ID, 어떤 표인지)
    "15104908": ("FILE_000000003681825", "법정동·월 전력사용량"),
    "15069678": ("FILE_000000002314410", "시군구·용도업종(소)·월 판매량"),
    "15069679": ("FILE_000000002334166", "시군구·계약종별(대) 판매량"),
}
PORTAL_FILE = "https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId={fid}&fileDetailSn=1&insertDataPrcus=N"

# 시도 이름은 해마다 바뀐다 — 강원도→강원특별자치도(2023), 전북→전북특별자치도
# (2024), 전남+광주→전남광주통합특별시(2026). 파일과 대조표가 다른 해의
# 이름을 쓰면 한 글자도 안 맞는다. 앞 두 글자로 줄여 견준다.
_SIDO_KEY = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주",
    "대전": "대전", "울산": "울산", "세종": "세종", "경기": "경기", "강원": "강원",
    "충북": "충북", "충청북": "충북", "충남": "충남", "충청남": "충남",
    "전북": "전북", "전라북": "전북", "전남": "전남", "전라남": "전남",
    "경북": "경북", "경상북": "경북", "경남": "경남", "경상남": "경남", "제주": "제주",
}


def sido_key(name: str) -> str:
    """'강원특별자치도' → '강원', '전라남도' → '전남', '전남광주통합특별시' → '전남광주'."""
    n = re.sub(r"\s+", "", str(name or ""))
    if n.startswith("전남광주") or n.startswith("광주전남"):
        return "전남광주"
    for k in sorted(_SIDO_KEY, key=len, reverse=True):
        if n.startswith(k):
            return _SIDO_KEY[k]
    return n[:2]


def norm_sgg(name: str) -> str:
    """시군구 이름 정규화 — 띄어쓰기·'시 구' 붙임. '수원시 팔달구' → '수원시팔달구'."""
    return re.sub(r"\s+", "", str(name or ""))


def build_code_map(con) -> dict:
    """region_umd 에서 (시도키, 시군구) → 시군구코드 대조표.

    같은 (시도, 시군구) 에 코드가 둘 이상이면(옛·새 세대 코드가 함께 있는
    전남광주) **거래 표가 쓰는 쪽**을 고른다 — 패널이 거래와 붙기 때문이다.
    """
    rows = con.execute("""
        SELECT DISTINCT sigungu_cd, sigungu, full_nm FROM region_umd
        WHERE sigungu_cd IS NOT NULL AND full_nm IS NOT NULL
    """).fetchall()
    in_trade = {r[0] for r in con.execute(
        "SELECT DISTINCT sigungu_cd FROM trade WHERE sigungu_cd IS NOT NULL").fetchall()}
    cands: dict[tuple, set] = {}
    for code, sgg, full in rows:
        sido = str(full).split()[0] if full else ""
        key = (sido_key(sido), norm_sgg(sgg or ""))
        cands.setdefault(key, set()).add(str(code))
    out = {}
    for key, codes in cands.items():
        if len(codes) == 1:
            out[key] = next(iter(codes))
        else:
            pref = [c for c in codes if c in in_trade]
            out[key] = sorted(pref or codes)[-1]
    return out


# 옛 이름 → 지금 이름. 파일이 옛 이름을 쓰는 것을 첫 적재(run 34807148446)에서
# 봤다 — 인천 남구는 2018 년에 미추홀구가 됐다.
SGG_ALIAS = {("인천", "남구"): "미추홀구"}

# 시도 키가 갈라진 경우 — 파일은 '광주광역시'·'전라남도' 로, 대조표는
# '전남광주통합특별시'(2026) 로 온다. 둘 다 같은 땅이다.
SIDO_FALLBACK = {"광주": ("전남광주",), "전남": ("전남광주",), "전남광주": ("광주", "전남")}

# 시도를 옮긴 곳 — 파일은 옛 소속으로 쓴다 (run 34808317290 에서 남은 것).
# 군위군은 2023-07 대구로, 연기군은 2012-07 세종이 됐다.
SGG_MOVED = {("경북", "군위군"): ("대구", "군위군"), ("충남", "연기군"): ("세종", "")}


def resolve(code_map: dict, sido: str, sgg: str) -> str | None:
    """이름 둘 → 시군구코드. 못 찾으면 None (호출 쪽이 센다).

    첫 적재에서 못 이은 것 셋을 여기서 잇는다:
      · 광주·전남 ↔ 전남광주통합특별시 (시도 이름 세대 차)
      · 세종 — 시군구 칸이 비어 온다(단층제). 세종 코드 하나로 잇는다
      · 구가 있는 시 — 파일은 '수원시' 통째, 대조표는 '수원시 장안구'…
        구 코드들이 앞 네 자리를 같이 쓰므로 시 코드는 앞 네 자리 + '0'
    """
    sk = sido_key(sido)
    g = norm_sgg(sgg)
    if g in ("", "nan", "None"):
        g = ""
    g = SGG_ALIAS.get((sk, g), g)
    if (sk, g) in SGG_MOVED:
        sk, g = SGG_MOVED[(sk, g)]
    tries = [sk, *SIDO_FALLBACK.get(sk, ())]
    for s in tries:
        if (s, g) in code_map:
            return code_map[(s, g)]
    # 세종 — 시군구 이름이 없다. 그 시도의 코드가 하나면 그것이다.
    if sk == "세종" or g == "":
        codes = {c for (s, _g), c in code_map.items() if s == sk}
        if len(codes) == 1:
            return next(iter(codes))
        if sk == "세종":
            return "36110"
    for s in tries:
        # '수원시팔달구' 로 왔는데 대조표가 '팔달구' 인 경우, 또 그 반대
        for (cs, cg), code in code_map.items():
            if cs == s and cg and g and (cg.endswith(g) or g.endswith(cg)) and len(cg) >= 2 \
                    and not (g.endswith("시") and cg.startswith(g) and len(cg) > len(g)):
                return code
        # 구가 있는 시 — 그 시의 구 코드들이 앞 네 자리를 같이 쓰면 시 코드는 +'0'
        if g.endswith("시"):
            gu = {code for (cs, cg), code in code_map.items()
                  if cs == s and cg.startswith(g) and len(cg) > len(g)}
            heads = {c[:4] for c in gu}
            if gu and len(heads) == 1:
                return next(iter(heads)) + "0"
    return None


def power_rows(dataset: str, df, code_map: dict) -> tuple[list[tuple], dict]:
    """한 파일 → region_series 행들. (rows, 진단) 을 돌려준다.

    열 이름은 4차 탐침에서 본 것 그대로다. 파일이 바뀌면 여기가 깨지고,
    깨지면 소리가 난다 — 그것이 맞다.
    """
    import pandas as pd
    cols = {c.strip().strip('"'): c for c in df.columns}
    df = df.rename(columns={v: k for k, v in cols.items()})
    diag = {"dataset": dataset, "rows_in": int(len(df)), "unmatched": {}, "rows_out": 0}
    out = []

    def _code(sido, sgg):
        c = resolve(code_map, sido, sgg)
        if c is None:
            k = f"{sido} {sgg}"
            diag["unmatched"][k] = diag["unmatched"].get(k, 0) + 1
        return c

    def _num(v):
        try:
            return float(str(v).replace(",", "").strip())
        except ValueError:
            return None

    if dataset == "15104908":
        # 시도,시군구,법정동,년도,월,전체호수,전력사용량 — 법정동을 시군구로 모은다
        need = {"시도", "시군구", "년도", "월", "전력사용량"}
        if not need.issubset(df.columns):
            raise ValueError(f"{dataset}: 열이 다릅니다 {list(df.columns)[:8]}")
        df = df.assign(_code=[_code(a, b) for a, b in zip(df["시도"], df["시군구"])])
        df = df.dropna(subset=["_code"])
        df["_period"] = df["년도"].astype(str).str.zfill(4) + df["월"].astype(str).str.zfill(2)
        df["_kwh"] = pd.to_numeric(df["전력사용량"].astype(str).str.replace(",", ""), errors="coerce")
        g = df.groupby(["_code", "_period"], as_index=False)["_kwh"].sum()
        for r in g.itertuples(index=False):
            out.append((r._0 if hasattr(r, "_0") else r[0], r[1], float(r[2]),
                        "power_kwh_total", "kWh", f"data.go.kr {dataset}"))
    elif dataset in ("15069678", "15069679"):
        # 조회기간,시도,시군구,용도업종(소)|계약종별(대),판매량
        dim = "용도업종(소)" if "용도업종(소)" in df.columns else "계약종별(대)"
        need = {"조회기간", "시도", "시군구", dim, "판매량"}
        if not need.issubset(df.columns):
            raise ValueError(f"{dataset}: 열이 다릅니다 {list(df.columns)[:8]}")
        prefix = "power_kwh_use:" if dim.startswith("용도") else "power_kwh_contract:"
        for r in df.itertuples(index=False):
            row = dict(zip(df.columns, r))
            code = _code(row["시도"], row["시군구"])
            if code is None:
                continue
            per = re.sub(r"[^0-9]", "", str(row["조회기간"]))[:6]   # 2016-10 → 201610
            val = _num(row["판매량"])
            if val is None or len(per) < 6:
                continue
            out.append((code, per, val, prefix + str(row[dim]).strip(), "kWh",
                        f"data.go.kr {dataset}"))
    else:
        raise ValueError(f"모르는 파일 {dataset}")
    diag["rows_out"] = len(out)
    return out, diag


def load_power(con, only: list[str] | None = None, timeout: int = 120) -> list[dict]:
    """전력 파일 셋을 러너가 직접 받아 region_series 에 넣는다."""
    import io
    import pandas as pd
    code_map = build_code_map(con)
    if not code_map:
        raise RuntimeError("region_umd 가 비어 대조표를 못 만듭니다 — 먼저 읍면동을 채우십시오")
    diags = []
    for dataset, (fid, label) in POWER_FILES.items():
        if only and dataset not in only:
            continue
        url = PORTAL_FILE.format(fid=fid)
        try:
            raw = fetch_portal_file(url, timeout=timeout)
        except Exception as exc:                      # noqa: BLE001
            diags.append({"dataset": dataset, "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        text = _decode_table(raw)
        if text is None:
            diags.append({"dataset": dataset, "error": f"{len(raw):,}바이트 · 글자로 못 읽음"})
            continue
        df = pd.read_csv(io.StringIO(text), dtype=str)
        rows, diag = power_rows(dataset, df, code_map)
        diag["label"] = label
        if rows:
            con.executemany(
                "INSERT OR REPLACE INTO region_series"
                " (sigungu_cd, period, value, metric, unit, source) VALUES (?,?,?,?,?,?)",
                rows)
        diags.append(diag)
    return diags


# ── 한전 빅데이터 Open API — 시군구 × 계약종별 × 월 ─────────────────
#
# 탐침 7차(run 34808315954)가 확정한 것: 시군구(cityCd) 없이 시도(metroCd)만
# 주면 그 시도의 **모든 시군구**가 한 번에 온다. 항목은
#   year month metro(시도 이름) city(시군구 이름) cntr(계약종)
#   custCnt(호수) powerUsage(kWh) bill(원) unitCost(원/kWh) cntrPwr(계약전력)
# 그러면 전국 한 달이 시도 수만큼의 호출이다 — 열두 해가 3천 회 안이다.
# 파일 셋(2016-10~2017-03 · 2020 여섯 시점 · 2025)이 못 준 '여러 해 월별' 을
# 이것이 준다. 키는 Vercel 의 KEPCO_KEY — 중계기가 끼운다.

KEPCO_URL = "https://bigdata.kepco.co.kr/openapi/v1/powerUsage/contractType.do"
# 행정표준 시도 코드. 강원(42→51 · 2023)·전북(45→52 · 2024)은 두 세대를 다
# 두드린다 — 한전이 어느 쪽을 쓰는지 모른다. 빈 답은 series_crawl 에 0 으로
# 남아 다음 판에 다시 부르지 않는다.
KEPCO_METRO = ["11", "26", "27", "28", "29", "30", "31", "36", "41",
               "42", "51", "43", "44", "45", "52", "46", "47", "48", "50"]
KEPCO_SOURCE = "KEPCO contractType"


def kepco_page(year: int, month: int, metro: str, timeout: int = 40) -> list[dict]:
    """한 (연, 월, 시도). 봉투에 data 가 없으면 예외 — 조용히 0 이 되지 않는다."""
    res = http.get_json(KEPCO_URL, {"year": f"{year:04d}", "month": f"{month:02d}",
                                    "metroCd": metro, "returnType": "json"}, timeout=timeout)
    if isinstance(res, dict) and "data" in res:
        return res["data"] or []
    raise RuntimeError(f"한전: {str(res)[:200]}")


def kepco_rows(data: list[dict], code_map: dict) -> tuple[list[tuple], dict]:
    """한전 항목들 → region_series 행. 이름을 코드에 잇고 못 이은 것은 센다.

    지표: power_kwh_contract:{계약종} (kWh) · power_cust_contract:{계약종} (호) ·
    power_kwh_total (계약종 합). 계약종 이름의 빈칸('심  야')은 지운다.
    """
    diag = {"rows_in": len(data), "unmatched": {}}
    out = []
    totals: dict[tuple[str, str], float] = {}
    for d in data:
        metro, city = str(d.get("metro") or ""), str(d.get("city") or "")
        code = resolve(code_map, metro, city)
        if code is None:
            k = f"{metro} {city}".strip()
            diag["unmatched"][k] = diag["unmatched"].get(k, 0) + 1
            continue
        per = f"{str(d.get('year') or '')[:4]}{str(d.get('month') or '').zfill(2)}"
        if len(per) != 6:
            continue
        cntr = re.sub(r"\s+", "", str(d.get("cntr") or "")) or "기타"
        kwh, cust = _f(d.get("powerUsage")), _f(d.get("custCnt"))
        if kwh is not None:
            out.append((code, per, kwh, f"power_kwh_contract:{cntr}", "kWh", KEPCO_SOURCE))
            totals[(code, per)] = totals.get((code, per), 0.0) + kwh
        if cust is not None:
            out.append((code, per, cust, f"power_cust_contract:{cntr}", "호", KEPCO_SOURCE))
    for (code, per), v in totals.items():
        out.append((code, per, v, "power_kwh_total", "kWh", KEPCO_SOURCE))
    diag["rows_out"] = len(out)
    return out, diag


def load_power_api(con, years: list[int], max_calls: int = 1000, timeout: int = 40,
                   log=print, max_seconds: int = 3600) -> dict:
    """(연, 월, 시도) 를 돌며 한전 전력을 region_series 에 넣는다. 이어받는다.

    끝낸 열쇠는 series_crawl 에 남긴다(받은 행 수 포함). 빈 답(0행)도 남기되,
    최근 두 해의 빈 답은 '아직 안 나온 달' 일 수 있어 다음 판에 다시 부른다.
    해마다 먼저 한 번(6월 · 경기) 두드려 그 해에 자료가 있는지 본다 — 없는
    해에 228회를 쓰지 않기 위해서다.
    """
    from datetime import date, datetime, timezone
    code_map = build_code_map(con)
    if not code_map:
        raise RuntimeError("region_umd 가 비어 대조표를 못 만듭니다 — 먼저 읍면동을 채우십시오")
    done = {k: n for k, n in con.execute(
        "SELECT key, n FROM series_crawl WHERE source = 'kepco'").fetchall()}
    this_year = date.today().year
    st = {"calls": 0, "rows": 0, "empty": 0, "failed": 0, "skipped_years": [], "unmatched": {}, "timed_out": False}
    # 한전은 한 호출이 3초를 넘는다 (run 34809088634: 1,500회에 85분 이상 → 러너
    # 90분 한도에 죽어 캐시 저장이 안 됐다). 허가 훑기와 같은 시간 예산을 둔다.
    deadline = time.monotonic() + max_seconds

    def out_of_time() -> bool:
        if time.monotonic() > deadline:
            st["timed_out"] = True
            return True
        return False

    def mark(key: str, n: int) -> None:
        con.execute("INSERT OR REPLACE INTO series_crawl VALUES (?,?,?,?)",
                    ["kepco", key, n, datetime.now(timezone.utc)])

    for y in years:
        if st["calls"] >= max_calls:
            break
        # 그 해에 자료가 있는가 — 이미 받은 열쇠가 하나라도 있으면 묻지 않는다
        if not any(k.startswith(f"{y:04d}") and n > 0 for k, n in done.items()):
            try:
                probe = kepco_page(y, 6, "41", timeout=timeout)
            except Exception as exc:                      # noqa: BLE001
                st["failed"] += 1
                log(f"  ✗ {y} 살피기: {str(exc)[:160]}")
                if "apikey" in str(exc).lower() or "limit" in str(exc).lower():
                    log("  키·한도 문제입니다 — 이 판은 여기서 멈춥니다.")
                    break
                continue
            st["calls"] += 1
            if not probe:
                st["skipped_years"].append(y)
                log(f"  {y}: 한전에 자료가 없다 (6월·경기 0행) — 이 해는 건너뜀")
                continue
        stop = False
        for m in range(1, 13):
            for metro in KEPCO_METRO:
                key = f"{y:04d}{m:02d}:{metro}"
                n_prev = done.get(key)
                if n_prev is not None and not (n_prev == 0 and y >= this_year - 1):
                    continue
                if st["calls"] >= max_calls or out_of_time():
                    stop = True
                    break
                try:
                    data = kepco_page(y, m, metro, timeout=timeout)
                except Exception as exc:                  # noqa: BLE001
                    st["failed"] += 1
                    log(f"  ✗ {key}: {str(exc)[:160]}")
                    if "apikey" in str(exc).lower() or "limit" in str(exc).lower():
                        log("  키·한도 문제입니다 — 이 판은 여기서 멈춥니다.")
                        stop = True
                        break
                    continue
                st["calls"] += 1
                rows, diag = kepco_rows(data, code_map)
                for k, v in diag["unmatched"].items():
                    st["unmatched"][k] = st["unmatched"].get(k, 0) + v
                if rows:
                    con.executemany(
                        "INSERT OR REPLACE INTO region_series"
                        " (sigungu_cd, period, value, metric, unit, source) VALUES (?,?,?,?,?,?)", rows)
                    st["rows"] += len(rows)
                else:
                    st["empty"] += 1
                mark(key, len(data))
                done[key] = len(data)
            if stop:
                break
        if stop:
            break
    if st["timed_out"]:
        log(f"  시간 예산({max_seconds // 60}분)에 닿아 멈췄습니다 — 다음 판이 이어받습니다.")
    st["left"] = sum(1 for y in years for m in range(1, 13) for metro in KEPCO_METRO
                     if f"{y:04d}{m:02d}:{metro}" not in done and y not in st["skipped_years"])
    return st


# ── 지방재정365 Open API — 자치단체별 지방세 징수실적 (연) ─────────────
#
# 사용자가 준 명세(2026-09-14): 요청주소 /lf/hub/DFGDGG · 기본인자 Key(필수)
# Type(필수) pIndex pSize · 검색인자 fyr(회계연도) wa_laf_hg_nm(지역명)
# laf_hg_nm(자치단체명) · 출력 fyr, wa_laf_hg_nm, laf_cd(자치단체코드),
# laf_hg_nm, pfin_stl_amt2~5 (회계연도-3 … 회계연도), rate(3년 평균 증가율),
# lup_ord. 보유연도 2017~2024 · 연간 · 요청제한 없음.
#
# 이것은 **지방세 총액**이다 — 세목(법인지방소득세)이 갈라져 있지 않다. 사슬
# 셋째 마디의 대용치로 우선 쓰고, 세목별 표가 따로 있으면 그것으로 바꾼다.
# 한 행에 4개년이 실려 오므로 fyr 하나를 부르면 앞 세 해도 같이 채워진다.
# 키는 Vercel 의 LOFIN_KEY — 중계기가 Key 에 끼운다.

LOFIN_URL = "https://www.lofin365.go.kr/lf/hub/DFGDGG"
LOFIN_SOURCE = "lofin365 DFGDGG"
LOFIN_PAGE = 1000
# 세목별 징수율 (사용자가 찾음, 2026-09-14 16:27): /lf/hub/KAAAG · 검색인자 fyr ·
# 출력 fyr, dtmk_cd(세목코드), dtmk_nm(세목명), cltn_dcsn_aggr_amt(부과액),
# rcvmt_aggr_amt(징수액), rate(징수율). 보유 2010~2024 · 산정기준 '순계, 결산'.
# 화면에 자치단체 칸이 안 보였다 — 전국 순계일 수 있다. 자치단체 칸이 오면
# region_series 로, 없으면 market_series(전국) 로 넣는다. 첫 호출이 정한다.
LOFIN_ITEMS_URL = "https://www.lofin365.go.kr/lf/hub/KAAAG"
LOFIN_ITEMS_SOURCE = "lofin365 KAAAG"
# 도시군세 세목별 비중 (사용자가 찾음, 16:49): /lf/hub/KAAAE · 출력 fyr,
# cap_dv_cd/cap_dv_nm(시도군구분 — 시세·군세·구세), dtmk_cd/dtmk_nm(세목),
# wa_laf_cd/wa_laf_hg_nm(시도), rcvmt_aggr_amt(금액), rate(비중). 2010~2024.
# 시군구 하나하나는 아니고 **시도 × 시·군·구 구분 × 세목** 이다. 시도 단위
# 법인지방소득세 시계열은 여기서 나온다. 열쇠는 시도 코드 2자리로 둔다 —
# region_series.sigungu_cd 에 2자리가 들어가면 시도 행이라는 뜻이다.
LOFIN_SIDO_URL = "https://www.lofin365.go.kr/lf/hub/KAAAE"
LOFIN_SIDO_SOURCE = "lofin365 KAAAE"


def sido_codes(code_map: dict) -> dict:
    """시도 키('경기') → 시도 코드 2자리. 대조표의 시군구 코드 앞 두 자리에서 —
    같은 시도에 두 세대가 섞이면 많은 쪽을 고른다."""
    from collections import Counter
    cnt: dict[str, Counter] = {}
    for (sk, _g), code in code_map.items():
        cnt.setdefault(sk, Counter())[str(code)[:2]] += 1
    return {sk: c.most_common(1)[0][0] for sk, c in cnt.items()}


def lofin_sido_rows(rows: list[dict], codes: dict) -> tuple[list[tuple], dict]:
    """시도 × 구분 × 세목 행 → region_series (sigungu_cd = 시도 2자리)."""
    diag = {"rows_in": len(rows), "keys": sorted(rows[0].keys()) if rows else [], "unmatched": {}, "items": set()}
    out = []
    for r in rows:
        try:
            fyr = int(str(r.get("fyr"))[:4])
        except (TypeError, ValueError):
            continue
        sido = str(r.get("wa_laf_hg_nm") or "").strip()
        code = codes.get(sido_key(sido)) if sido else None
        if code is None:
            for alt in SIDO_FALLBACK.get(sido_key(sido), ()):
                code = codes.get(alt)
                if code:
                    break
        if code is None:
            diag["unmatched"][sido or "(빈 시도)"] = diag["unmatched"].get(sido or "(빈 시도)", 0) + 1
            continue
        item = re.sub(r"\s+", "", str(r.get("dtmk_nm") or r.get("dtmk_cd") or "")) or "기타"
        div = re.sub(r"\s+", "", str(r.get("cap_dv_nm") or r.get("cap_dv_cd") or "")) or "전체"
        diag["items"].add(item)
        v = _f(r.get("rcvmt_aggr_amt"))
        if v is not None:
            out.append((code, f"{fyr:04d}", v, f"local_tax_sido:{item}:{div}", "원", LOFIN_SIDO_SOURCE))
        sh = _f(r.get("rate"))
        if sh is not None:
            out.append((code, f"{fyr:04d}", sh, f"local_tax_sido_share:{item}:{div}", "%", LOFIN_SIDO_SOURCE))
    diag["items"] = sorted(diag["items"])
    return out, diag


def _lofin_unwrap(res) -> tuple[list[dict], dict]:
    """봉투를 벗겨 (row 목록, head) 를 돌려준다. 봉투 모양은 통계연보와 같다 —
    {"DFGDGG": [{"head": [...]}, {"row": [...]}]}. 못 벗기면 예외."""
    node = res
    if isinstance(node, dict) and "row" not in node and len(node) == 1:
        node = next(iter(node.values()))
    rows, head = None, {}
    if isinstance(node, list):
        for part in node:
            if isinstance(part, dict) and "row" in part:
                rows = part["row"]
            elif isinstance(part, dict) and "head" in part:
                for h in part["head"] or []:
                    if isinstance(h, dict):
                        head.update(h)
    elif isinstance(node, dict) and "row" in node:
        rows = node["row"]
    if rows is None:
        result = head.get("RESULT") or (res.get("RESULT") if isinstance(res, dict) else None)
        raise RuntimeError(f"지방재정365: {result or str(res)[:200]}")
    return (rows if isinstance(rows, list) else [rows]), head


def lofin_page(fyr: int, pindex: int = 1, psize: int = LOFIN_PAGE, timeout: int = 40,
               url: str = LOFIN_URL) -> tuple[list[dict], dict]:
    res = http.get_json(url, {"Type": "json", "pIndex": str(pindex), "pSize": str(psize),
                              "fyr": str(fyr)}, timeout=timeout)
    return _lofin_unwrap(res)


def lofin_item_rows(rows: list[dict], code_map: dict) -> tuple[list[tuple], list[tuple], dict]:
    """세목별 행 → (region_series 행, market_series 행, 진단).

    자치단체 이름 칸(laf_hg_nm)이 있으면 시군구별로, 없으면 전국 합계로 둔다.
    값은 징수액(rcvmt_aggr_amt); 부과액·징수율도 따로 지표로 남긴다.
    """
    diag = {"rows_in": len(rows), "keys": sorted(rows[0].keys()) if rows else [], "unmatched": {}, "items": set()}
    reg, nat = [], []
    for r in rows:
        try:
            fyr = int(str(r.get("fyr"))[:4])
        except (TypeError, ValueError):
            continue
        item = re.sub(r"\s+", "", str(r.get("dtmk_nm") or r.get("dtmk_cd") or "")) or "기타"
        diag["items"].add(item)
        vals = (("rcvmt_aggr_amt", "local_tax_item", "원"), ("cltn_dcsn_aggr_amt", "local_tax_levied", "원"),
                ("rate", "local_tax_rate", "%"))
        sido_nm = str(r.get("wa_laf_hg_nm") or "")
        name = strip_sido_prefix(str(r.get("laf_hg_nm") or "").strip(), sido_nm)
        if name:
            code = resolve(code_map, sido_nm, name)
            if code is None:
                k = f"{r.get('wa_laf_hg_nm', '')} {name}".strip()
                diag["unmatched"][k] = diag["unmatched"].get(k, 0) + 1
                continue
            for src, metric, unit in vals:
                v = _f(r.get(src))
                if v is not None:
                    reg.append((code, f"{fyr:04d}", v, f"{metric}:{item}", unit, LOFIN_ITEMS_SOURCE))
        else:
            for src, metric, unit in vals:
                v = _f(r.get(src))
                if v is not None:
                    nat.append((f"{metric}:{item}", f"{fyr:04d}", v, f"전국 {item} {metric}", "A", LOFIN_ITEMS_SOURCE))
    diag["items"] = sorted(diag["items"])
    return reg, nat, diag


def load_tax_items(con, years: list[int], timeout: int = 40, log=print, hub: str = "KAAAG") -> dict:
    """세목별 표를 회계연도마다 받아 넣는다 — KAAAG(세목별 징수율) · KAAAE(도시군세 세목별 비중)."""
    code_map = build_code_map(con)
    codes = sido_codes(code_map)
    url = LOFIN_SIDO_URL if hub == "KAAAE" else LOFIN_ITEMS_URL
    st = {"hub": hub, "calls": 0, "region_rows": 0, "nat_rows": 0, "failed": 0, "unmatched": {}, "items": set(), "keys": [], "years": {}}
    for y in years:
        pindex, got = 1, 0
        while True:
            try:
                rows, head = lofin_page(y, pindex, timeout=timeout, url=url)
            except Exception as exc:                      # noqa: BLE001
                st["failed"] += 1
                log(f"  ✗ {hub} {y} p{pindex}: {str(exc)[:200]}")
                break
            st["calls"] += 1
            if hub == "KAAAE":
                reg, diag = lofin_sido_rows(rows, codes)
                nat = []
            else:
                reg, nat, diag = lofin_item_rows(rows, code_map)
            st["keys"] = st["keys"] or diag["keys"]
            st["items"].update(diag["items"])
            for k, v in diag["unmatched"].items():
                st["unmatched"][k] = st["unmatched"].get(k, 0) + v
            if reg:
                con.executemany("INSERT OR REPLACE INTO region_series (sigungu_cd, period, value, metric, unit, source)"
                                " VALUES (?,?,?,?,?,?)", reg)
                st["region_rows"] += len(reg)
            if nat:
                con.executemany("INSERT OR REPLACE INTO market_series (series, period, value, label, cycle, source)"
                                " VALUES (?,?,?,?,?,?)", nat)
                st["nat_rows"] += len(nat)
            got += len(rows)
            total = head.get("list_total_count") or head.get("totalCount")
            if len(rows) < LOFIN_PAGE or (total and got >= int(total)):
                break
            pindex += 1
        st["years"][y] = got
    st["items"] = sorted(st["items"])
    return st


def strip_sido_prefix(name: str, sido: str) -> str:
    """'경기수원시' → '수원시' · '인천중구' → '중구' · '서울본청' → '본청'.

    지방재정365 는 자치단체명 앞에 시도 이름을 붙여 온다 (첫 적재 run
    34813423737 에서 34개 이름이 그래서 안 이어졌다). 같은 이름의 구가
    여러 시도에 있어 그렇게 쓰는 것이다 — 우리는 시도를 따로 받으므로 뗀다.
    """
    # 남는 글자가 한 자면 떼지 않는다 — '경기도' 에서 '경기' 를 떼면 '도' 만
    # 남아 이름이 아니게 된다 (시도 본청 행이 그렇게 온다).
    for pre in (sido, sido_key(sido)):
        if pre and name.startswith(pre) and len(name) - len(pre) >= 2:
            return name[len(pre):]
    return name


def lofin_rows(rows: list[dict], code_map: dict) -> tuple[list[tuple], dict]:
    """한 행 = 자치단체 × 회계연도, 값은 4개년 (amt2=fyr-3 … amt5=fyr).

    **시도 본청 행은 버리지 않는다.** 광역시·도의 시세(취득세 등)가 거기
    잡히므로 시도 코드 두 자리를 열쇠로 두어 시군구 행과 갈라 둔다
    (KAAAE 와 같은 규칙).
    """
    diag = {"rows_in": len(rows), "unmatched": {}, "sido_rows": 0, "laf_cd": {}}
    codes = sido_codes(code_map)
    out = []
    for r in rows:
        sido = str(r.get("wa_laf_hg_nm") or "").strip()
        name = strip_sido_prefix(str(r.get("laf_hg_nm") or "").strip(), sido)
        try:
            fyr = int(str(r.get("fyr"))[:4])
        except (TypeError, ValueError):
            continue
        if not name or name.endswith("본청") or (sido_key(name) == sido_key(sido)
                                                and norm_sgg(name) == norm_sgg(sido)):
            diag["sido_rows"] += 1
            code = codes.get(sido_key(sido))
            if code is None:
                diag["unmatched"][f"{sido} {name}".strip()] = \
                    diag["unmatched"].get(f"{sido} {name}".strip(), 0) + 1
                continue
        else:
            code = resolve(code_map, sido, name)
        if code is None:
            k = f"{sido} {name}".strip()
            diag["unmatched"][k] = diag["unmatched"].get(k, 0) + 1
            continue
        if r.get("laf_cd"):
            diag["laf_cd"][code] = str(r["laf_cd"])
        for k, off in (("pfin_stl_amt2", 3), ("pfin_stl_amt3", 2), ("pfin_stl_amt4", 1), ("pfin_stl_amt5", 0)):
            v = _f(r.get(k))
            if v is None:
                continue
            out.append((code, f"{fyr - off:04d}", v, "local_tax_total", "원", LOFIN_SOURCE))
    diag["rows_out"] = len(out)
    return out, diag


def load_local_tax(con, years: list[int], timeout: int = 40, log=print) -> dict:
    """회계연도마다 전 자치단체를 받아 region_series.local_tax_total 에 넣는다."""
    code_map = build_code_map(con)
    if not code_map:
        raise RuntimeError("region_umd 가 비어 대조표를 못 만듭니다 — 먼저 읍면동을 채우십시오")
    st = {"calls": 0, "rows": 0, "failed": 0, "unmatched": {}, "sido_rows": 0, "years": {}, "sample": None}
    for y in years:
        pindex, got = 1, 0
        while True:
            try:
                rows, head = lofin_page(y, pindex, timeout=timeout)
            except Exception as exc:                      # noqa: BLE001
                st["failed"] += 1
                log(f"  ✗ {y} p{pindex}: {str(exc)[:200]}")
                break
            st["calls"] += 1
            if rows and st["sample"] is None:
                st["sample"] = {k: rows[0].get(k) for k in ("fyr", "wa_laf_hg_nm", "laf_cd", "laf_hg_nm", "pfin_stl_amt5")}
            recs, diag = lofin_rows(rows, code_map)
            for k, v in diag["unmatched"].items():
                st["unmatched"][k] = st["unmatched"].get(k, 0) + v
            st["sido_rows"] += diag["sido_rows"]
            if recs:
                con.executemany(
                    "INSERT OR REPLACE INTO region_series"
                    " (sigungu_cd, period, value, metric, unit, source) VALUES (?,?,?,?,?,?)", recs)
                st["rows"] += len(recs)
            got += len(rows)
            total = head.get("list_total_count") or head.get("totalCount")
            if len(rows) < LOFIN_PAGE or (total and got >= int(total)):
                break
            pindex += 1
        st["years"][y] = got
    return st


# ── 포털 파일 하나를 이름으로 받아 data/raw 에 두기 ─────────────────
#
# 산업단지(15041930) · 철도역 좌표 같은 '파일형' 데이터셋은 로그인 없이
# 중계기로 받힌다 (5차). 번호만 주면 상세 화면에서 내려받기 링크를 찾아
# 받고, 무엇이 왔는지(형식·열·첫 줄) 말한다. 우리 이름으로 접는 일은 각
# 적재기(load-h3 등)가 한다 — 두 군데서 하면 어긋났을 때 어느 쪽이 틀렸는지
# 알 수 없다.

def sniff_ext(raw: bytes) -> str:
    """받은 바이트의 형식. zip 과 xlsx 는 둘 다 PK 로 시작한다 — 안에
    [Content_Types].xml 이 있으면 xlsx 다."""
    if raw[:2] == b"PK":
        return "xlsx" if b"[Content_Types].xml" in raw[:4000] else "zip"
    if raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls"
    return "csv"


def fetch_portal_dataset(dataset_id: str, timeout: int = 90) -> tuple[bytes, str, dict]:
    """(바이트, 확장자, 상세 화면 정보). 내려받기 링크가 없으면 예외."""
    d = detail(dataset_id, "fileData", timeout=timeout)
    links = d.get("downloads") or []
    if not links:
        raise RuntimeError(f"{dataset_id}: 상세 화면에 내려받기 링크가 없다 — "
                           f"{(d.get('_raw_head') or d.get('title') or '')[:200]}")
    url = "https://www.data.go.kr/cmm/cmm/" + html.unescape(links[0])
    raw = fetch_portal_file(url, timeout=timeout)
    return raw, sniff_ext(raw), d


def read_any_table(path) -> "pd.DataFrame":
    """csv/xlsx/xls 를 읽는다. xlsx 는 첫 시트, 머리글이 첫 줄이 아니면
    (제목 줄이 위에 있는 통계표) '지정' 이나 '단지' 가 든 줄을 머리글로 잡는다."""
    import pandas as pd
    path = str(path)
    if path.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(path, header=None)
        # 제목 줄('전국산업단지현황')에도 '단지' 가 들어 있다. 낱말이 든 줄 중
        # 채워진 칸이 가장 많은 줄이 머리글이다 — 제목 줄은 칸 하나뿐이다.
        best, hdr = -1, 0
        for i in range(min(15, len(raw))):
            cells = [str(v) for v in raw.iloc[i].tolist() if pd.notna(v)]
            if any(w in " ".join(cells) for w in ("지정", "단지", "명칭", "역명", "주소", "위도")):
                if len(cells) > best:
                    best, hdr = len(cells), i
        return pd.read_excel(path, header=hdr)
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"{path}: 인코딩을 알 수 없습니다")


# ── 건축인허가 훑기 — 건축HUB → permit ────────────────────────────
#
# 6차(run 34807146961)에서 확정한 것:
#   · 법정동 없이는 빈 몸통 → (시군구, 법정동) 단위로 부른다
#   · 쪽 크기 최대 100 (1000 을 달라 해도 100)
#   · 허가일 필터(startDate·endDate) 가 먹는다 — 개포동 전체 991 → 2024년 46
#   · 항목: archPmsDay(허가일) realStcnsDay(실착공) useAprDay(사용승인)
#          totArea(연면적) mainPurpsCdNm(주용도) jiyukCdNm(용도지역) archGbCdNm
#
# 전국은 법정동+리 약 2만 곳 × 쪽수다. 포털은 하루 호출 한도가 있고 러너는
# 90분에 죽으므로, **이어받기**가 설계의 중심이다: (시군구, 법정동) 마다 전체
# 건수와 받은 건수를 permit_crawl 에 남기고, 다음 판은 안 끝난 곳부터 간다.

HUB_URL = "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo"
HUB_PAGE = 100
# 허가일 하한. 전국 첫 판(run 34808645542)이 65분에 7,536회로 1,185개 동을
# 끝냈다 — 남은 19,057개 동이면 열여섯 판이다. 패널은 2006년부터이고 선행
# 시차는 길어야 3년이라 2000년 이전 허가는 쓸 데가 없다. 1940년대부터 쌓인
# 도시 동의 쪽수를 이것이 크게 줄인다.
HUB_SINCE = "20000101"


def _f(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def _i(v):
    try:
        return int(float(str(v).replace(",", ""))) if v not in (None, "") else None
    except ValueError:
        return None


def permit_row(item: dict) -> tuple | None:
    """건축HUB 한 항목 → permit 한 행. 열쇠가 없으면 None."""
    pk = item.get("mgmPmsrgstPk")
    if not pk:
        return None
    return (str(pk), str(item.get("sigunguCd") or ""), str(item.get("bjdongCd") or ""),
            item.get("platPlc"), item.get("archGbCdNm"), item.get("mainPurpsCdNm"),
            item.get("jiyukCdNm"), _f(item.get("platArea")), _f(item.get("archArea")),
            _f(item.get("totArea")), _i(item.get("hhldCnt")),
            str(item.get("archPmsDay") or "") or None, str(item.get("realStcnsDay") or "") or None,
            str(item.get("useAprDay") or "") or None, str(item.get("crtnDay") or "") or None)


# 빈 몸통(HTTP 200 에 0바이트)이 300회에 14회 왔다 (run 34807667125). 상류의
# 순간 결함이라 같은 쪽을 다시 부르면 온다. 한 쪽에 최대 이만큼 부른다.
HUB_TRIES = 3


def hub_page(sgg: str, bjd: str, page: int, timeout: int = 40) -> tuple[list[dict], int]:
    """한 쪽. (항목들, 전체 건수). 봉투가 이상하면 예외 — 조용히 0 이 되지 않는다.

    JSON 이 아닌 몸통(빈 200)은 HUB_TRIES 번까지 다시 부른다 — 그 뒤에도
    아니면 예외로 올려 그 법정동을 이 판의 실패로 남긴다 (다음 판이 이어받는다).
    """
    for attempt in range(1, HUB_TRIES + 1):
        try:
            res = http.get_json(HUB_URL, {"sigunguCd": sgg, "bjdongCd": bjd, "numOfRows": str(HUB_PAGE),
                                          "pageNo": str(page), "_type": "json",
                                          "startDate": HUB_SINCE, "endDate": "20991231"}, timeout=timeout)
            break
        except http.ApiError as exc:
            if "JSON 이 아닙니다" not in str(exc) or attempt == HUB_TRIES:
                raise
            time.sleep(1.5 * attempt)
    if "response" not in res:
        # 키 미등록 등은 OpenAPI_ServiceResponse 로 온다
        msg = (res.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader") or res
        raise RuntimeError(f"건축HUB: {msg}")
    body = res["response"].get("body") or {}
    total = int(body.get("totalCount") or 0)
    items = (body.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, total


def bjdong_targets(con, sigungu: list[str] | None = None) -> list[tuple[str, str]]:
    """훑을 (시군구, 법정동5) 목록 — region_umd 의 읍면동·리 전부.

    리(里)도 따로 부른다. 읍·면의 건물은 '공도읍 승두리'(25321) 같은 리 코드에
    잡히고 '공도읍'(25300) 자체에는 거의 없다. 리를 빼면 농촌이 통째로 빈다.
    """
    q = "SELECT DISTINCT sigungu_cd, substr(region_cd, 6, 5) FROM region_umd WHERE length(region_cd) = 10"
    rows = con.execute(q).fetchall()
    out = [(str(a), str(b)) for a, b in rows if a and b]
    if sigungu:
        keep = set(sigungu)
        out = [(a, b) for a, b in out if a in keep or any(a.startswith(k) for k in keep if len(k) == 2)]
    return sorted(out)


def crawl_permits(con, sigungu: list[str] | None = None, max_calls: int = 8000,
                  timeout: int = 40, log=print, workers: int = 1, max_seconds: int = 3900) -> dict:
    """(시군구, 법정동) 을 돌며 permit 을 채운다. 예산이 다하면 멈춘다 — 이어받는다.

    두 예산이 있다. 호출 수(max_calls)는 포털의 하루 한도를, 시간(max_seconds)은
    러너의 90분 한도를 지킨다. 러너가 시간에 죽으면 그 뒤의 캐시 저장이 안 돌아
    이 판이 받은 것이 **통째로** 사라진다 — 그래서 65분에 스스로 멈춘다.

    workers 만큼 법정동을 나란히 부른다. 한 호출이 1초쯤이라(run 34807667125:
    300회 5분) 혼자면 8,000회가 시간 예산을 넘는다. DB 쓰기는 자물쇠로 한 줄씩.
    """
    from datetime import datetime, timezone
    from concurrent.futures import ThreadPoolExecutor
    targets = bjdong_targets(con, sigungu)
    done = {(a, b): (t, f) for a, b, t, f in con.execute(
        "SELECT sigungu_cd, bjdong_cd, total, fetched FROM permit_crawl").fetchall()}
    todo = [(a, b) for a, b in targets if not (done.get((a, b)) and done[(a, b)][1] >= done[(a, b)][0])]
    log(f"대상 {len(targets):,}곳 · 끝난 {len(targets) - len(todo):,}곳 · 남은 {len(todo):,}곳"
        f" · 예산 {max_calls:,}회 · {max_seconds // 60}분 · 일꾼 {workers}")
    state = {"calls": 0, "rows": 0, "finished": 0, "failed": 0, "stop": False, "timed_out": False}
    lock = threading.Lock()
    deadline = time.monotonic() + max_seconds

    def exhausted() -> bool:
        """자물쇠 안에서 부른다. 시간에 닿았으면 그 사실을 남긴다."""
        if state["stop"] or state["calls"] >= max_calls:
            return True
        if time.monotonic() > deadline:
            state["timed_out"] = True
            return True
        return False

    def take_call() -> bool:
        with lock:
            if exhausted():
                return False
            state["calls"] += 1
            return True

    def work(sgg: str, bjd: str) -> None:
        prev = done.get((sgg, bjd))
        fetched = prev[1] if prev else 0
        page = fetched // HUB_PAGE + 1
        total = prev[0] if prev else None
        try:
            while take_call():
                items, total = hub_page(sgg, bjd, page, timeout=timeout)
                recs = [r for r in (permit_row(it) for it in items) if r]
                fetched = min(total, (page - 1) * HUB_PAGE + len(items))
                with lock:
                    if recs:
                        con.executemany(
                            "INSERT OR REPLACE INTO permit VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", recs)
                        state["rows"] += len(recs)
                    con.execute(
                        "INSERT OR REPLACE INTO permit_crawl VALUES (?,?,?,?,?)",
                        [sgg, bjd, total, fetched, datetime.now(timezone.utc)])
                if fetched >= total or not items:
                    with lock:
                        state["finished"] += 1
                    return
                page += 1
        except Exception as exc:                      # noqa: BLE001
            with lock:
                state["failed"] += 1
                log(f"  ✗ {sgg} {bjd} p{page}: {str(exc)[:160]}")
                if "SERVICE_KEY" in str(exc) or "LIMITED" in str(exc).upper():
                    log("  키·한도 문제입니다 — 이 판은 여기서 멈춥니다.")
                    state["stop"] = True

    if workers <= 1:
        for sgg, bjd in todo:
            with lock:
                if exhausted():
                    break
            work(sgg, bjd)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            # 한 번에 다 넣지 않는다 — 예산이 다한 뒤 2만 개가 헛돌지 않게 묶음으로.
            for i in range(0, len(todo), workers * 8):
                with lock:
                    if exhausted():
                        break
                list(pool.map(lambda t: work(*t), todo[i:i + workers * 8]))
    if state["timed_out"]:
        log(f"  시간 예산({max_seconds // 60}분)에 닿아 멈췄습니다 — 다음 판이 이어받습니다.")
    left = con.execute("""
        SELECT count(*) FROM (
          SELECT DISTINCT sigungu_cd, substr(region_cd, 6, 5) AS b FROM region_umd WHERE length(region_cd)=10
        ) t LEFT JOIN permit_crawl c ON c.sigungu_cd = t.sigungu_cd AND c.bjdong_cd = t.b
        WHERE c.total IS NULL OR c.fetched < c.total
    """).fetchone()[0]
    return {"calls": state["calls"], "rows": state["rows"], "finished": state["finished"],
            "failed": state["failed"], "left_total": left,
            "permits": con.execute("SELECT count(*) FROM permit").fetchone()[0]}


# 주용도 → 갈래. 정규식이 아니라 '들어 있는 말' 로 본다 — 주용도 이름이 길다
# ('제2종근린생활시설', '공장', '창고시설', '단독주택', '공동주택').
PURPS_GROUPS = [
    ("factory",    ("공장",)),
    ("warehouse",  ("창고", "물류")),
    ("housing",    ("주택", "아파트", "기숙사", "주거")),
    ("commercial", ("근린생활", "판매", "업무", "숙박", "위락", "관광")),
    ("farm",       ("동물", "식물", "축사", "농")),
]


def purps_group(name: str | None) -> str:
    n = str(name or "")
    for g, words in PURPS_GROUPS:
        if any(w in n for w in words):
            return g
    return "other"


def aggregate_permits(con) -> int:
    """permit → region_series: 시군구 × 허가월 × 갈래의 연면적 합과 건수."""
    import pandas as pd
    from datetime import date
    # 허가일에 1944년·3003년·'250007' 같은 값이 섞여 온다 (run 34807667125).
    # 1990-01 ~ 이번 달 밖은 버린다 — 패널은 2006년부터고, 그 앞 십몇 해는
    # 선행 시차용이다.
    this_month = date.today().strftime("%Y%m")
    df = con.execute("""
        SELECT sigungu_cd, substr(pms_day, 1, 6) AS period, main_purps, tot_area
        FROM permit WHERE pms_day IS NOT NULL AND length(pms_day) >= 6 AND sigungu_cd <> ''
          AND substr(pms_day, 1, 6) BETWEEN '199001' AND ?
    """, [this_month]).fetchdf()
    if df.empty:
        return 0
    df["grp"] = df["main_purps"].map(purps_group)
    df["tot_area"] = pd.to_numeric(df["tot_area"], errors="coerce").fillna(0.0)
    rows = []
    g = df.groupby(["sigungu_cd", "period", "grp"]).agg(area=("tot_area", "sum"), n=("tot_area", "size")).reset_index()
    for r in g.itertuples(index=False):
        rows.append((r.sigungu_cd, r.period, float(r.area), f"permit_area_m2:{r.grp}", "m2", "건축HUB 15136267"))
        rows.append((r.sigungu_cd, r.period, float(r.n), f"permit_count:{r.grp}", "건", "건축HUB 15136267"))
    tot = df.groupby(["sigungu_cd", "period"]).agg(area=("tot_area", "sum"), n=("tot_area", "size")).reset_index()
    for r in tot.itertuples(index=False):
        rows.append((r.sigungu_cd, r.period, float(r.area), "permit_area_m2:all", "m2", "건축HUB 15136267"))
        rows.append((r.sigungu_cd, r.period, float(r.n), "permit_count:all", "건", "건축HUB 15136267"))
    # 앞 판이 남긴 permit_* 행을 먼저 지운다 — INSERT OR REPLACE 는 같은 열쇠만
    # 덮으므로, 걸러낸 쓰레기 기간(194410 · 300309)이 옛 행으로 그대로 남는다
    # (run 34808645542 에서 실제로 그랬다).
    con.execute("DELETE FROM region_series WHERE metric LIKE 'permit_%'")
    con.executemany(
        "INSERT OR REPLACE INTO region_series (sigungu_cd, period, value, metric, unit, source)"
        " VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


# ── OpenDART (전자공시) — 대기업 신규시설투자 공시 ──────────────────────
#
# 사건 인자의 원천이다. '언제·어디에 얼마를 짓겠다' 는 발표가 삽을 뜨기
# 한참 전에 나오고, 땅값은 그 발표부터 움직인다. 원장(사람이 신문을 읽고
# 적는 표)으로도 되지만 공시는 **날짜가 분 단위로 박혀 있고 빠짐이 없다.**
#
# 인증키는 crtfc_key 로 중계기가 끼운다 (api/relay.js). 두 마디가 필요하다:
#   list.json     공시 목록 — corp_code · corp_name · report_nm · rcept_dt
#   company.json  기업개황 — adres(주소). 목록에는 주소가 없다.
DART_LIST = "https://opendart.fss.or.kr/api/list.json"
DART_COMPANY = "https://opendart.fss.or.kr/api/company.json"

# 공시유형. B=주요사항보고서 — '신규 시설투자등' 이 여기 산다.
DART_TYPES = {"B": "주요사항보고서", "A": "정기공시", "I": "거래소공시"}

# 우리가 찾는 보고서 이름. 상호는 담지 않는다 — 주소와 금액만 쓴다.
DART_WANT = ("신규시설투자", "신규 시설투자", "유형자산", "시설투자")


def dart_call(url: str, params: dict, timeout: int = 40) -> dict:
    """OpenDART 한 번 부르기. **status 를 먼저 본다.**

    OpenDART 는 HTTP 200 에 `{"status":"013","message":"조회된 데이타가
    없습니다."}` 를 실어 보낸다. 200 을 성공으로 읽으면 '자료가 없다' 가
    '한 건 왔다' 로 둔갑한다 — KOSIS 에서 이미 겪은 실수다.

    자리표를 넣어 부른다. 키는 중계기 밖으로 안 나간다.
    """
    p = dict(params)
    p["crtfc_key"] = "__via_relay__"
    resp = http.get(url, p, timeout=timeout)
    body = resp.json()
    status = str(body.get("status", ""))
    if status and status != "000":
        raise RuntimeError(f"OpenDART [{status}] {body.get('message', '')}")
    return body


def dart_list(bgn: str, end: str, ty: str = "B", page: int = 1,
              size: int = 100, timeout: int = 40) -> tuple[list[dict], int]:
    """기간 안의 공시 목록 한 쪽. (행, 전체쪽수) 를 돌려준다."""
    body = dart_call(DART_LIST, {
        "bgn_de": bgn, "end_de": end, "pblntf_ty": ty,
        "page_no": str(page), "page_count": str(size),
    }, timeout=timeout)
    return body.get("list", []), int(body.get("total_page", 1) or 1)


def dart_windows(bgn: str, end: str, days: int = 89) -> list[tuple[str, str]]:
    """기간을 89일 토막으로 자른다.

    **OpenDART 는 corp_code 없이 부르면 검색기간을 3개월로 묶는다**
    ([100] "corp_code가 없는 경우 검색기간은 3개월만 가능합니다"). 첫
    호출이 그것으로 거절당했다 — 키가 죽은 것이 아니라 업무 규칙이다.
    경계에서 하루가 새지 않게 89일로 자른다.
    """
    from datetime import datetime, timedelta            # noqa: PLC0415
    lo = datetime.strptime(bgn, "%Y%m%d")
    hi = datetime.strptime(end, "%Y%m%d")
    out = []
    while lo <= hi:
        cut = min(lo + timedelta(days=days), hi)
        out.append((lo.strftime("%Y%m%d"), cut.strftime("%Y%m%d")))
        lo = cut + timedelta(days=1)
    return out


def dart_list_all(bgn: str, end: str, ty: str = "B", max_pages: int = 20,
                  timeout: int = 40) -> list[dict]:
    """기간 전체를 89일씩·쪽마다 훑는다. 빈 토막은 [013] 으로 오니 넘긴다."""
    rows = []
    for lo, hi in dart_windows(bgn, end):
        page = 1
        while page <= max_pages:
            try:
                got, pages = dart_list(lo, hi, ty, page=page, timeout=timeout)
            except RuntimeError as exc:
                if "013" in str(exc):                   # 그 토막에 공시가 없다
                    break
                raise
            rows.extend(got)
            if page >= pages:
                break
            page += 1
    return rows


def dart_address(corp_code: str, timeout: int = 40) -> str:
    """회사 주소 한 줄. 목록에는 주소가 없어 따로 묻는다.

    **주소만 가져온다.** 대표자 이름(ceo_nm)은 사람 이름이라 손대지 않는다.
    """
    body = dart_call(DART_COMPANY, {"corp_code": corp_code}, timeout=timeout)
    return str(body.get("adres", "") or "")


# ── KOSIS 지방세통계 — 시군구 × 세목 (2026-09-14) ────────────────────
#
# 지방재정365 가 준 것은 **총액**뿐이었다 (2014~2024, 세목은 전국 순계).
# KOSIS 에 시도마다 표가 하나씩 있고 그 안이 **시군구 × 세목**이다.
#
#   TX_11007_A065  '1-11. 경기도'  1994~2024
#     OBJ 축1  15110AR0 시군구별   (경기 시군구 전부 + 합계)
#     OBJ 축2  15110AD6 세목별     (시세/군세/구세 아래 지방소비세·주민세·
#                                   지방소득세·재산세·자동차세·담배소비세…)
#     2023년 한 해가 990행, 단위 **천원**
#
# 그러니 시도 열아홉 표면 전국이 덮이고 **서른 해**가 온다. 기초자치단체
# 표(TX_11007_A116 계열)는 시군구마다 한 장이라 500장이 넘는데, 같은 것을
# 이쪽은 열아홉 장으로 준다.
#
# **표 번호를 짐작하지 않는다.** 1-9 울산이 A064 인데 1-11 경기가 A065 다 —
# 가운데 한 자리가 비어 있어 규칙을 세우면 틀린 표를 받는다. 이름으로 찾는다.
KOSIS_TAX_ORG = "110"
# 표 이름이 '1-11. 경기도' 꼴이고, 분류 경로에 '시도·시군구별' 이 든 것만.
KOSIS_TAX_NAME = re.compile(r"^\s*1-\d+\.\s*(.+?)\s*$")
# 검색은 한 번에 스무 건만 준다. 그래서 **시도 이름 자체**로도 찾는다 —
# 첫 판(run 95)이 표를 열셋만 찾아 서울·부산·대구·세종이 통째로 빠졌다.
# 시도 이름은 우리가 이미 아는 것이라 추측이 아니다.
_TAX_SIDO = ("서울특별시", "부산광역시", "대구광역시", "인천광역시",
             "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
             "경기도", "강원특별자치도", "충청북도", "충청남도",
             "전북특별자치도", "전라남도", "경상북도", "경상남도",
             "제주특별자치도")
# 시도 이름만으로 물으면 그 시도의 표가 수백 개라 우리 것이 스무 건 안에
# 안 든다 — 2판(run 96)에서 부산·대구·세종이 그렇게 빠졌다. **'징수실적'
# 을 붙여** 물으면 같은 스무 건이 우리 쪽으로 좁혀진다.
KOSIS_TAX_TERMS = tuple(
    ["징수실적", "지방소득세", "지방세통계", "시군구별 징수"]
    + [f"{s} 징수실적" for s in _TAX_SIDO]
    + list(_TAX_SIDO)
)

# 이름이 바뀌거나 없어진 시군구. **지어내지 않고 적어 둔다.**
#
#   청원군      2014 청주시에 통합 — 청주시로 잇는다
#   인천 중구   2026 영종구·제물포구로 갈림
#   인천 서구   2026 서구·검단구로 갈림
#
# 갈라진 쪽(인천 둘)은 **한 곳으로 잇지 않는다.** 하나를 골라 이으면 그
# 구의 옛 값이 실제보다 커진다. 합쳐진 쪽(청원군)만 잇는다 — 그것은
# 값이 새로 생기는 것이 아니라 같은 땅이 한 이름으로 묶인 것이다.
KOSIS_SGG_ALIAS = {("충북", "청원군"): "청주시"}


def kosis_tax_tables() -> dict[str, str]:
    """시도별 징수실적 표를 **이름으로** 찾는다. {tblId: 시도이름}."""
    from . import kosis                                  # noqa: PLC0415
    found: dict[str, str] = {}
    for term in KOSIS_TAX_TERMS:
        try:
            rows = kosis.search(term)
        except Exception:                                # noqa: BLE001
            continue
        for r in rows:
            tbl = str(r.get("TBL_ID", ""))
            nm = str(r.get("TBL_NM", ""))
            path = str(r.get("MT_ATITLE", ""))
            if not tbl.startswith("TX_11007_"):
                continue
            if "시도·시군구별" not in path:
                continue
            m = KOSIS_TAX_NAME.match(nm)
            if not m:
                continue
            sido = m.group(1)
            # '특별시 및 광역시 징수실적(총괄)' 같은 묶음 표는 뺀다 —
            # 시군구 축이 아니라 시도 축이다.
            if "총괄" in sido:
                continue
            found[tbl] = sido
    return found


def _sido_key(sido: str) -> str:
    """'충청북도' → '충북' 처럼 대조표가 쓰는 짧은 열쇠로."""
    s = str(sido or "").strip()
    for long_, short in (("특별자치도", ""), ("특별자치시", ""), ("광역시", ""),
                         ("특별시", ""), ("도", "")):
        if s.endswith(long_) and long_:
            s = s[: -len(long_)]
            break
    # '충청북' → '충북', '전라남' → '전남', '경상북' → '경북'
    if len(s) == 3 and s[1] in "청라상":
        s = s[0] + s[2]
    return s


def kosis_tax_rows(rows, sido: str, code_map: dict,
                   sido_cd: dict | None = None) -> tuple[list[tuple], dict]:
    """KOSIS 한 표의 행을 region_series 행으로 접는다.

    단위가 **천원**이라 1,000을 곱해 원으로 맞춘다 — 지방재정365 쪽이
    원이고, 둘을 나란히 볼 때 단위가 다르면 한쪽이 천 배로 보인다.
    """
    out, diag = [], {"unmatched": {}, "total": 0, "skipped": 0}
    for r in rows:
        sgg = str(r.get("C1_NM", "")).strip()
        item = str(r.get("C2_NM", "")).strip()
        year = str(r.get("PRD_DE", "")).strip()
        raw = r.get("DT")
        if not sgg or not item or not year:
            diag["skipped"] += 1
            continue
        diag["total"] += 1
        # '합계' 행은 시군구가 아니라 시도 총계다. 시군구 칸에 넣으면
        # 한 지역이 시도 전체 값을 가진 것처럼 보인다 — 버린다.
        if sgg in ("합계", "계", "소계"):
            continue
        try:
            val = float(str(raw).replace(",", ""))
        except (TypeError, ValueError):
            continue
        # 시도가 제 이름으로 앉은 행은 **본청**이다 (도세·시세의 시도 몫).
        # 버리면 광역시·도가 걷는 취득세가 통째로 사라진다. 지방재정365
        # 쪽과 같은 규칙으로 시도 코드 두 자리를 열쇠로 둔다.
        if sgg == sido or sgg == _sido_key(sido):
            code = (sido_cd or {}).get(_sido_key(sido))
            if not code:
                diag["unmatched"][f"{sido} 본청"] = diag["unmatched"].get(
                    f"{sido} 본청", 0) + 1
                continue
            out.append((code, year, val * 1000.0,
                        f"local_tax_kosis:{item}", "원", "KOSIS 지방세통계"))
            continue
        name = KOSIS_SGG_ALIAS.get((_sido_key(sido), sgg), sgg)
        code = resolve(code_map, sido, name)
        if not code:
            diag["unmatched"][f"{sido} {sgg}"] = diag["unmatched"].get(
                f"{sido} {sgg}", 0) + 1
            continue
        out.append((code, year, val * 1000.0,
                    f"local_tax_kosis:{item}", "원", "KOSIS 지방세통계"))
    return out, diag


def load_local_tax_kosis(con, years: list[str], *, code_map: dict | None = None,
                         max_seconds: int = 3000, log=print) -> dict:
    """시도 표를 하나씩 훑어 시군구 × 세목을 싣는다. **이어받는다.**

    열쇠는 (표, 해) 다. 한 판이 시간에 걸려 멈춰도 다음 판이 안 받은
    (표, 해)부터 간다 — 서른 해 × 열아홉 표면 570 호출이고, 한 호출이
    990행이라 한 판에 다 안 들어갈 수 있다.
    """
    from . import kosis                                  # noqa: PLC0415
    import time as _t                                    # noqa: PLC0415

    started = _t.time()
    if code_map is None:
        code_map = build_code_map(con)
    sido_cd = sido_codes(code_map)
    tables = kosis_tax_tables()
    st = {"tables": len(tables), "calls": 0, "rows": 0, "failed": 0,
          "skipped_done": 0, "unmatched": {}, "stopped": False}
    log(f"KOSIS 지방세통계 — 시도 표 {len(tables)}개: "
        f"{', '.join(sorted(tables.values()))}")
    if not tables:
        log("  ✗ 표를 하나도 못 찾았다 — 검색어나 분류 경로가 바뀐 것이다")
        return st

    done = {r[0] for r in con.execute(
        "SELECT key FROM series_crawl WHERE source = 'kosis_tax'").fetchall()}
    for tbl, sido in sorted(tables.items()):
        for y in years:
            key = f"{tbl}:{y}"
            if key in done:
                st["skipped_done"] += 1
                continue
            if _t.time() - started > max_seconds:
                st["stopped"] = True
                log(f"  ⏱ 시간 예산({max_seconds}초)에 멈춘다 — 다음 판이 이어받는다")
                return st
            try:
                rows = kosis.fetch_table_auto(KOSIS_TAX_ORG, tbl, y, y)
            except kosis.KosisError as exc:
                # 그 해에 자료가 없는 표가 있다 (세종은 2012년부터).
                # 오류로 세되 '받았다' 로 남겨 다시 묻지 않는다.
                con.execute(
                    "INSERT OR REPLACE INTO series_crawl (source, key, n, done_at)"
                    " VALUES ('kosis_tax', ?, 0, current_timestamp)", [key])
                st["failed"] += 1
                if st["failed"] <= 5:
                    log(f"  ✗ {sido} {y}: {str(exc)[:120]}")
                continue
            except Exception as exc:                     # noqa: BLE001
                st["failed"] += 1
                if st["failed"] <= 5:
                    log(f"  ✗ {sido} {y}: {type(exc).__name__} {str(exc)[:120]}")
                continue
            st["calls"] += 1
            recs, diag = kosis_tax_rows(rows, sido, code_map, sido_cd)
            for k, v in diag["unmatched"].items():
                st["unmatched"][k] = st["unmatched"].get(k, 0) + v
            if recs:
                con.executemany(
                    "INSERT OR REPLACE INTO region_series"
                    " (sigungu_cd, period, value, metric, unit, source)"
                    " VALUES (?,?,?,?,?,?)", recs)
                st["rows"] += len(recs)
            con.execute(
                "INSERT OR REPLACE INTO series_crawl (source, key, n, done_at)"
                " VALUES ('kosis_tax', ?, ?, current_timestamp)",
                [key, len(recs)])
    return st


def describe_local_tax_kosis(con, log=print) -> None:
    rows = con.execute("""
        SELECT substr(period, 1, 4) AS y, count(DISTINCT sigungu_cd) AS n,
               count(*) AS rows
        FROM region_series WHERE metric LIKE 'local_tax_kosis:%'
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    if not rows:
        log("  (아직 없음)")
        return
    log(f"  해 {len(rows)}개 · {rows[0][0]}~{rows[-1][0]}")
    for y, n, cnt in rows[:3] + rows[-3:]:
        log(f"    {y}: 시군구 {n}곳 · {cnt:,}행")
    items = con.execute("""
        SELECT replace(metric, 'local_tax_kosis:', '') AS item, count(*) AS n
        FROM region_series WHERE metric LIKE 'local_tax_kosis:%'
        GROUP BY 1 ORDER BY 2 DESC LIMIT 12
    """).fetchall()
    log(f"  세목 {len(items)}개(상위): " + " · ".join(f"{a}({b:,})" for a, b in items))


# ── 지방소득세 법인세분 (시도 × 세원별) ─────────────────────────────
#
# 시군구 표의 세목은 '지방소득세' 하나로 개인분·법인분이 합쳐져 있다.
# 갈린 것은 이 표뿐이고, 지역 축이 **시도까지**다 (§5-4·§5-6).
#
#   DT_11007_A646  '8-2. 과세유형별 지방소득세 과세현황'  2010~2024
#     축  15110AA3 시도별 · 15110AR9 세원별(법인세분 …)
#
# 시군구 고유의 법인 활동은 여기서 못 얻는다. 그래도 싣는 까닭은 시군구
# 총액을 **시도 법인 비중으로 안분**할 재료가 되기 때문이다. 안분한 값은
# 안분한 값이라고 이름에 남긴다 — 나중에 원자료로 착각하지 않게.
KOSIS_CORP_TBL = "DT_11007_A646"
# 이 표는 축이 **셋**이다 (시도별 · 징수방법별 · 세원별). 둘만 물어도
# 200 이 오는데 그때는 세원 축이 통째로 빠진다 — run 98 에서 '보통징수 ·
# 신고납부 · 특별징수' 만 받았다. 바닥을 셋으로 못박는다.
KOSIS_CORP_AXES = 3
# 시도 칸에 섞여 오는 소계 행. 시도가 아니므로 싣지 않는다.
KOSIS_CORP_SKIP = ("합계", "계", "전국", "총계", "시계", "군계", "구계", "지방")


def load_local_tax_corp(con, years: list[str], *, code_map: dict | None = None,
                        log=print) -> dict:
    """시도 × 세원별 지방소득세. 열쇠는 시도 코드 두 자리다."""
    from . import kosis                                  # noqa: PLC0415
    if code_map is None:
        code_map = build_code_map(con)
    codes = sido_codes(code_map)
    st = {"calls": 0, "rows": 0, "failed": 0, "unmatched": {}, "items": set()}
    done = {r[0] for r in con.execute(
        "SELECT key FROM series_crawl WHERE source = 'kosis_tax_corp'").fetchall()}
    for y in years:
        key = f"{KOSIS_CORP_TBL}:{y}"
        if key in done:
            continue
        try:
            rows = kosis.fetch_table_auto(KOSIS_TAX_ORG, KOSIS_CORP_TBL, y, y,
                                          min_axes=KOSIS_CORP_AXES)
        except Exception as exc:                         # noqa: BLE001
            st["failed"] += 1
            if st["failed"] <= 3:
                log(f"  ✗ {y}: {type(exc).__name__} {str(exc)[:120]}")
            continue
        st["calls"] += 1
        recs = []
        for r in rows:
            sido = str(r.get("C1_NM", "")).strip()
            # 축이 셋이라 C2·C3 중 어느 쪽이 세원인지는 표가 정한다.
            # **'법인세분' 이 든 쪽**을 세원으로 삼고, 다른 쪽은 이름에
            # 같이 적는다 — 징수방법까지 알면 나중에 가려 쓸 수 있다.
            c2 = str(r.get("C2_NM", "")).strip()
            c3 = str(r.get("C3_NM", "")).strip()
            item, how = (c3, c2) if c3 else (c2, "")
            raw = r.get("DT")
            if not sido or not item or sido in KOSIS_CORP_SKIP:
                continue
            try:
                val = float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                continue
            code = codes.get(_sido_key(sido))
            if not code:
                st["unmatched"][sido] = st["unmatched"].get(sido, 0) + 1
                continue
            name = f"{item}:{how}" if how and how not in ("합계", "계") else item
            st["items"].add(name)
            recs.append((code, y, val * 1000.0,
                         f"local_tax_corp:{name}", "원", "KOSIS 지방세통계"))
        if recs:
            con.executemany(
                "INSERT OR REPLACE INTO region_series"
                " (sigungu_cd, period, value, metric, unit, source)"
                " VALUES (?,?,?,?,?,?)", recs)
            st["rows"] += len(recs)
        con.execute(
            "INSERT OR REPLACE INTO series_crawl (source, key, n, done_at)"
            " VALUES ('kosis_tax_corp', ?, ?, current_timestamp)",
            [key, len(recs)])
    log(f"지방소득세 세원별 — 호출 {st['calls']} · 행 {st['rows']:,}"
        f" · 실패 {st['failed']}")
    if st["items"]:
        log(f"  세원: {' · '.join(sorted(st['items']))}")
    if st["unmatched"]:
        log(f"  못 이은 시도: {st['unmatched']}")
        if {"광주광역시", "전라남도"} & set(st["unmatched"]):
            log("    ※ 광주·전남은 2026 통합으로 우리 대조표에 옛 이름이"
                " 없다 — 통합 코드로 이을지는 따로 정한다")
    return st
