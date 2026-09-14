"""브이월드 층이 **실제로 그림을 주는지** 두드린다 (2026-09-14).

이름이 목록에 있다고 그림이 오는 것은 아니다. 같은 자리에서 이미 세 겹으로
틀린 적이 있다 — WMTS 는 통째로 404 였고, 대문자는 XML 을 줬고, 'uq111' 은
용도지역이 아니라 도시지역이었다 (scripts/vworld_zoning.py).

'개발' 층에 건 일곱 장을 그래서 두드린다. 재는 것은 둘이다.

  바이트 수      1,784B 언저리면 **빈 그림**이다 (투명 PNG 한 장 크기).
  칠해진 화소    0 이면 아무것도 안 그렸다는 뜻이다.

빈 그림이 오는 층은 목록에서 빼고 왜 뺐는지 남긴다. '켰는데 아무것도 안
나온다' 는 화면은 고장으로 읽힌다 — 없는 것보다 나쁘다.
"""
from __future__ import annotations

import io
import math
import os
import sys

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WMS = "https://api.vworld.kr/req/wms"
WFS = "https://api.vworld.kr/req/wfs"

LAYERS = [
    ("lt_c_wgisiegug", "국가산업단지"),
    ("lt_c_wgisieilban", "일반산업단지"),
    ("lt_c_wgisiedosi", "첨단산업단지"),
    ("lt_c_wgisienong", "농공단지"),
    ("lt_c_lhzone", "사업지구경계도"),
    ("lt_c_damdan", "단지경계"),
    ("lt_c_upisuq151", "도시계획(도로)"),
    ("lt_c_adsigg", "시군구"),
    ("lt_c_ademd", "읍면동"),
]

# 두드릴 자리 — 산업단지가 실제로 있는 곳이라야 '빈 그림' 과 '그 칸에
# 아무것도 없음' 이 안 헷갈린다. 화성 향남·안산 반월·아산 탕정.
SPOTS = [
    ("화성 향남", 37.0, 126.93),
    ("안산 반월", 37.30, 126.80),
    ("아산 탕정", 36.80, 127.08),
    # 첨단산업단지가 세 자리 모두 빈 그림이었다 (1차). 층이 죽은 것과
    # '그 자리에 없는 것' 을 가르려면 **있는 자리**를 하나 넣어야 한다.
    ("성남 판교", 37.402, 127.108),
]


def merc_bbox(lat: float, lon: float, half_m: float = 4000.0) -> str:
    """그 자리를 가운데 둔 사각형 (EPSG:3857, 미터)."""
    x = lon * 20037508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
    y = y * 20037508.34 / 180
    return f"{x - half_m},{y - half_m},{x + half_m},{y + half_m}"


def call(url: str, params: dict, timeout: int = 60):
    """중계기는 목적지를 **target 한 칸**에 통째로 받는다
    (scripts/vworld_layers.py 와 같은 길). 인증키는 중계기가 끼운다."""
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    import urllib.parse                                # noqa: PLC0415
    target = f"{url}?{urllib.parse.urlencode(params)}"
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def png_bytes(raw: bytes) -> bytes:
    """**중계기는 그림을 base64 로 감싸 보낸다** (글자가 아닌 몸통은 전부).

    처음엔 그것을 모르고 그대로 Pillow 에 넣어 '열 수 없음' 이 아홉 줄
    나왔다 — 층이 죽은 줄로 읽힐 뻔했다. PNG 머리(\x89PNG)가 아니면
    base64 로 보고 풀어 본다.
    """
    if raw[:4] == b"\x89PNG":
        return raw
    import base64                                      # noqa: PLC0415
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:                                  # noqa: BLE001
        return raw


def painted(raw: bytes) -> int | str:
    """칠해진 화소 수. Pillow 가 없으면 '?' 를 돌려준다."""
    try:
        from PIL import Image                          # noqa: PLC0415
    except ImportError:
        return "?"
    try:
        im = Image.open(io.BytesIO(png_bytes(raw))).convert("RGBA")
    except Exception:                                  # noqa: BLE001
        return "열 수 없음"
    return sum(1 for p in im.getdata() if p[3] > 8)


def main() -> None:
    print("=" * 72)
    print("브이월드 '개발' 층 — 그림이 실제로 오는가")
    print("=" * 72)
    for name, label in LAYERS:
        print(f"\n[{name}] {label}")
        for spot, lat, lon in SPOTS:
            try:
                resp = call(WMS, {
                    "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
                    "LAYERS": name, "STYLES": "", "CRS": "EPSG:3857",
                    "BBOX": merc_bbox(lat, lon),
                    "WIDTH": "256", "HEIGHT": "256",
                    "FORMAT": "image/png", "TRANSPARENT": "true",
                })
            except Exception as exc:                   # noqa: BLE001
                print(f"   {spot:10s} 실패 {type(exc).__name__}")
                continue
            raw = resp.content
            ctype = resp.headers.get("content-type", "")
            if "xml" in ctype or raw[:5] == b"<?xml":
                print(f"   {spot:10s} ✗ XML 이 왔다: {raw[:120]!r}")
                continue
            print(f"   {spot:10s} {resp.status_code} · {len(raw):,}B"
                  f" · 칠해진 화소 {painted(raw)}")

    # WFS 도 한 자리 — 행정구역 한 덩이가 오는가 (mode=admin 의 길).
    print("\n" + "=" * 72)
    print("행정구역 WFS — 누른 자리를 감싸는 폴리곤이 오는가")
    print("=" * 72)
    for name, label in (("lt_c_adsigg", "시군구"), ("lt_c_ademd", "읍면동")):
        lat, lon = 37.0, 126.93
        d = 0.0001
        try:
            resp = call(WFS, {
                "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0",
                "TYPENAME": name,
                "BBOX": f"{lon - d},{lat - d},{lon + d},{lat + d}",
                "SRSNAME": "EPSG:4326", "OUTPUT": "application/json",
                "MAXFEATURES": "4", "RESULTTYPE": "results",
                "DOMAIN": "https://toji.fyi/",
            })
            body = resp.json()
        except Exception as exc:                       # noqa: BLE001
            print(f"  {name} ({label}) 실패: {type(exc).__name__} {exc}")
            continue
        feats = (body or {}).get("features") or []
        print(f"  {name} ({label}): {len(feats)}건")
        if feats:
            props = feats[0].get("properties") or {}
            print(f"    속성 열쇠: {sorted(props)}")
            print(f"    값: {dict(list(props.items())[:6])}")


if __name__ == "__main__":
    main()
