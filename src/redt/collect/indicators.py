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
    """후보 하나를 두드려 상태와 본문 머리를 돌려준다. 죽지 않는다."""
    try:
        resp = http.get(cand["url"], dict(cand["params"]), timeout=timeout)
        head = resp.text[:800]
        return {"name": cand["name"], "url": cand["url"], "status": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
                "head": head, "keys": _top_keys(resp.text)}
    except Exception as exc:                          # noqa: BLE001
        return {"name": cand["name"], "url": cand["url"], "error": f"{type(exc).__name__}: {exc}"[:400]}


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
    return {"portal": found, "candidates": knocked}


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
