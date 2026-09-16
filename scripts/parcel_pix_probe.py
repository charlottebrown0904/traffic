"""필지 선이 화면과 틀어지는가 — 화소로 잰다 (2026-09-16 지시).

  "필지경계와 지도 틀어짐 발생 (대구)"

앞 탐침(parcel_shift_probe)은 **자료끼리** 견줬다 — 지오코더 점이 그
지번의 필지 안에 드는가. 다섯 곳 중 넷이 들었고 대구 북구가 2m 로 가장
잘 맞았다. 즉 **자료는 밀리지 않았다.** 그런데 화면은 틀어져 보인다.

그러면 남는 자리는 하나다 — **우리가 그리는 자리**다. 화면의 필지 선은
브이월드가 칠해 주는 그림이 아니라, 우리가 WFS 로 좌표를 받아 Leaflet
으로 직접 그리는 선이다(api/tile.js parcelLines → app.js drawCadastral).
바탕 타일은 브이월드가 그린 그림이고, 선은 우리가 그린 것이다. 둘 사이가
어긋날 자리가 거기에 있다.

그래서 **같은 층을 두 길로 받아 겹친다.**

  ① 브이월드가 칠한 지적 그림 (WMS, EPSG:3857, 타일 한 칸)
  ② 우리가 받는 지적 좌표 (WFS, EPSG:4326) 를 같은 칸에 우리 셈법으로 찍기

둘 다 같은 필지의 같은 선이다. 우리 셈법이 맞으면 두 그림의 선이 **같은
화소**에 놓인다. 어긋나면 그 어긋난 화소 수가 곧 답이고, z17 에서 한 화소는
1m 남짓이라 미터로 바로 읽힌다.

맞춰 보는 방법은 밀어 보기다. -12~+12 화소를 다 밀어 보고 가장 잘 겹치는
자리를 찾는다. (0,0) 이 이기면 우리 셈법이 맞는 것이고, 다른 자리가
이기면 그 방향과 크기가 곧 버그의 모양이다.

**대조군을 함께 잰다** — 서울·안성도 같이. 대구만 재고 '대구가 문제' 라고
하면 그건 측정이 아니라 짐작이다.

  python scripts/parcel_pix_probe.py
"""
from __future__ import annotations

import base64
import io
import math
import os
import sys
import urllib.parse

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WMS = "https://api.vworld.kr/req/wms"
WFS = "https://api.vworld.kr/req/wfs"
DOMAIN = os.environ.get("VWORLD_DOMAIN", "https://toji.fyi")

LAYER = "lp_pa_cbnd_bubun"
Z = 17
SIZE = 256
# 밀어 볼 범위. z17 한 화소가 1m 남짓이니 ±12m 를 본다.
SHIFT = 12
E = 20037508.342789244

# 앞 탐침이 지오코더에서 받은 점 그대로. 내가 새로 고르지 않는다.
SPOTS = [
    ("대구 중구", 35.871949, 128.595969),
    ("대구 북구", 35.896148, 128.522670),
    ("서울 중구", 37.563004, 126.986864),
    ("경기 안성", 36.997168, 127.173984),
    ("부산 중구", 35.101470, 129.036193),
]


def relay(url: str, params: dict, timeout: int = 90):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    target = f"{url}?{urllib.parse.urlencode(params)}"
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def png_bytes(raw: bytes) -> bytes:
    """중계기는 글자가 아닌 몸통을 base64 로 감싸 보낸다."""
    if raw[:4] == b"\x89PNG":
        return raw
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:                                  # noqa: BLE001
        return raw


def merc(lon: float, lat: float) -> tuple[float, float]:
    x = lon * E / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * E / 180.0


def tile_of(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2 ** z
    r = math.radians(lat)
    xt = int((lon + 180.0) / 360.0 * n)
    yt = int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n)
    return xt, yt


def merc_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    side = 2.0 * E / (2 ** z)
    return (-E + x * side, E - (y + 1) * side, -E + (x + 1) * side, E - y * side)


def deg_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2 ** z

    def lat(ty: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2.0 * ty / n))))

    return (x / n * 360.0 - 180.0, lat(y + 1),
            (x + 1) / n * 360.0 - 180.0, lat(y))


def wms_mask(z: int, x: int, y: int):
    """브이월드가 **칠한** 지적 그림. 알파가 있는 화소가 선이다."""
    from PIL import Image                              # noqa: PLC0415
    minx, miny, maxx, maxy = merc_bbox(z, x, y)
    r = relay(WMS, {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
        "LAYERS": LAYER, "STYLES": "", "CRS": "EPSG:3857",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": str(SIZE), "HEIGHT": str(SIZE),
        "FORMAT": "image/png", "TRANSPARENT": "true",
        "key": "__via_relay__", "DOMAIN": DOMAIN,
    })
    im = Image.open(io.BytesIO(png_bytes(r.content))).convert("RGBA")
    px = im.load()
    return {(i, j) for j in range(SIZE) for i in range(SIZE) if px[i, j][3] > 24}


def wfs_mask(z: int, x: int, y: int):
    """우리가 받는 좌표를, **우리 셈법으로** 같은 칸에 찍는다.

    api/tile.js parcelLines 와 같은 호출이라야 뜻이 있다 — 1.1.0,
    BBOX 는 [w,s,e,n], SRSNAME 은 EPSG:4326.
    """
    from PIL import Image, ImageDraw                   # noqa: PLC0415
    w, s, e, n = deg_bbox(z, x, y)
    r = relay(WFS, {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": LAYER, "BBOX": f"{w},{s},{e},{n}",
        "SRSNAME": "EPSG:4326", "OUTPUT": "application/json",
        "MAXFEATURES": "600", "RESULTTYPE": "results",
        "key": "__via_relay__", "DOMAIN": DOMAIN,
    })
    try:
        body = r.json()
    except Exception:                                  # noqa: BLE001
        return None, 0
    feats = body.get("features") or []
    minx, miny, maxx, maxy = merc_bbox(z, x, y)
    im = Image.new("1", (SIZE, SIZE), 0)
    dr = ImageDraw.Draw(im)

    def put(ring):
        pts = []
        for c in ring:
            mx, my = merc(float(c[0]), float(c[1]))
            pts.append(((mx - minx) / (maxx - minx) * SIZE,
                        (maxy - my) / (maxy - miny) * SIZE))
        if len(pts) >= 2:
            dr.line(pts, fill=1, width=1)

    for f in feats:
        g = (f or {}).get("geometry") or {}
        polys = (g.get("coordinates") or []) if g.get("type") == "MultiPolygon" \
            else [g.get("coordinates") or []] if g.get("type") == "Polygon" else []
        for rings in polys:
            for ring in rings:
                put(ring)
    px = im.load()
    return {(i, j) for j in range(SIZE) for i in range(SIZE) if px[i, j]}, len(feats)


def grow(mask: set, r: int = 1) -> set:
    out = set()
    for (i, j) in mask:
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                out.add((i + di, j + dj))
    return out


def best_shift(theirs: set, ours: set):
    """가장 잘 겹치는 밀기. (0,0) 이 이기면 우리 셈법이 맞다."""
    fat = grow(ours, 1)
    rows = []
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            hit = sum(1 for (i, j) in theirs if (i + dx, j + dy) in fat)
            rows.append((hit, dx, dy))
    rows.sort(key=lambda t: (-t[0], abs(t[1]) + abs(t[2])))
    zero = next(h for h, dx, dy in rows if dx == 0 and dy == 0)
    return rows[0], zero


def main() -> None:
    bar = "=" * 72
    print(bar)
    print("필지 선이 화면과 틀어지는가 — 같은 층을 두 길로 받아 화소로 견준다")
    print(bar)
    print("  ① 브이월드가 칠한 지적 그림(WMS)  ② 우리가 받아 우리가 찍은 선(WFS)")
    print(f"  z{Z} · 한 화소 ≈ 1m · -{SHIFT}~+{SHIFT} 화소를 밀어 본다")
    print()
    for name, lat, lon in SPOTS:
        x, y = tile_of(lon, lat, Z)
        try:
            theirs = wms_mask(Z, x, y)
            ours, cnt = wfs_mask(Z, x, y)
        except Exception as err:                       # noqa: BLE001
            print(f"  {name:<10} 못 쟀다 — {type(err).__name__}: {err}")
            continue
        if ours is None:
            print(f"  {name:<10} WFS 가 JSON 을 안 줬다")
            continue
        if not theirs or not ours:
            print(f"  {name:<10} 그림 화소 {len(theirs)} · 우리 화소 "
                  f"{len(ours)} · 필지 {cnt} — 견줄 것이 없다")
            continue
        (hit, dx, dy), zero = best_shift(theirs, ours)
        tag = "**(0,0) 이 이긴다 — 우리 셈법이 맞다**" if (dx, dy) == (0, 0) \
            else f"**({dx:+d},{dy:+d}) 로 밀어야 맞는다**"
        print(f"  {name:<10} 필지 {cnt:>3}개 · 그림선 {len(theirs):>5}화소 · "
              f"우리선 {len(ours):>5}화소")
        print(f"  {'':<10} 겹침 제자리 {zero / len(theirs) * 100:5.1f}% → "
              f"가장 잘 겹칠 때 {hit / len(theirs) * 100:5.1f}%  {tag}")
    print()
    print(bar)
    print("무엇을 보고 판단하나")
    print(bar)
    print("  · 어디서나 (0,0) → 우리 셈법은 맞다. 틀어짐은 다른 데 있다")
    print("  · 대구만 밀림 → 그 지역 그림과 좌표가 서로 다른 기준이다")
    print("  · 어디서나 같은 방향으로 밀림 → 우리 좌표 변환이 틀렸다")


if __name__ == "__main__":
    main()
