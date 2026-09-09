"""토지특성(도로접·형상)을 IC 한 곳에 실제로 붙여 보고 **비용을 잰다.**

사장님 지시(2026-09-07): "남이천 IC 를 샘플로 봅시다."

무엇을 재는가. 셋이다.

  1. 얼마나 드는가   호출 몇 번 · 몇 분 · 필지 몇 개
  2. 다 받아지는가   한 번에 오는 수에 한도가 있어 잘리지 않는가
  3. **붙는가**      받은 필지가 우리 거래 행에 실제로 이어지는가

3번이 제일 중요하다. 받을 수 있어도 안 붙으면 소용이 없다. 그리고
붙이는 열쇠가 반만 맞는다 — 저쪽은 읍면동을 숫자 코드로 주고 우리는
이름으로 갖고 있다. 그래서 두 길을 다 재 본다.

  지번 조인   시군구코드 + 본번-부번          (읍면동이 빠져 겹칠 수 있다)
  좌표 조인   거래 점이 필지 도형 안에 드는가  (지번 좌표에만 쓸 수 있다)

겹침률까지 세야 '붙었다' 를 믿을 수 있다.

  python scripts/landchar_sample.py [영업소이름] [반경km]
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vworld_landprice import fetch, why                       # noqa: E402

NED = "https://api.vworld.kr/ned/wfs/getLandCharacteristicsWFS"
# 브이월드 콘솔에 등록된 서비스 주소. 배포 주소가 바뀌면
# 콘솔에도 더해야 한다 (2026-09-08 사도 토지 → 토지 고고).
DOMAIN = os.environ.get("VWORLD_DOMAIN", "toji.fyi")
TYPENAME = "dt_d194"

# 한 번에 받아 볼 최대 피처 수. 돌려받은 수가 이것과 같으면 **잘린 것**
# 이므로 그 칸을 넷으로 쪼개 다시 부른다. 한도를 모른 채 큰 칸으로
# 훑으면 조용히 절반만 받고 '이 동네는 필지가 적네' 로 읽는다.
PAGE = 1000
MIN_TILE_DEG = 0.0015          # 이보다 잘게는 안 쪼갠다 (약 170m)


def hav_km(a_lat, a_lon, b_lat, b_lon) -> float:
    R, p = 6371.0088, math.pi / 180
    return 2 * R * math.asin(math.sqrt(
        math.sin((b_lat - a_lat) * p / 2) ** 2
        + math.cos(a_lat * p) * math.cos(b_lat * p)
        * math.sin((b_lon - a_lon) * p / 2) ** 2))


def in_ring(lat: float, lon: float, ring: list) -> bool:
    """점이 다각형 안에 드는가 (광선 교차). 라이브러리 없이 한다."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            xin = x1 + (lat - y1) * (x2 - x1) / ((y2 - y1) or 1e-12)
            if lon < xin:
                inside = not inside
    return inside


def polygons(geom: dict) -> list:
    """MultiPolygon·Polygon 에서 바깥 고리들만."""
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates") or []
    if t == "Polygon":
        return [c[0]] if c else []
    if t == "MultiPolygon":
        return [p[0] for p in c if p]
    return []


def jibun_of(row: dict) -> str:
    """본번·부번 → 우리 거래의 jibun 형식('8-85' · '8')."""
    try:
        mn = int(row.get("mnnm") or 0)
        sl = int(row.get("slno") or 0)
    except ValueError:
        return ""
    if not mn:
        return ""
    return f"{mn}-{sl}" if sl else f"{mn}"


class Stats:
    def __init__(self):
        self.calls = 0
        self.truncated = 0
        self.errors: list[str] = []
        self.t0 = time.monotonic()

    @property
    def secs(self) -> float:
        return time.monotonic() - self.t0


def fetch_tile(box: tuple, st: Stats) -> list[dict]:
    """한 칸을 받는다. 잘렸으면 넷으로 쪼개 다시 받는다."""
    w, s, e, n = box
    st.calls += 1
    body = fetch(NED, {
        "key": "", "domain": DOMAIN, "typename": TYPENAME,
        "bbox": f"{w},{s},{e},{n}", "srsName": "EPSG:4326",
        "output": "application/json",       # GML 로 요청하면 중계기가 죽는다
        "maxFeatures": str(PAGE), "resultType": "results",
    })
    try:
        feats = json.loads(body).get("features", [])
    except ValueError:
        reason = why(body) or body[:90]
        st.errors.append(f"{w:.4f},{s:.4f} → {reason}")
        return []

    if len(feats) < PAGE:
        return feats
    # 한도에 닿았다 = 잘렸다. 더 잘게 쪼갤 수 있으면 쪼갠다.
    st.truncated += 1
    if (e - w) <= MIN_TILE_DEG:
        return feats                      # 더는 못 쪼갠다. 잘린 채로 둔다
    mx, my = (w + e) / 2, (s + n) / 2
    out = []
    for sub in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)):
        out += fetch_tile(sub, st)
    return out


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "남이천"
    radius = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    tile = float(os.environ.get("TILE_DEG", "0.01"))

    from redt import db
    with db.connect(read_only=True) as con:
        tg = con.execute(
            "SELECT tollgate_id, name, lat, lon FROM tollgate "
            "WHERE name = ? AND lat IS NOT NULL", [name]).fetchdf()
        if tg.empty:
            sys.exit(f"영업소 '{name}' 을 찾지 못했습니다.")
        r = tg.iloc[0]
        lat, lon = float(r["lat"]), float(r["lon"])
        print(f"영업소 {r['name']} ({r['tollgate_id']}) {lat:.6f},{lon:.6f}"
              f" · 반경 {radius}km · 칸 {tile}도")

        # 그 반경 안 토지 거래. **좌표가 있는 것만** — 조인 대상이 그것뿐이다.
        trades = con.execute("""
            SELECT trade_id, sigungu_cd, umd, jibun, lat, lon, geocode_level,
                   jimok, land_use, price_per_m2, deal_year
            FROM trade
            WHERE kind = 'land' AND lat IS NOT NULL
              AND NOT coalesce(is_cancelled, FALSE)
        """).fetchdf()
    trades["km"] = [hav_km(lat, lon, a, b)
                    for a, b in zip(trades["lat"], trades["lon"])]
    trades = trades[trades["km"] <= radius].copy()
    # 사장님이 보시는 세 지역. 조인률도 이 기준으로 봐야 뜻이 있다.
    keep = trades["land_use"].fillna("").str.contains("계획관리|생산관리|자연녹지")
    trades_core = trades[keep]
    parcel = trades[trades["geocode_level"] == "parcel"]
    parcel_core = trades_core[trades_core["geocode_level"] == "parcel"]
    print(f"  반경 안 토지 거래 {len(trades):,}건"
          f" (그중 지번 좌표 {len(parcel):,}건)")
    print(f"    계획관리·생산관리·자연녹지 {len(trades_core):,}건"
          f" (지번 좌표 {len(parcel_core):,}건)")

    # ── 받는다 ──
    dlat = radius / 111.0
    dlon = radius / (111.0 * math.cos(lat * math.pi / 180))
    w, s, e, n = lon - dlon, lat - dlat, lon + dlon, lat + dlat
    boxes = []
    y = s
    while y < n:
        x = w
        while x < e:
            boxes.append((x, y, min(x + tile, e), min(y + tile, n)))
            x += tile
        y += tile
    print(f"\n  칸 {len(boxes)}개로 훑습니다…")

    st = Stats()
    feats: list[dict] = []
    for i, box in enumerate(boxes, 1):
        feats += fetch_tile(box, st)
        if i % 10 == 0 or i == len(boxes):
            print(f"    {i}/{len(boxes)} 칸 · 호출 {st.calls} ·"
                  f" 필지 {len(feats):,} · {st.secs:.0f}초", flush=True)

    rows = [dict(f.get("properties") or {}, __geom=f.get("geometry"))
            for f in feats]
    # 같은 필지가 칸 경계에서 두 번 올 수 있다.
    seen, uniq = set(), []
    for row in rows:
        pnu = row.get("pnu")
        if pnu and pnu in seen:
            continue
        if pnu:
            seen.add(pnu)
        uniq.append(row)

    print(f"\n{'=' * 66}\n비용\n{'=' * 66}")
    print(f"  호출 {st.calls}회 · {st.secs / 60:.1f}분"
          f" · 필지 {len(uniq):,}개 (중복 제거 전 {len(rows):,})")
    print(f"  한도에 닿아 쪼갠 칸 {st.truncated}회")
    if st.errors:
        print(f"  ⚠ 실패한 칸 {len(st.errors)}개 — 이 결과는 완전하지 않습니다")
        for line in st.errors[:5]:
            print(f"      {line}")
    if not uniq:
        sys.exit("필지를 하나도 못 받았습니다. 여기서 멈춥니다.")

    # ── 사장님이 보시는 세 지역만 ──
    # 지시(2026-09-07): "자연녹지, 계획관리, 생산관리 지역만 보면 됩니다."
    # settings.yaml 의 land_use_filter 와 같다. 전체 분포도 함께 내되,
    # **판단의 근거가 되는 숫자는 이 세 지역 것**이어야 한다.
    def zone_of(row) -> str:
        return str(row.get("prpos_area_1_nm") or "")

    core = [r for r in uniq
            if any(k in zone_of(r) for k in ("계획관리", "생산관리", "자연녹지"))]
    print(f"\n{'=' * 66}\n받은 것\n{'=' * 66}")
    print(f"  전체 {len(uniq):,}개 중 계획관리·생산관리·자연녹지"
          f" **{len(core):,}개** ({len(core) / len(uniq):.0%})")

    def mix_of(rows, col):
        out: dict[str, int] = {}
        for row in rows:
            out[str(row.get(col) or "(빈 값)")] = out.get(
                str(row.get(col) or "(빈 값)"), 0) + 1
        return out

    for col, label in (("prpos_area_1_nm", "용도지역"),
                       ("lndcgr_code_nm", "지목"),
                       ("tpgrph_hg_code_nm", "지세"),
                       ("tpgrph_frm_code_nm", "형상 (순서 없음 — 종류일 뿐)")):
        mix = mix_of(core, col)
        filled = sum(v for k, v in mix.items() if k != "(빈 값)")
        print(f"\n  {label} — 채워진 것 {filled:,}/{len(core):,}"
              f" ({filled / max(len(core), 1):.0%})")
        for k, v in sorted(mix.items(), key=lambda x: -x[1])[:7]:
            print(f"      {k:<16} {v:>6,}")

    # ── 도로접면. 이것만 등급으로 본다 ──
    #
    # 사장님 지시: "도로를 접하는 가가 제일 중요합니다." 형상과 달리
    # 도로접면은 **순서가 있다** — 광대로 > 중로 > 소로 > 세로(가) >
    # 세로(불) > 맹지. 순서를 버리고 종류로만 넣으면 '맹지가 소로보다
    # 비쌀 수도 있다' 는 가능성을 열어 두는 셈이라 계수가 흔들린다.
    from redt.usage import road_grade, road_car_ok, is_corner
    GRADE_NAME = {5: "광대로", 4: "중로", 3: "소로",
                  2: "세로(차 가능)", 1: "세로(차 불가)", 0: "맹지"}
    print(f"\n  도로접면 — 원값")
    for k, v in sorted(mix_of(core, "road_side_code_nm").items(),
                       key=lambda x: -x[1])[:8]:
        print(f"      {k:<16} {v:>6,}")

    grades = [road_grade(r.get("road_side_code_nm")) for r in core]
    known = [g for g in grades if g is not None]
    print(f"\n  도로접면 — 등급 (아는 것 {len(known):,}/{len(core):,}"
          f" · 모름 {len(grades) - len(known):,})")
    for g in (5, 4, 3, 2, 1, 0):
        n = sum(1 for x in known if x == g)
        if n:
            print(f"      {g} {GRADE_NAME[g]:<14} {n:>6,}"
                  f"  ({n / max(len(known), 1):.0%})")
    car = [road_car_ok(r.get("road_side_code_nm")) for r in core]
    car_ok = sum(1 for x in car if x == 1)
    car_kn = sum(1 for x in car if x is not None)
    corner = sum(1 for r in core if is_corner(r.get("road_side_code_nm")) == 1)
    print(f"\n      자동차 진입 가능 {car_ok:,}/{car_kn:,}"
          f" ({car_ok / max(car_kn, 1):.0%})"
          f" — 못 들어가면 공장도 창고도 못 짓습니다")
    print(f"      각지(두 면 이상 접함) {corner:,}"
          f" ({corner / max(len(core), 1):.0%})")

    # 도로 등급이 값과 실제로 이어지는가. 공시지가로 바로 볼 수 있다 —
    # 우리 거래에 붙이기 전에 **이 자료 안에서** 확인해 두면, 나중에
    # 계수가 이상할 때 자료 탓인지 모형 탓인지 가릴 수 있다.
    print(f"\n  도로 등급별 공시지가 (원/㎡, 중앙값) — 값과 이어지는가")
    for g in (5, 4, 3, 2, 1, 0):
        vals = sorted(float(r.get("pblntf_pclnd") or 0)
                      for r in core
                      if road_grade(r.get("road_side_code_nm")) == g
                      and str(r.get("pblntf_pclnd") or "").strip())
        vals = [v for v in vals if v > 0]
        if len(vals) >= 10:
            med = vals[len(vals) // 2]
            print(f"      {g} {GRADE_NAME[g]:<14} {med:>10,.0f}  (n={len(vals):,})")

    # ── 붙는가 ──
    print(f"\n{'=' * 66}\n붙는가\n{'=' * 66}")

    # (가) 지번 조인. 읍면동이 빠져 있어 겹칠 수 있다 — 겹침을 센다.
    by_key: dict[tuple, list] = {}
    for row in uniq:
        jb = jibun_of(row)
        if not jb:
            continue
        by_key.setdefault((str(row.get("ld_cpsg_code") or ""), jb), []).append(row)
    dup = sum(1 for v in by_key.values() if len(v) > 1)
    matched = sum(1 for t in trades.itertuples()
                  if (str(t.sigungu_cd), str(t.jibun)) in by_key)
    print(f"\n  (가) 지번 조인  {matched:,}/{len(trades):,}"
          f" ({matched / max(len(trades), 1):.0%})")
    print(f"      열쇠 {len(by_key):,}개 중 필지가 둘 이상 걸린 것"
          f" {dup:,}개 ({dup / max(len(by_key), 1):.0%})")
    if dup:
        print("      → 겹치는 만큼은 어느 필지인지 못 가립니다."
              " 읍면동 코드가 있어야 합니다.")

    # (나) 좌표 조인. 지번 좌표를 가진 거래에만 쓸 수 있다.
    hit = 0
    for t in parcel.itertuples():
        for row in uniq:
            for ring in polygons(row.get("__geom")):
                if in_ring(t.lat, t.lon, ring):
                    hit += 1
                    break
            else:
                continue
            break
    hit_core = 0
    for t in parcel_core.itertuples():
        for row in uniq:
            for ring in polygons(row.get("__geom")):
                if in_ring(t.lat, t.lon, ring):
                    hit_core += 1
                    break
            else:
                continue
            break
    print(f"\n  (나) 좌표 조인  {hit:,}/{len(parcel):,}"
          f" ({hit / max(len(parcel), 1):.0%}) — 지번 좌표 거래만")
    print(f"      그중 세 지역 {hit_core:,}/{len(parcel_core):,}"
          f" ({hit_core / max(len(parcel_core), 1):.0%})")
    print("      점이 필지 도형 안에 드는지로 봅니다. 읍면동 코드가"
          " 없어도 되고 겹칠 일이 없습니다.")

    print(f"\n{'=' * 66}\n전국으로 늘리면\n{'=' * 66}")
    per_km2 = len(uniq) / (math.pi * radius ** 2)
    print(f"  이 동네 필지 밀도 {per_km2:,.0f}개/km²")
    print(f"  호출 {st.calls}회로 {math.pi * radius ** 2:.0f}km² 를 훑었습니다"
          f" ({st.secs / max(st.calls, 1):.1f}초/회)")
    print("  ※ 영업소 561곳 × 이 비용이 전국치입니다. 동네마다 밀도가")
    print("    달라 그대로 곱하면 틀립니다 — 도시권에서 한 곳 더 재야 합니다.")


if __name__ == "__main__":
    main()
