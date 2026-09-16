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


# 이름이 바뀐 노선. 자료는 옛 이름을, OSM 은 새 이름을 쓴다.
ALIAS = {"88올림픽": "광주대구"}


def route_key(name: str) -> str:
    """'경부선' 도 '경부고속도로' 도 '경부' 로 모은다.

    **가장 큰 걸림돌은 붙임표였다.** 우리 자료는 '고창-담양선' 인데
    OSM 은 '고창담양고속도로' 다. 116건이 '노선 못 찾음' 으로 떨어진
    까닭의 태반이 이 한 글자였다.
    """
    s = re.sub(r"[\s·・‧\-–—_]", "", str(name or ""))
    s = re.sub(r"의지선$", "", s)
    s = re.sub(r"(고속국도|고속도로|고속화도로|지선|선)$", "", s)
    return ALIAS.get(s, s)


def route_keys(name: str) -> list[str]:
    """한 칸에 노선이 여럿 적힌 것이 있다 ('대전-통영선,중부선').
    쉼표로 갈라 하나씩 다 시도한다."""
    out, seen = [], set()
    for part in re.split(r"[,/·]|\s및\s", str(name or "")):
        k = route_key(part)
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


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


def corridor(route, a, b):
    """**그래프가 끊겼을 때의 대안.**

    고속도로는 상·하행이 **따로 그려진** 길이라, 두 끝이 서로 다른 쪽에
    걸리면 최단경로가 아예 안 나온다(첫 실행에서 '경로 없음' 113건).
    그럴 때는 잇는 대신 **훑는다** — a→b 선분에 그림자를 드리워, 그
    그림자 안에 드는 노선의 점만 모아 순서대로 꿴다.

    한 자리에 상·하행 두 점이 다 들어오면 선이 갈지자가 되므로, 진행
    방향을 200칸으로 나눠 **칸마다 가장 가까운 점 하나만** 남긴다.
    """
    ab = km(a, b)
    if ab < 0.2:
        return None
    # 선분 위 그림자 위치 t(0~1)와 옆으로 벗어난 거리를 잰다.
    dla, dlo = b[0] - a[0], b[1] - a[1]
    den = dla * dla + dlo * dlo
    if den <= 0:
        return None
    # 굽은 길도 품도록 폭을 넉넉히 — 다만 구간이 길수록만 넓어진다.
    wide = max(2.0, min(12.0, ab * 0.35))
    bins = {}
    for w in route.ways:
        for pt in w["pts"]:
            t = ((pt[0] - a[0]) * dla + (pt[1] - a[1]) * dlo) / den
            if not (0.0 <= t <= 1.0):
                continue
            foot = (a[0] + t * dla, a[1] + t * dlo)
            d = km(pt, foot)
            if d > wide:
                continue
            k = int(t * 200)
            if k not in bins or d < bins[k][0]:
                bins[k] = (d, pt)
    if len(bins) < 3:
        return None
    return [bins[k][1] for k in sorted(bins)]


def snap(routes: dict, name: str, a, b, ext_km: float):
    """(좌표들, 비) 또는 (None, 까닭).

    **틀린 선형은 직선보다 나쁘다.** 그물을 통과 못 하면 좌표를 안 내고,
    부르는 쪽이 직선으로 되돌린다.
    """
    cands = [routes[k] for k in route_keys(name) if k in routes]
    if not cands:
        # **OSM 에는 이름 없이 번호만 붙은 조각이 있다** (열쇠가 '30',
        # '45' 처럼 숫자로 잡힌다). 당진영덕 20건이 여기서 떨어졌다.
        #
        # 어느 번호가 어느 노선인지 **내가 적어 넣지 않는다** — 오늘
        # 추측으로 네 번 틀렸다. 숫자 열쇠를 전부 후보로 던져 놓고,
        # 두 끝과의 거리와 경로비 그물이 고르게 둔다. 틀린 것은 그물이
        # 걸러 내고, 걸리면 직선으로 되돌아간다.
        cands = [r for k, r in routes.items() if k.isdigit()]
    if not cands:
        return None, "노선 못 찾음"
    # 여럿이면 두 끝에 더 가까운 쪽을 고른다.
    r = min(cands, key=lambda x: (x.nearest_node(tuple(a))[1]
                                  + x.nearest_node(tuple(b))[1]))
    pts = r.path(tuple(a), tuple(b))
    if not pts:
        # 이어 붙이기가 안 되면 훑어서 모은다 (상·하행이 갈린 자리).
        pts = corridor(r, tuple(a), tuple(b))
    if not pts:
        return None, "경로 없음"
    if not ext_km:
        return None, "연장 없음"
    length = sum(km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    ratio = length / ext_km
    if not (PATH_LO <= ratio <= PATH_HI):
        return None, f"경로비 {ratio:.2f}"
    return [[round(p[0], 5), round(p[1], 5)] for p in simplify(pts)], ratio
