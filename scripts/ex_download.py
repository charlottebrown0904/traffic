"""고속도로 공공데이터 포털의 월별 파일을 중계기로 내려받는다.

포털 화면이 보내는 요청을 그대로 흉내낸다.
  엔드포인트 /openoasis/portal/download/view2
  파라미터   type, num, collectCycle, dataSupplyYear, dataSupplyMonth ...

  python scripts/ex_download.py <YYYY> <MM> [저장경로]
인자 없이 저장경로를 주지 않으면 내려받지 않고 응답만 살핀다.
"""
from __future__ import annotations

import base64
import os
import sys
import urllib.parse
import urllib.request

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")

BASE = "https://data.ex.co.kr/openoasis/portal/download/view2"


def build(year: str, month: str, cycle: str = "1", extra: dict | None = None) -> str:
    params = {
        "type": "TCS",
        "num": "34",
        "collectCycle": cycle,          # 1일 집계
        "dataSupplyYear": year,
        "dataSupplyMonth": month,
        "dataSupplyDate": f"{year}{month}",
        "requestfrom": "dataset",
    }
    params.update(extra or {})
    return f"{BASE}?{urllib.parse.urlencode(params)}"


def fetch(target: str) -> tuple[int, dict, bytes]:
    url = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            headers = {k.lower(): v for k, v in resp.headers.items()}
            if headers.get("x-relay-encoding") == "base64":
                raw = base64.b64decode(raw)
            return resp.status, headers, raw
    except urllib.error.HTTPError as exc:
        return exc.code, {}, exc.read()[:400]
    except Exception as exc:                       # noqa: BLE001
        return 0, {}, f"{type(exc).__name__} {exc}".encode()


def main() -> None:
    year, month = sys.argv[1], sys.argv[2].zfill(2)
    out = sys.argv[3] if len(sys.argv) > 3 else None

    target = build(year, month)
    print("  요청:", target)
    status, headers, body = fetch(target)
    print(f"  http={status}  {len(body):,} bytes")
    print("  상류 content-type:", headers.get("x-relay-content-type", headers.get("content-type")))

    if body[:2] == b"PK":
        print("  ★ ZIP 파일입니다")
    elif body[:1] in (b"<", b"{"):
        print("  본문 앞부분:", body[:250].decode("utf-8", "replace").replace("\n", " "))
    else:
        print("  앞 40바이트:", body[:40])

    if out and body[:2] == b"PK":
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(body)
        print("  저장:", out)


if __name__ == "__main__":
    main()
