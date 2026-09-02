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

    두 가지를 반드시 먼저 확인한다. 이 확인 없이 '정점' 을 고르면, 전부
    잡음인 계수 중 절댓값이 가장 큰 것을 뽑아 그럴듯한 이야기를 만들게 된다.

      1. 위약 밴드(가장 먼 구간)가 추정됐는가.
         표본 부족으로 비었는데 그 안쪽 밴드를 위약이라 부르면, 하지도 않은
         검정을 한 것처럼 보인다. 실제로 10-20km 가 비었을 때 5-10km 를
         위약으로 쓰고 '지역 효과 가능성' 이라 단정한 적이 있다.
      2. 유의한 계수가 하나라도 있는가.
         전부 p>0.05 면 방향을 말할 근거가 없다. '효과가 없다' 도 아니고
         '아직 모른다' 이다.

    **가장 가까운 밴드를 근거리 대표로 쓰지 않는다.** 선행연구
    (docs/literature.md 1번)에서 IC 인접은 오히려 가격이 낮고 2~4km 가
    정점이었다. 위약을 뺀 나머지 중 계수가 가장 큰 밴드를 찾아 비교한다.
    """
    lines = []
    for kind, grp in elasticity.groupby("kind"):
        grp = grp.copy()
        grp["lo"] = grp["band"].str.split("-").str[0].astype(float)
        grp = grp.sort_values("lo")

        fitted = grp.dropna(subset=["beta"])
        thin = grp[grp["beta"].isna()]
        thin_note = ""
        if len(thin):
            names = " · ".join(f"{r['band']}({int(r['n'])}행)" for _, r in thin.iterrows())
            thin_note = f"\n        표본 부족으로 추정 못 한 밴드: {names}"

        if len(fitted) < 2:
            lines.append(f"[{kind}] 추정된 밴드가 {len(fitted)}개뿐이라 비교할 수 "
                         f"없습니다.{thin_note}")
            continue

        far = grp.iloc[-1]                       # 위약 = 설계상 가장 먼 밴드
        if pd.isna(far["beta"]):
            shape = " · ".join(f"{r['band']} {r['beta']:+.2f}(p={r['p']:.2f})"
                               for _, r in fitted.iterrows())
            lines.append(
                f"[{kind}] ⚠️ 위약 밴드 {far['band']}km 를 추정하지 못했습니다"
                f"(표본 {int(far['n'])}행). **위약 검정을 하지 못했으므로 아래 계수를"
                f" IC 효과로 해석할 수 없습니다.**\n        밴드별: {shape}{thin_note}")
            continue

        inner = fitted[fitted["band"] != far["band"]]
        sig = inner[inner["p"] < 0.05]
        shape = " · ".join(f"{r['band']} {r['beta']:+.2f}(p={r['p']:.2f})"
                           for _, r in inner.iterrows())

        if sig.empty:
            lines.append(
                f"[{kind}] 어느 밴드에서도 유의한 관계가 없습니다 (모두 p≥0.05). "
                f"효과가 없다는 뜻이 아니라 **아직 판단할 표본이 아니라는 뜻**입니다."
                f"\n        밴드별: {shape}"
                f"\n        위약 {far['band']}km β={far['beta']:+.2f}(p={far['p']:.2f})"
                f"{thin_note}")
            continue

        # 부호를 먼저 본다. 절댓값으로 '정점' 을 고르면 **음수 계수에 초록
        # 체크가 붙는다.** 실제로 붙었다 — 화물 0-1km β=-0.78(p=0.045)에
        # "✅ 거리 감쇠 확인 — IC 효과로 해석 가능" 이라고 찍혔다. 그 값의
        # 뜻은 '화물이 늘수록 그 땅값이 내려간다' 로, 가설과 정반대다.
        pos = sig[sig["beta"] > 0]
        neg = sig[sig["beta"] < 0]

        if pos.empty:
            worst = neg.loc[neg["beta"].idxmin()]
            lines.append(
                f"[{kind}] ⚠️ 유의한 계수가 **음수**입니다 — 가설과 반대 방향입니다."
                f"\n        {worst['band']}km β={worst['beta']:+.3f}(p={worst['p']:.3f})"
                f" → 교통량이 늘수록 그 구간 땅값이 내려갔다는 뜻입니다."
                f"\n        위약 {far['band']}km β={far['beta']:+.3f}(p={far['p']:.3f})"
                f"\n        밴드별: {shape}{thin_note}")
            continue

        peak = pos.loc[pos["beta"].idxmax()]
        # 위약이 유의하면 크기 비교는 의미가 없다. 멀리서도 같은 일이
        # 벌어지고 있다는 뜻이라, IC 주변만의 효과가 아니다.
        if far["p"] < 0.05 and far["beta"] > 0:
            verdict = "⚠️ 위약 밴드도 유의한 양수 — IC 효과가 아니라 지역 효과입니다"
        elif peak["beta"] > abs(far["beta"]) * 1.5:
            verdict = "✅ 거리 감쇠 확인 — IC 효과로 해석 가능"
        else:
            verdict = "⚠️ 위약 밴드와 크기가 비슷함 — 지역 효과일 가능성. 통제변수 보강 필요"

        near = inner.iloc[0]
        note = ""
        if peak["band"] != near["band"] and near["beta"] > 0:
            note = (f"\n        └ 정점이 최근접({near['band']}km, β={near['beta']:+.2f})이"
                    f" 아니라 {peak['band']}km 입니다 — 역U자. 선행연구와 같은 모양입니다.")
        neg_note = ""
        if len(neg):
            names = " · ".join(f"{r['band']} {r['beta']:+.2f}" for _, r in neg.iterrows())
            neg_note = (f"\n        ⚠ 같은 종류에서 음수로 유의한 밴드도 있습니다: {names}."
                        " 부호가 밴드마다 뒤집히면 하나의 효과로 보기 어렵습니다.")
        lines.append(
            f"[{kind}] 정점 {peak['band']}km β={peak['beta']:+.3f}(p={peak['p']:.3f}) / "
            f"위약 {far['band']}km β={far['beta']:+.3f}(p={far['p']:.3f}) → {verdict}"
            f"\n        밴드별: {shape}{note}{neg_note}{thin_note}")

    return "\n".join(lines) if lines else "추정 가능한 계수가 없습니다 (표본 부족)."
