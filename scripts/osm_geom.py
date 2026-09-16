"""OSM 고속도로 선형 — 두 끝을 잇는 직선을 **실제 노선**으로 바꾼다.

2026-09-16 지시: "저희가 넣은 것은 직선이라 맞지 않아요.. 정합성을
맞출 수 있는 방법과 기본 지도처럼 표시할 수 있는 방법을." → 실측 뒤
"1번으로 우선 표시하고 3번을 계속 파고 들어갑니다."

## 왜 OSM 인가

배경 지도가 tile.openstreetmap.org 다. 화면에 보이던 그 점선이 바로
OSM 의 `construction=motorway` 였다 (탐침 run 17: 세종포천고속도로 34건).
지도에는 있는데 우리에게 없던 것이 아니라, 우리가 안 가져온 것이다.

## 이름이 있어야 쓴다

선형만 있고 이름이 없으면 "이 선이 우리 어느 구간이냐" 를 못 잇는다.
OSM 은 둘 다 준다 — `name`('경부고속도로')과 `ref`(노선번호 1). 도로공사
API 의 `routeName`('경부선')과 여기서 만난다.

## 조각을 어떻게 잇나

OSM 은 교차로마다 길을 쪼개 둔다(한 조각 꼭짓점 가운데값 3개). 그래서
**노선마다 그래프를 세운다** — 마디는 조각의 양 끝, 변은 조각 자체다.
그 위에서 시점에 가장 가까운 자리부터 종점까지 최단경로를 찾고, 지나온
조각의 좌표를 이어 붙인다.

상·하행이 따로 있는 구간은 한쪽을 따라간다. 선 하나를 그리는 것이
목적이므로 그것으로 충분하다.

## 검산이 조여진다

지금까지는 직선거리÷연장이라 0.4~1.4 라는 헐거운 그물을 쓸 수밖에
없었다(길은 굽으니까). **경로 길이**로 재면 1.0 근처로 조여진다.
그래서 여기서는 0.75~1.30 을 쓴다 — 이 그물을 통과 못 하면 엉뚱한
길을 따라간 것이므로 직선으로 되돌린다.

ODbL: OSM 자료다. 화면에 출처를 적는다.
"""
from __future__ import annotations

import heapq
import math
import re
from collections import defaultdict

OVERPASS = "https://overpass-api.de/api/interpreter"
# 남한 전체. 제주까지 넣는다.
KR_BBOX = (33.0, 124.5, 38.7, 131.2)
UA = {"User-Agent": "toji.fyi highway-geometry builder (github/traffic)",
      "Accept": "application/json"}

# 경로 길이 ÷ 고시 연장. 직선일 때(0.4~1.4)보다 훨씬 좁게 잡는다.
PATH_LO, PATH_HI = 0.75, 1.30


def km(a, b) -> float:
    la1, lo1 = a
    la2, lo2 = b
    dla, dlo = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = (math.sin(dla / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(dlo / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def route_key(name: str) -> str:
    """'경부선' 도 '경부고속도로' 도 '경부' 로 모은다."""
    s = re.sub(r"\s+", "", str(name or ""))
    s = re.sub(r"(고속국도|고속도로|고속화도로|지선|선)$", "", s)
    return s


def fetch(session, timeout: int = 900) -> list[dict]:
    """남한의 고속도로 조각을 통째로 받는다 (준공 + 공사중)."""
    # **상자로 자르면 일본이 들어온다.** 33~38.7N·124.5~131.2E 는 규슈와
    # 혼슈 서쪽 끝을 품어서, 첫 실행의 '노선 130개' 에 中国自動車道·
    # 九州自動車道 가 섞였다. 나라 경계로 자른다 — 느려도 이것이 맞다.
    q = f"""[out:json][timeout:{timeout}];
area["ISO3166-1"="KR"][admin_level=2]->.kr;
(
  way["highway"="motorway"](area.kr);
  way["highway"="construction"]["construction"="motorway"](area.kr);
);
out geom;"""
    r = session.post(OVERPASS, data={"data": q}, headers=UA, timeout=timeout + 60)
    r.raise_for_status()
    out = []
    for el in r.json().get("elements", []):
        g = el.get("geometry") or []
        if len(g) < 2:
            continue
        t = el.get("tags", {})
        nm = t.get("name") or t.get("ref") or ""
        if not nm:
            continue
        out.append({
            "key": route_key(nm),
            "name": t.get("name") or "",
            "ref": t.get("ref") or "",
            "building": t.get("highway") == "construction",
            "pts": [(p["lat"], p["lon"]) for p in g],
        })
    return out


def _node(pt):
    """좌표를 마디 이름으로. OSM 은 조각끼리 꼭짓점을 공유하므로 반올림
    하면 그대로 붙는다. 6자리 ≈ 0.1m — 붙을 것만 붙는다."""
    return (round(pt[0], 6), round(pt[1], 6))


class Route:
    """노선 하나. 조각을 그래프로 세워 두고 두 점 사이를 잘라 준다."""

    def __init__(self, ways: list[dict]):
        self.ways = ways
        self.edges = defaultdict(list)          # 마디 → [(이웃, 길이, 좌표들)]
        for w in ways:
            pts = w["pts"]
            a, b = _node(pts[0]), _node(pts[-1])
            if a == b:
                continue
            d = sum(km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
            self.edges[a].append((b, d, pts))
            self.edges[b].append((a, d, pts[::-1]))

    def nearest_node(self, pt):
        """그 자리에 가장 가까운 마디. 없으면 (None, 큰 수)."""
        best, bd = None, 1e9
        for nd in self.edges:
            d = km(pt, nd)
            if d < bd:
                best, bd = nd, d
        return best, bd

    def path(self, a, b):
        """a→b 최단경로의 좌표들. 못 찾으면 None."""
        sa, da = self.nearest_node(a)
        sb, db = self.nearest_node(b)
        if sa is None or sb is None or sa == sb:
            return None
        # 시점·종점이 이 노선에서 너무 멀면 다른 노선을 잡은 것이다.
        if da > 8 or db > 8:
            return None
        dist = {sa: 0.0}
        prev = {}
        pq = [(0.0, sa)]
        seen = set()
        while pq:
            d, u = heapq.heappop(pq)
            if u in seen:
                continue
            seen.add(u)
            if u == sb:
                break
            for v, w, pts in self.edges[u]:
                nd = d + w
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = (u, pts)
                    heapq.heappush(pq, (nd, v))
        if sb not in prev and sb != sa:
            return None
        # 거꾸로 따라가며 좌표를 잇는다.
        chain, cur = [], sb
        while cur != sa:
            step = prev.get(cur)
            if step is None:
                return None
            u, pts = step
            chain.append(pts)
            cur = u
        chain.reverse()
        out = []
        for pts in chain:
            out.extend(pts if not out else pts[1:])
        return out or None


def build_routes(ways: list[dict]) -> dict:
    by = defaultdict(list)
    for w in ways:
        by[w["key"]].append(w)
    return {k: Route(v) for k, v in by.items() if len(v) >= 2}


def simplify(pts, tol_m: float = 25.0):
    """Douglas-Peucker. 꼭짓점을 그대로 실으면 파일이 통째로 커진다 —
    25m 면 화면에서 구분이 안 되는 차이다."""
    if len(pts) < 3:
        return pts
    tol = tol_m / 111_000.0

    def far(lo, hi):
        """lo~hi 선분에서 가장 멀리 벗어난 점과 그 거리."""
        ax, ay = pts[lo]
        bx, by_ = pts[hi]
        dx, dy = bx - ax, by_ - ay
        den = dx * dx + dy * dy
        worst, wi = -1.0, -1
        for i in range(lo + 1, hi):
            px, py = pts[i]
            if den <= 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / den))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > worst:
                worst, wi = d, i
        return worst, wi

    # **되돌이(재귀)로 짜면 긴 경로에서 스택이 넘친다.** 노선 하나가
    # 수천 점이 되기도 하므로 쌓아 두고 푼다.
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        worst, wi = far(lo, hi)
        if wi > 0 and worst > tol:
            keep.add(wi)
            stack.append((lo, wi))
            stack.append((wi, hi))
    return [pts[i] for i in sorted(keep)]


def snap(routes: dict, name: str, a, b, ext_km: float):
    """(좌표들, 비) 또는 (None, 까닭).

    **틀린 선형은 직선보다 나쁘다.** 그물을 통과 못 하면 좌표를 안 내고,
    부르는 쪽이 직선으로 되돌린다.
    """
    key = route_key(name)
    r = routes.get(key)
    if r is None:
        return None, "노선 못 찾음"
    pts = r.path(tuple(a), tuple(b))
    if not pts:
        return None, "경로 없음"
    if not ext_km:
        return None, "연장 없음"
    length = sum(km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    ratio = length / ext_km
    if not (PATH_LO <= ratio <= PATH_HI):
        return None, f"경로비 {ratio:.2f}"
    return [[round(p[0], 5), round(p[1], 5)] for p in simplify(pts)], ratio
