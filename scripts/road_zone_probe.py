"""도로구역을 어디서 받나 — 내가 닫았다고 한 문을 다시 연다 (2026-09-16).

지시(캡처 5장, 천안 북면 양곡리 361-7):

  1. 옆 필지까지 회색 처리된다
  2. 고속도로에 포함되는 필지는 토지이음에 **획지가 분리되어 도로구역**
     으로 들어가 있다
  3. 즉 **도로구역**(개별법령 → 국토계획법외의 법령에 따른 지역지구)과
     **도시계획시설(KRAS) 대로2류**에 해당하는 것으로 골라야 한다.
     터널 구간의 임야는 도로에 포함되지 않는다.

맞는 말씀이다. 지금 우리가 하는 것은 '선에서 30m 안' 이라는 **근사**고,
도로구역은 **관이 실제로 정한 경계**다. 근사를 아무리 다듬어도 정답이
되지 않는다 — 옆 필지가 딸려 오는 것도, 터널 위 임야가 딸려 오는 것도
근사의 성질이지 값을 잘못 고른 탓이 아니다.

앞서 나는 "브이월드 WFS 177개 층에 도로구역이 없다" 고 적었다. 그것은
**이름에 '도로·구역' 이 든 층 31개를 훑은 결과**였다. 토지이음이 그것을
보여 주고 있으므로 자료 자체는 있다 — 내가 안 찾은 것이거나 다른 문에
있는 것이다. 그래서 셋을 다시 잰다.

  Q1  브이월드 층 **177개를 통째로** 찍는다. 거르지 않고 눈으로 본다.
  Q2  그 자리(천안 양곡리)의 도시계획시설을 **모든 칸**으로 받는다.
      안성에는 없던 대로2류가 여기 있나.
  Q3  **PNU 로 지역지구를 묻는 길**이 있나. 이것이 열리면 도형이 없어도
      된다 — 후보 필지마다 '도로구역인가' 를 물으면 그만이다.

  python scripts/road_zone_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WFS = "https://api.vworld.kr/req/wfs"
DOMAIN = os.environ.get("VWORLD_DOMAIN", "https://toji.fyi")

# 받은 캡처 그대로. 세종포천고속도로가 지나고 토지이음이 도로구역과
# 대로2류를 함께 보여 주는 자리다.
LAT, LON = 36.848137, 127.275422
PNU = "4413133030103610007"
BOX = (36.835, 127.262, 36.862, 127.290)      # s, w, n, e


def relay(url: str, params: dict | None = None, timeout: int = 90):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    target = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def bar(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ── Q1 ────────────────────────────────────────────────────────────────
def all_layers() -> None:
    bar("Q1 · 브이월드가 연 층을 **통째로** 찍는다 (거르지 않는다)")
    print("  앞서 '도로구역이 없다' 고 적은 것은 이름으로 거른 31개만 본")
    print("  결과였다. 토지이음이 보여 주고 있으니 자료는 있다.")
    print()
    r = relay(WFS, {"SERVICE": "WFS", "REQUEST": "GetCapabilities",
                    "VERSION": "2.0.0", "DOMAIN": DOMAIN,
                    "key": "__via_relay__"})
    try:
        root = ET.fromstring(r.text)
    except Exception as err:                           # noqa: BLE001
        print(f"  목록을 못 읽었다 — {type(err).__name__}: {str(err)[:120]}")
        return
    rows = []
    for ft in root.iter():
        if not ft.tag.endswith("FeatureType"):
            continue
        name = title = ""
        for kid in ft:
            if kid.tag.endswith("}Name") or kid.tag == "Name":
                name = (kid.text or "").strip()
            if kid.tag.endswith("}Title") or kid.tag == "Title":
                title = (kid.text or "").strip()
        if name:
            rows.append((name, title))
    print(f"  층 {len(rows)}개")
    for i in range(0, len(rows), 3):
        print("   " + " | ".join(
            f"{n:<22}{t[:16]}" for n, t in rows[i:i + 3]))


# ── Q2 ────────────────────────────────────────────────────────────────
def kras_here() -> None:
    bar("Q2 · 그 자리의 도시계획시설을 **모든 칸**으로 받는다")
    print("  안성 서운면에는 '대로' 26개가 전부 주간선·보조간선·집산도로")
    print("  였다. 천안 양곡리에는 대로2류가 있다고 캡처가 말한다.")
    print()
    s, w, n, e = BOX
    r = relay(WFS, {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": "lt_c_upisuq151", "OUTPUT": "application/json",
        "SRSNAME": "EPSG:4326", "MAXFEATURES": "1000",
        "BBOX": f"{w},{s},{e},{n}",
        "DOMAIN": DOMAIN, "key": "__via_relay__",
    })
    try:
        feats = r.json().get("features") or []
    except Exception:                                  # noqa: BLE001
        print(f"  JSON 이 아니다 — {r.text[:160]}")
        return
    print(f"  도형 {len(feats)}개")
    if not feats:
        return
    vals = defaultdict(Counter)
    for f in feats:
        for k, v in (f.get("properties") or {}).items():
            vals[k][str(v)] += 1
    for k in sorted(vals):
        top = " · ".join(f"'{a}'×{b}" for a, b in vals[k].most_common(6))
        print(f"    {k:<11}({len(vals[k])}가지) {top[:96]}")
    print()
    big = [f for f in feats
           if "대로" in str((f.get("properties") or {}).get("atr_nam") or "")]
    print(f"  '대로' 가 든 시설 {len(big)}개:")
    for f in big[:12]:
        p = f.get("properties") or {}
        ring = ((f.get("geometry") or {}).get("coordinates") or [[[]]])
        n_pt = len(ring[0][0]) if ring and ring[0] and ring[0][0] else 0
        print(f"    {str(p.get('atr_nam')):<9}{str(p.get('exc_nam')):<8}"
              f"{str(p.get('pmi_nam')):<22}꼭짓점 {n_pt}개")


# ── Q3 ────────────────────────────────────────────────────────────────
def zone_by_pnu() -> None:
    bar("Q3 · **PNU 로 지역지구를 묻는 길**이 있나 (이게 열리면 끝난다)")
    print("  도형이 없어도 된다. 후보 필지마다 '도로구역인가' 만 물으면")
    print(f"  그만이다. 두드릴 지번: 양곡리 361-7 · PNU {PNU}")
    print()
    # 문서에 있는 길을 **추측하지 않고 여럿 두드린다.** 어느 것이 사는지는
    # 응답이 말해 준다. 열쇠는 중계기가 끼운다.
    tries = [
        ("NED 토지이용계획 속성",
         "https://api.vworld.kr/ned/data/getLandUseAttr",
         {"pnu": PNU, "format": "json", "numOfRows": "100", "pageNo": "1",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("NED 토지이용계획 속성(단수형)",
         "https://api.vworld.kr/ned/data/landUseAttr",
         {"pnu": PNU, "format": "json", "numOfRows": "100", "pageNo": "1",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("NED 용도지역지구",
         "https://api.vworld.kr/ned/data/getPossessionAttr",
         {"pnu": PNU, "format": "json", "numOfRows": "10", "pageNo": "1",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("data.go.kr 토지이용계획",
         "http://apis.data.go.kr/1611000/nsdi/LandUseService/attr/getLandUseAttr",
         {"pnu": PNU, "format": "json", "numOfRows": "100", "pageNo": "1"}),
        ("data.go.kr 토지이용계획(WFS)",
         "http://apis.data.go.kr/1611000/nsdi/LandUseService/wfs/getLandUseWFS",
         {"typename": "F251", "bbox": f"{BOX[1]},{BOX[0]},{BOX[3]},{BOX[2]}",
          "srsname": "EPSG:4326", "maxFeatures": "10"}),
    ]
    for label, url, params in tries:
        try:
            r = relay(url, params, timeout=60)
            body = r.text or ""
        except Exception as err:                       # noqa: BLE001
            print(f"  {label:<26} 못 불렀다 — {type(err).__name__}")
            continue
        head = " ".join(body[:200].split())
        ok = ("도로구역" in body) or ("prposAreaDstrcCodeNm" in body)
        print(f"  {label:<26} {r.status_code} · {len(body):>6}B"
              f"{'  ← **도로구역이 들어 있다**' if ok else ''}")
        print(f"  {'':<26} {head[:150]}")
        if ok:
            # 무엇이 오는지 이름만 뽑아 본다.
            try:
                obj = json.loads(body)
                names = set()

                def walk(o):
                    if isinstance(o, dict):
                        for k, v in o.items():
                            if "Nm" in k and isinstance(v, str):
                                names.add(v)
                            walk(v)
                    elif isinstance(o, list):
                        for v in o:
                            walk(v)

                walk(obj)
                print(f"  {'':<26} 지역지구: {' · '.join(sorted(names))[:200]}")
            except Exception:                          # noqa: BLE001
                pass
        print()


def zone_shapes() -> None:
    """**면으로도 받을 수 있나.** 이것이 값을 100배 가른다.

    속성(PNU 하나에 한 번)만 되면 한 칸에 필지 50개를 물어야 한다.
    면(상자 하나에 한 번)이 되면 칸마다 한 번이면 끝이다.

    앞 실행에서 data.go.kr 두 줄이 400 으로 막혔는데, 까닭은 자료가
    아니라 **내가 http:// 로 적어서**였다(중계기: "https 만 허용합니다").
    같은 길을 https 로 다시 두드린다.
    """
    bar("Q4 · 도로구역을 **면으로** 받을 수 있나 (값이 100배 갈린다)")
    s, w, n, e = BOX
    tries = [
        ("NED WFS (브이월드)",
         "https://api.vworld.kr/ned/wfs/getLandUseWFS",
         {"typename": "F251", "bbox": f"{w},{s},{e},{n}",
          "srsname": "EPSG:4326", "maxFeatures": "20",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("NED 데이터 (도형)",
         "https://api.vworld.kr/ned/data/getLandUseArea",
         {"pnu": PNU, "format": "json", "numOfRows": "50", "pageNo": "1",
          "key": "__via_relay__", "domain": DOMAIN}),
        ("NSDI WFS (https 로 다시)",
         "https://apis.data.go.kr/1611000/nsdi/LandUseService/wfs/getLandUseWFS",
         {"typename": "F251", "bbox": f"{w},{s},{e},{n}",
          "srsname": "EPSG:4326", "maxFeatures": "20"}),
        ("NSDI 속성 (https 로 다시)",
         "https://apis.data.go.kr/1611000/nsdi/LandUseService/attr/getLandUseAttr",
         {"pnu": PNU, "format": "json", "numOfRows": "50", "pageNo": "1"}),
        # 목록에서 눈에 띈 층 하나. 이름이 '토지이용계획도' 다.
        ("lt_c_lhblpn 토지이용계획도",
         WFS,
         {"SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
          "TYPENAME": "lt_c_lhblpn", "OUTPUT": "application/json",
          "SRSNAME": "EPSG:4326", "MAXFEATURES": "20",
          "BBOX": f"{w},{s},{e},{n}", "DOMAIN": DOMAIN,
          "key": "__via_relay__"}),
    ]
    for label, url, params in tries:
        try:
            r = relay(url, params, timeout=60)
            body = r.text or ""
        except Exception as err:                       # noqa: BLE001
            print(f"  {label:<26} 못 불렀다 — {type(err).__name__}")
            continue
        hit = "도로구역" in body
        geom = ("coordinates" in body) or ("gml:" in body) or ("<gml" in body)
        print(f"  {label:<26} {r.status_code} · {len(body):>7}B"
              f"{'  도로구역 있음' if hit else ''}"
              f"{'  · **도형이 온다**' if geom else ''}")
        print(f"  {'':<26} {' '.join(body[:190].split())[:170]}")
        print()


def main() -> None:
    all_layers()
    kras_here()
    zone_by_pnu()
    zone_shapes()
    bar("무엇을 보고 판단하나")
    print("  · 도로구역 층이 목록에 있으면 → 그 면으로 필지를 고른다 (최선)")
    print("  · PNU 로 지역지구를 물을 수 있으면 → 도형 없이도 정확히 고른다")
    print("  · 대로2류가 그 자리에 있으면 → 이미 가진 층으로도 절반은 된다")
    print("  · 셋 다 막히면 → 띠를 좁히는 것 말고는 길이 없다고 말한다")


if __name__ == "__main__":
    main()
