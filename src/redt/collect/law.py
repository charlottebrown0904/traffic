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
PORTAL_SEARCH = "https://apis.data.go.kr/1170000/law/lawSearchList.do"
PORTAL_SERVICE = "https://apis.data.go.kr/1170000/law/lawService.do"
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


def _direct(url: str, params: dict):
    """중계기를 거치지 않고 바로 부른다 — 러너 IP 로. 등록 도메인을 Referer 로 싣는다."""
    import requests
    oc = os.getenv("LAW_OC") or "test"
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
    return get_once(url, {"serviceKey": VIA_RELAY, "target": "ordin", "type": kind, **params}, timeout=40)


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


def _find_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
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


def relevant(payload) -> list[dict]:
    out = []
    for a in articles(payload):
        text = " ".join(str(v) for v in a.values() if isinstance(v, (str, int)))
        if any(k in text for k in KEYWORDS):
            out.append({"no": _pick(a, "조문번호", "조번호"), "title": _pick(a, "조문제목"),
                        "text": _pick(a, "조문내용")[:6000]})
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
    # 2) 공공데이터포털 길 — 어느 주소·형식이 통하는지 그대로 찍는다
    out["portal"] = {}
    for label, url, kind in (("lawSearchList XML", PORTAL_SEARCH, "XML"),
                             ("lawSearchList JSON", PORTAL_SEARCH, "JSON"),
                             ("ordinSearchList XML", PORTAL_SEARCH.replace("lawSearchList", "ordinSearchList"), "XML"),
                             ("lawSearchList XML target=law", PORTAL_SEARCH, "XML")):
        try:
            p = {"query": query, "display": "3"}
            if label.endswith("target=law"):
                p["target"] = "law"
            r = _portal_raw(url, p, kind)
            snip = re.sub(r"\s+", " ", r.text)[:220]
            out["portal"][label] = {"status": r.status_code, "snippet": snip}
            print(f"포털 {label}: HTTP {r.status_code} · {snip}")
        except Exception as e:                      # noqa: BLE001
            out["portal"][label] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            print(f"포털 {label}: 실패 {out['portal'][label]['error']}")
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


def fetch(query: str = "도시계획 조례", limit: int | None = None) -> dict:
    """목록을 받고 본문을 하나씩 받아 관심 조문만 data/ordinance/ 에 남긴다.
    재개 가능 — 본문 원문이 RAW_DIR 에 있으면 다시 안 받는다."""
    rows, why = list_all(query)
    if why:
        print(f"목록 실패: {why}")
        return {"listed": 0, "fetched": 0, "why": why}
    # 이름에 '도시계획 조례'·'도시계획조례' 가 든 것만 (시행규칙·다른 조례 제외)
    want = [r for r in rows if re.sub(r"\s", "", r["_name"]).endswith("도시계획조례")]
    print(f"목록 {len(rows)}건 → 도시계획조례 {len(want)}건")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fetched = 0
    index = []
    for r in want[:limit] if limit else want:
        mst = r["_mst"]
        raw = RAW_DIR / f"{mst}.json"
        if raw.exists():
            payload = json.loads(raw.read_text(encoding="utf-8"))
        else:
            payload, why = body(mst)
            if payload is None:
                print(f"  {r['_org']} {r['_name']}: {why[:100]}")
                polite_sleep(0.5)
                continue
            raw.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            fetched += 1
            polite_sleep(0.4)
        rel = relevant(payload)
        slug = re.sub(r"[^\w가-힣]+", "_", f"{r['_org']}_{r['_name']}").strip("_")
        (OUT_DIR / f"{slug}.json").write_text(json.dumps(
            {"org": r["_org"], "name": r["_name"], "mst": mst, "articles": rel},
            ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"org": r["_org"], "name": r["_name"], "mst": mst, "n": len(rel), "file": f"{slug}.json"})
    (OUT_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"본문 새로 받음 {fetched}건 · 관심 조문 파일 {len(index)}개 → {OUT_DIR}")
    return {"listed": len(rows), "wanted": len(want), "fetched": fetched, "files": len(index)}
