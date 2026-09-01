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
    # 셀이 하나도 조건을 못 채우면 빈 표가 된다. 그대로 sort_values 를 부르면
    # 컬럼이 없어 KeyError 로 죽는다. 그러면 '표본이 얇다' 가 아니라 '코드가
    # 깨졌다' 처럼 보인다. 컬럼을 갖춘 빈 표를 돌려준다.
    cols = ["band", "kind", "n", "pearson_lnP_lnT", "spearman"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values(["kind", "band"])


def panel_health(panel: pd.DataFrame, volume_col: str = "volume_total") -> pd.DataFrame:
    """밴드×종류별로 쓸 수 있는 행이 몇 개인지.

    패널 행수만 보면 넉넉해 보여도, 셀당 최소 거래건수를 못 채운 칸은
    price_index 가 결측이라 회귀에 들어가지 못한다. 그 차이를 눈으로
    보여주지 않으면 '표본 부족' 이라는 말이 어디서 왔는지 알 수 없다.
    """
    out = []
    for (band, kind), grp in panel.groupby(["band", "kind"]):
        usable = grp.dropna(subset=["price_index", volume_col])
        usable = usable[usable[volume_col] > 0]
        d_col = f"d_ln_{volume_col}_lag1"
        diffable = (grp.dropna(subset=["d_ln_price", d_col])
                    if d_col in grp.columns else grp.iloc[0:0])
        out.append({
            "band": band, "kind": kind,
            "패널행": len(grp),
            "가격지수있음": int(grp["price_index"].notna().sum()),
            "수준분석가능": len(usable),
            "변화분석가능": len(diffable),
            "영업소수": int(diffable["tollgate_id"].nunique()) if len(diffable) else 0,
        })
    return pd.DataFrame(out).sort_values(["kind", "band"])


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

    if not rows:
        return pd.DataFrame(columns=["band", "kind", "n", "n_tollgates", "beta",
                                     "se", "t", "p", "r2", "note"])
    out = pd.DataFrame(rows).sort_values(["kind", "band"])
    return out


def interpret(elasticity: pd.DataFrame) -> str:
    """위약 밴드 검사 — 결과를 믿어도 되는지 자동 판정.

    **가장 가까운 밴드를 근거리 대표로 쓰면 안 된다.** 선행연구(docs/literature.md 1번)
    에서 IC 인접은 오히려 가격이 낮고 2~4km 가 정점이었다. 최근접 밴드만 보고
    '효과 없음' 이라 결론내면, 정작 효과가 있는 구간을 통째로 놓친다.

    그래서 위약 밴드(가장 먼 구간)를 뺀 나머지 중 **계수가 가장 큰 밴드**를
    골라 위약과 비교한다. 어느 거리에서 효과가 나타나는지는 데이터가 답한다.
    """
    lines = []
    for kind, grp in elasticity.dropna(subset=["beta"]).groupby("kind"):
        grp = grp.copy()
        grp["lo"] = grp["band"].str.split("-").str[0].astype(float)
        grp = grp.sort_values("lo")
        if len(grp) < 2:
            lines.append(f"[{kind}] 밴드가 하나뿐이라 위약 검정을 할 수 없습니다.")
            continue

        far = grp.iloc[-1]                       # 위약 대조군 = 가장 먼 밴드
        inner = grp.iloc[:-1]
        peak = inner.loc[inner["beta"].abs().idxmax()]

        verdict = (
            "✅ 거리 감쇠 확인 — IC 효과로 해석 가능"
            if abs(peak["beta"]) > abs(far["beta"]) * 1.5 and peak["p"] < 0.05
            else "⚠️ 원거리 밴드에서도 계수가 큼 — 지역 효과일 가능성. 통제변수 보강 필요"
        )
        shape = " · ".join(
            f"{r['band']} {r['beta']:+.2f}" for _, r in inner.iterrows())
        near = inner.iloc[0]
        note = ""
        if peak["band"] != near["band"]:
            note = (f"\n        └ 정점이 최근접({near['band']}km, β={near['beta']:+.2f})이 아니라 "
                    f"{peak['band']}km 입니다 — 역U자. 선행연구와 같은 모양입니다.")

        lines.append(
            f"[{kind}] 정점 {peak['band']}km β={peak['beta']:.3f}(p={peak['p']:.3f}) / "
            f"위약 {far['band']}km β={far['beta']:.3f}(p={far['p']:.3f}) → {verdict}"
            f"\n        밴드별: {shape}{note}"
        )
    return "\n".join(lines) if lines else "추정 가능한 계수가 없습니다 (표본 부족)."
