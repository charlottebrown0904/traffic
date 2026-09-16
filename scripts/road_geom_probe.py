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
from collections import Counter, defaultdict

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
OVERPASS = "https://overpass-api.de/api/interpreter"
VW_WFS = "https://api.vworld.kr/req/wfs"

# 받은 화면 그대로 — 안성 입장면·서운면. 세종포천고속도로
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
    q = f"""[out:json][timeout:120];
(
  way["highway"~"^(motorway|motorway_link|construction|proposed)$"]({s},{w},{n},{e});
);
out geom;"""
    head = {"User-Agent": "toji.fyi road-geometry probe (contact via github)",
            "Accept": "application/json"}
    try:
        r = requests.post(OVERPASS, data={"data": q}, headers=head, timeout=180)
    except requests.RequestException as exc:
        print(f"  ✗ 못 불렀다: {type(exc).__name__} {exc}")
        return
    if r.status_code != 200:
        print(f"  ✗ HTTP {r.status_code}: {r.text[:200]}")
        return
    els = r.json().get("elements", [])
    print(f"  길 {len(els)}개")
    for k, v in Counter(x["tags"].get("highway") for x in els).most_common():
        print(f"    highway={k:16s} {v}개")

    # **앞선 탐침의 구멍.** construction 74개 중 12개만 찍어 보고 'primary
    # 뿐' 이라고 읽을 뻔했다. 하위 종류를 통째로 센다 — 고속도로 공사가
    # 있는지 없는지는 이 표가 정한다.
    for tag in ("construction", "proposed"):
        c = Counter(x["tags"].get(tag) for x in els if x["tags"].get(tag))
        print(f"\n  {tag}=* 하위 종류: {dict(c) or '없음'}")
        mot = [x for x in els
               if x["tags"].get(tag) in ("motorway", "motorway_link", "trunk")]
        for x in mot[:8]:
            t = x["tags"]
            print(f"    {str(t.get('name') or t.get('ref') or '(이름없음)')[:28]:30s}"
                  f" {tag}={t.get(tag)} · 꼭짓점 {len(x.get('geometry') or [])}개")

    # **우리 자료와 이으려면 이름이 맞아야 한다.** 도로공사 API 는
    # routeName('경부선') 을 준다. OSM 쪽 이름·번호가 뭘로 오는지 본다.
    mw = [x for x in els if x["tags"].get("highway") == "motorway"]
    print(f"\n  motorway 의 이름/번호 (우리 routeName 과 이을 열쇠):")
    for k in ("name", "ref"):
        c = Counter(x["tags"].get(k) for x in mw if x["tags"].get(k))
        print(f"    {k:5s} {' · '.join(f'{a!r}×{b}' for a, b in c.most_common(6))[:120]}")
    pts = sorted(len(x.get("geometry") or []) for x in mw if x.get("geometry"))
    if pts:
        print(f"    꼭짓점: 가운데값 {pts[len(pts) // 2]}개 · 가장 많은 것 {pts[-1]}개"
              f" · 2개짜리 {sum(1 for x in pts if x <= 2)}개")
    print("\n  ※ OSM 은 ODbL 이다 — 쓰려면 출처 표기와 조건을 확인해야 한다.")


def vworld() -> None:
    print("\n" + "=" * 72)
    print("2. 브이월드 도로중심선 lt_l_n3a0020000 — 관이 가진 선형")
    print("=" * 72)
    # **앞선 탐침은 1000개 상한에 잘렸다.** 넓은 상자에서 이름 없는 동네
    # 길이 먼저 1000개를 채우면 고속도로가 못 들어온다 — 그걸 '자료에
    # 없다' 로 읽으면 틀린다. 경부고속도로 바로 위 좁은 상자로 묻는다.
    s, w, n, e = 36.99, 127.25, 37.02, 127.29
    print(f"  상자: 경부고속도로 위 {s},{w} ~ {n},{e}")
    q = {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": "lt_l_n3a0020000", "OUTPUT": "application/json",
        "SRSNAME": "EPSG:4326", "MAXFEATURES": "1000",
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

    def coords(f):
        g = f.get("geometry") or {}
        co = g.get("coordinates") or []
        if g.get("type") == "MultiLineString":
            co = co[0] if co else []
        return co

    # **어느 칸에 '고속' 이 들어 있나.** 앞선 탐침은 name 만 보고 '0개' 라고
    # 적었는데, 그건 자료가 아니라 내가 고른 칸이 틀린 것이었다.
    hit = defaultdict(int)
    for f in feats:
        for k, v in (f.get("properties") or {}).items():
            if "고속" in str(v):
                hit[k] += 1
    print(f"\n  '고속' 이 들어 있는 칸: {dict(hit) or '없음'}")

    # 칸마다 실제로 어떤 값이 오는지 — 추측 대신 눈으로 본다.
    for k in ("name", "rdnm", "rddv", "rdln", "rdnu", "scls", "rest"):
        vals = Counter(str((f.get("properties") or {}).get(k))
                       for f in feats)
        top = " · ".join(f"{v!r}×{n}" for v, n in vals.most_common(5))
        print(f"    {k:6s} {top[:110]}")

    pts = sorted(len(coords(f)) for f in feats if coords(f))
    if pts:
        print(f"\n  꼭짓점: 가운데값 {pts[len(pts) // 2]}개 · 가장 많은 것 {pts[-1]}개"
              f" · 2개짜리 {sum(1 for x in pts if x <= 2)}개")


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
