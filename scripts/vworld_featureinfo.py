"""용도지역 '이름' 을 어디서 얻을지 서버에 묻는다.

지금 화면은 색면만 깔려 있고 그 색이 무슨 뜻인지 알 방법이 없다. 두 길이
있는데 둘 다 **서버가 지원해야** 쓸 수 있다.

  GetFeatureInfo     필지를 누르면 그 자리의 용도지역 이름을 준다.
                     정확하고, 휴대폰에서 범례를 띄우지 않아도 된다.
  GetLegendGraphic   레이어의 공식 범례 그림을 준다. 색과 이름의 대응을
                     우리가 지어내지 않아도 된다.

레이어 이름을 추측했다가 세 겹으로 틀린 적이 있다(api/tile.js 주석).
그래서 이번에도 묻는다. GetCapabilities 에는 **어떤 레이어가 조회
가능(queryable)한지**와 **어떤 INFO_FORMAT 을 주는지**가 적혀 있다.

  python scripts/vworld_featureinfo.py
"""
from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redt.collect.http import get                      # noqa: E402

WMS = "https://api.vworld.kr/req/wms"
LAYERS = ["lt_c_uq111", "lt_c_uq112", "lt_c_uq113", "lt_c_uq114"]

# 화면에서 확인할 지점 — 용인 원삼(사장님 스크린샷 근처)과 화성 향남.
POINTS = [("용인 원삼", 37.132, 127.353), ("화성 향남", 37.100, 126.930)]

MERC_EDGE = 20037508.342789244


def merc(lat: float, lon: float) -> tuple[float, float]:
    x = lon * MERC_EDGE / 180.0
    y = math.log(math.tan((90 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    return x, y * MERC_EDGE / 180.0


def box_around(lat: float, lon: float, half_m: float = 200.0):
    """그 점을 한가운데 두는 작은 bbox 와, 그 안에서의 픽셀 좌표."""
    cx, cy = merc(lat, lon)
    bbox = f"{cx - half_m},{cy - half_m},{cx + half_m},{cy + half_m}"
    return bbox, 128, 128          # 256×256 의 한가운데


def call(params: dict, label: str, show: int = 500):
    print(f"\n── {label}")
    try:
        resp = get(WMS, {**params, "key": ""}, timeout=25)
    except Exception as exc:                                # noqa: BLE001
        print(f"   호출 실패: {type(exc).__name__}: {str(exc)[:160]}")
        return None
    ctype = resp.headers.get("content-type", "")
    body = resp.content
    print(f"   HTTP {resp.status_code} · {ctype} · {len(body):,}B")
    if ctype.startswith("image/"):
        print("   (그림)")
        return resp
    text = resp.text
    print("   " + text[:show].replace("\n", "\n   "))
    return resp


print("=" * 72)
print("1. GetCapabilities — 무엇이 조회 가능하고 어떤 형식을 주는가")
print("=" * 72)
cap = call({"SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0"},
           "GetCapabilities", show=0)

if cap is not None and not cap.headers.get("content-type", "").startswith("image/"):
    text = cap.text
    print(f"   길이 {len(text):,}자")
    # 네임스페이스가 붙어 오므로 태그 이름만 본다.
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        root = None
        print(f"   XML 파싱 실패: {exc}")
    if root is not None:
        def tag(e):
            return e.tag.split("}")[-1]

        fmts = [e.text for e in root.iter()
                if tag(e) == "Format" and e.text and "/" in e.text]
        info = sorted({f for f in fmts if f in (
            "text/html", "text/plain", "text/xml", "application/json",
            "application/vnd.ogc.gml", "application/geo+json")})
        print(f"\n   GetFeatureInfo 가 준다고 적힌 형식: {info or '(못 찾음)'}")

        found = {}
        for lyr in root.iter():
            if tag(lyr) != "Layer":
                continue
            name = next((tag(c) == "Name" and c.text for c in lyr), None)
            names = [c.text for c in lyr if tag(c) == "Name"]
            if not names:
                continue
            nm = names[0]
            if nm in LAYERS:
                found[nm] = lyr.get("queryable", "0")
        print(f"   우리 레이어의 queryable 값: {found or '(목록에 없음)'}")
        if not found:
            hits = sorted(set(re.findall(r"lt_c_uq11\d", text)))
            print(f"   (본문에서 찾은 비슷한 이름: {hits or '없음'})")

print()
print("=" * 72)
print("2. GetFeatureInfo — 필지를 누르면 이름이 오는가")
print("=" * 72)
for label, lat, lon in POINTS:
    bbox, i, j = box_around(lat, lon)
    for fmt in ("text/xml", "application/json", "text/html", "text/plain"):
        call({
            "SERVICE": "WMS", "REQUEST": "GetFeatureInfo", "VERSION": "1.3.0",
            "LAYERS": ",".join(LAYERS), "QUERY_LAYERS": ",".join(LAYERS),
            "CRS": "EPSG:3857", "BBOX": bbox,
            "WIDTH": "256", "HEIGHT": "256", "I": str(i), "J": str(j),
            "INFO_FORMAT": fmt, "FEATURE_COUNT": "10",
        }, f"{label} · INFO_FORMAT={fmt}")

print()
print("=" * 72)
print("3. GetLegendGraphic — 공식 범례 그림이 오는가")
print("=" * 72)
for lyr in LAYERS:
    call({"SERVICE": "WMS", "REQUEST": "GetLegendGraphic", "VERSION": "1.3.0",
          "LAYER": lyr, "FORMAT": "image/png"}, f"범례 {lyr}")

print()
print("끝. 위 결과로 화면에 무엇을 붙일지 정한다 — 추측하지 않는다.")
