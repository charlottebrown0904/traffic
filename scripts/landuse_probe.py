"""용도지구·용도구역과 '다른 법령에 따른 지역·지구' 를 받을 수 있는가.

보고(2026-09-10): "다른 법령에 다른 용도 지구, 용도 구역은 못 가져
오나요? 단순히 용도 지역으로만 토지를 평가하니 오류가 발생됩니다.
(농림지역의 농업진흥구역, 준보전산지, 개발제한구역 등)에 따라 개발
방식이 달라짐"

맞는 지적입니다. 지금 카드는 **용도지역 한 줄**만 보여주고, 레이더의
'개발 여지' 축도 그것 하나로 계산합니다. 그런데 실제로 무엇을 지을 수
있는지는 그 위에 겹친 것들이 정합니다.

  계획관리지역   + 농업진흥구역   → 사실상 농업용 말고는 어렵다
  자연녹지지역   + 개발제한구역   → 원칙적으로 신축 불가
  계획관리지역   + 준보전산지     → 산지전용허가가 따로 필요하다
  어디든         + 접도구역       → 도로 경계에서 일정 폭 건축 제한

토지이음 화면(스크린샷)의 '다른 법령 등에 따른 지역·지구등' 칸이
바로 그것입니다. 그 자료를 우리가 받을 수 있는지 봅니다.

**이름을 맞히지 않습니다.** 이 저장소는 레이어 이름을 세 번 틀렸습니다.
서버에 무엇이 열려 있는지 목록으로 받고, 그 다음에 실제로 한 점을
찔러 봅니다.
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
HALF = 0.00012        # api/tile.js 의 PARCEL_HALF_DEG 와 같은 값

# 스크린샷의 그 필지. 계획관리 + 자연녹지가 겹쳐 있고, 토지이음에는
# 가축사육제한·건축허가제한·접도구역·준보전산지가 더 붙어 있었습니다.
SPOT = "경상북도 상주시 함창읍 대조리 707-1"

# 이미 우리가 타일로 쓰는 넷. WFS 로도 한 점을 물을 수 있는지 봅니다.
#   111 용도지역 · 112 용도지구 · 113 용도구역 · 114 (확인 필요)
KNOWN = ["lt_c_uq111", "lt_c_uq112", "lt_c_uq113", "lt_c_uq114"]

# 목록에서 이런 말이 든 것을 후보로 봅니다.
NEEDLES = ("용도", "지구", "구역", "토지이용", "규제", "산지", "농업",
           "개발제한", "보호", "접도")

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
    q = ("service=address&request=getcoord&version=2.0&crs=epsg:4326"
         f"&type=PARCEL&address={urllib.parse.quote(address)}")
    code, text = relay("https://api.vworld.kr/req/address?" + q)
    try:
        pt = json.loads(text)["response"]["result"]["point"]
        return float(pt["x"]), float(pt["y"])
    except Exception:                                        # noqa: BLE001
        print(f"  좌표를 못 얻었습니다 (http={code}) {show(text, 160)}")
        return None


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
    """그 점을 품는가. 네모로 부르면 이웃이 같이 오므로 골라내야 한다."""
    if not geom:
        return False
    t = geom.get("type")
    polys = geom["coordinates"] if t == "MultiPolygon" else \
        [geom["coordinates"]] if t == "Polygon" else []
    return any(r and in_ring(r[0], lon, lat) for r in polys)


def catalog() -> list[tuple[str, str]]:
    """서버가 무엇을 여는가. WFS 목록에서 후보를 고른다."""
    print("① 브이월드 WFS 가 여는 것 중 지역·지구로 보이는 것")
    code, text = relay("https://api.vworld.kr/req/wfs?"
                       "SERVICE=WFS&REQUEST=GetCapabilities&VERSION=1.1.0")
    print(f"   http={code} {len(text):,}B")
    if code != 200:
        print("   " + show(text))
        return []
    pairs = re.findall(r"<Name>([^<]+)</Name>\s*<Title>([^<]*)</Title>", text)
    hits = [(n, t) for n, t in pairs
            if any(w in t for w in NEEDLES) or any(w in n for w in ("uq", "uf"))]
    print(f"   레이어 {len(pairs):,}개 중 후보 {len(hits)}개")
    for n, t in sorted(hits, key=lambda x: x[1]):
        print(f"     {n:<24} {t}")
    # 이름을 콕 집어 확인한다. 위 목록은 길어 로그에서 잘리기 쉽다.
    print("   ── 콕 집어 찾기")
    for word in ("개발제한", "산지", "접도", "농업진흥", "군사", "문화재"):
        found = [f"{n}({t})" for n, t in pairs if word in t]
        print(f"     {word:<6} {', '.join(found) if found else '— 목록에 없음'}")
    return hits


# 개발 가부를 실제로 가르는 층만 고른 것. 다 부르면 스무 번이 넘습니다.
# **한 요청에 여럿을 담을 수 있는지**가 이번 탐침의 핵심입니다.
SHORTLIST = [
    "lt_c_ud801",        # 개발제한구역 — 원칙적으로 신축 불가
    "lt_c_agrixue101",   # 농업진흥지역도 — 농업진흥구역/농업보호구역
    "lt_c_um000",        # 가축사육제한구역
    "lt_c_upisuq171",    # 개발행위허가제한지역
    "lt_c_uf151",        # 산림보호구역
    "lt_c_um710",        # 상수원보호
    "lt_c_uo101",        # 교육환경보호구역
    "lt_c_uq121",        # 경관지구
    "lt_c_uq124",        # 방화지구
    "lt_c_uq126",        # 보호지구
    "lt_c_uq130",        # 특정용도제한지구
]


def multi(lon: float, lat: float) -> None:
    """한 요청에 여러 층을 담을 수 있는가.

    WFS 1.1.0 은 TYPENAME 에 쉼표로 여럿을 적을 수 있다고 되어 있습니다.
    된다면 스무 번이 한 번이 됩니다 — 이번 일의 성패가 여기 달렸습니다.
    WMS 쪽은 이미 그렇게 쓰고 있습니다(용도지역 네 장을 한 번에).
    """
    print("   여러 층을 한 요청에 담을 수 있는가 (쉼표로)")
    print("   ※ 토지특성(dt_d194)까지 같이 담으면 호출이 안 늘어난다")
    names = ",".join(["dt_d194"] + SHORTLIST)
    q = ("SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0"
         f"&TYPENAME={names}&SRSNAME=EPSG:4326"
         "&OUTPUT=application/json&MAXFEATURES=50&RESULTTYPE=results"
         f"&BBOX={lon - HALF},{lat - HALF},{lon + HALF},{lat + HALF}")
    code, text = relay("https://api.vworld.kr/req/wfs?" + q)
    try:
        feats = (json.loads(text) or {}).get("features") or []
    except Exception:                                        # noqa: BLE001
        print(f"     http={code}  안 됩니다 — {show(text, 260)}")
        return
    print(f"     http={code}  {len(feats)}건  {len(text):,}B"
          f"  ← 이 크기가 클릭 한 번의 무게다")
    kinds = {}
    for f in feats:
        kinds[str(f.get("id") or "?").split(".")[0]] = \
            kinds.get(str(f.get("id") or "?").split(".")[0], 0) + 1
    print(f"     층별: {kinds}")
    for f in feats[:10]:
        p = {k: v for k, v in (f.get("properties") or {}).items()
             if k != "ag_geom" and v not in (None, "")}
        label = " / ".join(str(v) for k, v in p.items() if k.endswith("_nm"))
        print(f"       · {f.get('id') or ''} {label or json.dumps(p, ensure_ascii=False)[:100]}")


def portal_search() -> None:
    """공공데이터포털에 토지이용계획 API 가 무슨 이름으로 있는가.

    길을 네 번 찍어 봤는데 넷 다 '해당 서비스 없거나 폐기됨' 이었습니다.
    더 찍지 않고 **목록에서 찾습니다.**
    """
    print("   공공데이터포털에서 '토지이용계획' 을 찾는다")
    url = ("https://www.data.go.kr/tcs/dss/selectDataSetList.do"
           "?dType=API&keyword=" + urllib.parse.quote("토지이용계획"))
    code, text = relay(url)
    print(f"     http={code} {len(text):,}B")
    # 목록 화면의 제목만 긁는다. 자바스크립트로 그려지면 안 나옵니다.
    titles = re.findall(r'title="([^"]{4,60})"', text)[:20]
    for t in dict.fromkeys(titles):
        print(f"       · {t}")
    if not titles:
        print("       (제목을 못 긁었습니다 — 자바스크립트로 그리는 화면입니다)")


def poke(typename: str, lon: float, lat: float) -> None:
    """한 점을 찔러 무엇이 오는지. 오는 칸 이름을 그대로 적는다."""
    q = ("SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0"
         f"&TYPENAME={typename}&SRSNAME=EPSG:4326"
         "&OUTPUT=application/json&MAXFEATURES=30&RESULTTYPE=results"
         f"&BBOX={lon - HALF},{lat - HALF},{lon + HALF},{lat + HALF}")
    code, text = relay("https://api.vworld.kr/req/wfs?" + q)
    try:
        feats = (json.loads(text) or {}).get("features") or []
    except Exception:                                        # noqa: BLE001
        print(f"   {typename:<24} http={code}  {show(text, 150)}")
        return
    if not feats:
        print(f"   {typename:<24} http={code}  겹치는 것 없음")
        return
    names = []
    for f in feats:
        p = {k: v for k, v in (f.get("properties") or {}).items()
             if k != "ag_geom" and v not in (None, "")}
        # 사람이 읽는 이름으로 보이는 칸만 골라 적는다.
        label = " / ".join(str(v) for k, v in p.items()
                           if k.endswith("_nm") or k in ("dgm_nm", "name"))
        names.append(label or json.dumps(p, ensure_ascii=False)[:120])
    print(f"   {typename:<24} http={code}  {len(feats)}건")
    for nm in names[:8]:
        print(f"       · {nm}")
    first = {k: v for k, v in (feats[0].get("properties") or {}).items()
             if k != "ag_geom"}
    print(f"       칸: {', '.join(list(first)[:14])}")


def main() -> int:
    if not TOKEN:
        print("::error::중계기 토큰이 없습니다")
        return 1
    print(f"BASE={BASE}\n")
    hits = catalog()
    print()

    pt = geocode(SPOT)
    if not pt:
        return 1
    lon, lat = pt
    print(f"② 그 필지를 찔러 본다 — {SPOT}")
    print(f"   좌표 {lat:.6f}, {lon:.6f}\n")
    print("   이미 타일로 쓰는 넷")
    for t in KNOWN:
        poke(t, lon, lat)
    print()

    # 목록에서 새로 나온 후보 가운데 안 찔러 본 것.
    more = [n for n, _ in hits if n not in KNOWN][:12]
    if more:
        print("   목록에서 새로 나온 후보")
        for t in more:
            poke(t, lon, lat)
    print()

    # ③ 토지이용계획을 **한 번에** 주는 길.
    #
    # 층마다 따로 부르면 필지 하나에 스무 번이 넘습니다. 토지이음이
    # 보여주는 그 표를 통째로 주는 API 가 있어야 합니다. 기관마다
    # 길 이름이 달라 **맞히지 않고 두드려 봅니다.**
    print("③ 토지이용계획을 한 번에 주는 길이 있는가")
    pnu = parcel_pnu(lon, lat)
    print(f"   그 필지의 PNU: {pnu or '못 얻음'}")

    multi(lon, lat)
    print()
    print("\n   가) 브이월드 데이터 API")
    for label, data in [("LT_C_LANDINFOBASEMAP", "LT_C_LANDINFOBASEMAP"),
                        ("LT_C_UQ111", "LT_C_UQ111")]:
        url = ("https://api.vworld.kr/req/data?service=data"
               "&request=GetFeature&format=json&size=10"
               f"&data={data}&geomFilter=POINT({lon} {lat})"
               "&domain=https://toji.fyi/")
        code, text = relay(url)
        print(f"     {label:<26} http={code}  {show(text, 700)}")

    if not pnu:
        return 0
    print("\n   나) 공공데이터포털 — 토지이용계획 후보 길들")
    # 중계기가 serviceKey 를 붙여 줍니다 (api/relay.js 의 ALLOW).
    cands = [
        ("국가공간정보 토지이용계획(속성)",
         "https://apis.data.go.kr/1611000/nsdi/LandUseService/attr/getLandUseAttr"),
        ("국가공간정보 토지이용계획(다른 철자)",
         "https://apis.data.go.kr/1611000/nsdi/LandUseAttrService/attr/getLandUseAttr"),
        ("국가공간정보 토지특성",
         "https://apis.data.go.kr/1611000/nsdi/LandCharacteristicsService/attr/getLandCharacteristics"),
        ("토지이용규제 LURIS",
         "https://apis.data.go.kr/1613000/LandUseRegulationService/getLandUseRegulation"),
    ]
    for label, base in cands:
        url = (f"{base}?pnu={pnu}&format=json&numOfRows=100&pageNo=1"
               "&type=json")
        code, text = relay(url)
        print(f"     {label:<28} http={code}  {show(text, 200)}")
    print()
    portal_search()
    return 0


def parcel_pnu(lon: float, lat: float) -> str | None:
    """그 필지의 PNU. 공공데이터포털 쪽은 좌표가 아니라 PNU 로 묻는다."""
    q = ("SERVICE=WFS&REQUEST=GetFeature&VERSION=1.1.0"
         "&TYPENAME=lp_pa_cbnd_bubun&SRSNAME=EPSG:4326"
         "&OUTPUT=application/json&MAXFEATURES=100&RESULTTYPE=results"
         f"&BBOX={lon - HALF},{lat - HALF},{lon + HALF},{lat + HALF}")
    code, text = relay("https://api.vworld.kr/req/wfs?" + q)
    try:
        feats = (json.loads(text) or {}).get("features") or []
    except Exception:                                        # noqa: BLE001
        return None
    hit = next((f for f in feats if hits(f.get("geometry"), lon, lat)), None)
    return ((hit or {}).get("properties") or {}).get("pnu")


if __name__ == "__main__":
    sys.exit(main())
