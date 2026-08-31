"""파일데이터 자동변환 오픈API(api.odcloud.kr)를 중계기로 들여다본다.

  python scripts/odcloud_peek.py <데이터셋번호> <uddi> [page]

총 건수, 컬럼, 첫 행, 그리고 집계일자의 범위를 알아본다.
집계일자 범위가 우리 분석의 성패를 가른다 — 1년치뿐이면 연도별 변화를 못 본다.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")


def call(ds: str, uddi: str, page: int, per: int = 5) -> dict | str:
    target = (f"https://api.odcloud.kr/api/{ds}/v1/{uddi}"
              f"?page={page}&perPage={per}&returnType=JSON")
    url = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:                       # noqa: BLE001
        return f"(실패) {type(exc).__name__} {exc}"


def date_of(row: dict) -> str | None:
    for k, v in row.items():
        if "일자" in k or "date" in k.lower():
            return str(v)
    return None


def main() -> None:
    ds, uddi = sys.argv[1], sys.argv[2]
    first = call(ds, uddi, 1)
    if isinstance(first, str):
        print(" ", first)
        return
    total = first.get("totalCount")
    rows = first.get("data") or []
    print(f"  총 {total:,}건" if isinstance(total, int) else f"  totalCount={total}")
    if not rows:
        print("  (행 없음)", json.dumps(first, ensure_ascii=False)[:300])
        return
    print("  컬럼:", list(rows[0].keys()))
    print("  첫 행:", json.dumps(rows[0], ensure_ascii=False)[:400])
    print("  가장 앞 집계일자:", date_of(rows[0]))

    if isinstance(total, int) and total > 5:
        last_page = (total + 4) // 5
        last = call(ds, uddi, last_page)
        if isinstance(last, dict) and last.get("data"):
            print("  가장 뒤 집계일자:", date_of(last["data"][-1]))


if __name__ == "__main__":
    main()
