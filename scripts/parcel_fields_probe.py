"""필지를 눌러도 정보가 안 나오는 곳이 있다 — 무엇이 없는지 잰다.

보고(2026-09-10): "현재 정보가 확인이 안되는 토지가 있습니다. 계획관리
지역만 클릭이 되는 것 같은데 확인 필요합니다."

지금 화면은 **dt_d194 한 곳**에만 묻습니다. 그 표에 없는 필지는
'필지를 못 찾았습니다' 가 되는데, 그것이 '땅이 없다' 로 읽힙니다.

여기서 세 가지를 나눠 봅니다.

  ① 어느 표에 있고 어느 표에 없는가
     같은 점을 dt_d194(토지특성)와 lp_pa_cbnd_bubun(연속지적도)에
     각각 물어, 한쪽에만 있는 경우를 찾습니다. 경계선은 이미 연속
     지적도로 그리고 있으므로, 그 표에 있으면 최소한 지번·면적·도형은
     보여줄 수 있습니다.

  ② 각 표가 실제로 무슨 칸을 주는가
     이름을 맞히지 않고 받아서 적습니다. 이 저장소는 레이어 이름을
     세 번 틀렸습니다.

  ③ 주소(도로명)를 어디서 받는가
     요구사항: 필지 카드에 도로명 주소. 브이월드 역지오코딩이
     도로명과 지번을 같이 주는지 봅니다.

좌표는 주소로 만듭니다 — 스크린샷의 그 필지를 그대로 두드리려고.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE", "https://toji.fyi")
TOKEN = os.environ.get("TOKEN", "")
TIMEOUT = 45
HALF = 0.0006          # api/tile.js 의 PARCEL_HALF_DEG 와 같은 값

# 보고에 나온 두 곳. 하나는 되고 하나는 안 되는 것으로 보입니다.
SPOTS = [
    ("안 나온다고 하신 곳", "경기도 광주시 초월읍 지월리 14-1"),
    ("나온다고 하신 곳 (계획관리)", "경기도 안성시 공도읍 승두리 40"),
]

# 키가 응답에 실려 올 수 있다 — 로그로 나가기 전에 지운다.
HIDE = re.compile(r'(?i)((?:key|apikey|servicekey)=)[^&"\s<]+')


def show(text: str, n: int = 300) -> str:
    return " ".join(HIDE.sub(r"\1(가림)", text)[:n].split())


def relay(target: str) -> tuple[int, str]:
    url = f"{BASE}/api/relay?target={urllib.parse.quote(target, safe='')}"
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as exc:                                # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def geocode(address: str) -> tuple[float, float] | None:
    """지번 주소 → 좌표. 스크린샷의 그 필지를 그대로 두드리려고."""
    q = ("service=address&request=getcoord&version=2.0&crs=epsg:4326"
         f"&type=PARCEL&address={urllib.parse.quote(address)}")
    code, text = relay("https://api.vworld.kr/req/address?" + q)
    try:
        pt = json.loads(text)["response"]["result"]["point"]
        return float(pt["x"]), float(pt["y"])
    except Exception:                                        # noqa: BLE001
        print(f"    좌표를 못 얻었습니다 (http={code}) {show(text, 160)}")
        return None


def wfs(typename: str, lon: float, lat: float) -> tuple[int, list]:
    q = ("SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0"
         f"&TYPENAME={typename}&SRSNAME=EPSG:4326"
         "&OUTPUT=application/json&MAXFEATURES=30&RESULTTYPE=results"
         f"&BBOX={lon - HALF},{lat - HALF},{lon + HALF},{lat + HALF}")
    code, text = relay("https://api.vworld.kr/req/wfs?" + q)
    try:
        return code, (json.loads(text) or {}).get("features") or []
    except Exception:                                        # noqa: BLE001
        print(f"      읽지 못했습니다: {show(text, 200)}")
        return code, []


def in_ring(ring, lon, lat) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            cut = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if lon < cut:
                inside = not inside
    return inside


def hits(geom, lon, lat) -> bool:
    if not geom:
        return False
    t = geom.get("type")
    polys = geom["coordinates"] if t == "MultiPolygon" else \
        [geom["coordinates"]] if t == "Polygon" else []
    return any(r and in_ring(r[0], lon, lat) for r in polys)


def look(label: str, typename: str, lon: float, lat: float) -> None:
    code, feats = wfs(typename, lon, lat)
    hit = next((f for f in feats if hits(f.get("geometry"), lon, lat)), None)
    mark = "✓ 그 점을 품는 필지 있음" if hit else "✗ 없음"
    print(f"      {label:<28} http={code} 이웃 {len(feats):>2}개  {mark}")
    if hit:
        props = {k: v for k, v in (hit.get("properties") or {}).items()
                 if k not in ("ag_geom",)}
        print(f"        칸 {len(props)}개: {', '.join(list(props)[:14])}")
        keep = {k: v for k, v in props.items() if v not in (None, "")}
        print(f"        값: {show(json.dumps(keep, ensure_ascii=False), 460)}")


def address(lon: float, lat: float) -> None:
    """역지오코딩 — 도로명과 지번을 같이 주는가."""
    for kind in ("BOTH", "ROAD", "PARCEL"):
        q = ("service=address&request=getAddress&version=2.0"
             f"&crs=epsg:4326&point={lon},{lat}&type={kind}"
             "&format=json&simple=false")
        code, text = relay("https://api.vworld.kr/req/address?" + q)
        try:
            items = json.loads(text)["response"]["result"]
            got = " | ".join(
                f"{i.get('type')}: {i.get('text')}" for i in items)
        except Exception:                                    # noqa: BLE001
            got = show(text, 200)
        print(f"      type={kind:<7} http={code}  {got[:220]}")


def main() -> int:
    if not TOKEN:
        print("::error::중계기 토큰이 없습니다")
        return 1
    print(f"BASE={BASE}\n")
    for label, addr in SPOTS:
        print(f"── {label} — {addr}")
        pt = geocode(addr)
        if not pt:
            print()
            continue
        lon, lat = pt
        print(f"    좌표 {lat:.6f}, {lon:.6f}")
        print("    ① 어느 표에 있는가")
        look("dt_d194 (지금 쓰는 토지특성)", "dt_d194", lon, lat)
        look("lp_pa_cbnd_bubun (연속지적도)", "lp_pa_cbnd_bubun", lon, lat)
        look("lp_pa_cbnd_bonbun (연속지적도 본번)",
             "lp_pa_cbnd_bonbun", lon, lat)
        print("    ③ 주소는 어디서 받는가")
        address(lon, lat)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
