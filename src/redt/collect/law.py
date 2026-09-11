"""자치법규(조례) — 국가법령정보센터 Open API (docs/dev-constraints-and-costs.md §7).

건폐율·용적률의 값과 개발행위허가의 경사·임목·표고 기준은 법이 아니라
**시·군 도시계획조례** 에 있다. 226 곳을 손으로 읽을 수 없어 API 로 받는다.

  목록  https://www.law.go.kr/DRF/lawSearch.do?OC=…&target=ordin&type=JSON&query=도시계획 조례
  본문  https://www.law.go.kr/DRF/lawService.do?OC=…&target=ordin&type=JSON&MST=…

OC 는 open.law.go.kr 가입 아이디(이메일의 @ 앞부분)다. 키처럼 다룬다 —
러너에는 시크릿 LAW_OC, 중계기(api/relay.js)도 LAW_OC 를 끼워 넣는다.
law.go.kr 이 해외 IP 를 막는지는 probe 가 잰다. 이 컨테이너에서는 아예
못 나간다 (egress 차단, 2026-09-11).

응답 JSON 의 정확한 키를 미리 모른다 (문서 사이트도 여기서 못 연다). 그래서
본문은 **통째로 저장**하고, 조문은 키 이름에 '조문' 이 든 사전을 재귀로
찾아 뽑는다. 한 건을 받아 보면 probe 가 키를 적어 준다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..config import PROCESSED, ROOT, VIA_RELAY
from .http import get_once, polite_sleep

SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE = "https://www.law.go.kr/DRF/lawService.do"
# 같은 자료의 둘째 길 — 공공데이터포털 '법제처 국가법령정보 공유서비스'(15000115).
# apis.data.go.kr 은 중계기가 DATA_GO_KR_KEY 를 끼워 주고, 법제처처럼 호출 IP 를
# 등록하라고 하지 않는다 (run 23: law.go.kr 은 서울 중계기로도 "IP·도메인 등록" 거부).
# 활용가이드(2022-10-19, 사용자 제공): 자치법규 목록은 law/ordinSearchList.do,
# 파라미터는 serviceKey·target=ordin·query·numOfRows·pageNo, 응답은 XML 로
# totalCnt·law[]{자치법규일련번호, 자치법규명, 자치법규ID, 자치법규상세링크(…MST=)}.
# **본문 조회는 포털에 없다** — 상세링크가 law.go.kr DRF 를 가리키는데 그쪽은
# 호출 IP 등록을 요구한다. 그래서 본문은 law.go.kr 의 웹 페이지(ordinInfoP.do)를
# 중계기로 읽어 본다 (probe 가 잰다).
PORTAL_SEARCH = "https://apis.data.go.kr/1170000/law/ordinSearchList.do"
PORTAL_SERVICE = "https://apis.data.go.kr/1170000/law/lawService.do"
WEB_ORDIN = "https://www.law.go.kr/LSW/ordinInfoP.do"
RAW_DIR = PROCESSED / "ordinance"          # 본문 통째 (Actions 캐시에 남는다)
OUT_DIR = ROOT / "data" / "ordinance"      # 뽑은 조문 (저장소에 커밋)

# 우리가 찾는 조문 — 제목이나 본문에 이 말이 들면 남긴다.
KEYWORDS = ("건폐율", "용적률", "개발행위허가", "경사도", "임목", "표고", "입목",
            "성장관리", "자연취락", "개발진흥")


REFERER = "https://toji.fyi/"   # open.law.go.kr 에 등록한 서비스 주소 — 검증에 쓰일 수 있다


def _oc() -> str:
    """중계기가 켜져 있으면 늘 중계기로 (서울 IP · 중계기가 LAW_OC 를 끼운다).
    법제처는 호출 서버의 IP·도메인을 등록분과 견주므로(run 22 응답) 미국 러너의
    직접 호출은 통하지 않을 가능성이 크다."""
    from ..config import relay
    if relay().enabled:
        return VIA_RELAY
    return os.getenv("LAW_OC") or VIA_RELAY


def _direct(url: str, params: dict, oc: str | None = None):
    """중계기를 거치지 않고 바로 부른다 — 러너 IP 로. 등록 도메인을 Referer 로 싣는다.
    oc="test" 는 법제처 안내서의 공개 견본 계정 — 포털 상세링크가 이것을 쓴다."""
    import requests
    oc = oc or os.getenv("LAW_OC") or "test"
    return requests.get(url, params={**params, "OC": oc}, timeout=30,
                        headers={"User-Agent": "Mozilla/5.0 redt-research", "Referer": REFERER})


def _call(url: str, params: dict) -> tuple[dict | list | None, str]:
    """JSON 이면 (payload, ''), 아니면 (None, 왜) — HTML 오류 페이지가 온다.
    중계기가 목적지를 모르면(403 relayError) 직접 부른다."""
    resp = get_once(url, {"OC": _oc(), "target": "ordin", "type": "JSON", **params}, timeout=40)
    if resp.status_code == 403 and "relayError" in resp.text:
        try:
            resp = _direct(url, {"target": "ordin", "type": "JSON", **params})
        except Exception as e:                      # noqa: BLE001
            return None, f"중계기 거부 + 직접 호출 실패 ({type(e).__name__}: {str(e)[:120]})"
    body = resp.text
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code} " + re.sub(r"\s+", " ", body[:200])
    try:
        payload = json.loads(body)
    except ValueError:
        return None, "JSON 아님: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:240]
    # 법제처는 오류도 200 으로 준다: {"result": "사용자 정보 검증에 실패하였습니다.", "msg": …}
    if isinstance(payload, dict) and "msg" in payload and not _find_rows(payload):
        return None, f"{payload.get('result', '')} {payload.get('msg', '')}"[:240]
    return payload, ""


def _xml_obj(node):
    """XML 을 dict/list 로 — 조문 걷기(articles)가 JSON 과 같은 길을 타게."""
    kids = list(node)
    if not kids:
        return (node.text or "").strip()
    out: dict = {}
    for k in kids:
        v = _xml_obj(k)
        if k.tag in out:
            if not isinstance(out[k.tag], list):
                out[k.tag] = [out[k.tag]]
            out[k.tag].append(v)
        else:
            out[k.tag] = v
    return out


def _portal_raw(url: str, params: dict, kind: str = "XML"):
    # 가이드의 파라미터만 보낸다 — type 같은 낯선 이름은 게이트웨이가 HTTP_ERROR 04 로 돌려보낸다.
    return get_once(url, {"serviceKey": VIA_RELAY, "target": "ordin", **params}, timeout=40)


def portal_list(query: str, page: int = 1, rows: int = 100) -> tuple[list[dict], int, str]:
    """포털 자치법규 목록 한 쪽. (행들, totalCnt, 오류)."""
    import xml.etree.ElementTree as ET
    resp = _portal_raw(PORTAL_SEARCH, {"query": query, "numOfRows": str(rows), "pageNo": str(page)})
    body = resp.text
    if resp.status_code != 200:
        return [], 0, f"HTTP {resp.status_code} " + re.sub(r"\s+", " ", body[:200])
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return [], 0, "XML 아님: " + re.sub(r"\s+", " ", body)[:200]
    obj = _xml_obj(root)
    if isinstance(obj, dict) and "cmmMsgHeader" in obj:
        return [], 0, json.dumps(obj["cmmMsgHeader"], ensure_ascii=False)[:200]
    out = _find_rows(obj)
    total = _find_int(obj, ("totalCnt",))
    return out, total, ""


def web_body(ordin_seq: str) -> tuple[str, str]:
    """law.go.kr 웹 페이지의 본문 HTML — 중계기(서울)로. (html, 오류)."""
    resp = get_once(WEB_ORDIN, {"OC": VIA_RELAY, "ordinSeq": str(ordin_seq), "chrClsCd": "010202"}, timeout=40)
    if resp.status_code != 200:
        return "", f"HTTP {resp.status_code} " + re.sub(r"\s+", " ", resp.text[:160])
    return resp.text, ""


WEB_HOST = "https://www.law.go.kr"
# 틀 페이지(ordinInfoP.do)는 본문을 하위 요청으로 실어 온다(run 29: 66,180자에
# 건폐율 없음). 어느 주소인지 모르니 페이지 안의 .do 주소를 모아 차례로 재 본다.
WEB_FIXED = ("/LSW/ordinInfoR.do", "/LSW/ordinLsInfoR.do", "/LSW/ordinInfoRP.do", "/LSW/ordinPrint.do")


def web_candidates(seq: str, html: str) -> list[str]:
    """틀 페이지 HTML 에서 본문을 실어 올 법한 .do 주소 — ordinSeq 를 채워 절대 주소로.
    순서: 페이지에 있던 것(ordin·Info·Cntnts 가 이름에 든 것) → 고정 후보."""
    seen: list[str] = []

    def add(path: str, query: str = ""):
        if not path.startswith("/"):
            path = "/LSW/" + path
        q = dict(re.findall(r"([\w]+)=([^&]*)", query))
        q["ordinSeq"] = str(seq)
        q.setdefault("chrClsCd", "010202")
        url = WEB_HOST + path + "?" + "&".join(f"{k}={v}" for k, v in q.items() if not re.search(r"[<>{}'+]", v))
        if url not in seen:
            seen.append(url)

    for m in re.finditer(r"""["'(=]\s*((?:https?://www\.law\.go\.kr)?/?[\w./-]*?/?[\w-]+\.do)(\?[^"'\s<>)]*)?""", html):
        path = re.sub(r"^https?://www\.law\.go\.kr", "", m.group(1))
        name = path.rsplit("/", 1)[-1]
        if re.search(r"ordin|Info|Cntnts|cont|Jo", name) and not re.search(r"Search|List|Login|Popup|Ajax|Menu", name, re.I):
            add(path, (m.group(2) or "").lstrip("?"))
    for path in WEB_FIXED:
        add(path)
    return seen


def web_scan(seq: str, html: str, limit: int = 8) -> list[dict]:
    """후보를 차례로 받아 본다 — 어디에 조문(건폐율)이 있는지. 결과는 로그와 파일로."""
    out = []
    for i, url in enumerate(web_candidates(seq, html)[:limit]):
        try:
            resp = get_once(url, {"OC": VIA_RELAY}, timeout=40)
            status, text = resp.status_code, resp.text
        except Exception as e:                      # noqa: BLE001
            status, text = 0, f"{type(e).__name__}: {str(e)[:120]}"
        hit = "건폐율" in text
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
        out.append({"url": url, "status": status, "len": len(text), "has_gunpye": hit, "snippet": plain[:160]})
        print(f"   후보 {i + 1}: {url.split('?')[0].rsplit('/', 1)[-1]} → HTTP {status} · {len(text):,}자 · 건폐율 {'있음' if hit else '없음'}")
        if hit:
            print("      " + plain[:200])
        if text and status == 200:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            (RAW_DIR / f"probe-web-{seq}-{i + 1}.html").write_text(text, encoding="utf-8")
        polite_sleep()
    return out


def _portal(url: str, params: dict) -> tuple[dict | list | None, str]:
    """공공데이터포털 길. serviceKey 는 중계기가 끼운다. 포털은 XML 이 기본이다
    (run 25: type=JSON 은 게이트웨이가 HTTP_ERROR 04 로 돌려보냈다). XML 을 dict 로 바꾼다."""
    import xml.etree.ElementTree as ET
    resp = _portal_raw(url, params, "XML")
    body = resp.text
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code} " + re.sub(r"\s+", " ", body[:200])
    try:
        payload = json.loads(body)
    except ValueError:
        try:
            payload = _xml_obj(ET.fromstring(body))
        except ET.ParseError:
            return None, "JSON/XML 아님: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:240]
    text = json.dumps(payload, ensure_ascii=False)[:300]
    if not _find_rows(payload) and not articles(payload):
        return None, "행 없음: " + text
    return payload, ""


_ROUTE = {"portal": False}


def use_portal() -> bool:
    return _ROUTE["portal"] or os.getenv("LAW_ROUTE") == "portal"


def search(query: str, page: int = 1, display: int = 100) -> tuple[list[dict], int, str]:
    """목록 한 쪽. (행들, 전체 건수, 오류)."""
    params = {"query": query, "display": str(display), "page": str(page)}
    if use_portal():
        payload, why = _portal(PORTAL_SEARCH, params)
    else:
        payload, why = _call(SEARCH, params)
        if payload is None and "검증에 실패" in why:
            # 법제처가 호출 IP 를 거부하면 포털 길로 갈아탄다 (이 실행 동안 계속).
            payload, why2 = _portal(PORTAL_SEARCH, params)
            if payload is not None:
                _ROUTE["portal"] = True
            else:
                why = f"{why} / 포털: {why2}"
    if payload is None:
        return [], 0, why
    rows = _find_rows(payload)
    total = _find_int(payload, ("totalCnt", "total", "전체건수"))
    return rows, total, ""


def body(mst: str) -> tuple[dict | None, str]:
    if use_portal():
        return _portal(PORTAL_SERVICE, {"MST": str(mst)})
    return _call(SERVICE, {"MST": str(mst)})


ROW_KEYS = ("자치법규일련번호", "자치법규명", "자치법규ID", "법령명한글", "법령ID", "MST")


def _find_rows(payload) -> list[dict]:
    """목록 행들. XML 을 dict 로 바꾸면 한 건짜리 목록은 list 가 아니라 dict 하나로
    온다 (run 28: totalCnt 1 인데 0건으로 읽었다) — 행 열쇠가 든 dict 는 한 행이다."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        if any(k in payload for k in ROW_KEYS):
            return [payload]
        for v in payload.values():
            got = _find_rows(v)
            if got:
                return got
    return []


def _find_int(payload, names) -> int:
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in names:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
            got = _find_int(v, names)
            if got:
                return got
    return 0


def _pick(row: dict, *needles: str) -> str:
    for k, v in row.items():
        if any(n in k for n in needles) and v not in (None, ""):
            return str(v)
    return ""


def list_all(query: str, max_pages: int = 10) -> tuple[list[dict], str]:
    """목록을 끝까지 넘긴다. 행마다 mst·이름·기관을 우리 이름으로 붙인다."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        rows, total, why = search(query, page=page)
        if why:
            return out, why
        if not rows:
            break
        for r in rows:
            out.append({**r,
                        "_mst": _pick(r, "MST", "자치법규일련번호", "ordinSeq", "ID"),
                        "_name": _pick(r, "자치법규명", "lawNm", "명"),
                        "_org": _pick(r, "지자체기관명", "기관명", "org")})
        if len(out) >= total > 0:
            break
        polite_sleep(0.3)
    return out, ""


def articles(payload) -> list[dict]:
    """본문 JSON 에서 조문 사전을 재귀로 찾는다 — 키 이름에 '조문' 이 든 것."""
    found: list[dict] = []

    def walk(x):
        if isinstance(x, dict):
            if any("조문내용" in k or "조문제목" in k for k in x):
                found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(payload)
    return found


def flat_text(x) -> str:
    """조문 사전 안의 문자열을 순서대로 다 잇는다 — 항·호 속 문장까지.
    건폐율 수치는 대개 항·호에 있어 조문내용만 보면 놓친다."""
    parts: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for k, w in v.items():
                if k in ("조문번호", "조문여부", "조문키", "조문시행일자", "조문변경여부"):
                    continue
                walk(w)
        elif isinstance(v, list):
            for w in v:
                walk(w)
        elif isinstance(v, (str, int)) and str(v).strip():
            t = re.sub(r"\s+", " ", str(v)).strip()
            if not parts or t not in parts[-1]:
                parts.append(t)
    walk(x)
    return " ".join(parts)


def art_no(raw: str) -> str:
    """조문번호 → 사람 표기. '000100'→제1조, '005802'→제58조의2, '58'→제58조."""
    raw = str(raw or "").strip()
    if re.fullmatch(r"\d{6}", raw):
        jo, ui = int(raw[:4]), int(raw[4:])
        return f"제{jo}조" + (f"의{ui}" if ui else "")
    if re.fullmatch(r"\d+", raw):
        return f"제{int(raw)}조"
    return raw


def relevant(payload) -> list[dict]:
    out = []
    for a in articles(payload):
        text = flat_text(a)
        if any(k in text for k in KEYWORDS):
            no = _pick(a, "조문번호", "조번호")
            out.append({"no": no, "label": art_no(no), "title": _pick(a, "조문제목"), "text": text[:8000]})
    return out


def html_articles(html: str) -> list[dict]:
    """웹 본문(ordinInfoR.do)의 HTML 을 조문으로 자른다 — XML 이 안 올 때의 예비."""
    text = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html))
    text = re.sub(r"\s+", " ", text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    chunks = re.split(r"(?=제\d+조(?:의\d+)?\s*\()", text)
    out = []
    for c in chunks:
        m = re.match(r"제(\d+)조(?:의(\d+))?\s*\(([^)]*)\)", c)
        if not m:
            continue
        no = f"{int(m.group(1)):04d}{int(m.group(2) or 0):02d}"
        out.append({"조문번호": no, "조문제목": m.group(3).strip(), "조문내용": c.strip()})
    return out


ZONES = ("보전관리", "생산관리", "계획관리", "보전녹지", "생산녹지", "자연녹지", "농림", "자연환경보전")


def _pct(text: str, zone: str) -> str:
    m = re.search(zone + r"지역\s*[:：]?\s*(?:은|는)?\s*(\d{1,3})\s*(?:퍼센트|%|％)", text)
    return m.group(1) if m else ""


def summarize(rel: list[dict]) -> dict:
    """관심 조문에서 숫자만 뽑는다 — 표 한 줄. 못 찾으면 빈칸(원문을 보라는 뜻)."""
    out: dict = {}
    bc = " ".join(a["text"] for a in rel if "건폐율" in a["title"] and "용적률" not in a["title"])
    fa = " ".join(a["text"] for a in rel if "용적률" in a["title"])
    dv = " ".join(a["text"] for a in rel if "개발행위" in a["title"] or "개발행위" in a["text"][:60])
    for z in ZONES:
        out[f"건폐율_{z}"] = _pct(bc, z)
        out[f"용적률_{z}"] = _pct(fa, z)
    m = re.search(r"경사도[^.。]{0,60}?(\d{1,2})\s*도", dv)
    out["경사도_도"] = m.group(1) if m else ""
    m = re.search(r"표고[^.。]{0,80}?(\d{2,4})\s*(?:미터|m|ｍ)", dv)
    out["표고_m"] = m.group(1) if m else ""
    m = re.search(r"(?:입목|임목)축적[^.。]{0,80}?(\d{2,3})\s*(?:퍼센트|%|％)", dv)
    out["입목축적_pct"] = m.group(1) if m else ""
    return out


def probe(query: str = "안성시 도시계획 조례") -> dict:
    """한 건을 받아 본다 — 뚫리는지, JSON 키가 무엇인지."""
    out: dict = {"query": query, "oc_set": bool(os.getenv("LAW_OC"))}
    print(f"LAW_OC {'있음' if out['oc_set'] else '없음 — OC=test 로 닿는지만 본다'}")
    # 1) 직접 — 미국에서 열리는가
    try:
        r = _direct(SEARCH, {"target": "ordin", "type": "JSON", "query": query, "display": "3"})
        snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:200]
        out["direct"] = {"status": r.status_code, "snippet": snippet}
        print(f"직접 호출: HTTP {r.status_code} · {snippet}")
    except Exception as e:                          # noqa: BLE001
        out["direct"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
        print(f"직접 호출 실패: {out['direct']['error']}")
    # 2) 공공데이터포털 목록 (가이드대로) → 첫 행의 일련번호로 law.go.kr 웹 본문
    rows_p, total_p, why_p = portal_list(query, rows=5)
    out["portal"] = {"n": len(rows_p), "total": total_p, "why": why_p,
                     "keys": sorted(rows_p[0].keys()) if rows_p else []}
    print(f"포털 목록: {len(rows_p)}건 / 전체 {total_p}" + (f" — {why_p}" if why_p else ""))
    for r in rows_p[:5]:
        print("  ", {k: str(v)[:80] for k, v in r.items()})
    if rows_p:
        seq = _pick(rows_p[0], "자치법규일련번호", "일련번호", "ID")
        link = _pick(rows_p[0], "상세링크", "링크")
        # 포털 상세링크는 OC=test(공개 견본 계정)로 법제처 DRF 를 가리킨다 — 그 계정이면
        # IP 등록 없이 열리는지, 러너에서 바로 재 본다.
        for kind in ("HTML", "XML"):
            try:
                r = _direct(SERVICE, {"target": "ordin", "MST": seq, "type": kind}, oc="test")
                plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
                hit = "건폐율" in r.text
                out[f"drf_test_{kind}"] = {"status": r.status_code, "len": len(r.text), "has_gunpye": hit, "snippet": plain[:200]}
                print(f"DRF OC=test {kind} (MST={seq}): HTTP {r.status_code} · {len(r.text):,}자 · 건폐율 {'있음' if hit else '없음'} · {plain[:120]}")
                if hit:
                    RAW_DIR.mkdir(parents=True, exist_ok=True)
                    (RAW_DIR / f"probe-drf-{seq}.{kind.lower()}").write_text(r.text, encoding="utf-8")
            except Exception as e:                  # noqa: BLE001
                out[f"drf_test_{kind}"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
                print(f"DRF OC=test {kind} 실패: {out[f'drf_test_{kind}']['error']}")
        if link:
            print(f"상세링크: {link}")
        html, why_w = web_body(seq)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        out["web"] = {"seq": seq, "why": why_w, "len": len(html), "has_gunpye": "건폐율" in html,
                      "snippet": text[:300]}
        print(f"웹 본문 (ordinSeq={seq}): {why_w or 'HTTP 200'} · {len(html):,}자 · 건폐율 {'있음' if '건폐율' in html else '없음'}")
        print("   " + text[:300])
        if html:
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            (RAW_DIR / f"probe-web-{seq}.html").write_text(html, encoding="utf-8")
            dos = sorted(set(re.findall(r"[\w./-]+\.do(?:\?[^\"'\s<>)]*)?", html)))
            print(f"   틀 페이지 안의 .do 주소 {len(dos)}개: " + " · ".join(d[:70] for d in dos[:40]))
            out["web_scan"] = web_scan(seq, html)
    # 3) 우리 경로 — 법제처(중계기) → 거부되면 포털
    rows, total, why = search(query, display=5)
    out["route"] = "portal" if use_portal() else ("relay" if _oc() == VIA_RELAY else "direct")
    print(f"경로 {out['route']}: {len(rows)}건" + (f" — {why}" if why else ""))
    out["search"] = {"n": len(rows), "total": total, "why": why,
                     "keys": sorted(rows[0].keys()) if rows else []}
    print(f"목록: {len(rows)}건 / 전체 {total}" + (f" — {why}" if why else ""))
    for r in rows[:5]:
        print("  ", {k: str(v)[:40] for k, v in list(r.items())[:8]})
    if rows:
        mst = _pick(rows[0], "MST", "자치법규일련번호", "ordinSeq", "ID")
        payload, why = body(mst)
        out["body"] = {"mst": mst, "why": why}
        if payload is not None:
            arts = articles(payload)
            rel = relevant(payload)
            out["body"].update({"top_keys": _keys(payload), "articles": len(arts),
                                "article_keys": sorted(arts[0].keys()) if arts else [],
                                "relevant": len(rel)})
            print(f"본문: 조문 {len(arts)}개 · 관심 조문 {len(rel)}개 · 위 키 {_keys(payload)[:8]}")
            for a in rel[:6]:
                print(f"   {a['no']} {a['title']}: {a['text'][:100]}")
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            (RAW_DIR / f"probe-{mst}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                                       encoding="utf-8")
        else:
            print(f"본문 실패: {why}")
    (PROCESSED / "law_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _keys(payload) -> list[str]:
    if isinstance(payload, dict):
        ks = list(payload.keys())
        if len(ks) == 1 and isinstance(payload[ks[0]], dict):
            return [ks[0]] + list(payload[ks[0]].keys())
        return ks
    return []


# '군계획 조례' 가 '도시·군계획 조례' 도 부분일치로 잡는다. '·' 를 검색어에 넣으면
# 포털이 &middot; 로 바꿔 XML 이 깨진다(run 31).
QUERIES = ("도시계획 조례", "도시계획조례", "군계획 조례")
NAME_RE = re.compile(r"(도시|군|도시·군)계획조례$")


def portal_all(query: str, max_pages: int = 30, rows: int = 100) -> tuple[list[dict], str]:
    """포털 목록을 끝까지 넘긴다 (run 29·30: 이 길이 통한다)."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        got, total, why = portal_list(query, page=page, rows=rows)
        if why:
            return out, why
        out.extend(got)
        if not got or len(out) >= total:
            break
        polite_sleep(0.3)
    return out, ""


def wanted(rows: list[dict]) -> list[dict]:
    """도시계획조례(·군계획조례)만 — 시행규칙·다른 조례·폐지분·옛 기관('구 전라남도') 제외.
    같은 기관·이름은 최신 시행일 하나."""
    best: dict[tuple, dict] = {}
    for r in rows:
        name = _pick(r, "자치법규명", "lawNm", "명")
        if "시행규칙" in name or not NAME_RE.search(re.sub(r"\s", "", name)):
            continue
        if "폐지" in _pick(r, "제개정구분명"):
            continue
        org = _pick(r, "지자체기관명", "기관명", "org")
        if org.startswith("구 ") or org.startswith("구)"):
            continue
        key = (org, re.sub(r"\s", "", name))
        row = {**r, "_mst": _pick(r, "자치법규일련번호", "MST", "ordinSeq", "ID"), "_name": name, "_org": org,
               "_eff": _pick(r, "시행일자"), "_pub": _pick(r, "공포일자")}
        if key not in best or row["_eff"] > best[key]["_eff"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: (r["_org"], r["_name"]))


def body_xml(mst: str) -> tuple[dict | None, str]:
    """DRF 본문 XML — 공개 견본 계정(OC=test)으로 러너에서 바로 (run 30: 71,215자·건폐율 있음).
    안 되면 중계기로 같은 주소(중계기가 OC=test 를 살려 보내면 통한다). (payload, 오류)."""
    import xml.etree.ElementTree as ET
    params = {"target": "ordin", "MST": str(mst), "type": "XML"}
    tries = (lambda: _direct(SERVICE, params, oc="test"),
             lambda: get_once(SERVICE, {"OC": "test", **params}, timeout=40))
    why = ""
    for call in tries:
        try:
            r = call()
        except Exception as e:                      # noqa: BLE001
            why = f"{type(e).__name__}: {str(e)[:100]}"
            continue
        if r.status_code != 200:
            why = f"HTTP {r.status_code}"
            continue
        try:
            obj = _xml_obj(ET.fromstring(r.text))
        except ET.ParseError:
            why = "XML 아님: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:120]
            continue
        if articles(obj):
            return obj, ""
        why = "조문 없음: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:120]
    return None, why


def web_fragment(seq: str) -> tuple[str, str]:
    """law.go.kr 본문 조각(ordinInfoR.do) — 중계기(서울)로. run 30: 276,547자·건폐율 있음."""
    resp = get_once(WEB_HOST + "/LSW/ordinInfoR.do", {"OC": VIA_RELAY, "ordinSeq": str(seq), "chrClsCd": "010202"},
                    timeout=40)
    if resp.status_code != 200 or "제1조" not in resp.text:
        return "", f"HTTP {resp.status_code} · {len(resp.text):,}자"
    return resp.text, ""


def slug_of(r: dict) -> str:
    return re.sub(r"[^\w가-힣]+", "_", f"{r['_org']}_{r['_name']}").strip("_")


def fetch(query: str = "", limit: int | None = None) -> dict:
    """전국 도시계획조례 → data/ordinance/{기관_이름}.json (관심 조문) + index.json + summary.csv.
    재개 가능 — 본문 원문(RAW_DIR/{mst}.json|.html)이 있으면 다시 안 받는다."""
    import csv
    queries = [q.strip() for q in (query or "").split(",") if q.strip()] or list(QUERIES)
    rows: list[dict] = []
    for q in queries:
        got, why = portal_all(q)
        print(f"목록 '{q}': {len(got)}건" + (f" — {why}" if why else ""))
        rows.extend(got)
    want = wanted(rows)
    print(f"목록 합계 {len(rows)}건 → 도시계획조례 {len(want)}건 (기관별 최신 하나)")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched = failed = 0
    index = []
    for r in want[:limit] if limit else want:
        mst = r["_mst"]
        raw_j, raw_h = RAW_DIR / f"{mst}.json", RAW_DIR / f"{mst}.html"
        payload, source = None, ""
        if raw_j.exists():
            payload, source = json.loads(raw_j.read_text(encoding="utf-8")), "drf-xml"
        elif raw_h.exists():
            payload, source = {"조문": html_articles(raw_h.read_text(encoding="utf-8"))}, "web-html"
        else:
            payload, why = body_xml(mst)
            if payload is not None:
                source = "drf-xml"
                raw_j.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")   # XML→dict 그대로
            else:
                html, why_h = web_fragment(mst)
                if html:
                    raw_h.write_text(html, encoding="utf-8")
                    payload, source = {"조문": html_articles(html)}, "web-html"
                else:
                    failed += 1
                    print(f"  ✗ {r['_org']} {r['_name']} (MST {mst}): XML {why[:80]} / 웹 {why_h}")
                    polite_sleep(0.5)
                    continue
            fetched += 1
            polite_sleep(0.4)
        rel = relevant(payload)
        summ = summarize(rel)
        slug = slug_of(r)
        (OUT_DIR / f"{slug}.json").write_text(json.dumps(
            {"org": r["_org"], "name": r["_name"], "mst": mst, "effective": r["_eff"], "published": r["_pub"],
             "source": source, "summary": summ, "articles": rel}, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"org": r["_org"], "name": r["_name"], "mst": mst, "effective": r["_eff"], "source": source,
                      "n": len(rel), "file": f"{slug}.json", **summ})
    (OUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    if index:
        cols = list(index[0].keys())
        with open(OUT_DIR / "summary.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(index)
    print(f"본문 새로 받음 {fetched}건 · 실패 {failed}건 · 관심 조문 파일 {len(index)}개 → {OUT_DIR}")
    return {"listed": len(rows), "wanted": len(want), "fetched": fetched, "failed": failed, "files": len(index)}
