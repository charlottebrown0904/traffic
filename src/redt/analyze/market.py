"""시장 층 — 금리·물가·성장률이 지가변동률을 얼마나, 몇 달 뒤에 옮기는가.

미래 가치의 시장 층은 인자가 아니라 **시나리오**다 (docs/future-value.md
§3-1). 전국 모든 땅을 같은 방향으로 옮기므로 필지를 가르지 않는다. 그래서
전국 × 용도지역군의 월 지가변동률(R-ONE A_2024_00007)을 종속변수로, ECOS
의 기준금리(수준)·물가(전년동월비)·성장률(전년동기비)을 시차를 두고 넣어
계수를 재고, 앞으로 T년의 곡선을 금리 하락·유지·상승 셋으로 낸다.

    y_t (%/월) = a + b_r·금리_{t-L_r} + b_p·물가_{t-L_p} + b_g·성장_{t-L_g} + e_t

시차 L 은 정하지 않고 고른다 — 후보 격자에서 조정 R² 가 가장 큰 조합.
표본이 월 240개쯤이라 격자는 작게 둔다. 잔차 자기상관은 HAC(뉴이-웨스트)
표준오차로 받는다. 이것은 첫 판이다 — 뒤로 돌려 검산(2018 상태로 2023)이
통과해야 채택이다.
"""
from __future__ import annotations

import itertools
import math

import pandas as pd

ZONES = ("전국", "주거", "상업", "공업", "녹지", "관리", "농림", "자연환경")
LAGS = {"rate": (3, 6, 9, 12), "cpi": (0, 2, 4), "gdp": (0, 3, 6)}


def _pick_axes(df: pd.DataFrame) -> tuple[str, str]:
    """전국이 든 쪽이 지역 축, 나머지가 용도지역 축."""
    g = df["grp_nm"].astype(str)
    if g.str.contains("전국").any():
        return "grp_nm", "cls_nm"
    return "cls_nm", "grp_nm"


def landprice_monthly(con, statbl: str = "A_2024_00007") -> pd.DataFrame:
    """월 × 용도지역군 지가변동률(%), 전국만. 열 이름은 용도지역 이름 그대로."""
    df = con.execute(
        "SELECT period, grp_nm, cls_nm, itm_nm, value FROM landprice_index WHERE statbl = ? AND length(period) = 6",
        [statbl]).fetchdf()
    if df.empty:
        return df
    region, zone = _pick_axes(df)
    nat = df[df[region].astype(str).str.contains("전국")]
    piv = nat.pivot_table(index="period", columns=zone, values="value", aggfunc="first").sort_index()
    piv.index = pd.PeriodIndex(piv.index, freq="M")
    return piv


def macro_monthly(con) -> pd.DataFrame:
    """ECOS 계열을 월로 편다 — 금리 수준 · 물가 전년동월비 · 성장률(분기→월)."""
    ms = con.execute("SELECT series, period, value FROM market_series").fetchdf()
    out = {}
    m = ms[ms["series"] == "policy_rate"].set_index("period")["value"]
    m.index = pd.PeriodIndex(m.index, freq="M")
    out["rate"] = m.sort_index()
    c = ms[ms["series"] == "cpi"].set_index("period")["value"]
    c.index = pd.PeriodIndex(c.index, freq="M")
    c = c.sort_index()
    out["cpi"] = (c / c.shift(12) - 1) * 100
    g = ms[ms["series"] == "gdp_growth"].set_index("period")["value"]
    if len(g):
        g.index = pd.PeriodIndex(g.index.str.replace("Q", "Q"), freq="Q")
        gm = g.sort_index().resample("M").ffill()
        out["gdp"] = gm
    return pd.DataFrame(out)


def fit_zone(y: pd.Series, x: pd.DataFrame, lags: dict = LAGS):
    """시차 격자에서 조정 R² 최대인 조합. (결과, 시차) — statsmodels OLS·HAC."""
    import statsmodels.api as sm
    best = None
    # 분산이 없는 계열(예: 물가가 한 값으로 고정)은 상수와 겹쳐 행렬이 특이해지고
    # p 값이 nan 이 된다 — 그런 열은 빼고 적합한다.
    cols = [c for c in ("rate", "cpi", "gdp") if c in x.columns and x[c].dropna().std() > 1e-9]
    if not cols:
        return None
    grid = itertools.product(*[lags[c] for c in cols])
    for combo in grid:
        X = pd.DataFrame({c: x[c].shift(l) for c, l in zip(cols, combo)})
        d = pd.concat([y.rename("y"), X], axis=1).dropna()
        if len(d) < 60:
            continue
        res = sm.OLS(d["y"], sm.add_constant(d[cols])).fit(cov_type="HAC", cov_kwds={"maxlags": 6})
        if best is None or res.rsquared_adj > best[0].rsquared_adj:
            best = (res, dict(zip(cols, combo)))
    return best


def scenarios(res, lag: dict, last: dict, years: int = 3, rate_step: float = 1.0) -> dict:
    """앞으로 years 년의 누적 배율 셋 — 금리 −step / 0 / +step, 물가·성장은 마지막 값 유지."""
    p = res.params
    out = {}
    for name, dr in (("하락", -rate_step), ("유지", 0.0), ("상승", rate_step)):
        monthly = float(p.get("const", 0.0))
        for c in ("rate", "cpi", "gdp"):
            if c in p:
                v = last.get(c, 0.0) + (dr if c == "rate" else 0.0)
                monthly += float(p[c]) * v
        out[name] = {"monthly_pct": monthly,
                     "multiplier": {f"{t}y": round(math.exp(math.log1p(monthly / 100) * 12 * t), 4)
                                    for t in range(1, years + 1)}}
    return out


def run(con, years: int = 3) -> dict:
    lp = landprice_monthly(con)
    if lp.empty:
        return {"error": "landprice_index 가 비었다 — load-landprice 먼저"}
    x = macro_monthly(con)
    last = {c: float(x[c].dropna().iloc[-1]) for c in x.columns if x[c].notna().any()}
    out = {"n_months": int(len(lp)), "period": [str(lp.index.min()), str(lp.index.max())],
           "last_macro": last, "zones": {}}
    for zone in lp.columns:
        y = lp[zone].astype(float)
        best = fit_zone(y, x)
        if best is None:
            out["zones"][str(zone)] = {"error": "표본 부족"}
            continue
        res, lag = best
        out["zones"][str(zone)] = {
            "n": int(res.nobs), "adj_r2": float(res.rsquared_adj), "lags": lag,
            "coef": {k: float(v) for k, v in res.params.items()},
            "p": {k: float(v) for k, v in res.pvalues.items()},
            "scenarios": scenarios(res, lag, last, years=years)}
    return out


def describe(out: dict) -> str:
    if "error" in out:
        return out["error"]
    lines = [f"시장 층 적합 — 전국 월 지가변동률 {out['period'][0]}~{out['period'][1]} ({out['n_months']}개월)",
             "  마지막 거시: " + " · ".join(f"{k} {v:.2f}" for k, v in out["last_macro"].items()),
             "  용도지역    n   adjR²   금리계수(시차)     물가계수(시차)   성장계수(시차)   3년 배율 하락/유지/상승"]
    for z, r in out["zones"].items():
        if "error" in r:
            lines.append(f"  {z:<8} {r['error']}")
            continue
        c, p, l = r["coef"], r["p"], r["lags"]
        def cell(k):
            return f"{c.get(k, float('nan')):+.3f}{'*' if p.get(k, 1) < 0.05 else ' '}({l.get(k, '-')})" if k in c else "   —   "
        s3 = r["scenarios"]
        lines.append(f"  {z:<8} {r['n']:>4} {r['adj_r2']:>6.3f}   {cell('rate'):<16} {cell('cpi'):<15} {cell('gdp'):<15}"
                     f"  {s3['하락']['multiplier']['3y']:.3f}/{s3['유지']['multiplier']['3y']:.3f}/{s3['상승']['multiplier']['3y']:.3f}")
    lines.append("  * p<0.05 (HAC). 금리 계수는 음수여야 이론과 맞다 — 양수면 국면 변수가 빠진 것.")
    return "\n".join(lines)
