"""고속도로를 **필지로** 그릴 수 있나 — 재고 나서 만든다 (2026-09-16 지시).

  "계획은 살려 놓고 실제로 표시는 계획 도로처럼 **필지 기준으로 선택**될
   수 있도록 방법을 전환바랍니다."

두 문은 닫힌 것을 확인했다.

  · 도시계획시설(lt_c_upisuq151)에 '고속' 을 가려낼 칸이 **없다**
    (roadkras 탐침, 안성 589개의 모든 칸을 세어 확인). 토지이음에서 보신
    대로2류는 시내 간선도로다 — 주간선·보조간선·집산도로뿐이었다.
  · 브이월드 WFS 177개 층에 **도로구역도가 없다** (vworld-layers run 15,
    '도로·구역·고속·국도·노선' 으로 31개가 걸렸지만 도로형은 도시계획(도로)
    ·도로명주소도로·도로중심선 셋뿐).

남은 길은 하나다. **선은 우리가 이미 갖고 있다** — 관 자료 고속국도 링크
31,399개와 OSM 공사중 구간. 필지도 받을 수 있다 — 연속지적도. 그러면
선 둘레의 필지를 골라내면 그것이 곧 도로가 깔린 땅이고, 면이라 필지를
따라가고 누를 수 있다.

**만들기 전에 재야 할 것은 셋이다.**

  ① 고속도로 밑 필지가 실제로 지적에 잡히나 (한 칸에 몇 개나)
  ② 지목으로 갈리나 — 도로 밑은 지목이 '도로' 인가, 아니면 전·답인가
     (미보상·미분할 구간은 아직 원래 지목이다. 그러면 지목으로 못 거른다)
  ③ 거리 몇 m 로 잘라야 도로만 잡히고 옆 필지가 안 딸려 오나

셋 다 재고 나서 붙인다. 추측으로 고르면 오늘처럼 다섯 번 틀린다.

  python scripts/road_parcel_probe.py
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import urllib.parse
from collections import Counter

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "public" / "app" / "data"
RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
WFS = "https://api.vworld.kr/req/wfs"
DOMAIN = os.environ.get("VWORLD_DOMAIN", "https://toji.fyi")
CAD = "lp_pa_cbnd_bubun"
Z = 17
# 재 볼 거리들. 고속도로 본선은 왕복 4차로라도 용지폭이 30m 안팎이다.
BANDS = (10, 20, 30, 50)


def relay(url: str, params: dict, timeout: int = 90):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    target = f"{url}?{urllib.parse.urlencode(params)}"
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": target})


def load_road():
    local = WEB / "road.json"
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT / "src"))
    from redt import web_store as WS                    # noqa: PLC0415
    url = f"{WS.public_base()}/road.json"
    print(f"  road.json 이 없어 버킷에서 받는다 — {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.json()


def deg_bbox(z: int, x: int, y: int):
    n = 2 ** z

    def lat(ty: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2.0 * ty / n))))

    return (x / n * 360.0 - 180.0, lat(y + 1),
            (x + 1) / n * 360.0 - 180.0, lat(y))


def tile_of(lon: float, lat: float, z: int):
    n = 2 ** z
    r = math.radians(lat)
    return (int((lon + 180.0) / 360.0 * n),
            int((1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n))


def metres(a, b) -> float:
    """가까운 두 점 사이 거리. 한반도 위도에서 평면으로 봐도 된다."""
    (la1, lo1), (la2, lo2) = a, b
    k = math.cos(math.radians((la1 + la2) / 2))
    return math.hypot((la2 - la1) * 111_320.0, (lo2 - lo1) * 111_320.0 * k)


def seg_dist(p, a, b) -> float:
    """점에서 선분까지. 선 둘레를 재려면 꼭짓점 거리로는 모자라다."""
    k = math.cos(math.radians(p[0]))
    px, py = p[1] * k, p[0]
    ax, ay = a[1] * k, a[0]
    bx, by = b[1] * k, b[0]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return metres(p, a)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot((px - (ax + t * dx)) * 111_320.0,
                      (py - (ay + t * dy)) * 111_320.0)


def path_dist(p, path) -> float:
    return min(seg_dist(p, path[i], path[i + 1]) for i in range(len(path) - 1))


def fetch(z: int, x: int, y: int):
    """**keep 을 안 건다.** 어떤 칸이 오는지 눈으로 보고 고른다."""
    w, s, e, n = deg_bbox(z, x, y)
    r = relay(WFS, {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": CAD, "BBOX": f"{w},{s},{e},{n}",
        "SRSNAME": "EPSG:4326", "OUTPUT": "application/json",
        "MAXFEATURES": "600", "RESULTTYPE": "results",
        "key": "__via_relay__", "DOMAIN": DOMAIN,
    })
    try:
        return r.json().get("features") or []
    except Exception:                                  # noqa: BLE001
        return []


def ring_of(geom):
    t = (geom or {}).get("type")
    cs = (geom or {}).get("coordinates") or []
    if t == "Polygon" and cs:
        return cs[0]
    if t == "MultiPolygon" and cs and cs[0]:
        return cs[0][0]
    return []


def main() -> None:
    bar = "=" * 72
    print(bar)
    print("고속도로를 필지로 그릴 수 있나 — 선 둘레의 필지를 세어 본다")
    print(bar)
    rows = load_road()
    with_path = [r for r in rows if isinstance(r.get("path"), list)
                 and len(r["path"]) >= 2]
    print(f"  road.json {len(rows)}줄 · 선이 붙은 것 {len(with_path)}줄")
    if not with_path:
        sys.exit("선이 붙은 구간이 없다")

    # 공사중을 먼저 본다 — 땅 주인에게 중요한 것은 '앞으로 편입되는가' 다.
    def key(r):
        return (0 if (r.get("stage") or r.get("state") or "") != "준공" else 1,
                -len(r.get("path") or []))

    picked = sorted(with_path, key=key)[:3]
    seen_keys = False
    for r in picked:
        path = [tuple(p) for p in r["path"]]
        name = r.get("name") or r.get("sect") or "(이름 없음)"
        print()
        print(f"  ── {name} · 꼭짓점 {len(path)}개 · "
              f"{r.get('stage') or r.get('state') or '?'}")
        # 선 위에서 두 자리를 고른다 — 가운데와 4분의 1 지점.
        for frac in (0.25, 0.5):
            lat, lon = path[int(len(path) * frac)]
            x, y = tile_of(lon, lat, Z)
            feats = fetch(Z, x, y)
            if not feats:
                print(f"     {lat:.5f},{lon:.5f}  필지 0개 — 못 받았다")
                continue
            if not seen_keys:
                print("     받은 칸:", ", ".join(sorted(
                    (feats[0].get("properties") or {}).keys())))
                seen_keys = True
            near = []
            for f in feats:
                ring = ring_of(f.get("geometry"))
                if not ring:
                    continue
                # 필지의 **가장 가까운 꼭짓점**으로 잰다. 중심으로 재면
                # 길쭉한 도로 필지가 멀게 나온다.
                d = min(path_dist((float(c[1]), float(c[0])), path) for c in ring)
                near.append((d, (f.get("properties") or {})))
            near.sort(key=lambda t: t[0])
            print(f"     {lat:.5f},{lon:.5f}  한 칸에 필지 {len(feats)}개")
            for band in BANDS:
                inside = [p for d, p in near if d <= band]
                tally = Counter(str(p.get("lndcgr_code_nm") or "?")
                                for p in inside)
                top = " · ".join(f"{k}×{v}" for k, v in tally.most_common(5))
                print(f"       {band:>3}m 안 {len(inside):>3}개   {top or '없음'}")
            print("       가장 가까운 다섯:")
            for d, p in near[:5]:
                print(f"         {d:6.1f}m  "
                      f"{str(p.get('lnm_lndcgr_smbol') or p.get('jibun') or '?'):<12}"
                      f"{p.get('lndcgr_code_nm') or '?'}")
    print()
    print(bar)
    print("무엇을 보고 판단하나")
    print(bar)
    print("  · 가까운 필지의 지목이 '도로' → 지목으로 거를 수 있다")
    print("  · 전·답·임야가 섞임 → 아직 편입 전이다. 거리로만 골라야 한다")
    print("  · 30m 안이 두세 개뿐 → 도로 필지가 길쭉하다는 뜻, 맞게 잡힌 것")
    print("  · 30m 안이 수십 개 → 띠가 너무 넓다. 거리를 줄여야 한다")


if __name__ == "__main__":
    main()
