"""도로공사 영업소 명단 API 가 실제로 무엇을 주는지 확인한다.

교통량 파일에는 영업소가 475개 있는데 마스터에는 86개만 저장된다.
원인이 셋 중 어디인지 가려야 한다.

  1. API 가 애초에 86개만 준다
  2. 페이지네이션이 안 돌아 첫 페이지만 받는다
  3. 응답에는 다 있는데 우리 정규화(좌표 이상치 제외·중복 병합)에서 깎인다

그래서 가공하지 않은 응답을 그대로 세어 본다.

  RELAY_URL=... RELAY_TOKEN=... python scripts/ex_roster.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
BASE = "https://data.ex.co.kr/openapi"


def call(path: str, params: dict) -> dict | None:
    target = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    url = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:                        # noqa: BLE001
        print(f"  호출 실패: {type(exc).__name__} {exc}")
        return None


def rows_of(payload: dict) -> list[dict]:
    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def sweep(path: str, per_page: int) -> None:
    print(f"\n=== {path}  (numOfRows={per_page})")
    seen: list[dict] = []
    first_sig = None
    for page in range(1, 21):
        payload = call(path, {"key": os.environ.get("EX_KEY", ""), "type": "json",
                              "numOfRows": per_page, "pageNo": page})
        if payload is None:
            return
        if page == 1:
            meta = {k: v for k, v in payload.items() if not isinstance(v, list)}
            print(f"  응답 메타: {json.dumps(meta, ensure_ascii=False)[:300]}")
        items = rows_of(payload)
        if not items:
            print(f"  {page}페이지: 목록 없음 → 중단")
            break
        sig = str(items[0])
        if first_sig is not None and sig == first_sig:
            print(f"  {page}페이지가 1페이지와 동일 → 페이지네이션 미지원")
            break
        if page == 1:
            first_sig = sig
            print(f"  항목 키: {sorted(items[0])}")
            print(f"  1행 예시: {json.dumps(items[0], ensure_ascii=False)[:300]}")
        seen.extend(items)
        print(f"  {page}페이지 {len(items)}행 (누적 {len(seen)})")
        if len(items) < per_page:
            break

    codes = [str(r.get("unitCode", r.get("icCode", ""))).strip() for r in seen]
    codes = [c for c in codes if c]
    print(f"  총 {len(seen)}행 · 코드 있는 행 {len(codes)} · 서로 다른 코드 {len(set(codes))}")
    print(f"  코드 예시: {sorted(set(codes))[:12]}")

    # 좌표가 있는 행이 몇 개인지 — 정규화에서 깎이는 양을 가늠한다
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    good = [r for r in seen
            if (lat := num(r.get("yValue"))) is not None
            and (lon := num(r.get("xValue"))) is not None
            and 33 <= lat <= 39 and 124 <= lon <= 132]
    # IC 응답에는 unitCode 가 없고 icCode 를 쓴다. unitCode 만 보면 0 이 나온다.
    gcodes = {str(r.get("unitCode", r.get("icCode", ""))).strip() for r in good} - {""}
    print(f"  좌표 정상 {len(good)}행 · 그 중 서로 다른 코드 {len(gcodes)}")


if __name__ == "__main__":
    if not RELAY or not TOKEN:
        sys.exit("RELAY_URL / RELAY_TOKEN 이 필요합니다.")
    for path in ("locationinfo/locationinfoUnit", "locationinfo/locationinfoIc"):
        for per_page in (500, 1000):
            sweep(path, per_page)
