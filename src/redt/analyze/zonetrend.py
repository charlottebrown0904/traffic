"""우리 세 땅의 **지역별** 가격 추이 — 전국 평균을 내지 않는다.

2026-09-15 지시: "우리가 집중하려는 생산관리, 계획관리, 자연녹지 지역에
대한 가격 추이에 집중해 주시고, 전국으로 넓혀서 검토하는 것은 지양바랍니다.
**지역적 상승이 크다고 생각합니다.**"

## 왜 이 지시가 맞는가 — 앞선 판이 실패한 이유가 여기 있다

run 124 에서 예측이 기준선을 못 넘었는데, 기준점 27개 중 거의 전부에서
방향 적중이 늘오름과 **소수점까지 같았다**. 모형이 255개 시군구 전부에
같은 방향을 말하고 있었다는 뜻이다. 전국을 한 덩어리로 평균 낸 탓이다.

게다가 그 땅값 칸은 **모든 용도지역을 섞은 것**이었다. 한 시군구의
중앙 단가에 주거·상업·공업이 함께 들어가면, 해마다 어느 쪽이 더 팔렸나에
따라 중앙값이 움직인다 — 땅값이 아니라 **팔린 물건의 구성**이 움직이는
것이다. 그것을 놓고 예측을 겨뤘으니 이길 수가 없었다.

그래서 여기서는 둘 다 바꾼다.

    ① 세 용도지역만 본다 (생산관리 · 계획관리 · 자연녹지)
    ② 시군구를 **평균하지 않는다** — 흩어짐과 분위수로 말한다

## 무엇을 묻나

    흩어짐   같은 해에 시군구끼리 단가가 얼마나 다른가
    상승     10년 누적 배율이 시군구마다 얼마나 다른가 (지시의 그 물음)
    지속성   **앞 5년 많이 오른 곳이 뒤 2년에도 오르는가**

셋째가 이 표의 값어치다. 지역차가 크기만 하고 **이어지지 않으면** 미래를
못 말한다 — 지난 10년 많이 오른 곳을 짚어 봐야 다음 2년과 무관하기
때문이다. 이어져야 비로소 "어디가 오를 것이다" 를 말할 수 있다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

ZONES = ("생산관리", "계획관리", "자연녹지")
MIN_CELL = 5         # 시군구 × 용도지역 × 연 칸에 이만큼은 있어야 센다
MIN_SGG_YEAR = 20    # 한 해에 시군구가 이만큼은 있어야 흩어짐을 적는다
LOOK, HORIZON = 5, 2 # 앞 5년을 보고 뒤 2년을 묻는다


def pick_zone(land_use, zones=ZONES) -> str | None:
    """`land_use` 글자에서 우리 세 땅을 골라낸다.

    **군으로 뭉치지 않는다.** 생산관리와 계획관리는 건폐율·용적률도
    다르고 팔리는 값도 다르다 — '관리' 로 합치면 그 차이가 지워진다.
    """
    s = str(land_use or "")
    for z in zones:
        if z in s:
            return z
    return None


def panel(trades: pd.DataFrame, zones=ZONES, min_n: int = MIN_CELL) -> pd.DataFrame:
    """시군구 × 용도지역 × 연 중앙 ln 단가. 칸이 얇으면 버린다."""
    need = {"sigungu_cd", "deal_year", "price_per_m2", "land_use"}
    if trades is None or len(trades) == 0 or not need.issubset(trades.columns):
        return pd.DataFrame(columns=["sigungu_cd", "zone", "year", "ln_price", "n"])
    t = pd.DataFrame(trades).copy()
    t["zone"] = t["land_use"].map(lambda v: pick_zone(v, zones))
    t = t[t["zone"].notna()]
    t = t[pd.to_numeric(t["price_per_m2"], errors="coerce") > 0]
    if t.empty:
        return pd.DataFrame(columns=["sigungu_cd", "zone", "year", "ln_price", "n"])
    t["ln_price"] = pd.to_numeric(t["price_per_m2"]).map(math.log)
    g = (t.groupby(["sigungu_cd", "zone", "deal_year"])
         .agg(ln_price=("ln_price", "median"), n=("ln_price", "size")).reset_index())
    g = g[g["n"] >= min_n].rename(columns={"deal_year": "year"})
    return g.sort_values(["zone", "sigungu_cd", "year"])


def coverage(pan: pd.DataFrame) -> pd.DataFrame:
    """용도지역마다 시군구 몇 곳 · 몇 해 · 거래 몇 건. **재기 전에 이 표다.**"""
    if pan.empty:
        return pd.DataFrame()
    g = (pan.groupby("zone")
         .agg(시군구=("sigungu_cd", "nunique"), 칸=("ln_price", "size"),
              거래=("n", "sum"), 처음=("year", "min"), 끝=("year", "max"))
         .reset_index())
    return g.sort_values("칸", ascending=False)


def spread(pan: pd.DataFrame) -> pd.DataFrame:
    """해마다 **시군구끼리** 단가가 얼마나 다른가. 평균 한 줄로 안 접는다."""
    if pan.empty:
        return pd.DataFrame()
    rows = []
    for (z, y), blk in pan.groupby(["zone", "year"]):
        if len(blk) < MIN_SGG_YEAR:
            continue
        v = np.exp(blk["ln_price"].to_numpy())        # 원/㎡ 로 되돌려 읽기 쉽게
        q10, q50, q90 = (float(np.quantile(v, q)) for q in (0.10, 0.50, 0.90))
        rows.append({"zone": z, "year": int(y), "시군구": int(len(blk)),
                     "하위10%": round(q10), "중앙": round(q50), "상위10%": round(q90),
                     "위아래 배": round(q90 / q10, 2) if q10 > 0 else None})
    return pd.DataFrame(rows).sort_values(["zone", "year"])


def growth(pan: pd.DataFrame, base: int, last: int) -> pd.DataFrame:
    """시군구마다 base→last 누적 배율. **지시의 그 물음이다.**

    두 해가 다 있는 시군구만 센다 — 한쪽이 없는 곳을 끼우면 그 배율은
    다른 기간의 것이 되어 견줄 수 없다.
    """
    if pan.empty:
        return pd.DataFrame()
    a = pan[pan["year"] == base][["sigungu_cd", "zone", "ln_price"]]
    b = pan[pan["year"] == last][["sigungu_cd", "zone", "ln_price"]]
    m = a.merge(b, on=["sigungu_cd", "zone"], suffixes=("_b", "_l"))
    if m.empty:
        return pd.DataFrame()
    m["배율"] = np.exp(m["ln_price_l"] - m["ln_price_b"]).round(3)
    return m[["sigungu_cd", "zone", "배율"]].sort_values(["zone", "배율"],
                                                       ascending=[True, False])


def growth_spread(gr: pd.DataFrame) -> pd.DataFrame:
    """누적 배율의 분위수. 위아래가 벌어져 있으면 지역차가 큰 것이다."""
    if gr is None or gr.empty:
        return pd.DataFrame()
    rows = []
    for z, blk in gr.groupby("zone"):
        v = blk["배율"].to_numpy()
        q = {p: float(np.quantile(v, p / 100)) for p in (10, 25, 50, 75, 90)}
        rows.append({"zone": z, "시군구": int(len(v)),
                     "10%": round(q[10], 2), "25%": round(q[25], 2),
                     "중앙": round(q[50], 2), "75%": round(q[75], 2),
                     "90%": round(q[90], 2),
                     "위아래 배": round(q[90] / q[10], 2) if q[10] > 0 else None,
                     "내린 곳": int(np.sum(v < 1.0)),
                     "두 배 넘은 곳": int(np.sum(v >= 2.0))})
    return pd.DataFrame(rows).sort_values("zone")


def persistence(pan: pd.DataFrame, look: int = LOOK, horizon: int = HORIZON) -> pd.DataFrame:
    """**앞 `look`년 많이 오른 곳이 뒤 `horizon`년에도 오르는가.**

    기준해 t 마다 시군구를 가로로 놓고, 지난 오름(t−look → t)과 앞으로의
    오름(t → t+horizon)의 상관을 잰다. 시점을 안 흘린다 — t 에 실제로 알
    수 있던 것만으로 순위를 매기고, 그 뒤를 본다.

    양(+)이면 오르던 곳이 계속 오른다(지역성이 이어진다), 음(−)이면
    되돌아온다(평균 회귀). 0 이면 지난 오름은 앞일에 대해 아무 말도 안 한다.
    """
    if pan.empty:
        return pd.DataFrame()
    piv = pan.pivot_table(index=["zone", "sigungu_cd"], columns="year",
                          values="ln_price")
    rows = []
    years = sorted(c for c in piv.columns)
    for z in piv.index.get_level_values(0).unique():
        sub = piv.loc[z]
        for t in years:
            if (t - look) not in sub.columns or (t + horizon) not in sub.columns:
                continue
            past = sub[t] - sub[t - look]
            fut = sub[t + horizon] - sub[t]
            ok = past.notna() & fut.notna()
            n = int(ok.sum())
            if n < MIN_SGG_YEAR or past[ok].std() == 0 or fut[ok].std() == 0:
                continue
            r = float(np.corrcoef(past[ok], fut[ok])[0, 1])
            rows.append({"zone": z, "기준해": int(t), "시군구": n,
                         "지난오름↔앞으로": round(r, 3),
                         "앞으로 중앙": round(float(np.median(fut[ok])), 4)})
    return pd.DataFrame(rows).sort_values(["zone", "기준해"])


def persistence_verdict(pr: pd.DataFrame) -> str:
    """문. **이어져야 '어디가 오를 것이다' 를 말할 수 있다.**"""
    if pr is None or pr.empty:
        return "산출 보류 — 지속성을 잴 칸이 모자랍니다"
    out = []
    for z, blk in pr.groupby("zone"):
        r = blk["지난오름↔앞으로"]
        mean_r = float(r.mean())
        pos = int((r > 0).sum())
        out.append(f"{z} 평균 r={mean_r:+.3f} (양수 {pos}/{len(r)}해)")
    return " · ".join(out)


def top_bottom(gr: pd.DataFrame, names: dict | None = None, k: int = 10) -> pd.DataFrame:
    """가장 오른 곳과 가장 안 오른 곳. **이름을 붙여 눈으로 보게 한다.**"""
    if gr is None or gr.empty:
        return pd.DataFrame()
    rows = []
    for z, blk in gr.groupby("zone"):
        b = blk.sort_values("배율", ascending=False)
        for tag, part in (("위", b.head(k)), ("아래", b.tail(k))):
            for _i, r in part.iterrows():
                rows.append({"zone": z, "쪽": tag,
                             "sigungu_cd": r["sigungu_cd"],
                             "이름": (names or {}).get(r["sigungu_cd"], ""),
                             "배율": r["배율"]})
    return pd.DataFrame(rows)


# ── 공장·산단과 세 땅의 추이를 나란히 (2026-09-15 지시) ──────────────
#
# "적재하고 기업체 수, 밀도 등을 세 땅 추이와 함께 검토해 주세요"
#
# **한 시점 스냅샷이다.** 공장등록은 2025-10 한 장뿐이라 '공장이 늘어서
# 올랐다' 를 못 본다. 볼 수 있는 것은 '공장이 많은 곳이 더 올랐는가' —
# 횡단면이다. 인과가 아니라 동행이고, 그렇게만 적는다.

IND_LABEL = {
    "factory_all": "등록공장 수", "factory_done": "가동 공장 수",
    "factory_rest": "휴업 공장 수",
    "park_count": "산단 수", "park_area_km2": "산단 면적(㎢)",
    "park_tenant": "산단 입주업체", "park_active": "산단 가동업체",
    "population": "인구",
    "밀도:공장/만명": "공장 밀도 (만명당)",
    "밀도:공장/산단㎢": "공장 밀도 (산단㎢당)",
    "비율:가동/등록": "가동 비율",
}
MIN_PAIR = 25       # 짝이 이만큼은 있어야 상관을 적는다
QUINTILE = 5


def industry_wide(region_year: pd.DataFrame, year: int) -> pd.DataFrame:
    """시군구 × 지표 한 장. **밀도는 여기서 만든다.**

    밀도는 '몇 개' 를 '얼마나 빽빽한가' 로 바꾼다. 서울 중구와 화성시는
    공장 수가 비슷해도 전혀 다른 곳이다 — 나누는 것이 있어야 갈린다.
    나눌 것이 없으면 그 칸은 **비운다** (0 으로 채우지 않는다).
    """
    if region_year is None or len(region_year) == 0:
        return pd.DataFrame()
    r = pd.DataFrame(region_year)
    r = r[r["year"] == year]
    if r.empty:
        return pd.DataFrame()
    w = r.pivot_table(index="sigungu_cd", columns="metric", values="value")
    w.columns.name = None
    if "factory_all" in w and "population" in w:
        pop = w["population"].where(w["population"] > 0)
        w["밀도:공장/만명"] = w["factory_all"] / (pop / 10_000)
    if "factory_all" in w and "park_area_km2" in w:
        ar = w["park_area_km2"].where(w["park_area_km2"] > 0)
        w["밀도:공장/산단㎢"] = w["factory_all"] / ar
    if "factory_done" in w and "factory_all" in w:
        al = w["factory_all"].where(w["factory_all"] > 0)
        w["비율:가동/등록"] = w["factory_done"] / al
    return w.reset_index()


def against_industry(gr: pd.DataFrame, ind: pd.DataFrame,
                     cols: list[str] | None = None) -> pd.DataFrame:
    """용도지역마다 **누적 배율 ↔ 공장 지표**의 상관.

    수준(공장 수)과 밀도를 같이 본다. 수 는 도시 크기를 타고, 밀도는 덜
    탄다 — 둘이 갈리면 그것이 '큰 도시라서' 인지 '빽빽해서' 인지를 가른다.
    """
    if gr is None or gr.empty or ind is None or ind.empty:
        return pd.DataFrame()
    use = [c for c in (cols or list(IND_LABEL)) if c in ind.columns]
    m = gr.merge(ind, on="sigungu_cd", how="inner")
    rows = []
    for z, blk in m.groupby("zone"):
        for c in use:
            v = pd.to_numeric(blk[c], errors="coerce")
            g = pd.to_numeric(blk["배율"], errors="coerce")
            ok = v.notna() & g.notna() & (v > 0) & (g > 0)
            n = int(ok.sum())
            if n < MIN_PAIR:
                continue
            x, y = np.log(v[ok]), np.log(g[ok])
            if x.std() == 0 or y.std() == 0:
                continue
            rows.append({"zone": z, "지표": c, "이름": IND_LABEL.get(c, c),
                         "n": n, "r": round(float(np.corrcoef(x, y)[0, 1]), 3)})
    out = pd.DataFrame(rows)
    return out.sort_values(["zone", "r"], key=lambda s: s.abs() if s.name == "r" else s,
                           ascending=[True, False]) if len(out) else out


def quintiles(gr: pd.DataFrame, ind: pd.DataFrame, col: str,
              q: int = QUINTILE) -> pd.DataFrame:
    """지표로 시군구를 다섯 칸에 나누고 칸마다 **중앙 배율**을 본다.

    상관 하나보다 이 표가 낫다 — 관계가 곧은 직선이 아닐 때(가운데가 가장
    많이 오르는 꼴) 상관은 0 으로 나오지만 이 표에는 그대로 보인다.
    """
    if gr is None or gr.empty or ind is None or ind.empty or col not in ind.columns:
        return pd.DataFrame()
    m = gr.merge(ind[["sigungu_cd", col]], on="sigungu_cd", how="inner")
    m[col] = pd.to_numeric(m[col], errors="coerce")
    m = m[m[col].notna() & m["배율"].notna()]
    rows = []
    for z, blk in m.groupby("zone"):
        if len(blk) < q * 4:
            continue
        try:
            lab = pd.qcut(blk[col].rank(method="first"), q,
                          labels=[f"{i+1}분위" for i in range(q)])
        except ValueError:
            continue
        for tag, part in blk.groupby(lab, observed=True):
            rows.append({"zone": z, "지표": col, "칸": str(tag),
                         "시군구": int(len(part)),
                         f"{col} 중앙": round(float(part[col].median()), 2),
                         "배율 중앙": round(float(part["배율"].median()), 3),
                         "내린 곳": int((part["배율"] < 1).sum())})
    return pd.DataFrame(rows)
