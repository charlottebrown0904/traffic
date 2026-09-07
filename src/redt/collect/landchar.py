"""필지 특성(도로접·형상·지세)을 브이월드 토지특성 WFS 로 받는다.

## 왜

사장님 지시(2026-09-07): "토지의 경우 개발 가능 지, 모양, 도로 접등의
사유로 가격 변동이 많으니" · "도로를 접하는 가가 제일 중요합니다."

실측(남이천·안성 반경 3km)이 그 말을 숫자로 확인했다. 세 지역
(계획관리·생산관리·자연녹지) 공시지가 중앙값을 도로접별로 보면

    세로(차 불가) → 세로(차 가능)   남이천 +66% · 안성 +67%

농촌과 도시에서 같은 크기다. 값을 가르는 것은 도로 폭이 아니라 **차가
들어가느냐**다. 그 변수를 헤도닉이 안 쓰고 있어서 전·답·임야(토지
표본의 78%)의 잔차가 통째로 남아 교통량 계수를 덮고 있었다.

## 어떻게

**거래가 있는 칸만 훑는다.** 반경을 통째로 덮으면 10km 기준 IC 당 호출이
770회로 뛰는데, 거래는 고르게 퍼져 있지 않아 대부분의 칸이 헛돈다.
우리 거래 좌표를 칸으로 묶어 그 칸만 부른다.

**도형은 저장하지 않는다.** 받는 그 자리에서 점-다각형으로 맞추고 버린다.
전국이면 필지가 수백만 개라 도형을 남기면 DB 가 감당하지 못한다.

**칸 단위로 재개한다.** parcel_tile 에 남기므로 중간에 끊겨도 다음 실행이
이어받는다. 지오코딩에서 배운 것이다.
"""
from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from ..config import keys, settings
from .http import get_json

WFS = "https://api.vworld.kr/ned/wfs/getLandCharacteristicsWFS"
TYPENAME = "dt_d194"
DOMAIN = "sado-toji.vercel.app"

# 한 번에 받아 볼 최대 피처 수. 돌려받은 수가 이것과 같으면 **잘린 것**
# 이므로 칸을 넷으로 쪼개 다시 부른다. 안성에서 실제로 7번 걸렸다 —
# 이 장치가 없으면 조용히 절반만 받고 '여기는 필지가 적네' 로 읽는다.
PAGE = 1000
MIN_TILE_DEG = 0.0015          # 이보다 잘게는 안 쪼갠다 (약 170m)

# 화면 필드 → 우리 칸.
FIELDS = {
    "pnu": "pnu",
    "sigungu_cd": "ld_cpsg_code",
    "jimok": "lndcgr_code_nm",
    "land_use": "prpos_area_1_nm",
    "use_situation": "lad_use_sittn_nm",
    "area_m2": "lndpcl_ar",
    "road_side": "road_side_code_nm",
    "shape": "tpgrph_frm_code_nm",
    "slope": "tpgrph_hg_code_nm",
    "official_price": "pblntf_pclnd",
    "stdr_year": "stdr_year",
}


def _cfg() -> dict:
    cfg = settings().get("landchar") or {}
    return {
        "tile_deg": float(cfg.get("tile_deg", 0.01)),
        "workers": int(cfg.get("workers", 6) or 1),
        "calls_per_sec": float(cfg.get("calls_per_sec", 8) or 0),
    }


class _Pace:
    """워커가 몇 개든 합쳐서 초당 N건. geocode 의 것과 같은 취지다."""

    def __init__(self, per_sec: float):
        self._gap = 1.0 / per_sec if per_sec > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if not self._gap:
            return
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + self._gap
        if at - now > 0:
            time.sleep(at - now)


def tile_key(box: tuple) -> str:
    return ",".join(f"{v:.4f}" for v in box)


def tiles_for(points: pd.DataFrame, tile_deg: float) -> dict[str, tuple]:
    """거래 좌표를 칸으로 묶는다. **거래가 없는 칸은 만들지 않는다.**"""
    out: dict[str, tuple] = {}
    for lat, lon in zip(points["lat"], points["lon"]):
        if not (isinstance(lat, float) and isinstance(lon, float)):
            continue
        w = math.floor(lon / tile_deg) * tile_deg
        s = math.floor(lat / tile_deg) * tile_deg
        box = (w, s, w + tile_deg, s + tile_deg)
        out.setdefault(tile_key(box), box)
    return out


def _rings(geom: dict) -> list:
    """MultiPolygon·Polygon 에서 바깥 고리들."""
    if not geom:
        return []
    kind, coords = geom.get("type"), geom.get("coordinates") or []
    if kind == "Polygon":
        return [coords[0]] if coords else []
    if kind == "MultiPolygon":
        return [p[0] for p in coords if p]
    return []


def in_ring(lat: float, lon: float, ring: list) -> bool:
    """점이 다각형 안에 드는가 (광선 교차). shapely 없이 한다."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            if lon < x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-12):
                inside = not inside
    return inside


def fetch_tile(box: tuple, pace: _Pace) -> tuple[list[dict], bool]:
    """한 칸을 받는다. 잘렸으면 넷으로 쪼갠다. (피처, 쪼갰는가)"""
    pace.wait()
    w, s, e, n = box
    body = get_json(WFS, {
        # 중계기를 거칠 때는 VIA_RELAY 가 와서 http 가 알아서 벗겨 낸다.
        "key": keys().require("vworld"),
        "domain": DOMAIN, "typename": TYPENAME,
        "bbox": f"{w},{s},{e},{n}", "srsName": "EPSG:4326",
        # GML 로 요청하면 중계기가 죽는다 (docs/land-price-fallback.md).
        "output": "application/json",
        "maxFeatures": str(PAGE), "resultType": "results",
    })
    feats = (body or {}).get("features") or []
    if len(feats) < PAGE:
        return feats, False
    if (e - w) <= MIN_TILE_DEG:
        return feats, True          # 더는 못 쪼갠다. 잘린 채로 둔다
    mx, my = (w + e) / 2, (s + n) / 2
    out: list[dict] = []
    for sub in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)):
        got, _ = fetch_tile(sub, pace)
        out += got
    return out, True


def _row(props: dict) -> dict:
    out = {}
    for ours, theirs in FIELDS.items():
        v = props.get(theirs)
        out[ours] = None if v in (None, "") else v
    for num in ("area_m2", "official_price"):
        try:
            out[num] = float(out[num]) if out[num] is not None else None
        except (TypeError, ValueError):
            out[num] = None
    try:
        out["stdr_year"] = int(out["stdr_year"]) if out["stdr_year"] else None
    except (TypeError, ValueError):
        out["stdr_year"] = None
    return out


def match_tile(feats: list[dict], trades: pd.DataFrame
               ) -> tuple[list[dict], list[dict]]:
    """이 칸의 거래를 이 칸의 필지에 맞춘다. (필지행, 연결행)

    칸 하나 안에서만 도는 곱이라 전국을 한 번에 도는 것과 비용이 다르다.
    실측 도구는 거래 × 필지를 통째로 돌아 안성에서 4분 30초가 걸렸다.
    """
    parcels, links = [], []
    prepared = []
    for f in feats:
        props = f.get("properties") or {}
        pnu = props.get("pnu")
        if not pnu:
            continue
        rings = _rings(f.get("geometry"))
        if not rings:
            continue
        # 바깥 상자를 먼저 재 둔다. 대부분의 점은 여기서 걸러진다.
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        prepared.append((pnu, min(xs), min(ys), max(xs), max(ys), rings))
        parcels.append(_row(props))

    for t in trades.itertuples(index=False):
        for pnu, x0, y0, x1, y1, rings in prepared:
            if not (x0 <= t.lon <= x1 and y0 <= t.lat <= y1):
                continue
            if any(in_ring(t.lat, t.lon, r) for r in rings):
                links.append({"trade_id": t.trade_id, "pnu": pnu})
                break
    return parcels, links


def describe(con) -> None:
    """붙은 결과를 사람이 읽게. 도로접이 실제로 값을 가르는지까지 본다."""
    n_p = con.execute("SELECT count(*) FROM parcel").fetchone()[0]
    n_l = con.execute("SELECT count(*) FROM trade_parcel").fetchone()[0]
    n_t = con.execute("SELECT count(*) FROM parcel_tile").fetchone()[0]
    trunc = con.execute(
        "SELECT count(*) FROM parcel_tile WHERE truncated").fetchone()[0]
    print(f"\n=== 필지 특성 ===")
    print(f"  훑은 칸 {n_t:,} (그중 쪼갠 칸 {trunc:,})"
          f" · 필지 {n_p:,} · 거래에 붙은 것 {n_l:,}")
    if not n_l:
        return
    mix = con.execute("""
        SELECT coalesce(p.road_side, '(빈 값)') AS road, count(*) AS n
        FROM trade_parcel l JOIN parcel p USING (pnu)
        GROUP BY 1 ORDER BY n DESC LIMIT 10
    """).fetchdf()
    print("\n  도로접면 (거래 기준)")
    for r in mix.itertuples(index=False):
        print(f"    {r.road:<16} {int(r.n):>9,}")
