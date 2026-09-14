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
    # 같은 것이 포털에도 있는지 — 있으면 DATA_GO_KR_KEY 로 된다.
    {"name": "포털 한전 전력사용량 (후보)",
     "url": "https://apis.data.go.kr/B551236/PowerUsageService/getContractTypeUsage",
     "params": {"year": "2024", "month": "01", "metroCd": "41", "cityCd": "41550",
                "_type": "json"}},
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
                "head": head, "keys": _top_keys(resp.text)}
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


def _around(page: str, words: tuple, width: int = 260, limit: int = 6) -> list[str]:
    """낱말 둘레의 글자를 태그 벗겨 남긴다 — 구조를 모를 때의 실마리."""
    flat = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>", " ", page, flags=re.S | re.I))
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
                    keys += [f"item.{k}" for k in list(item[0])[:25]]
        return keys
    return []


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
    downloads, direct = [], []
    for d in details:
        for u in d.get("downloads", [])[:1]:
            full = "https://www.data.go.kr/cmm/cmm/" + u.lstrip("/")
            got = fetch_head(full, timeout=timeout)
            got["dataset"] = d["id"]
            downloads.append(got)
            dd = fetch_direct(full)
            dd["dataset"] = d["id"]
            direct.append(dd)
    return {"portal": found, "candidates": knocked, "details": details,
            "downloads": downloads, "direct": direct}


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
    lines.append("\n── 후보 두드리기 ──")
    for k in result["candidates"]:
        if "error" in k:
            lines.append(f"  ✗ {k['name']:<24} {k['error']}")
            continue
        keys = ", ".join(k["keys"][:12]) if k["keys"] else "(JSON 아님)"
        lines.append(f"  {k['status']} {k['name']:<24} {k['content_type'][:30]}")
        lines.append(f"       열쇠: {keys}")
        head = re.sub(r"\s+", " ", k["head"])[:220]
        lines.append(f"       머리: {head}")
    return "\n".join(lines)
