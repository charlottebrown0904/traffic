"""필지 조회(WFS)가 400 을 내는 이유를 브이월드 입으로 듣는다.

**로직을 워크플로 안에 쓰지 않는다.** 중첩 heredoc 때문에 YAML 이
깨졌고, 그것을 못 보고 밀었다. 파이썬 파일로 두면 문법을 바로 잰다.

키가 응답에 실려 올 수 있다 — 로그로 나가기 전에 지운다.
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE", "https://toji.fyi")
TOKEN = os.environ.get("TOKEN", "")
LAT = float(os.environ.get("LAT", "37.0080"))
LON = float(os.environ.get("LON", "127.2797"))
HALF = 0.0006          # api/tile.js 의 PARCEL_HALF_DEG 와 같은 값

BBOX = f"{LON - HALF},{LAT - HALF},{LON + HALF},{LAT + HALF}"
COMMON = ("SERVICE=WFS&REQUEST=GetFeature&SRSNAME=EPSG:4326"
          f"&OUTPUT=application/json&BBOX={BBOX}")

CASES = [
    ("지금 우리 꼴 (2.0.0 · TYPENAME · MAXFEATURES · dt_d194)",
     f"{COMMON}&VERSION=2.0.0&TYPENAME=dt_d194&MAXFEATURES=10&RESULTTYPE=results"),
    ("2.0.0 표준 철자 (TYPENAMES · COUNT)",
     f"{COMMON}&VERSION=2.0.0&TYPENAMES=dt_d194&COUNT=10"),
    ("1.1.0 (TYPENAME · MAXFEATURES)",
     f"{COMMON}&VERSION=1.1.0&TYPENAME=dt_d194&MAXFEATURES=10"),
    ("연속지적도 레이어 (lp_pa_cbnd_bubun)",
     f"{COMMON}&VERSION=1.1.0&TYPENAME=lp_pa_cbnd_bubun&MAXFEATURES=10"),
    ("무엇이 열려 있나 (GetCapabilities)",
     "SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0"),
]

# 키가 로그에 남지 않게. 값 모양이 무엇이든 통째로 가린다.
HIDE = re.compile(r'(?i)((?:key|apikey|servicekey)=)[^&"\s<]+')


def show(text: str, n: int = 420) -> str:
    return " ".join(HIDE.sub(r"\1(가림)", text)[:n].split())


def main() -> int:
    if not TOKEN:
        print("::error::중계기 토큰이 없습니다")
        return 1
    print(f"BBOX={BBOX}\n")
    for label, query in CASES:
        target = "https://api.vworld.kr/req/wfs?" + query
        url = f"{BASE}/api/relay?target={urllib.parse.quote(target, safe='')}"
        req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
        print(f"── {label} ──")
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read().decode("utf-8", "replace")
                print(f"  http={r.status}  {len(body)}B")
                print("  " + show(body))
        except urllib.error.HTTPError as e:            # noqa: PERF203
            body = e.read().decode("utf-8", "replace")
            print(f"  http={e.code}  {len(body)}B")
            print("  " + show(body))
        except Exception as exc:                        # noqa: BLE001
            print(f"  실패: {type(exc).__name__}: {exc}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
