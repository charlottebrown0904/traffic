"""필지 진단 — 다섯 축을 **또래 안의 백분위**로 재기 위한 분포.

요구사항(2026-09-08):

    "실거래를 보여주고 해당 필지를 클릭하면 스파이더 차트를 통해 여러가지
     인자들을 분석하여 어떤 방향이 좋을 지 판단할 수 있도록 보여주는
     방향으로 변경하겠습니다. (어떤 토지이든 나쁜 토지는 없다. 어떤
     방향으로 개발할 지가 문제다)"

## 왜 백분위인가 — 단일 점수를 안 만드는 이유

땅에 0~100 점 하나를 매기면 **가짜 정밀도**가 된다. 같은 필지가 물류창고
에는 A급이고 전원주택에는 C급인데, 하나의 숫자로 뭉개면 그 사실이
사라진다. 레이더는 "무엇이 강하고 무엇이 약한가" 만 말한다.

그리고 레이더에는 함정이 셋 있다.

  · 축 순서만 바꿔도 모양이 달라진다
  · 넓이는 아무 뜻이 없다
  · 단위가 다른 축을 한 그림에 겹친다

셋 다 **백분위**로 막는다. 모든 축을 '또래 몇 %' 로 통일하면 단위가
같아지고, 넓이를 점수로 쓰지 않으면 축 순서도 해롭지 않다. 그래서 이
파일은 **점수를 만들지 않는다** — 비교 대상의 분포만 만든다.

## 또래를 무엇으로 잡는가

같은 시군구 · 같은 용도지역에서 **실제로 거래된 땅**들이다. 전국 대비로
재면 시골 땅은 전부 찌그러진 별이 되어 아무것도 못 읽는다.

필지 표(parcel)가 아니라 거래(trade)를 기준으로 삼는 이유가 둘 있다.

  1. 필지 표에는 좌표가 없다. 도형은 점-다각형으로 맞춘 뒤 버린다
     (안 그러면 DB 가 감당이 안 된다). 교통 축은 좌표가 있어야 한다.
  2. '이 동네에서 실제로 팔린 땅' 이 사람이 견주고 싶은 대상이다.
"""
from __future__ import annotations

import datetime

from . import db
from .usage import road_grade

# 또래가 이보다 적으면 백분위가 우연이 된다. 시군구 → 시도 → 전국으로
# 물러난다. 어느 단계로 물러났는지는 화면이 말한다.
MIN_PEER = 30

# ── 가격 추세 축 (요구사항 2026-09-10) ─────────────────────────
#
# 왜 '수준' 이 아니라 '추세' 인가. 지금 비싼 땅이 좋은 땅은 아닙니다.
# 토지에서는 **오르는 중인지**가 사는 사람에게 더 중요한 정보입니다.
#
# 몇 해를 볼 것인가. 짧으면 한 해 튄 값에 통째로 끌려가고, 길면 이미
# 끝난 상승을 지금 일처럼 말합니다. 여덟 해를 창으로 두고 그 안에서
# 값이 있는 첫 해와 끝 해로 연평균 상승률을 잡습니다.
TREND_YEARS = 8
TREND_FROM = datetime.date.today().year - TREND_YEARS
# 한 해에 이보다 적으면 그 해는 버립니다. 두세 건의 중앙값은 그
# 동네 값이 아니라 그 두세 건의 값입니다.
MIN_TREND_N = 5
# 첫 해와 끝 해가 이만큼은 떨어져 있어야 상승률이라고 부를 수 있습니다.
MIN_TREND_SPAN = 3

# 분위 경계를 몇 개로 자를 것인가. 11개면 0·10·…·100 백분위다.
QUANTILES = [i / 10 for i in range(11)]

# 형상 — 넓게 쓸 수 있는 순서. 자루형·부정형은 같은 면적이라도 실제로
# 쓸 수 있는 땅이 줄어든다.
SHAPE_GRADE = {
    "정방형": 5, "가로장방": 4, "세로장방": 4, "장방형": 4,
    "사다리": 3, "삼각형": 2, "역삼각": 2, "부정형": 1, "자루형": 0,
}
# 지세 — 평지가 가장 쓰기 쉽다. 급경사·고지·저지는 개발비가 붙는다.
SLOPE_GRADE = {
    "평지": 5, "완경사": 4, "급경사": 2, "고지": 1, "저지": 1,
}

# 개발 여지 — 용도지역이 허용하는 폭. **이것은 우리가 추정한 값이 아니라
# 국토계획법이 정해 둔 것을 순서로 옮긴 것**이다. 계획관리에는 공장이
# 되고 보전관리에는 안 된다.
ZONE_LADDER = {
    "계획관리": 5,
    "생산관리": 3, "자연녹지": 3, "생산녹지": 3,
    "관리지역": 3,          # 세분 전(2006~2010) 신고값 — 가운데로 둔다
    "보전관리": 1, "보전녹지": 1, "농림": 1, "자연환경보전": 0,
    "개발제한": 0,
}

# 교통 축 — 중력 모형. 김진유(2011)의 대도시접근성지수와 같은 꼴이다
# (인구/거리). 우리는 인구 대신 **그 영업소를 실제로 지나가는 화물 통행량**
# 을 쓴다. IC 까지의 거리를 쓴 연구는 많지만 통행량으로 잰 것은 아직
# 못 찾았다 (docs 4-D).
#
# 반경은 10km. 조인(trade_tollgate_link)이 그 범위까지만 있고, 화면도
# 같은 반경으로 계산해야 같은 값이 나온다.
TRAFFIC_RADIUS_KM = 10.0
# 0 으로 나누는 것을 막는 최소 거리. IC 바로 옆 땅이 무한대가 되면
# 그 한 점이 분포를 통째로 망친다.
TRAFFIC_MIN_KM = 0.5

AXES = [
    {"key": "road", "label": "도로",
     "desc": "접한 도로의 폭과 각지 여부. 차가 들어가느냐가 단가를 "
             "+15.7% 가릅니다 (헤도닉 실측, 95% +12.3~+19.2%)."},
    {"key": "traffic", "label": "교통",
     "desc": "10km 안 영업소의 화물 통행량을 거리 제곱으로 나눠 더한 값. "
             "IC 까지의 거리가 아니라 실제로 몇 대가 지나가는지로 잽니다."},
    {"key": "zoning", "label": "개발 여지",
     "desc": "용도지역이 허용하는 폭. 이 시군구 안에서 이 용도지역보다 "
             "여지가 좁은 땅이 몇 %인지."},
    {"key": "price", "label": "가격 추세",
     "desc": "이 동네·이 용도지역의 실거래 단가가 최근 몇 해 동안 얼마나 "
             "올랐는지. 지금 비싼지 싼지가 아니라 **오르는 중인지**를 "
             "봅니다. 전국의 다른 동네·용도들과 견준 백분위입니다."},
    {"key": "land", "label": "모양·지세",
     "desc": "형상과 지세. 같은 면적이라도 자루형·급경사는 실제로 쓸 수 "
             "있는 땅이 줄어듭니다."},
]


def _grade_of(table: dict, text) -> int | None:
    """부분 일치로 등급을 찾는다. 자료가 '가로장방형'·'가로장방' 처럼 온다."""
    if not isinstance(text, str) or not text.strip():
        return None
    for key, grade in table.items():
        if key in text:
            return grade
    return None


def shape_grade(text) -> int | None:
    return _grade_of(SHAPE_GRADE, text)


def slope_grade(text) -> int | None:
    return _grade_of(SLOPE_GRADE, text)


def zone_grade(text) -> int | None:
    return _grade_of(ZONE_LADDER, text)


def land_grade(shape, slope) -> float | None:
    """모양·지세를 한 축으로. 둘 중 하나만 있으면 그것만 쓴다."""
    a, b = shape_grade(shape), slope_grade(slope)
    got = [g for g in (a, b) if g is not None]
    return sum(got) / len(got) if got else None


def _cum(counts: dict[int, int]) -> list[float]:
    """등급별 개수 → 등급 0..5 의 **누적 비율**.

    화면은 이것 하나로 백분위를 읽는다. 등급 g 인 필지의 백분위는
    '그보다 낮은 등급의 비율 + 같은 등급의 절반' 으로 잡는다 — 같은
    등급끼리는 순서가 없으므로 그 칸의 한가운데에 둔다.
    """
    total = sum(counts.values()) or 1
    out = []
    below = 0
    for g in range(6):
        here = counts.get(g, 0)
        out.append(round((below + here / 2) / total, 4))
        below += here
    return out


def _quantiles(values: list[float]) -> list[float]:
    """0·10·…·100 백분위 경계. 화면이 이 사이를 선형 보간해 읽는다."""
    v = sorted(values)
    if not v:
        return []
    n = len(v)
    out = []
    for q in QUANTILES:
        i = min(n - 1, max(0, int(round(q * (n - 1)))))
        out.append(round(float(v[i]), 2))
    return out


def build(groups: list[tuple[str, str]]) -> dict:
    """또래 분포를 만든다.

    groups 는 (묶음이름, LIKE조건) 목록 — webexport.LANDPRICE_GROUPS 와
    같은 것을 받는다. 화면의 용도지역 고르기와 같은 묶음을 써야
    '지도에서 본 것' 과 '필지 진단' 이 같은 땅을 말한다.
    """
    case = " ".join(f"WHEN t.land_use LIKE '%{like}%' THEN '{name}'"
                    for name, like in groups)
    with db.connect(read_only=True) as con:
        # 또래의 재료. 필지 특성이 붙은 거래만 쓴다 — 안 붙은 것은
        # 도로접·형상을 모르므로 분포에 넣을 수가 없다.
        rows = con.execute(f"""
            SELECT t.sigungu_cd,
                   CASE {case} ELSE NULL END AS grp,
                   pc.road_side, pc.shape, pc.slope, pc.official_price
            FROM trade t
            JOIN trade_parcel tp ON tp.trade_id = t.trade_id
            JOIN parcel pc ON pc.pnu = tp.pnu
            WHERE t.kind = 'land' AND t.lat IS NOT NULL
              AND NOT coalesce(t.is_cancelled, FALSE)
              AND t.sigungu_cd IS NOT NULL
        """).fetchdf()

        # 가격 추세 축 (요구사항 2026-09-10 — '가격 수준' 을 바꿉니다).
        #
        # 필지 하나에는 올해 공시지가 한 값뿐이라 그 땅만으로는 추세를
        # 못 냅니다. **그 땅이 속한 동네·용도지역의 실거래 단가**가
        # 최근 몇 해 어떻게 움직였는지를 씁니다.
        #
        # 해마다 중앙값을 내고 처음과 끝으로 연평균 상승률(CAGR)을
        # 잡습니다. 평균이 아니라 중앙값인 이유는, 거래 몇 건이 큰
        # 땅이면 평균이 통째로 끌려가기 때문입니다.
        #
        # 한 해에 MIN_TREND_N 건이 안 되는 해는 **버립니다** — 두세 건의
        # 중앙값은 그 동네 값이 아니라 그 두세 건의 값입니다.
        trend_rows = con.execute(f"""
            SELECT sigungu_cd,
                   CASE {case} ELSE NULL END AS grp,
                   deal_year,
                   median(price_per_m2) AS p50,
                   count(*) AS n
            FROM trade t
            WHERE t.kind = 'land' AND t.price_per_m2 IS NOT NULL
              AND NOT coalesce(t.is_cancelled, FALSE)
              AND t.sigungu_cd IS NOT NULL
              AND t.deal_year >= {TREND_FROM}
            GROUP BY 1, 2, 3
            HAVING count(*) >= {MIN_TREND_N}
        """).fetchdf()

        # 교통 축. 조인 표에 거리(10km 까지)가 이미 들어 있어서 여기서
        # 다시 재지 않는다. 화물 통행량은 가장 최근 해의 일평균을 쓴다.
        # 화물은 2·3·4·5종이다 — 2종도 물류에 많이 쓰인다.
        traffic = con.execute(f"""
            WITH vol AS (
                SELECT tollgate_id, avg_daily
                FROM (
                    SELECT tollgate_id, avg_daily,
                           row_number() OVER (PARTITION BY tollgate_id
                                              ORDER BY year DESC) AS rn
                    FROM traffic
                    -- 2종도 물류 차량이다 (요구사항 2026-09-10).
                    WHERE vehicle_type IN (2, 3, 4, 5) AND avg_daily IS NOT NULL
                ) WHERE rn = 1
            ),
            g AS (
                SELECT l.trade_id,
                       sum(v.avg_daily
                           / pow(greatest(l.distance_km, {TRAFFIC_MIN_KM}), 2)) AS grav
                FROM trade_tollgate_link l
                JOIN vol v ON v.tollgate_id = l.tollgate_id
                WHERE l.distance_km <= {TRAFFIC_RADIUS_KM}
                GROUP BY 1
            )
            SELECT t.sigungu_cd,
                   CASE {case} ELSE NULL END AS grp,
                   coalesce(g.grav, 0) AS grav
            FROM trade t
            LEFT JOIN g ON g.trade_id = t.trade_id
            WHERE t.kind = 'land' AND t.lat IS NOT NULL
              AND NOT coalesce(t.is_cancelled, FALSE)
              AND t.sigungu_cd IS NOT NULL
        """).fetchdf()

        # 개발 여지 — 시군구 안에서 이 용도지역보다 여지가 좁은 땅이 몇 %.
        # 또래(같은 용도지역) 안에서 재면 늘 같은 값이라 뜻이 없다.
        zones = con.execute("""
            SELECT sigungu_cd, coalesce(land_use, '') AS land_use, count(*) AS n
            FROM trade
            WHERE kind = 'land' AND NOT coalesce(is_cancelled, FALSE)
              AND sigungu_cd IS NOT NULL
            GROUP BY 1, 2
        """).fetchdf()

    peers: dict[str, dict] = {}
    bag: dict[str, dict] = {}

    def slot(key: str) -> dict:
        return bag.setdefault(key, {"road": {}, "land": {}, "price": [],
                                    "traffic": [], "n": 0})

    def add(key: str, r) -> None:
        s = slot(key)
        s["n"] += 1
        g = road_grade(r.road_side)
        if g is not None:
            s["road"][g] = s["road"].get(g, 0) + 1
        lg = land_grade(r.shape, r.slope)
        if lg is not None:
            k = int(round(lg))
            s["land"][k] = s["land"].get(k, 0) + 1
        if r.official_price and r.official_price > 0:
            s["price"].append(float(r.official_price))

    for r in rows.itertuples(index=False):
        if not r.grp:
            continue
        code = str(r.sigungu_cd)
        # 시군구 · 시도 · 전국 세 단계를 함께 채운다. 또래가 모자라면
        # 화면이 위로 물러난다.
        add(f"{code}|{r.grp}", r)
        add(f"{code[:2]}|{r.grp}", r)
        add(f"*|{r.grp}", r)

    for r in traffic.itertuples(index=False):
        if not r.grp:
            continue
        code = str(r.sigungu_cd)
        for key in (f"{code}|{r.grp}", f"{code[:2]}|{r.grp}", f"*|{r.grp}"):
            slot(key)["traffic"].append(float(r.grav))

    # ── 가격 추세 ────────────────────────────────────────────
    #
    # 해마다의 중앙값을 모아 연평균 상승률을 냅니다. 또래 열쇠는 위와
    # 같은 세 단계(시군구 · 시도 · 전국)로 채웁니다 — 시군구에서 해가
    # 모자라면 화면이 위로 물러납니다.
    years: dict[str, dict[int, float]] = {}
    for r in trend_rows.itertuples(index=False):
        if not r.grp or r.p50 is None or not (float(r.p50) > 0):
            continue
        code = str(r.sigungu_cd)
        for key in (f"{code}|{r.grp}", f"{code[:2]}|{r.grp}", f"*|{r.grp}"):
            # 위 단계는 여러 시군구가 같은 해에 들어오므로 **더한 뒤
            # 나누지 않습니다** — 중앙값의 평균은 중앙값이 아닙니다.
            # 대신 그 해의 값들을 모아 두었다가 아래에서 중앙값을 냅니다.
            years.setdefault(key, {}).setdefault(int(r.deal_year), [])
            years[key][int(r.deal_year)].append(float(r.p50))

    trends: dict[str, float] = {}
    for key, by_year in years.items():
        got = sorted((y, sorted(v)[len(v) // 2]) for y, v in by_year.items())
        if len(got) < 2:
            continue
        (y0, p0), (y1, p1) = got[0], got[-1]
        span = y1 - y0
        if span < MIN_TREND_SPAN or p0 <= 0 or p1 <= 0:
            continue
        trends[key] = (p1 / p0) ** (1.0 / span) - 1.0

    # 백분위로 읽으려면 견줄 분포가 있어야 합니다. **시군구 단계만**
    # 모아 전국 분포를 만듭니다 — 시도·전국 열쇠까지 섞으면 같은 땅이
    # 여러 번 세어져 분포가 가운데로 쏠립니다.
    trend_q = _quantiles([v for k, v in trends.items()
                          if not k.startswith("*|") and len(k.split("|")[0]) > 2])

    for key, s in bag.items():
        if s["n"] < MIN_PEER and not s["traffic"]:
            continue
        peers[key] = {
            "n": s["n"],
            "road": _cum(s["road"]),
            "land": _cum(s["land"]),
            "price": _quantiles(s["price"]),
            "traffic": _quantiles(s["traffic"]),
        }
        if key in trends:
            # 연평균 상승률. 화면이 원값을 그대로 적을 수 있게 싣습니다 —
            # 백분위만 주면 '상위 20%' 가 몇 %/년인지 알 수 없습니다.
            peers[key]["trend"] = round(trends[key], 5)
            peers[key]["trend_span"] = sorted(years[key])[-1] - sorted(years[key])[0]

    # 시군구별 개발 여지 사다리.
    sigungu: dict[str, dict] = {}
    for r in zones.itertuples(index=False):
        g = zone_grade(r.land_use)
        if g is None:
            continue
        d = sigungu.setdefault(str(r.sigungu_cd), {})
        d[g] = d.get(g, 0) + int(r.n)
    zone_pct = {}
    for code, counts in sigungu.items():
        zone_pct[code] = _cum(counts)

    with_trend = sum(1 for v in peers.values() if "trend" in v)
    print(f"  필지 진단 또래 {len(peers):,}묶음"
          f" (시군구·시도·전국 3단계) · 시군구 사다리 {len(zone_pct):,}곳")
    print(f"  가격 추세 {with_trend:,}묶음 ({with_trend / max(1, len(peers)):.0%})"
          f" · 최근 {TREND_YEARS}년 · 전국 분포 {len(trend_q)}분위")
    return {
        "axes": AXES,
        "min_peer": MIN_PEER,
        "traffic": {"radius_km": TRAFFIC_RADIUS_KM, "min_km": TRAFFIC_MIN_KM},
        # 화면이 **같은 사다리**를 써야 한다. 여기서 한 번만 정한다.
        "shape_grade": SHAPE_GRADE,
        "slope_grade": SLOPE_GRADE,
        "zone_ladder": ZONE_LADDER,
        "peers": peers,
        # 전국 시군구×용도의 연평균 상승률 분포. 한 또래의 추세를
        # 백분위로 바꾸는 자입니다.
        "trend_q": trend_q,
        "trend_years": TREND_YEARS,
        "zone_pct": zone_pct,
    }
