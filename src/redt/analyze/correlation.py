"""Step 3 분석 — 거리밴드별 교통량 탄력성 추정.

세 층으로 나눠 보고한다.
  L1 baseline  : 수준-수준 상관 (교란 심함, 참고용)
  L2 core      : Δln(가격) ~ Δln(교통량, 1년 시차) + 연도FE + 시군구FE, 영업소 클러스터 SE
  L3 placebo   : 가장 먼 밴드에서도 계수가 크면 IC 효과가 아니라 지역 효과라는 신호
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


def _fit(data: pd.DataFrame, formula: str, cluster: str = "tollgate_id"):
    return smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data[cluster]}
    )


def level_correlation(panel: pd.DataFrame, volume_col: str = "volume_total") -> pd.DataFrame:
    """L1: 수준 상관. 밴드×물건종류별 Pearson / Spearman."""
    rows = []
    df = panel.dropna(subset=["price_index", volume_col])
    df = df[df[volume_col] > 0]
    for (band, kind), grp in df.groupby(["band", "kind"]):
        if len(grp) < 30:
            continue
        ln_vol = np.log(grp[volume_col])
        rows.append({
            "band": band,
            "kind": kind,
            "n": len(grp),
            "pearson_lnP_lnT": grp["price_index"].corr(ln_vol),
            "spearman": grp["price_index"].corr(ln_vol, method="spearman"),
        })
    return pd.DataFrame(rows).sort_values(["kind", "band"])


def elasticity_by_band(panel: pd.DataFrame, volume_col: str = "volume_total",
                       lag: int = 1, min_obs: int = 50) -> pd.DataFrame:
    """L2 + L3: 밴드별 β. 이 표 하나가 Step 4 스코어링의 근거가 된다."""
    treat = f"d_ln_{volume_col}_lag{lag}"
    needed = ["d_ln_price", treat, "year", "sigungu_cd", "tollgate_id"]
    missing = [c for c in needed if c not in panel.columns]
    if missing:
        raise KeyError(f"패널에 없는 컬럼: {missing}")

    df = panel.dropna(subset=needed).copy()
    df["year"] = df["year"].astype(int)

    rows = []
    for (band, kind), grp in df.groupby(["band", "kind"]):
        if len(grp) < min_obs or grp["tollgate_id"].nunique() < 10:
            rows.append({"band": band, "kind": kind, "n": len(grp), "note": "표본 부족"})
            continue

        formula = f"d_ln_price ~ {treat} + C(year)"
        if grp["sigungu_cd"].nunique() > 1:
            formula += " + C(sigungu_cd)"
        model = _fit(grp, formula)
        rows.append({
            "band": band,
            "kind": kind,
            "n": len(grp),
            "n_tollgates": grp["tollgate_id"].nunique(),
            "beta": model.params[treat],
            "se": model.bse[treat],
            "t": model.tvalues[treat],
            "p": model.pvalues[treat],
            "r2": model.rsquared,
            "note": "",
        })

    out = pd.DataFrame(rows).sort_values(["kind", "band"])
    return out


def interpret(elasticity: pd.DataFrame) -> str:
    """위약 밴드 검사 — 결과를 믿어도 되는지 자동 판정."""
    lines = []
    for kind, grp in elasticity.dropna(subset=["beta"]).groupby("kind"):
        grp = grp.copy()
        grp["lo"] = grp["band"].str.split("-").str[0].astype(float)
        grp = grp.sort_values("lo")
        near, far = grp.iloc[0], grp.iloc[-1]
        verdict = (
            "✅ 거리 감쇠 확인 — IC 효과로 해석 가능"
            if abs(near["beta"]) > abs(far["beta"]) * 1.5 and near["p"] < 0.05
            else "⚠️ 원거리 밴드에서도 계수가 큼 — 지역 효과일 가능성. 통제변수 보강 필요"
        )
        lines.append(
            f"[{kind}] 근거리 {near['band']}km β={near['beta']:.3f}(p={near['p']:.3f}) / "
            f"원거리 {far['band']}km β={far['beta']:.3f}(p={far['p']:.3f}) → {verdict}"
        )
    return "\n".join(lines) if lines else "추정 가능한 계수가 없습니다 (표본 부족)."
