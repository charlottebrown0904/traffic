"""용도지역을 지도에 깔 최적 경로를 **서버에 물어서** 정한다.

왜 필요한가
-----------
api/tile.js 에 레이어 이름을 `LT_C_UQ111` 로 박아 넣었는데, 그 이름은
이 저장소 어디에도 근거가 없다 — 내가 추측한 것이다. 그리고 앞선 WFS
탐침(docs/land-price-fallback.md)이 실제로 확인한 토지이용계획도 레이어
이름은 **`lt_c_lhblpn`** 이었다. 추측한 이름이 아예 없을 수 있다.

레이어 이름을 추측하지 않는다. WMS·WMTS 에는 서버가 가진 목록을 통째로
돌려주는 표준 요청 GetCapabilities 가 있다. 그것을 쓴다.

무엇을 갈라야 하는가
--------------------
용도지역을 화면에 깔 길이 셋인데, 비용과 결과물이 전혀 다르다.

  WMTS 타일   z/x/y 로 잘린 래스터. 가장 싸고 빠르다. 다만 브이월드
              WMTS 가 배경지도만 주고 주제도는 안 줄 수 있다 — 확인 대상.
  WMS GetMap  bbox 로 그려주는 래스터. 브이월드가 **공식 색으로** 그려
              주므로 지적편집도와 같은 화면이 된다.
  WFS 벡터    필지 도형 + 용도지역 이름. 색을 우리가 정하고, 필지를
              눌러 속성을 볼 수 있다. 대신 건수가 많으면 무겁다.

이 스크립트는 셋을 다 두드려 보고 **무엇이 실제로 오는지**를 찍는다.
`make` 로 도는 검사가 아니라, 러너에서 한 번 돌려 판단 근거를 만드는
탐침이다 (scripts/vworld_layers.py 와 같은 성격).

  python scripts/vworld_zoning.py
"""
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
DOMAIN = "sado-toji.vercel.app"

# 화성 향남 일대 — 계획관리·공장이 실제로 많고, 우리가 보는 IC 근처다.
BBOX = "126.87,37.06,126.93,37.11"
# 같은 자리를 덮는 z=13 타일. WMTS·WMS 를 같은 땅으로 비교하기 위한 것.
TILE = {"z": 13, "x": 6989, "y": 3494}

# 이름에 이것이 들어 있으면 눈여겨본다.
NEEDLES = ("용도지역", "지역지구", "토지이용", "도시계획", "uq1", "lhblpn")


def tag(el) -> str:
    return el.tag.split("}")[-1]


def fetch(url: str, params: dict, binary: bool = False):
    """중계기를 지나 부른다. (본문, 상류 타입, 바이트수) 를 돌려준다."""
    target = f"{url}?{urllib.parse.urlencode(params)}"
    relayed = f"{RELAY}/api/relay?" + urllib.parse.urlencode({"target": target})
    req = urllib.request.Request(relayed, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read()
            # 중계기는 바이너리를 base64 로 감싸 보내고 원래 타입을 헤더에 남긴다.
            up = resp.headers.get("x-relay-content-type") or \
                 resp.headers.get("content-type") or ""
            if resp.headers.get("x-relay-encoding") == "base64":
                import base64
                data = base64.b64decode(raw)
                return (data if binary else data[:400].decode("utf-8", "replace")), up, len(data)
            return (raw if binary else raw.decode("utf-8", "replace")), up, len(raw)
    except Exception as exc:                       # noqa: BLE001
        return f"__ERR__ {type(exc).__name__} {exc}", "", 0


def say(body, kind: str = "") -> str:
    """서버가 하는 말만 뽑는다. 원문을 그대로 흘리면 안 읽힌다."""
    if isinstance(body, bytes):
        if body[:8] == b"\x89PNG\r\n\x1a\n":
            return "★ PNG 그림"
        body = body[:400].decode("utf-8", "replace")
    if body.startswith("__ERR__"):
        return body[:110]
    m = re.search(r'<ServiceException[^>]*(?:code="([^"]*)")?[^>]*>([^<]*)', body)
    if m:
        return f"{m.group(1) or ''} {(m.group(2) or '').strip()}".strip()
    m = re.search(r'"resultMsg"\s*:\s*"([^"]*)"', body)
    if m:
        return m.group(1)
    if "Capabilities" in body:
        return f"목록 옴 ({len(body):,}바이트)"
    return re.sub(r"\s+", " ", body[:110])


def layer_names(xml_text: str, want: tuple[str, ...]) -> list[tuple[str, str]]:
    """(Name, Title). WMS 는 Layer, WMTS 는 Layer 안에 ows:Identifier 를 쓴다."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if tag(el) not in ("Layer", "FeatureType"):
            continue
        name = title = ""
        for child in el:
            if tag(child) in ("Name", "Identifier"):
                name = (child.text or "").strip()
            elif tag(child) == "Title":
                title = (child.text or "").strip()
        if name:
            out.append((name, title))
    if not want:
        return out
    return [(n, t) for n, t in out
            if any(w.lower() in (n + t).lower() for w in want)]


def main() -> int:
    if not RELAY or not TOKEN:
        print("RELAY_URL / RELAY_TOKEN 이 없습니다. 이 탐침은 러너에서 돌립니다.")
        return 1

    print("=" * 68)
    print(" 용도지역을 지도에 깔 길 — 서버에 물어봅니다")
    print("=" * 68)

    # ── 1. WMS 목록 ──────────────────────────────────────────────
    print("\n1. WMS 가 가진 레이어 (GetCapabilities)")
    body, _, _ = fetch("https://api.vworld.kr/req/wms", {
        "SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0",
        "domain": DOMAIN,
    })
    print(f"   {say(body)}")
    hits = layer_names(body, NEEDLES)
    allw = layer_names(body, ())
    print(f"   전체 {len(allw)}개 · 용도지역 관련 {len(hits)}개")
    for n, t in hits[:25]:
        print(f"     {n:<24} {t}")

    # ── 2. WMTS 목록 ─────────────────────────────────────────────
    print("\n2. WMTS 가 가진 레이어 (주제도를 주는가?)")
    body2, _, _ = fetch("https://api.vworld.kr/req/wmts/1.0.0/WMTSCapabilities.xml",
                        {"domain": DOMAIN})
    print(f"   {say(body2)}")
    allm = layer_names(body2, ())
    print(f"   전체 {len(allm)}개: {', '.join(n for n, _ in allm[:20]) or '(못 읽음)'}")
    hitm = layer_names(body2, NEEDLES)
    print(f"   용도지역 관련 {len(hitm)}개"
          + (f": {', '.join(n for n, _ in hitm)}" if hitm else " ← 없으면 WMTS 로는 못 깝니다"))

    # ── 3. 이름 후보를 실제로 그려본다 ───────────────────────────
    print("\n3. 실제로 그림이 오는가 (WMS GetMap · 화성 향남)")
    for layer in ("LT_C_UQ111", "lt_c_uq111", "lt_c_lhblpn", "LT_C_LHBLPN"):
        img, up, n = fetch("https://api.vworld.kr/req/wms", {
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
            "LAYERS": layer, "STYLES": "", "CRS": "EPSG:4326",
            # 1.3.0 의 EPSG:4326 은 축 순서가 lat,lon 이다.
            "BBOX": "37.06,126.87,37.11,126.93",
            "WIDTH": "256", "HEIGHT": "256", "FORMAT": "image/png",
            "TRANSPARENT": "true", "domain": DOMAIN,
        }, binary=True)
        print(f"   {layer:<14} {up or '(타입 없음)':<28} {n:>7,}B  {say(img)}")

    print("\n4. WMTS 타일로도 오는가 (내가 박아 넣은 방식)")
    for layer in ("LT_C_UQ111", "lt_c_uq111", "Base"):
        img, up, n = fetch(
            f"https://api.vworld.kr/req/wmts/1.0.0/{layer}/"
            f"{TILE['z']}/{TILE['y']}/{TILE['x']}.png", {}, binary=True)
        print(f"   {layer:<14} {up or '(타입 없음)':<28} {n:>7,}B  {say(img)}")

    # ── 5. 벡터로 받으면 무엇이 오는가 ──────────────────────────
    print("\n5. WFS 벡터 — 용도지역 이름이 값으로 오는가")
    for typename in ("lt_c_lhblpn", "lt_c_uq111"):
        body3, _, _ = fetch("https://api.vworld.kr/req/wfs", {
            "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
            "TYPENAME": typename, "BBOX": BBOX, "SRSNAME": "EPSG:4326",
            "OUTPUT": "application/json", "MAXFEATURES": "2",
            "domain": DOMAIN,
        })
        print(f"   {typename:<14} {say(body3)}")
        # 어떤 칸이 오는지가 판단의 핵심이다.
        keys = sorted(set(re.findall(r'"([a-z_0-9]+)"\s*:', body3)))[:22]
        if keys:
            print(f"     칸: {', '.join(keys)}")

    # ── 6. 웹 머케이터로도 그려주는가 ────────────────────────────
    #
    # Leaflet 의 타일 격자는 **웹 머케이터(EPSG:3857)** 다. 4326 으로
    # 받아 머케이터 격자에 붙이면 위도가 늘어나 땅이 어긋난다. 남은
    # 가정이 이것 하나뿐이라 확인한다 — 앞의 두 가정(레이어 이름·WMTS)이
    # 다 틀렸으므로 이번엔 묻고 간다.
    print("\n6. 웹 머케이터(EPSG:3857)로도 그려주는가 — Leaflet 격자와 맞추려면 필요")
    # 화성 향남을 덮는 머케이터 좌표 (m). z=13 타일 한 장 크기쯤.
    MERC = "14122000,4438000,14127000,4443000"
    for crs_key in ("CRS", "SRS"):
        for layer in ("lt_c_lhblpn", "lt_c_uq112"):
            img, up, n = fetch("https://api.vworld.kr/req/wms", {
                "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
                "LAYERS": layer, "STYLES": "", crs_key: "EPSG:3857",
                "BBOX": MERC, "WIDTH": "256", "HEIGHT": "256",
                "FORMAT": "image/png", "TRANSPARENT": "true", "domain": DOMAIN,
            }, binary=True)
            print(f"   {crs_key}={layer:<14} {up or '(타입 없음)':<26} {n:>7,}B  {say(img)}")

    # ── 7. 관리지역(계획·생산관리가 있는 곳)도 그려지는가 ────────
    print("\n7. 우리 필터가 보는 용도지역이 어느 레이어에 있는가")
    print("   land_use_filter = 계획관리 · 생산관리 · 자연녹지")
    for layer, what in (("lt_c_uq111", "도시지역 (자연녹지가 이 안)"),
                        ("lt_c_uq112", "관리지역 (계획·생산관리가 이 안)"),
                        ("lt_c_lhblpn", "토지이용계획도 (전부 한 장)")):
        img, up, n = fetch("https://api.vworld.kr/req/wms", {
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
            "LAYERS": layer, "STYLES": "", "CRS": "EPSG:4326",
            "BBOX": "37.06,126.87,37.11,126.93",
            "WIDTH": "256", "HEIGHT": "256", "FORMAT": "image/png",
            "TRANSPARENT": "true", "domain": DOMAIN,
        }, binary=True)
        print(f"   {layer:<14} {n:>7,}B  {say(img):<12} {what}")

    print("\n8. 토지이용계획도의 용도지역 이름 값 (필지를 눌렀을 때 띄울 것)")
    body4, _, _ = fetch("https://api.vworld.kr/req/wfs", {
        "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
        "TYPENAME": "lt_c_lhblpn", "BBOX": BBOX, "SRSNAME": "EPSG:4326",
        "OUTPUT": "application/json", "MAXFEATURES": "12", "domain": DOMAIN,
    })
    names = re.findall(r'"zonename"\s*:\s*"([^"]*)"', body4)
    codes = re.findall(r'"zonecode"\s*:\s*"([^"]*)"', body4)
    print(f"   zonename: {', '.join(sorted(set(names))) or '(없음)'}")
    print(f"   zonecode: {', '.join(sorted(set(codes))[:12]) or '(없음)'}")

    # ── 9. 네 장을 한 번에 겹쳐 주는가 ──────────────────────────
    #
    # 용도지역은 대분류별로 레이어가 넷이다(도시·관리·농림·자연환경보전).
    # WMS 규격은 LAYERS 를 쉼표로 여러 장 받게 되어 있는데, 브이월드가
    # 그것을 지키는지는 별개다. 지키면 타일 한 장에 한 번만 부르면 되고,
    # 안 지키면 네 번 불러 우리가 겹쳐야 한다 — 비용이 네 배다.
    print("\n9. 용도지역 네 장을 한 요청에 겹쳐 주는가 (LAYERS 쉼표)")
    combos = [
        ("lt_c_uq111", "도시 한 장"),
        ("lt_c_uq111,lt_c_uq112", "도시+관리"),
        ("lt_c_uq111,lt_c_uq112,lt_c_uq113,lt_c_uq114", "네 장 전부"),
    ]
    for layers, what in combos:
        img, up, n = fetch("https://api.vworld.kr/req/wms", {
            "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
            "LAYERS": layers, "STYLES": "", "CRS": "EPSG:3857",
            "BBOX": "14122000,4438000,14127000,4443000",
            "WIDTH": "256", "HEIGHT": "256", "FORMAT": "image/png",
            "TRANSPARENT": "true", "domain": DOMAIN,
        }, binary=True)
        print(f"   {what:<12} {n:>7,}B  {say(img)}   ({layers})")

    # ── 10. 지적도(필지 경계)가 있는가 ──────────────────────────
    #
    # 네이버 지적편집도는 용도지역 색 위에 필지 경계선이 얹혀 있다.
    # 그 선이 있어야 '이 필지' 를 눈으로 짚을 수 있다.
    print("\n10. 필지 경계선 레이어가 있는가 (지적편집도의 그 선)")
    body5, _, _ = fetch("https://api.vworld.kr/req/wms", {
        "SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.3.0",
        "domain": DOMAIN,
    })
    for n, t in layer_names(body5, ("지적", "필지", "경계", "연속")):
        print(f"     {n:<24} {t}")

    # ── 11. 한 점의 용도지역을 물을 수 있는가 ───────────────────
    #
    # 필지를 눌렀을 때 '계획관리지역' 이라고 띄우려면 점 하나의 값을
    # 알아야 한다. WMS 규격의 GetFeatureInfo 가 그것이다. 되면 WFS 로
    # 도형을 다 받아올 필요가 없다 — 훨씬 싸다.
    print("\n11. 누른 점의 용도지역을 물을 수 있는가 (GetFeatureInfo)")
    for layers in ("lt_c_uq112", "lt_c_uq111,lt_c_uq112"):
        got, up, n = fetch("https://api.vworld.kr/req/wms", {
            "SERVICE": "WMS", "REQUEST": "GetFeatureInfo", "VERSION": "1.3.0",
            "LAYERS": layers, "QUERY_LAYERS": layers, "STYLES": "",
            "CRS": "EPSG:4326", "BBOX": "37.06,126.87,37.11,126.93",
            "WIDTH": "256", "HEIGHT": "256", "I": "128", "J": "128",
            "INFO_FORMAT": "application/json", "domain": DOMAIN,
        })
        print(f"   {layers:<26} {say(got)}")

    print("\n" + "=" * 68)
    print(" 판단: 3·4 에서 PNG 가 온 방식이 화면에 깔 수 있는 길입니다.")
    print("       6 이 통과하면 Leaflet 격자에 그대로 얹을 수 있습니다.")
    print("       8 에 용도지역 이름이 오면 필지를 눌러 속성을 띄울 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
