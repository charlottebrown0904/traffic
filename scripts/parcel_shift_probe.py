"""필지경계가 지도와 틀어지는가 — 대구에서 (2026-09-16 지시).

  "필지경계와 지도 틀어짐 발생 (대구)"

## 무엇을 가려야 하나

어긋남은 셋 중 하나다.

  1. **자료가 틀렸다** — 연속지적도 좌표 자체가 밀려 있다
  2. **바탕지도가 틀렸다** — 타일을 딴 좌표계로 깔고 있다
  3. **우리가 틀렸다** — 받은 좌표를 잘못 그린다

눈으로는 셋이 똑같아 보인다. 그래서 **같은 주소를 두 원천에 따로 물어
서로 얼마나 떨어져 있는지 잰다.** 둘 다 브이월드이고 둘 다 EPSG:4326 을
달라고 하므로, 답이 맞다면 지오코더의 점은 그 지번의 필지 **안에** 있어야
한다. 밖에 있으면 그 거리가 곧 어긋난 양이다.

**대조군을 함께 잰다** — 경기도에서도 같이 벌어지면 전국 문제이고,
대구에서만 벌어지면 지역 문제다. 한 곳만 재고 '대구가 문제' 라고 하면
그건 측정이 아니라 짐작이다.

  python scripts/parcel_shift_probe.py
"""
from __future__ import annotations

import math
import os
import sys
import urllib.parse

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
ADDR = "https://api.vworld.kr/req/address"
WFS = "https://api.vworld.kr/req/wfs"
CADASTRE = "lp_pa_cbnd_bubun"

# 받은 캡처 둘 + 대조군. 대구에서만 벌어지는지 보려면 다른 데도 재야 한다.
SPOTS = [
    ("대구 중구",  "대구광역시 중구 동성로2가 5-2"),
    ("대구 북구",  "대구광역시 북구 금호동 834"),
    ("서울 중구",  "서울특별시 중구 명동2가 1-1"),
    ("경기 안성",  "경기도 안성시 공도읍 승두리 1"),
    ("부산 중구",  "부산광역시 중구 중앙동4가 1"),
]


def relay(url: str, timeout: int = 90):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": url})


def km(a, b) -> float:
    la1, lo1 = a
    la2, lo2 = b
    dla, dlo = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = (math.sin(dla / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(dlo / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def geocode(addr: str):
    q = {"service": "address", "request": "getcoord", "version": "2.0",
         "crs": "epsg:4326", "type": "PARCEL", "address": addr,
         "format": "json", "key": "__via_relay__"}
    try:
        d = relay(f"{ADDR}?{urllib.parse.urlencode(q)}").json()
    except Exception as exc:                            # noqa: BLE001
        return None, f"{type(exc).__name__}"
    r = (d or {}).get("response") or {}
    if r.get("status") != "OK":
        return None, str(r.get("status"))
    p = (r.get("result") or {}).get("point") or {}
    try:
        return (float(p["y"]), float(p["x"])), None
    except (KeyError, TypeError, ValueError):
        return None, "좌표 못 읽음"


def parcels_near(pt, half=0.0012):
    """그 점 언저리 필지들 (약 ±130m)."""
    la, lo = pt
    q = {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
         "TYPENAME": CADASTRE, "OUTPUT": "application/json",
         "SRSNAME": "EPSG:4326", "MAXFEATURES": "200",
         "BBOX": f"{la - half},{lo - half},{la + half},{lo + half}",
         "key": "__via_relay__", "DOMAIN": "https://toji.fyi"}
    try:
        return (relay(f"{WFS}?{urllib.parse.urlencode(q)}").json()
                or {}).get("features") or []
    except Exception:                                   # noqa: BLE001
        return []


def rings(f):
    g = f.get("geometry") or {}
    co = g.get("coordinates") or []
    if g.get("type") == "MultiPolygon":
        return [r for poly in co for r in poly]
    if g.get("type") == "Polygon":
        return co
    return []


def inside(pt, ring) -> bool:
    """점이 고리 안에 있나 (짝수-홀수). ring 은 [경도, 위도] 다."""
    la, lo = pt
    on = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > la) != (y2 > la):
            xx = x1 + (la - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if lo < xx:
                on = not on
    return on


def centroid(ring):
    if not ring:
        return None
    la = sum(p[1] for p in ring) / len(ring)
    lo = sum(p[0] for p in ring) / len(ring)
    return (la, lo)


def main() -> None:
    print("=" * 72)
    print("필지경계가 지도와 틀어지는가 — 지오코더 점이 그 필지 안에 있나")
    print("=" * 72)
    print("  둘 다 브이월드이고 둘 다 EPSG:4326 을 달라고 한다.")
    print("  맞다면 점은 그 지번의 필지 **안에** 있어야 한다.\n")

    for label, addr in SPOTS:
        pt, err = geocode(addr)
        if not pt:
            print(f"  {label:9s} ✗ 지오코딩 실패 ({err}) — {addr}")
            continue
        feats = parcels_near(pt)
        if not feats:
            print(f"  {label:9s} 점 {pt[0]:.6f},{pt[1]:.6f} · 언저리 필지 0개")
            continue
        # 점을 품은 필지가 있나
        holder = None
        best, bd = None, 1e9
        for f in feats:
            for ring in rings(f):
                if inside(pt, ring):
                    holder = f
                c = centroid(ring)
                if c:
                    d = km(pt, c)
                    if d < bd:
                        best, bd = f, d
        pnu = str(((holder or best or {}).get("properties") or {}).get("pnu")
                  or ((holder or best or {}).get("properties") or {}).get("jibun")
                  or "?")
        print(f"  {label:9s} 점 {pt[0]:.6f},{pt[1]:.6f} · 언저리 {len(feats)}개"
              f" · {'**품은 필지 있음**' if holder else '품은 필지 없음'}"
              f" · 가장 가까운 필지 중심까지 {bd * 1000:.0f}m · {pnu[:20]}")

    print("\n" + "=" * 72)
    print("무엇을 보고 판단하나")
    print("=" * 72)
    print("  · 어디서나 '품은 필지 있음' → 자료는 맞다. 어긋남은 바탕지도 쪽")
    print("  · 대구만 '없음' + 거리가 큼 → 그 지역 지적 좌표가 밀려 있다")
    print("  · 전국이 '없음' → 우리가 좌표를 잘못 쓰고 있다")


if __name__ == "__main__":
    main()
