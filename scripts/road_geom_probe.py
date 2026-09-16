"""선형을 어디서 얻나 — 직선을 **실제 노선 모양**으로 바꾸려면 (2026-09-16 지시).

  "기본 지도를 보시면 고속화 도로(주황 점선), 고속도로(빨간 점선)가
   표시되어 있습니다. 저희가 넣은 것은 직선이라 맞지 않아요..
   정합성을 맞출 수 있는 방법과 기본 지도처럼 표시할 수 있는 방법을"

**결정적 단서는 배경 지도 자신이다.** 우리 배경은 tile.openstreetmap.org
이므로, 화면에 보이는 그 점선은 OSM 이 가진 선형이다. 즉 '지도에는 있는데
우리에게 없는' 것이 아니라 **우리가 아직 안 가져온 것**이다.

두 자리를 잰다. 안성 화면(입장면·서운면 언저리)을 그대로 쓴다.

  1. OSM Overpass — highway=motorway / construction / proposed
     construction=motorway 가 있으면 '공사중'이 선형째로 온다
  2. 브이월드 도로중심선 lt_l_n3a0020000 — name 에 노선 이름이 온다
     (층 조사에서 확인함). 다만 **아직 없는 길**은 수치지도에 없을 것이다

재는 것은 셋이다.
  · 몇 개가 오나           — 0이면 그 길은 닫혔다
  · 꼭짓점이 몇 개인가     — 2면 직선이라 지금과 다를 게 없다
  · 이름과 상태 칸이 뭔가  — 공사중·계획을 가려낼 수 있는가

  python scripts/road_geom_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from collections import Counter

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
OVERPASS = "https://overpass-api.de/api/interpreter"
VW_WFS = "https://api.vworld.kr/req/wfs"

# 사장님이 보내 준 화면 그대로 — 안성 입장면·서운면. 세종포천고속도로
# 공사 구간이 이 안을 지난다.
BOX = (36.90, 127.15, 37.10, 127.45)          # S, W, N, E


def relay(url: str, timeout: int = 90):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": url})


def osm() -> None:
    print("=" * 72)
    print("1. OSM Overpass — 배경 지도에 보이는 그 선을 그대로 받아 본다")
    print("=" * 72)
    s, w, n, e = BOX
    q = f"""[out:json][timeout:90];
(
  way["highway"="motorway"]({s},{w},{n},{e});
  way["highway"="motorway_link"]({s},{w},{n},{e});
  way["highway"="construction"]({s},{w},{n},{e});
  way["highway"="proposed"]({s},{w},{n},{e});
  way["highway"="trunk"]({s},{w},{n},{e});
);
out geom;"""
    try:
        r = requests.post(OVERPASS, data={"data": q}, timeout=120)
    except requests.RequestException as exc:
        print(f"  ✗ 못 불렀다: {type(exc).__name__} {exc}")
        return
    if r.status_code != 200:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:200]}")
        return
    els = r.json().get("elements", [])
    print(f"  길 {len(els)}개")
    kinds = Counter(e_["tags"].get("highway") for e_ in els)
    for k, v in kinds.most_common():
        print(f"    highway={k:14s} {v}개")

    # 공사중·계획을 가려낼 수 있는가 — construction/proposed 의 속칭 칸
    print("\n  공사중·계획으로 읽히는 길:")
    n_show = 0
    for e_ in els:
        t = e_.get("tags", {})
        hw = t.get("highway")
        if hw not in ("construction", "proposed"):
            continue
        sub = t.get("construction") or t.get("proposed") or "?"
        geom = e_.get("geometry") or []
        print(f"    {t.get('name', '(이름없음)')[:30]:32s} {hw}={sub}"
              f" · 꼭짓점 {len(geom)}개")
        n_show += 1
        if n_show >= 12:
            break
    if not n_show:
        print("    (없음)")

    # **꼭짓점 수가 핵심이다.** 2개면 직선이라 지금과 다를 게 없다.
    pts = [len(e_.get("geometry") or []) for e_ in els if e_.get("geometry")]
    if pts:
        pts.sort()
        print(f"\n  꼭짓점: 가운데값 {pts[len(pts) // 2]}개 ·"
              f" 가장 많은 것 {pts[-1]}개 · 2개짜리 {sum(1 for p in pts if p <= 2)}개")
        big = max(els, key=lambda x: len(x.get("geometry") or []))
        g = big.get("geometry") or []
        print(f"  가장 긴 길 '{big['tags'].get('name', '?')}' 의 앞 3점: "
              f"{[(round(p['lat'], 5), round(p['lon'], 5)) for p in g[:3]]}")
    print("\n  ※ OSM 은 ODbL 이다 — 쓰려면 출처 표기와 조건을 확인해야 한다.")


def vworld() -> None:
    print("\n" + "=" * 72)
    print("2. 브이월드 도로중심선 lt_l_n3a0020000 — 관이 가진 선형")
    print("=" * 72)
    s, w, n, e = BOX
    q = {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": "lt_l_n3a0020000", "OUTPUT": "application/json",
        "SRSNAME": "EPSG:4326", "MAXFEATURES": "200",
        "BBOX": f"{s},{w},{n},{e}",
        "key": "__via_relay__", "DOMAIN": "https://toji.fyi",
    }
    try:
        r = relay(f"{VW_WFS}?{urllib.parse.urlencode(q)}")
        body = r.json()
    except Exception as exc:                               # noqa: BLE001
        print(f"  ✗ 못 불렀다: {type(exc).__name__} {exc}")
        return
    feats = body.get("features") or []
    print(f"  길 {len(feats)}개")
    if not feats:
        print(f"  응답 머리: {json.dumps(body, ensure_ascii=False)[:300]}")
        return
    print(f"  칸 이름: {sorted((feats[0].get('properties') or {}))}")
    named = [f for f in feats
             if "고속" in str((f.get("properties") or {}).get("name") or "")]
    print(f"\n  이름에 '고속' 이 든 길 {len(named)}개:")
    for f in named[:12]:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        co = g.get("coordinates") or []
        if g.get("type") == "MultiLineString":
            co = co[0] if co else []
        print(f"    {str(p.get('name'))[:34]:36s} 꼭짓점 {len(co)}개"
              f" · 종류 {p.get('rdcode') or p.get('dvyn') or ''}")


def main() -> None:
    osm()
    vworld()
    print("\n" + "=" * 72)
    print("무엇을 보고 판단하나")
    print("=" * 72)
    print("  · 꼭짓점이 2개면 직선 — 지금과 다를 게 없다")
    print("  · construction=motorway 가 오면 **공사중을 선형째** 얻는다")
    print("  · 도로중심선에 '아직 없는 길' 이 있는지가 계획·공사의 갈림길")


if __name__ == "__main__":
    main()
