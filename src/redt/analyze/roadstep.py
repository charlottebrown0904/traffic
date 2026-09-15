"""필지 층 첫 칸 — **도로가 붙으면 얼마나 오르는가** (2026-09-15).

미래 가치의 필지 층(docs/future-value.md §3-3)에서 가장 잘 재지는 항목이다.
용도지역 변경·규제 해제는 고시를 읽어야 하지만, 도로 접면은 우리가 이미
전국 필지에 갖고 있다(`parcel.road_side`). 그리고 그 한 계단이 이 서비스의
출발점이었다 — "도로를 접하는 가가 제일 중요합니다" (2026-09-07).

**우리에게 사다리가 이미 둘 있다.** 그런데 둘 다 거래에서 나온 것이 아니다.

  valuation.ROAD_INDEX   감정평가서 원장에서 읽은 격차율 (맹지 .80 · 소로 1.10)
  bijunpyo_index()       관이 만든 토지가격비준표

셋째를 만든다: **우리 실거래로 잰 사다리.** 세 개를 나란히 놓으면 '평가사가
그렇게 본다' 와 '시장이 그렇게 값을 매긴다' 가 갈린다.

왜 헤도닉(transform.panel)의 계수를 그대로 못 쓰는가. 그쪽은 도로접면을
`C(road_side)` 로 넣는데 결측을 'NA' 로 채우고, patsy 가 그 'NA' 를 기준
수준으로 잡는다. 그래서 찍히는 '맹지 +3.2%' 는 **조사 안 된 땅 대비**다 —
사다리의 기준으로 쓸 수 없는 값이다. 여기서는 기준을 맹지로 못박고,
등급을 모르는 건은 **섞지 않고 버린다**.

식

    ln(단가) = α + Σ δ_g·1[등급=g] + 각지 + ln면적
               + C(지목) + C(용도지역) + 시군구FE + 연도FE
    배율(g) = exp(δ_g)                     기준 g=0 (맹지)

등급은 **범주**다. 선형으로 넣지 않는다 — 실측에서 중로가 광대로보다
비쌌고 맹지가 세로(불)보다 비쌌다(usage.py 주석). 큰길이 늘 좋은 것은
아니다. 순서를 강요하면 그 뒤집힘이 직선에 묻힌다.

**미래 가치에 쓰는 것은 계단 하나다** — 맹지에서 차가 들어오는 길에 붙을
때의 배율. 그것이 도로 개설로 실제로 일어나는 변화이고, 나머지 계단은
같은 표에서 참고로 읽는다.
"""
from __future__ import annotations

import math

import pandas as pd

from ..usage import ROAD_NARROW_OK, is_corner, road_grade

# 등급 이름 — 화면과 표에 그대로 쓴다. usage.ROAD_GRADE 와 같은 뜻이다.
GRADE_NAME = {0: "맹지", 1: "세로(불)", 2: "세로(가)", 3: "소로",
              4: "중로", 5: "광대로"}
BASE_GRADE = 0                  # 기준 = 맹지
MIN_LEVEL_N = 300               # 이만큼 안 되는 등급은 계수를 안 적는다
FIT_MAX = 300_000               # 러너 메모리 — 시군구 더미가 빽빽이 펴진다


def prepare(trades: pd.DataFrame) -> pd.DataFrame:
    """거래표 → 등급이 붙은 표본. **등급을 모르는 건은 버린다.**

    맹지와 한 칸에 섞으면 '도로가 없는 땅' 과 '조사가 안 된 땅' 이 같아진다
    (usage.road_grade 주석). 기준 등급이 오염되면 사다리 전체가 틀어진다.
    """
    need = {"price_per_m2", "area_m2", "road_side"}
    if trades is None or len(trades) == 0 or not need.issubset(trades.columns):
        return pd.DataFrame()
    df = pd.DataFrame(trades).copy()
    df = df[(pd.to_numeric(df["price_per_m2"], errors="coerce") > 0)
            & (pd.to_numeric(df["area_m2"], errors="coerce") > 0)]
    if df.empty:
        return pd.DataFrame()
    df["grade"] = df["road_side"].map(road_grade)
    df = df[df["grade"].notna()].copy()
    if df.empty:
        return df
    df["grade"] = df["grade"].astype(int)
    df["ln_price"] = pd.to_numeric(df["price_per_m2"]).map(math.log)
    df["ln_area"] = pd.to_numeric(df["area_m2"]).map(math.log)
    df["corner"] = df["road_side"].map(is_corner).fillna(0).astype(int)
    for col in ("jimok", "land_use", "sigungu_cd"):
        if col in df:
            df[col] = df[col].fillna("NA").replace("", "NA").astype(str)
    return df


def formula(df: pd.DataFrame) -> str:
    terms = [f"C(grade, Treatment(reference={BASE_GRADE}))", "ln_area"]
    if "corner" in df and df["corner"].nunique() > 1:
        terms.append("corner")
    for col in ("jimok", "land_use", "sigungu_cd", "deal_year"):
        if col in df and df[col].nunique() > 1:
            terms.append(f"C({col})")
    return "ln_price ~ " + " + ".join(terms)


def fit(df: pd.DataFrame, fit_max: int = FIT_MAX, seed: int = 20260915):
    """적합. 표준오차는 시군구로 묶는다 (같은 군의 필지는 서로 닮는다)."""
    import statsmodels.formula.api as smf              # noqa: PLC0415
    if df.empty or df["grade"].nunique() < 2:
        return None
    use = df if len(df) <= fit_max else df.sample(fit_max, random_state=seed)
    groups = use["sigungu_cd"] if "sigungu_cd" in use else pd.Series("?", index=use.index)
    return smf.ols(formula(use), data=use).fit(
        cov_type="cluster", cov_kwds={"groups": groups})


def ladder(df: pd.DataFrame, res) -> pd.DataFrame:
    """등급별 배율 표. 기준(맹지)은 1.00 으로 적는다."""
    if res is None or df.empty:
        return pd.DataFrame()
    counts = df["grade"].value_counts().to_dict()
    rows = []
    for g in sorted(GRADE_NAME):
        n = int(counts.get(g, 0))
        if not n:
            continue
        if g == BASE_GRADE:
            rows.append({"등급": GRADE_NAME[g], "grade": g, "n": n, "배율": 1.0,
                         "p": None, "낮": 1.0, "높": 1.0, "기준": True,
                         "얇음": n < MIN_LEVEL_N})
            continue
        key = next((t for t in res.params.index
                    if t.startswith("C(grade") and t.endswith(f"[T.{g}]")), None)
        if key is None:
            continue
        b, se = float(res.params[key]), float(res.bse[key])
        rows.append({"등급": GRADE_NAME[g], "grade": g, "n": n,
                     "배율": round(math.exp(b), 3),
                     "p": round(float(res.pvalues[key]), 4),
                     "낮": round(math.exp(b - 1.96 * se), 3),
                     "높": round(math.exp(b + 1.96 * se), 3),
                     "기준": False, "얇음": n < MIN_LEVEL_N})
    return pd.DataFrame(rows)


def car_step(tab: pd.DataFrame) -> dict:
    """**미래 가치에 쓰는 계단** — 맹지 → 차가 들어오는 길.

    도로 개설로 실제로 일어나는 변화가 이것이다. 차 진입 가능한 등급
    (세로(가) 이상) 가운데 **가장 낮은 것**을 쓴다 — 길이 하나 나면 대개
    세로나 소로가 붙고, 광대로가 붙는다고 가정하면 부풀린 셈이 된다.
    """
    if tab.empty:
        return {"ok": False, "why": "표가 비었습니다"}
    ok = tab[(tab["grade"] >= ROAD_NARROW_OK) & (~tab["얇음"]) & (~tab["기준"])]
    if ok.empty:
        return {"ok": False, "why": f"차 진입 가능한 등급에 거래가 {MIN_LEVEL_N}건 이상인 칸이 없습니다"}
    row = ok.sort_values("grade").iloc[0]
    if row["p"] is None or float(row["p"]) >= 0.05:
        return {"ok": False, "why": f"{row['등급']} 계수가 맹지와 안 갈립니다 (p={row['p']})"}
    if float(row["배율"]) <= 1.0:
        return {"ok": False, "why": f"{row['등급']}가 맹지보다 안 비쌉니다 (×{row['배율']})"}
    return {"ok": True, "등급": row["등급"], "배율": float(row["배율"]),
            "낮": float(row["낮"]), "높": float(row["높"]),
            "n": int(row["n"]), "p": float(row["p"]),
            "why": f"맹지 → {row['등급']} ×{row['배율']}"
                   f" (95% {row['낮']}~{row['높']}, n={int(row['n']):,})"}


def verdict(df: pd.DataFrame, tab: pd.DataFrame) -> tuple[bool, str]:
    """이 사다리로 값을 말할 수 있는가. **못 하는 쪽이 기본이다.**"""
    if tab.empty:
        return False, "계수를 못 세웠습니다"
    base = tab[tab["기준"]]
    if base.empty:
        return False, "기준(맹지) 칸이 없습니다"
    if bool(base.iloc[0]["얇음"]):
        return False, (f"기준(맹지) 거래가 {int(base.iloc[0]['n']):,}건뿐입니다"
                       f" — {MIN_LEVEL_N}건은 있어야 합니다")
    step = car_step(tab)
    return bool(step["ok"]), step["why"]


# ── 우리 값 옆에 놓을 두 사다리 ────────────────────────────────────
#
# 셋을 나란히 보는 것이 이 표의 요점이다. 어느 하나를 '맞다' 고 고르는
# 것이 아니라, **얼마나 떨어져 있는지**를 사람이 보게 한다.
def reference_ladders() -> dict:
    from .. import valuation as V                      # noqa: PLC0415
    road = dict(V.ROAD_INDEX)
    # ROAD_INDEX 는 글자 조각 → 배율이다. 등급 이름으로 옮겨 적는다.
    appraisal = {
        "맹지": road.get("맹지"),
        "세로(불)": road.get("(불)"),
        "세로(가)": road.get("(가)"),
        "소로": road.get("소로"),
        "중로": road.get("중로"),
        "광대로": road.get("광대"),
    }
    # 비준표는 {'rows': {'도로접면': [[이름, 배율], ...]}} 모양이다.
    # 이름이 우리 등급보다 잘게 갈려 있어(광대한면·광대소각·…) 등급으로
    # 접는다 — 같은 등급 안에서는 한면 것을 쓴다 (각지 보너스는 따로다).
    bj = V.bijunpyo_index() or {}
    raw = dict((bj.get("rows") or {}).get("도로접면") or [])
    pick = lambda *names: next((raw[n] for n in names if n in raw), None)
    bijunpyo = {
        "맹지": pick("맹지"),
        "세로(불)": pick("세로(불)"),
        "세로(가)": pick("세로(가)"),
        "소로": pick("소로한면"),
        "중로": pick("중로한면"),
        "광대로": pick("광대한면", "광대로한면"),
    }
    return {"평가서 원장": appraisal, "비준표": bijunpyo,
            "비준표 출처": bj.get("source") or ""}


def compare(tab: pd.DataFrame) -> pd.DataFrame:
    """세 사다리를 **맹지=1.00 으로 다시 맞춰** 한 표에 놓는다.

    관의 두 표는 세로(가)를 1.00 으로 둔다. 우리 것은 맹지가 기준이다.
    기준이 다른 숫자를 나란히 적으면 읽는 사람이 반드시 잘못 읽는다 —
    셋 다 맹지로 나눠 '맹지에서 몇 배' 로 통일한다.
    """
    refs = reference_ladders()
    rows = []
    for g in sorted(GRADE_NAME):
        name = GRADE_NAME[g]
        row = {"등급": name}
        hit = tab[tab["등급"] == name] if not tab.empty else tab
        row["우리 실거래"] = (None if hit.empty or bool(hit.iloc[0]["얇음"])
                              else float(hit.iloc[0]["배율"]))
        for label in ("평가서 원장", "비준표"):
            tbl = refs.get(label) or {}
            base, v = tbl.get("맹지"), tbl.get(name)
            row[label] = round(v / base, 3) if base and v else None
        rows.append(row)
    return pd.DataFrame(rows)
