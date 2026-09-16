"""고속도로 **건설·공사 현황** API 가 실제로 무엇을 주는가 (2026-09-16 지시).

브이월드 도로층은 넷 다 **이미 난 길**만 담는다(road_plan_probe.py). 계획·
공사를 담은 칸이 하나도 없었다. 그래서 지도층이 아니라 **사업 자료**에서
찾는다.

후보는 한국도로공사 포털(data.ex.co.kr)이다. 우리는 이미 교통량을 여기서
받고 있고 중계기 ALLOW 에도 들어 있다. 목록에 '공사현황' 이 있다면 —

  노선명 · 구간명 · 사업명 · 공사연장 · 공사기간 · 준공날짜 ·
  **공사 시점·종점 주소** · 준공/시공 구분

— 주소가 있으니 우리 지오코더로 좌표를 붙여 지도에 그릴 수 있다.

재는 것은 둘이다.
  1. 목록에 무엇이 있나 (이름으로 찾는다)
  2. 실제로 불러 보면 어떤 칸이 오나 (**주소와 기간이 오는가**)

  python scripts/road_build_probe.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
EX = "https://data.ex.co.kr"

WANT = ("공사", "건설", "노선", "사업")


def relay(url: str, timeout: int = 45):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": url})


def text_of(html: str) -> str:
    body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    body = re.sub(r"<[^>]+>", "\n", body)
    return re.sub(r"\n{2,}", "\n", body)


def main() -> None:
    print("=" * 72)
    print("한국도로공사 OpenAPI 목록 — 공사·건설이 있는가")
    print("=" * 72)
    resp = relay(f"{EX}/openapi/intro/introduce02")
    html = resp.text
    print(f"  목록 페이지 {resp.status_code} · {len(html):,}자")
    # apiId 와 그 옆 이름을 뽑는다.
    ids = re.findall(r"apiId=(\d+)", html)
    print(f"  apiId {len(set(ids))}개: {sorted(set(ids))[:40]}")
    flat = text_of(html)
    lines = [l.strip() for l in flat.split("\n") if l.strip()]
    hits = [l for l in lines if any(w in l for w in WANT) and len(l) < 60]
    print(f"  '{'/'.join(WANT)}' 가 든 줄 {len(hits)}개:")
    for l in dict.fromkeys(hits):
        print(f"     {l}")

    # ── 후보 apiId 를 하나씩 열어 본다 ───────────────────────────
    print("\n" + "=" * 72)
    print("후보 API 의 설명 페이지 — 어떤 칸이 오나")
    print("=" * 72)
    for api_id in sorted(set(ids)):
        r = relay(f"{EX}/openapi/basicinfo/openApiInfoM?apiId={api_id}")
        t = text_of(r.text)
        head = [l.strip() for l in t.split("\n") if l.strip()][:6]
        name = " / ".join(head[:3])
        if not any(w in t for w in WANT):
            continue
        print(f"\n  [apiId={api_id}] {name[:90]}")
        # 칸 이름이 표로 적혀 있다 — 주소·기간·준공이 있는지가 핵심이다.
        for key in ("주소", "기간", "준공", "착공", "연장", "구간", "노선",
                    "시점", "종점", "개통"):
            if key in t:
                near = [l.strip() for l in t.split("\n")
                        if key in l and len(l.strip()) < 70]
                if near:
                    print(f"     {key}: {list(dict.fromkeys(near))[:3]}")
        url = re.findall(r"(https?://data\.ex\.co\.kr/openapi/[A-Za-z0-9/_.\-]+)", r.text)
        if url:
            print(f"     엔드포인트 후보: {list(dict.fromkeys(url))[:4]}")

    # ── 공공데이터포털 쪽 설명도 본다 (www.data.go.kr 는 통과 전용) ──
    print("\n" + "=" * 72)
    print("공공데이터포털 15076874 (고속도로 공사현황) 설명")
    print("=" * 72)
    r = relay("https://www.data.go.kr/data/15076874/openapi.do")
    t = text_of(r.text)
    lines = [l.strip() for l in t.split("\n") if l.strip()]
    keep = [l for l in lines
            if any(w in l for w in ("공사", "구간", "노선", "주소", "기간",
                                    "준공", "연장", "엔드포인트", "활용"))
            and len(l) < 120]
    print(f"  {r.status_code} · {len(t):,}자")
    for l in list(dict.fromkeys(keep))[:40]:
        print(f"     {l}")


if __name__ == "__main__":
    main()
