"""우리가 찍는 자리가 브이월드가 칠하는 자리와 같은가 — 화소로 잰다.

  "필지경계와 지도 틀어짐 발생 (대구)"  (2026-09-16 지시)

parcelshift 탐침이 답을 반쯤 줬다. 지오코더 점이 그 지번의 필지 **안에**
드는지 다섯 곳에서 쟀더니 넷이 들었고 대구 북구가 2m 로 가장 잘 맞았다.
**자료는 안 밀렸다.** 그러면 남는 자리는 우리가 그리는 자리다.

1차는 못 쟀다. 지적층을 WMS 로 받아 대조군으로 쓰려 했는데 다섯 곳 모두
**빈 그림**이 왔다. 그건 이미 재 놓은 것이었다 — 브이월드 WMS 는
lp_pa_cbnd_bubun 을 안 그려 준다(scripts/cadastral_tile_probe.py). 애초에
그래서 화면이 선을 직접 그린다. 재 놓은 것을 안 보고 대조군으로 골랐다.

**그래서 칠해지는 층으로 잰다.** 물음은 층과 무관하다 — "경위도를 화소로
옮기는 우리 셈법이 브이월드와 같은 자리를 가리키나". 용도지역·도시계획도로
는 WMS 가 실제로 칠해 주고(화면에 이미 그렇게 깔린다) WFS 로 좌표도 준다.
같은 층을 두 길로 받아 겹치면 셈법이 그대로 드러난다.

  ① 브이월드가 칠한 그림 (WMS, EPSG:3857, 타일 한 칸)
  ② 그 층의 좌표 (WFS, EPSG:4326) 를 우리 셈법으로 같은 칸에 찍기

-12~+12 화소를 다 밀어 보고 가장 잘 겹치는 자리를 찾는다. (0,0) 이 이기면
우리 셈법이 맞다. z17 에서 한 화소는 1m 남짓이라 어긋난 화소가 곧 미터다.

**덤으로 상한도 센다.** 한 칸에 600개까지만 받는다(api/tile.js
PARCEL_VEC_MAX). 도심 한 칸이 그 위면 필지가 **빠진 채** 그려진다 —
어긋남과 빠짐은 화면에서 비슷해 보인다. 대구 중구는 z17 한 칸에 이미
283개였다. z16 은 그 넷을 합친 넓이다.

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

CAD = "lp_pa_cbnd_bubun"
# 셈법을 재는 데 쓸 층. WMS 가 **실제로 칠해 주는** 것이라야 뜻이 있다.
REF = [("lt_c_uq111", "용도지역(도시)"), ("lt_c_upisuq151", "도시계획(도로)")]
Z = 17
SIZE = 256
SHIFT = 12
E = 20037508.342789244
VEC_MAX = 600                       # api/tile.js PARCEL_VEC_MAX 와 같은 값

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
    return (int((lon + 180.0) / 360.0 * n),
            int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n))


def merc_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    side = 2.0 * E / (2 ** z)
    return (-E + x * side, E - (y + 1) * side, -E + (x + 1) * side, E - y * side)


def deg_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2 ** z

    def lat(ty: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2.0 * ty / n))))

    return (x / n * 360.0 - 180.0, lat(y + 1),
            (x + 1) / n * 360.0 - 180.0, lat(y))


def wms_mask(layer: str, z: int, x: int, y: int) -> set:
    from PIL import Image                              # noqa: PLC0415
    minx, miny, maxx, maxy = merc_bbox(z, x, y)
    r = relay(WMS, {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
        "LAYERS": layer, "STYLES": "", "CRS": "EPSG:3857",
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": str(SIZE), "HEIGHT": str(SIZE),
        "FORMAT": "image/png", "TRANSPARENT": "true",
        "key": "__via_relay__", "DOMAIN": DOMAIN,
    })
    im = Image.open(io.BytesIO(png_bytes(r.content))).convert("RGBA")
    px = im.load()
    return {(i, j) for j in range(SIZE) for i in range(SIZE) if px[i, j][3] > 24}


def wfs_feats(layer: str, z: int, x: int, y: int, cap: int = VEC_MAX):
    """api/tile.js parcelLines 와 **같은 호출**이라야 뜻이 있다."""
    w, s, e, n = deg_bbox(z, x, y)
    r = relay(WFS, {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": layer, "BBOX": f"{w},{s},{e},{n}",
        "SRSNAME": "EPSG:4326", "OUTPUT": "application/json",
        "MAXFEATURES": str(cap), "RESULTTYPE": "results",
        "key": "__via_relay__", "DOMAIN": DOMAIN,
    })
    try:
        return (r.json().get("features") or [])
    except Exception:                                  # noqa: BLE001
        return None


def paint(feats, z: int, x: int, y: int, fill: bool) -> set:
    """받은 좌표를 **우리 셈법으로** 같은 칸에 찍는다."""
    from PIL import Image, ImageDraw                   # noqa: PLC0415
    minx, miny, maxx, maxy = merc_bbox(z, x, y)
    im = Image.new("1", (SIZE, SIZE), 0)
    dr = ImageDraw.Draw(im)
    for f in feats:
        g = (f or {}).get("geometry") or {}
        t = g.get("type")
        polys = (g.get("coordinates") or []) if t == "MultiPolygon" \
            else [g.get("coordinates") or []] if t == "Polygon" else []
        for rings in polys:
            for k, ring in enumerate(rings):
                pts = []
                for c in ring:
                    mx, my = merc(float(c[0]), float(c[1]))
                    pts.append(((mx - minx) / (maxx - minx) * SIZE,
                                (maxy - my) / (maxy - miny) * SIZE))
                if len(pts) < 2:
                    continue
                if fill and k == 0:
                    dr.polygon(pts, fill=1)
                elif fill:
                    dr.polygon(pts, fill=0)            # 구멍
                else:
                    dr.line(pts, fill=1, width=1)
    px = im.load()
    return {(i, j) for j in range(SIZE) for i in range(SIZE) if px[i, j]}


def best_shift(theirs: set, ours: set):
    rows = []
    for dy in range(-SHIFT, SHIFT + 1):
        for dx in range(-SHIFT, SHIFT + 1):
            hit = sum(1 for (i, j) in theirs if (i + dx, j + dy) in ours)
            rows.append((hit, dx, dy))
    rows.sort(key=lambda t: (-t[0], abs(t[1]) + abs(t[2])))
    zero = next(h for h, dx, dy in rows if dx == 0 and dy == 0)
    return rows[0], zero


def main() -> None:
    bar = "=" * 72
    print(bar)
    print("우리 셈법이 브이월드와 같은 자리를 가리키나 — 화소로 견준다")
    print(bar)
    print("  지적은 WMS 가 안 칠해 준다(이미 잰 것). 그래서 **칠해지는 층**으로")
    print(f"  잰다 — 물음은 층과 무관하다. z{Z} · 한 화소 ≈ 1m · ±{SHIFT} 화소")
    print()
    for name, lat, lon in SPOTS:
        x, y = tile_of(lon, lat, Z)
        print(f"  {name}")
        for layer, label in REF:
            try:
                theirs = wms_mask(layer, Z, x, y)
                feats = wfs_feats(layer, Z, x, y)
            except Exception as err:                   # noqa: BLE001
                print(f"    {label:<14} 못 쟀다 — {type(err).__name__}: {err}")
                continue
            if feats is None:
                print(f"    {label:<14} WFS 가 JSON 을 안 줬다")
                continue
            if not theirs or not feats:
                print(f"    {label:<14} 그림 {len(theirs):>5}화소 · 도형 "
                      f"{len(feats):>3}개 — 이 칸엔 없다")
                continue
            ours = paint(feats, Z, x, y, fill=True)
            if not ours:
                print(f"    {label:<14} 우리가 찍은 것이 0화소 — 도형이 점·선이다")
                continue
            (hit, dx, dy), zero = best_shift(theirs, ours)
            tag = "**(0,0) 이 이긴다 — 셈법이 맞다**" if (dx, dy) == (0, 0) \
                else f"**({dx:+d},{dy:+d}) 로 밀어야 맞는다 ≈ {math.hypot(dx, dy):.0f}m**"
            print(f"    {label:<14} 그림 {len(theirs):>5}화소 · 우리 "
                  f"{len(ours):>5}화소 · 도형 {len(feats):>3}개")
            print(f"    {'':<14} 제자리 {zero / len(theirs) * 100:5.1f}% → "
                  f"가장 잘 겹칠 때 {hit / len(theirs) * 100:5.1f}%  {tag}")
        # 상한에 걸리면 필지가 **빠진 채** 그려진다. 어긋남과 비슷해 보인다.
        for zz in (16, 17):
            xx, yy = tile_of(lon, lat, zz)
            fs = wfs_feats(CAD, zz, xx, yy)
            if fs is None:
                print(f"    필지 z{zz}        못 셌다")
                continue
            over = " ← **상한에 걸렸다. 빠진 필지가 있다**" if len(fs) >= VEC_MAX else ""
            print(f"    필지 z{zz}        한 칸에 {len(fs):>3}개 "
                  f"(상한 {VEC_MAX}){over}")
        print()
    print(bar)
    print("무엇을 보고 판단하나")
    print(bar)
    print("  · 어디서나 (0,0) → 우리 셈법은 맞다. 남은 것은 빠짐(상한)이다")
    print("  · 대구만 밀림 → 그 지역 그림과 좌표가 서로 다른 기준이다")
    print("  · 어디서나 같은 방향으로 밀림 → 우리 좌표 변환이 틀렸다")
    print("  · 상한에 걸린 칸이 있으면 → 그 칸은 필지가 빠진 채 그려진다")


if __name__ == "__main__":
    main()
