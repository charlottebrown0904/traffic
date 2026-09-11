"""'현재 가치' 2판 — 공시지가기준법 산출 (표준지 방식).

감정평가에 관한 규칙 §14 가 정한 순서 그대로다.

    토지단가 = 표준지공시지가 × 시점수정 × 지역요인 × 개별요인 × 그 밖의 요인

감정평가서 52건(docs/appraisal-review.md)에서 확인한 것:

  · 41건 전부 이 식으로 값을 냈고, 네 마디를 곱하면 44/45건이 평가서
    산출단가와 0.3% 안에서 맞는다.
  · 값을 가르는 것은 '그 밖의 요인'(1.3~5.7배)이다. 개별요인은 도로가
    아닌 한 ±30% 안에서 논다.
  · 시점수정은 1.000~1.017, 지역요인은 41건 전부 1.00 이다.

이 모듈은 **점수를 만들지 않는다.** 평가사가 산출표에 적는 다섯 마디를
같은 순서로 만들고, 마디마다 무엇을 근거로 그 값을 썼는지 글로 남긴다.
화면은 이 표를 그대로 보여준다 — 값 하나가 아니라 산출 과정이 상품이다.

자료가 없는 마디는 **1.00 으로 채우지 않고 비운 채 표시한다.** 시점수정을
모르면 '시점수정 (자료 없음)' 이지 1.00 이 아니다. 조사가 안 된 것과
차이가 없는 것은 다르다.

## 무엇이 아직 없는가

  · 표준지 자료 — 표준지공시지가 파일(data.go.kr 15004246)을 아직
    못 붙였다. `pick_standard()` 는 후보 목록을 받는 함수로 두었고,
    후보를 어디서 받을지는 docs/radar-and-current-value.md §4 에 있다.
  · 지가변동률 — 한국부동산원 월간 지가변동률을 아직 안 받는다.
    `time_factor()` 는 월별 변동률 목록을 받으면 그것을 곱하고, 없으면
    또래 추세로 대신하되 그 사실을 적는다.
  · 거래사례 기준 그 밖의 요인 — `trade_other_factor()` 는 우리 실거래
    DB 로 계산하는 SQL 인데, 이 저장소의 실행 환경에 DB 가 없어 **여기서
    돌려 보지 못했다.** 평가선례 기준(원장) 쪽은 검산했다.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data" / "appraisal" / "ledger.tsv"

# ─────────────────────────────────────────────────────────────────
# 1. 분류 — 용도지역군 · 지목군 · 지대
#
# 평가서는 지대(농경지대·임야지대·주택지대·상업지대·공업지대)마다 다른
# 항목표를 쓴다. 그 밖의 요인 표는 (용도지역군 × 지목군) 으로 쌓는다
# (docs/appraisal-review.md §3·§5 와 같은 묶음).
# ─────────────────────────────────────────────────────────────────

ZONE_GROUPS = [
    ("관리", ("관리",)),
    ("녹지", ("녹지",)),
    ("농림", ("농림", "자연환경")),
    ("주거", ("주거", "일주", "전주")),
    ("상업", ("상업",)),
    ("공업", ("공업",)),
]

# 지목군. 지목이 먼저고, 없으면 이용상황으로 짚는다.
USE_GROUPS = [
    ("임야", ("임야", "자연림", "토지임야", "임")),
    ("전·답", ("전", "답", "과수", "묵", "농", "목장")),
    ("대", ("대", "주거", "주택", "나지", "상업")),
    ("공장·도로", ("공장", "공업", "도로", "잡종", "창고", "주차")),
]

# 지대. 개별요인 항목표를 고르는 열쇠다.
ZONE_KIND_BY_USE = {"임야": "임야지대", "전·답": "농경지대", "대": "주택지대",
                    "공장·도로": "공업지대"}


def _first(text, table, default=None):
    t = str(text or "")
    for name, keys in table:
        if any(k in t for k in keys):
            return name
    return default


def zone_group(land_use) -> str | None:
    return _first(land_use, ZONE_GROUPS)


def use_group(jimok, use_situation=None) -> str | None:
    # '전' 은 '전용주거' 에도 들어 있어 지목을 먼저 본다.
    j = str(jimok or "").strip()
    if j:
        if j in ("임야",):
            return "임야"
        if j in ("전", "답", "과수원", "목장용지"):
            return "전·답"
        if j in ("대",):
            return "대"
        if j in ("공장용지", "도로", "잡종지", "창고용지", "주차장"):
            return "공장·도로"
    return _first(use_situation, USE_GROUPS) or _first(jimok, USE_GROUPS)


def zone_kind(land_use, jimok, use_situation=None) -> str:
    zg = zone_group(land_use)
    ug = use_group(jimok, use_situation)
    if zg == "상업" and ug in ("대", None):
        return "상업지대"
    if zg == "공업" and ug in ("대", "공장·도로", None):
        return "공업지대"
    return ZONE_KIND_BY_USE.get(ug, "농경지대" if zg in ("관리", "녹지", "농림")
                                else "주택지대")


# ─────────────────────────────────────────────────────────────────
# 2. 개별요인 — 격차율 표
#
# 값은 평가서 41건에서 관측한 격차율(docs/appraisal-review.md §4)에 맞춘
# 것이다. 지수를 두고 **대상 ÷ 표준지** 로 격차율을 만든다 — 그래야
# 표준지가 맹지든 소로든 같은 표로 읽힌다.
#
# 검산(scripts/test_valuation.py): 41건에 이 표를 대입하면 평가사가
# 적은 개별요인과 중앙 1.00, ±10% 안 23건, ±15% 안 29건이 맞는다.
# 벗어난 건은 표준지 지세가 원장에 없거나(급경사 임야 0.75~0.80),
# 특례(현황도로·자연취락·선하지)가 걸린 건이다.
# ─────────────────────────────────────────────────────────────────

# 도로접면 지수. 순서는 usage.road_grade 의 사다리와 같다.
# 도로접면 글은 원천마다 다르다 — 평가서 '세로(가)', 토지특성·표준지
# '세로한면(가)'·'세로각지(불)'. 그래서 '세로(가)' 를 통째로 찾지 않고
# **순서대로** 광대·중로·소로를 먼저, 그다음 '(불)'·'(가)' 로 세로를 가른다.
ROAD_INDEX = [
    ("맹지", 0.80), ("광대", 1.25), ("중로", 1.18), ("소로", 1.10),
    ("(불)", 0.88), ("불가", 0.88), ("(가)", 1.00), ("가능", 1.00),
]
ROAD_CORNER_BONUS = 0.03        # 각지 — 평가서는 1.02~1.05 를 적었다

SHAPE_INDEX = [
    ("정방", 1.00), ("가장", 1.00), ("가로장방", 1.00),
    ("세장", 1.00), ("세로장방", 1.00), ("장방", 1.00),
    ("사다리", 0.98), ("삼각", 0.93), ("역삼각", 0.93),
    ("부정", 0.95), ("자루", 0.90),
]

# 지세. 임야는 급경사 감가가 더 크다 (평가서 0.75~0.85, 농지 0.88~0.93).
SLOPE_INDEX = {
    "임야지대": [("평지", 1.00), ("완경사", 0.95), ("급경사", 0.82),
               ("고지", 0.92), ("저지", 0.92)],
    "*": [("평지", 1.00), ("완경사", 0.97), ("급경사", 0.88),
          ("고지", 0.95), ("저지", 0.95)],
}

# 지목·이용상황이 표준지와 다를 때 (대상, 표준지) → 격차율.
USE_MISMATCH = {
    ("임야", "대"): (0.90, "지목 임야 — 대지 표준지 대비 (평가서 0.90)"),
    ("임야", "전·답"): (0.80, "자연림 — 전 표준지 대비 (평가서 0.80)"),
    ("전·답", "임야"): (1.25, "개간·농지 — 임야 표준지 대비 (평가서 1.25)"),
    ("전·답", "대"): (0.85, "농지 — 대지 표준지 대비"),
}

# 특례 — 식 밖에서 값을 바꾸는 규칙 (docs/appraisal-review.md §4 특례표).
SPECIAL = {
    "현황도로": (0.33, "현황이 도로 — 인근 토지의 1/3 (보상법 시행규칙 §26 준용)"),
    "도시계획시설도로저촉": (0.85, "도시계획시설 도로 저촉 부분 85%"),
    "도시계획시설공원": (0.60, "도시계획시설 공원 (평가서 0.60)"),
    "선하지": (0.88, "선하지·철탑 (평가서 0.85~0.90)"),
    "자연취락지구": (1.15, "자연취락지구 안 — 표준지가 밖일 때 (평가서 접근 1.35, 행정 0.95 를 눌러 잡음)"),
    "지구단위계획": (1.10, "일단 건축허가·지구단위계획 (평가서 1.10)"),
}

# 표준지와 반드시 같아야 하는 구역. 다르면 격차율로 메우지 않고 표준지를
# 다시 고르라고 한다 — 평가사도 그렇게 한다.
#
# 다만 표준지 자료(브이월드 속성)에는 용도지역·용도지구만 있고 농업진흥·
# 보전산지는 **없다.** 없는 것을 '다르다' 로 읽으면 후보가 전부 사라진다.
# 그래서 거르는 것은 표준지 쪽에도 적히는 개발제한구역뿐이고, 나머지는
# 경고로 남긴다 ('농업진흥' 은 진흥구역·진흥지역·보호구역을 다 잡는다).
MUST_MATCH = ("개발제한구역", "농업진흥", "보전산지")
STD_KNOWN = ("개발제한구역",)

# 면적. 주택·상업·공업지대에서만 본다 — 농지·임야는 평가서가 면적
# 격차를 거의 안 적었다 (8㎡ 소필지 한 건뿐).
AREA_RULES = {
    "주택지대": [(0.0, 0.5, 0.95, "과소 필지"), (0.5, 3.0, 1.00, None),
              (3.0, math.inf, 0.95, "과대 필지")],
    "상업지대": [(0.0, 0.5, 0.95, "과소 필지"), (0.5, 3.0, 1.00, None),
              (3.0, math.inf, 0.95, "과대 필지")],
    "공업지대": [(0.0, 0.3, 0.95, "과소 필지"), (0.3, 5.0, 1.00, None),
              (5.0, math.inf, 0.97, "과대 필지")],
}


def _index(text, table):
    t = str(text or "")
    for key, v in table:
        if key in t:
            return v
    return None


def road_index(text) -> float | None:
    """도로접면 → 지수. '2차선 포장도로' 처럼 사다리 밖의 글은 세로(가)로 본다."""
    if not text:
        return None
    t = str(text)
    if "지정되지" in t or "미상" in t:
        return None
    v = _index(t, ROAD_INDEX)
    if v is None and ("차선" in t or "포장" in t):
        v = 1.00
    if v is not None and "각지" in t and "맹지" not in t:
        v += ROAD_CORNER_BONUS
    return v


def shape_index(text) -> float | None:
    return _index(text, SHAPE_INDEX)


def slope_index(text, kind) -> float | None:
    return _index(text, SLOPE_INDEX.get(kind, SLOPE_INDEX["*"]))


def _ratio(a, b):
    """대상 ÷ 표준지. 한쪽이라도 모르면 None — 1.00 으로 메우지 않는다."""
    if a is None or b is None or not b:
        return None
    return a / b


def individual_factor(subject: dict, std: dict) -> dict:
    """개별요인 비교표.

    subject·std 는 토지특성 칸 그대로다: land_use, land_use2, jimok,
    use_situation, road_side, shape, slope, area_m2, 그리고 겹친 구역
    이름 목록 zones (선택). 항목마다 (조건, 대상, 표준지, 격차율, 사유)
    를 남기고, 곱한 값과 경고를 함께 돌려준다.
    """
    kind = zone_kind(subject.get("land_use"), subject.get("jimok"),
                     subject.get("use_situation"))
    items = []
    warnings = []

    def add(cond, mine, theirs, ratio, why):
        items.append({"cond": cond, "subject": mine, "std": theirs,
                      "ratio": None if ratio is None else round(ratio, 3),
                      "why": why})

    # 특례가 걸리면 그것이 전부다.
    use_txt = str(subject.get("use_situation") or "")
    if "도로" in use_txt and ("현황" in use_txt or subject.get("jimok") == "도로"):
        r, why = SPECIAL["현황도로"]
        add("기타(특례)", use_txt, std.get("use_situation"), r, why)
        return {"kind": kind, "items": items, "factor": r, "warnings": warnings,
                "special": "현황도로"}

    # 가로·접근 — 도로접면
    rs, rd = road_index(subject.get("road_side")), road_index(std.get("road_side"))
    r = _ratio(rs, rd)
    add("가로·접근 (도로접면)", subject.get("road_side"), std.get("road_side"), r,
        None if r is not None else "도로접면을 한쪽이라도 모른다")
    if r is None:
        warnings.append("도로접면 미상 — 격차율에서 뺐다")

    # 획지 — 형상 (임야지대는 평가서가 획지 항목을 안 쓴다)
    if kind != "임야지대":
        ss, sd = shape_index(subject.get("shape")), shape_index(std.get("shape"))
        r = _ratio(ss, sd)
        add("획지 (형상)", subject.get("shape"), std.get("shape"), r,
            None if r is not None else "형상을 한쪽이라도 모른다")

    # 자연·획지 — 지세
    ls, ld = slope_index(subject.get("slope"), kind), slope_index(std.get("slope"), kind)
    r = _ratio(ls, ld)
    add("자연·획지 (지세)", subject.get("slope"), std.get("slope"), r,
        None if r is not None else "지세를 한쪽이라도 모른다")
    if r is None:
        warnings.append("지세 미상 — 격차율에서 뺐다 (표준지 지세가 없는 원천이 있다)")

    # 획지 — 면적
    rules = AREA_RULES.get(kind)
    a, b = subject.get("area_m2"), std.get("area_m2")
    if rules and a and b:
        q = float(a) / float(b)
        for lo, hi, ratio, why in rules:
            if lo <= q < hi:
                add("획지 (면적)", f"{float(a):,.0f}㎡", f"{float(b):,.0f}㎡", ratio,
                    why or "표준지의 0.5~3배 안")
                break

    # 지목·이용상황
    ug_s = use_group(subject.get("jimok"), subject.get("use_situation"))
    ug_d = use_group(std.get("jimok"), std.get("use_situation"))
    if ug_s and ug_d and ug_s != ug_d:
        r, why = USE_MISMATCH.get((ug_s, ug_d), (None, "지목군이 다르다 — 표준지를 다시 고를 것"))
        add("행정·기타 (지목·이용상황)", ug_s, ug_d, r, why)
        if r is None:
            warnings.append(f"지목군 불일치 {ug_s}/{ug_d} — 표준지 재선정 권고")

    # 행정 — 겹친 구역
    zs = set(_zone_names(subject))
    zd = set(_zone_names(std))
    for name in MUST_MATCH:
        if (name in zs) != (name in zd):
            if name in STD_KNOWN:
                warnings.append(f"{name} 이(가) 대상·표준지 한쪽에만 있다 — 표준지를 같은 구역에서 다시 고를 것")
            elif name in zs:
                warnings.append(f"대상이 {name} 안인데 표준지 자료에는 그 구역 정보가 없어 같은지 확인하지 못했다")
    for name, (ratio, why) in SPECIAL.items():
        if name in ("현황도로",):
            continue
        if name in zs and name not in zd:
            add("행정 (지구·구역)", name, "—", ratio, why)
        elif name in zd and name not in zs and name == "자연취락지구":
            add("행정 (지구·구역)", "—", name, 0.95, "표준지가 자연취락지구 (평가서 0.95)")

    factor = 1.0
    for it in items:
        if it["ratio"] is not None:
            factor *= it["ratio"]
    return {"kind": kind, "items": items, "factor": round(factor, 3),
            "warnings": warnings, "special": None}


def _zone_names(p: dict) -> list[str]:
    out = []
    for k in ("land_use", "land_use2"):
        v = p.get(k)
        if v and "지정되지" not in str(v):
            out.append(str(v))
    for z in p.get("zones") or []:
        out.append(z if isinstance(z, str) else str(z.get("label") or ""))
    # '개발제한구역' 같은 구역 이름만 남긴다.
    names = []
    for s in out:
        for key in MUST_MATCH + tuple(SPECIAL):
            if key in s and key not in names:
                names.append(key)
    return names


# ─────────────────────────────────────────────────────────────────
# 3. 비교표준지 선정
#
# 감정평가 실무기준(610-1.5.2.1)의 순서다: ① 용도지역·지구가 같고
# ② 이용상황이 같고 ③ 주위환경이 비슷하고 ④ 가까운 것. 평가서 41건에서
# 용도지역은 41/41, 지목군은 39/41 일치했고 도로접면은 20/41 이 달랐다
# — 도로접면은 격차율로 메우는 항목이지 선정 조건이 아니다.
# ─────────────────────────────────────────────────────────────────

def _grade_of_road(text) -> int | None:
    from .usage import road_grade
    return road_grade(text)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0088
    p = math.pi / 180
    d_lat = (lat2 - lat1) * p
    d_lon = (lon2 - lon1) * p
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(d_lon / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def pick_standard(subject: dict, candidates: list[dict], top: int = 3) -> list[dict]:
    """후보 표준지에서 비교표준지를 고른다. 점수가 낮을수록 좋다.

    점수 = 거리(km) + 불일치 벌점.  벌점은 '그만큼 먼 것과 같다' 로
    읽는다: 도로접면 한 단 0.3km, 형상 다름 0.2km, 지세 한 단 0.3km,
    이용상황 다름 0.5km, 읍면동 다름 1.0km.

    용도지역군과 MUST_MATCH 구역은 **거른다** (벌점이 아니다). 그것이
    다른 표준지는 아무리 가까워도 후보가 아니다.
    """
    zg = zone_group(subject.get("land_use"))
    ug = use_group(subject.get("jimok"), subject.get("use_situation"))
    zs = set(_zone_names(subject))
    lat, lon = subject.get("lat"), subject.get("lon")
    umd = str(subject.get("pnu") or "")[:10]
    rows = []
    for c in candidates:
        if zg and zone_group(c.get("land_use")) != zg:
            continue
        zc = set(_zone_names(c))
        if any((n in zs) != (n in zc) for n in STD_KNOWN):
            continue
        # 같은 용도지역군 안에서도 세분(계획관리/생산관리)이 다르면 거른다.
        if subject.get("land_use") and c.get("land_use") \
                and str(subject["land_use"])[:4] != str(c["land_use"])[:4]:
            continue
        pen = 0.0
        why = []
        if ug and use_group(c.get("jimok"), c.get("use_situation")) != ug:
            pen += 0.5
            why.append("지목군 다름")
        g1, g2 = _grade_of_road(subject.get("road_side")), _grade_of_road(c.get("road_side"))
        if g1 is not None and g2 is not None and g1 != g2:
            pen += 0.3 * abs(g1 - g2)
            why.append(f"도로접면 {abs(g1 - g2)}단 차")
        if subject.get("shape") and c.get("shape") \
                and shape_index(subject["shape"]) != shape_index(c["shape"]):
            pen += 0.2
            why.append("형상 다름")
        s1 = slope_index(subject.get("slope"), "*")
        s2 = slope_index(c.get("slope"), "*")
        if s1 is not None and s2 is not None and s1 != s2:
            pen += 0.3
            why.append("지세 다름")
        if umd and str(c.get("pnu") or "")[:10] != umd:
            pen += 1.0
            why.append("다른 읍면동")
        dist = None
        if lat is not None and lon is not None and c.get("lat") is not None:
            dist = haversine_km(float(lat), float(lon), float(c["lat"]), float(c["lon"]))
        score = (dist or 0.0) + pen
        rows.append({**c, "distance_km": None if dist is None else round(dist, 3),
                     "penalty": round(pen, 2), "score": round(score, 3),
                     "why": ", ".join(why) or "조건 일치"})
    rows.sort(key=lambda r: r["score"])
    return rows[:top]


# ─────────────────────────────────────────────────────────────────
# 4. 시점수정
#
# 표준지 공시기준일(매년 1월 1일) → 가격시점. 평가서는 한국부동산원
# 월간 지가변동률(시군구·용도지역별)을 누계로 곱했고 값은 1.000~1.017
# 이었다. 월별 변동률이 오면 그것을 쓰고, 없으면 또래 연간 추세를
# 달수로 환산하되 **어디서 온 값인지 적는다.**
# ─────────────────────────────────────────────────────────────────

def time_factor(base_date: dt.date, at: dt.date,
                monthly_rates: list[float] | None = None,
                annual_trend: float | None = None) -> dict:
    months = (at.year - base_date.year) * 12 + (at.month - base_date.month) \
        + (at.day - base_date.day) / 30.0
    months = max(0.0, months)
    if monthly_rates:
        f = 1.0
        for r in monthly_rates:
            f *= 1.0 + float(r) / 100.0
        return {"factor": round(f, 5), "months": round(months, 1),
                "source": f"지가변동률 {len(monthly_rates)}개월 누계"}
    if annual_trend is not None:
        f = (1.0 + float(annual_trend)) ** (months / 12.0)
        # 평가서 관측 범위(1.000~1.017) 밖으로는 안 나간다 — 추세는
        # 실거래 중앙값의 움직임이라 공시지가 변동률보다 거칠다.
        f = min(1.03, max(0.98, f))
        return {"factor": round(f, 5), "months": round(months, 1),
                "source": "또래 실거래 추세로 대신함 (지가변동률 자료 없음)"}
    return {"factor": None, "months": round(months, 1), "source": "자료 없음"}


# ─────────────────────────────────────────────────────────────────
# 5. 그 밖의 요인
#
# 두 갈래를 다 적고 하나로 결정한다 — 평가서가 그렇게 한다.
#   평가선례 기준: 원장(ledger.tsv)의 f_other.  (시군구 → 시도 → 전국)
#   거래사례 기준: 우리 실거래 DB 의 실거래단가 ÷ 개별공시지가 중앙값.
#     검산: 원장 39건의 (결정단가 ÷ 개별공시지가) 중앙 2.3 = f_other
#     중앙 2.3 — 개별요인 중앙이 1.0 이라 두 자가 같은 것을 가리킨다.
# ─────────────────────────────────────────────────────────────────

MIN_CELL = 3


def load_ledger(path: Path = LEDGER) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def ledger_other_factor(sido: str | None, sigungu: str | None,
                        land_use: str | None, jimok: str | None,
                        use_situation: str | None = None,
                        rows: list[dict] | None = None) -> dict:
    """평가선례 기준 그 밖의 요인. 물러난 단계를 함께 돌려준다."""
    rows = rows if rows is not None else load_ledger()
    zg = zone_group(land_use)
    ug = use_group(jimok, use_situation)
    pool = [(r, _num(r.get("f_other"))) for r in rows]
    pool = [(r, v) for r, v in pool if v]

    def cell(pred, level):
        vals = sorted(v for r, v in pool if pred(r))
        if len(vals) < MIN_CELL:
            return None
        return {"median": round(statistics.median(vals), 2),
                "q1": round(vals[len(vals) // 4], 2),
                "q3": round(vals[(3 * len(vals)) // 4], 2),
                "n": len(vals), "level": level}

    def zg_of(r):
        return zone_group(r.get("land_use"))

    def ug_of(r):
        return use_group(r.get("jimok"), r.get("use_situation"))

    tries = []
    if sigungu:
        tries.append((lambda r: r.get("sigungu", "").startswith(sigungu[:3])
                      and zg_of(r) == zg and ug_of(r) == ug, "같은 시군구 · 용도지역군 · 지목군"))
    if sido:
        tries.append((lambda r: r.get("sido") == sido and zg_of(r) == zg and ug_of(r) == ug,
                      "같은 시·도 · 용도지역군 · 지목군"))
    tries.append((lambda r: zg_of(r) == zg and ug_of(r) == ug, "전국 · 용도지역군 · 지목군"))
    tries.append((lambda r: zg_of(r) == zg, "전국 · 용도지역군"))
    tries.append((lambda r: True, "전국 전체"))
    for pred, level in tries:
        got = cell(pred, level)
        if got:
            got["source"] = "평가선례"
            return got
    return {"median": None, "n": 0, "level": None, "source": "평가선례"}


TRADE_OTHER_SQL = """
-- 거래사례 기준 그 밖의 요인: 실거래단가 ÷ 개별공시지가.
-- 최근 3년, 취소 제외, 필지 특성이 붙은 거래만. 10~90% 를 잘라
-- 한두 건의 이상치가 중앙값 밖의 사분위를 흔들지 않게 한다.
WITH r AS (
    SELECT t.sigungu_cd,
           CASE {zone_case} ELSE NULL END AS zg,
           CASE
             WHEN pc.jimok = '임야' THEN '임야'
             WHEN pc.jimok IN ('전','답','과수원','목장용지') THEN '전·답'
             WHEN pc.jimok = '대' THEN '대'
             WHEN pc.jimok IN ('공장용지','도로','잡종지','창고용지','주차장') THEN '공장·도로'
             ELSE NULL END AS ug,
           t.price_per_m2 / pc.official_price AS ratio
    FROM trade t
    JOIN trade_parcel tp ON tp.trade_id = t.trade_id
    JOIN parcel pc ON pc.pnu = tp.pnu
    WHERE t.kind = 'land'
      AND NOT coalesce(t.is_cancelled, FALSE)
      AND t.price_per_m2 > 0 AND pc.official_price > 0
      AND t.deal_year >= {from_year}
)
SELECT sigungu_cd, zg, ug,
       count(*) AS n,
       quantile_cont(ratio, 0.5) AS median,
       quantile_cont(ratio, 0.25) AS q1,
       quantile_cont(ratio, 0.75) AS q3
FROM r
WHERE zg IS NOT NULL AND ug IS NOT NULL
  AND ratio BETWEEN 0.3 AND 20
GROUP BY 1, 2, 3
HAVING count(*) >= 10
"""


def trade_other_factor(con, groups: list[tuple[str, str]], years: int = 3) -> dict:
    """거래사례 기준 그 밖의 요인을 (시군구|용도지역군|지목군) 열쇠로 만든다.

    groups 는 (용도지역군 이름, LIKE 조각) 목록이다. **이 저장소의
    실행 환경에는 DB 가 없어 여기서 돌려 보지 못했다** — SQL 은
    parcelscore.build 와 같은 표·같은 조인을 쓴다.
    """
    case = " ".join(f"WHEN t.land_use LIKE '%{like}%' THEN '{name}'" for name, like in groups)
    from_year = dt.date.today().year - years
    df = con.execute(TRADE_OTHER_SQL.format(zone_case=case, from_year=from_year)).fetchdf()
    out = {}
    for r in df.itertuples(index=False):
        out[f"{r.sigungu_cd}|{r.zg}|{r.ug}"] = {
            "median": round(float(r.median), 2), "q1": round(float(r.q1), 2),
            "q3": round(float(r.q3), 2), "n": int(r.n), "source": "거래사례",
        }
    return out


def decide_other(ledger: dict | None, trade: dict | None) -> dict:
    """두 갈래에서 하나를 정한다.

    둘 다 있으면 건수로 가중한 기하평균 — 거래사례가 수십 건이면 그쪽이
    이기고, 평가선례 셋뿐이면 거의 안 움직인다. 한쪽뿐이면 그것.
    범위는 있는 쪽의 사분위를 그대로 쓴다.
    """
    have = [s for s in (ledger, trade) if s and s.get("median")]
    if not have:
        return {"factor": None, "q1": None, "q3": None, "basis": "자료 없음", "sources": []}
    if len(have) == 1:
        s = have[0]
        return {"factor": s["median"], "q1": s.get("q1"), "q3": s.get("q3"),
                "basis": f"{s['source']} 기준 (n={s['n']}, {s.get('level') or '시군구'})",
                "sources": have}
    w = [min(float(s["n"]), 30.0) for s in have]
    lg = sum(wi * math.log(s["median"]) for wi, s in zip(w, have)) / sum(w)
    f = math.exp(lg)
    q1 = min(s.get("q1") or f for s in have)
    q3 = max(s.get("q3") or f for s in have)
    return {"factor": round(f, 2), "q1": round(q1, 2), "q3": round(q3, 2),
            "basis": " · ".join(f"{s['source']} {s['median']} (n={s['n']})" for s in have)
            + " → 건수 가중 기하평균",
            "sources": have}


# ─────────────────────────────────────────────────────────────────
# 6. 산출·결정
# ─────────────────────────────────────────────────────────────────

def round_decided(x: float) -> int:
    """평가서의 결정단가 자리수. 1만 원 아래는 100원, 100만 원 아래는
    1,000원, 그 위는 10,000원 단위 — 원장 44건이 이 규칙을 따랐다
    (예외 1건 3,294,000)."""
    if x < 10_000:
        unit = 100
    elif x < 1_000_000:
        unit = 1_000
    else:
        unit = 10_000
    return int(round(x / unit) * unit)


def appraise(subject: dict, std: dict, at: dt.date | None = None,
             time: dict | None = None, other: dict | None = None) -> dict:
    """다섯 마디를 곱해 산출표를 만든다.

    std 에는 표준지 공시지가 price 와 공시기준일 base_date(YYYY-MM-DD)
    가 있어야 한다. time·other 를 안 주면 원장으로 그 밖의 요인을 찾고
    시점수정은 '자료 없음' 으로 비운다.
    """
    at = at or dt.date.today()
    price = _num(std.get("price"))
    base = std.get("base_date")
    base_date = dt.date.fromisoformat(str(base)) if base else dt.date(at.year, 1, 1)
    t = time or time_factor(base_date, at)
    indiv = individual_factor(subject, std)
    if other is None:
        led = ledger_other_factor(subject.get("sido"), subject.get("sigungu"),
                                  subject.get("land_use"), subject.get("jimok"),
                                  subject.get("use_situation"))
        other = decide_other(led, None)

    parts = {
        "표준지공시지가": price,
        "시점수정": t.get("factor"),
        "지역요인": 1.0,
        "개별요인": indiv["factor"],
        "그 밖의 요인": other.get("factor"),
    }
    missing = [k for k, v in parts.items() if v is None]
    unit = None
    decided = None
    total = None
    lo = hi = None
    if not missing:
        unit = price * t["factor"] * 1.0 * indiv["factor"] * other["factor"]
        decided = round_decided(unit)
        area = _num(subject.get("area_m2"))
        total = int(decided * area) if area else None
        if other.get("q1") and other.get("q3"):
            lo = round_decided(price * t["factor"] * indiv["factor"] * other["q1"])
            hi = round_decided(price * t["factor"] * indiv["factor"] * other["q3"])
    return {
        "at": at.isoformat(),
        "std": {k: std.get(k) for k in ("pnu", "label", "land_use", "jimok", "use_situation",
                                         "road_side", "shape", "slope", "area_m2",
                                         "price", "base_date", "distance_km")},
        "time": t,
        "region": {"factor": 1.0, "why": "같은 인근지역에서 표준지를 골랐다 (평가서 41/41 이 1.00)"},
        "individual": indiv,
        "other": other,
        "parts": parts,
        "missing": missing,
        "unit_calc": None if unit is None else round(unit),
        "unit_decided": decided,
        "range": None if lo is None else [lo, hi],
        "total_krw": total,
        "warnings": indiv["warnings"],
    }


def render(result: dict) -> str:
    """평가서 산출표 꼴의 글. 화면·CLI 가 같은 것을 보여준다."""
    won = lambda v: "—" if v is None else f"{v:,.0f}"
    s = result["std"]
    lines = ["현재 가치 (공시지가기준법)"]
    lines.append(f"  가격시점    {result['at']}")
    lines.append("  비교표준지  " + " · ".join(str(x) for x in (
        s.get("label") or s.get("pnu"), s.get("land_use"), s.get("jimok") or s.get("use_situation"),
        s.get("road_side"), s.get("shape"), s.get("slope")) if x)
        + f" · 공시 {won(_num(s.get('price')))}원/㎡"
        + (f" ({s['base_date']})" if s.get("base_date") else "")
        + (f" · {s['distance_km']}km" if s.get("distance_km") is not None else ""))
    t = result["time"]
    lines.append(f"  시점수정    {t['factor'] if t['factor'] is not None else '(자료 없음)'}"
                 f"   {t['source']}" + (f" · {t['months']}개월" if t.get("months") else ""))
    lines.append(f"  지역요인    1.000   {result['region']['why']}")
    ind = result["individual"]
    lines.append(f"  개별요인    {ind['factor']:.3f}   [{ind['kind']}]")
    for it in ind["items"]:
        r = "—" if it["ratio"] is None else f"{it['ratio']:.3f}"
        lines.append(f"      {it['cond']:<18s} {str(it['subject'] or '—'):<12s}"
                     f" / {str(it['std'] or '—'):<12s} × {r}"
                     + (f"   {it['why']}" if it.get("why") else ""))
    o = result["other"]
    lines.append(f"  그 밖의 요인 {o['factor'] if o.get('factor') else '(자료 없음)'}   {o.get('basis', '')}")
    if result["missing"]:
        lines.append(f"  산출 보류 — 비어 있는 마디: {', '.join(result['missing'])}")
    else:
        p = result["parts"]
        lines.append(f"  산출단가    {won(p['표준지공시지가'])} × {p['시점수정']} × 1.000 × "
                     f"{p['개별요인']} × {p['그 밖의 요인']} = {won(result['unit_calc'])}원/㎡")
        lines.append(f"  결정단가    {won(result['unit_decided'])}원/㎡"
                     + (f"   (흔히 {won(result['range'][0])}~{won(result['range'][1])})"
                        if result.get("range") else ""))
        if result.get("total_krw"):
            lines.append(f"  총액        {won(result['total_krw'])}원")
    for w in result["warnings"]:
        lines.append(f"  ! {w}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# 6-b. 화면용 표 — 격차율 표와 그 밖의 요인을 JSON 하나로
#
# 화면(app.js)은 산식만 옮기고 **숫자는 이 표에서 읽는다.** 표가 두 곳에
# 있으면 언젠가 어긋난다. 그 밖의 요인은 원장에서 (시도 → 전국) 으로
# 물러난 값을 용도지역군 × 지목군마다 미리 계산해 둔다.
# ─────────────────────────────────────────────────────────────────

SIDO_NAMES = {"11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주", "30": "대전",
              "31": "울산", "36": "세종", "41": "경기", "43": "충북", "44": "충남", "45": "전북",
              "46": "전남", "47": "경북", "48": "경남", "50": "제주", "51": "강원", "52": "전북"}


def tables_for_web() -> dict:
    rows = load_ledger()
    zones = [z for z, _ in ZONE_GROUPS]
    uses = [u for u, _ in USE_GROUPS]
    other = {}
    for zg in zones:
        for ug in uses:
            # 대표 용도지역·지목 문자열로 조회한다 (그룹 이름이 부분 문자열).
            key = f"{zg}|{ug}"
            other[key] = {"*": ledger_other_factor(None, None, zg, None, ug, rows)}
            for code, name in SIDO_NAMES.items():
                got = ledger_other_factor(name, None, zg, None, ug, rows)
                if got.get("level", "").startswith("같은 시·도"):
                    other[key][code] = got
    return {
        "road_index": ROAD_INDEX, "road_corner_bonus": ROAD_CORNER_BONUS,
        "shape_index": SHAPE_INDEX, "slope_index": SLOPE_INDEX,
        "use_mismatch": {f"{a}|{b}": v for (a, b), v in USE_MISMATCH.items()},
        "special": SPECIAL, "must_match": list(MUST_MATCH), "std_known": list(STD_KNOWN),
        "area_rules": {k: [[lo, (None if hi == math.inf else hi), r, why] for lo, hi, r, why in v]
                       for k, v in AREA_RULES.items()},
        "other": other,
        "time_clamp": [0.98, 1.03],
        "zone_groups": ZONE_GROUPS, "use_groups": USE_GROUPS,
        "ledger_n": len(rows),
    }


# ─────────────────────────────────────────────────────────────────
# 7. 검산 — 원장 41건에 격차율 표를 대입해 평가사 값과 견준다
# ─────────────────────────────────────────────────────────────────

def check_ledger(rows: list[dict] | None = None) -> dict:
    """개별요인 표를 평가서와 견준다.

    원장에는 표준지의 도로접면·형상만 있고 지세가 없다. 그래서 여기서는
    도로·형상·지목군만 대입한다 — 지세 격차가 든 건은 그만큼 벗어난다.
    """
    rows = rows if rows is not None else load_ledger()
    out = []
    for r in rows:
        obs = _num(r.get("f_indiv"))
        if not obs:
            continue
        use = r.get("use_situation") or ""
        if "도로" in use and "현황" in use:
            continue        # 특례 0.33 — 표가 아니라 규칙이 정한다
        subject = {"land_use": r.get("land_use"), "jimok": r.get("jimok"),
                   "use_situation": use, "road_side": r.get("road"),
                   "shape": r.get("shape")}
        std = {"road_side": r.get("std_road"), "shape": r.get("std_shape"),
               "jimok": r.get("jimok")}
        got = individual_factor(subject, std)
        out.append({"file_id": r.get("file_id"), "sigungu": r.get("sigungu"),
                    "use": use, "obs": obs, "pred": got["factor"],
                    "ratio": round(got["factor"] / obs, 3)})
    ratios = sorted(o["ratio"] for o in out)
    n = len(ratios)
    return {
        "n": n,
        "median": round(statistics.median(ratios), 3) if n else None,
        "within_10": sum(1 for x in ratios if 0.9 <= x <= 1.1),
        "within_15": sum(1 for x in ratios if 0.85 <= x <= 1.15),
        "rows": out,
    }
