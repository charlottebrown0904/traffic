"""도로공사 API 를 서울 중계기로 호출해 응답을 요약한다.

파라미터 이름을 문서에서 못 읽으니, 응답 message 가 무엇을 요구하는지 보고
후보를 하나씩 좁힌다.

  python scripts/ex_probe.py <경로> [key=value ...]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")


def call(path: str, extra: list[str]) -> dict | str:
    query = ["type=json", "numOfRows=2", "pageNo=1", *extra]
    target = f"https://data.ex.co.kr/openapi/{path}?" + "&".join(query)
    url = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as exc:                       # noqa: BLE001
        return f"(호출 실패) {type(exc).__name__}"
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return "(JSON 아님) " + body[:120].replace("\n", " ")


def describe(result: dict | str) -> str:
    if isinstance(result, str):
        return result
    rows = result.get("list")
    if rows:
        keys = list(rows[0].keys())
        head = json.dumps(rows[0], ensure_ascii=False)[:260]
        return f"★ 데이터 {result.get('count')}건\n      키: {keys}\n      첫행: {head}"
    return f"code={result.get('code')}  message={result.get('message')}"


if __name__ == "__main__":
    print("   ", describe(call(sys.argv[1], sys.argv[2:])))
