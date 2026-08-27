"""분석 패널 구축: 헤도닉 보정 가격지수 + 교통량 결합.

핵심은 '평균 ㎡당 가격'을 쓰지 않는 것. 어떤 해에 대형 필지 한 건이 거래되면
평균이 통째로 흔들리기 때문에(구성 변화), 물건 특성을 회귀로 걷어낸 뒤 집계한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from ..config import settings


def winsorize(series: pd.Series, pct: float) -> pd.Series:
    lo, hi = series.quantile(pct), series.quantile(1 - pct)
    return series.clip(lo, hi)


def hedonic_adjust(trades: pd.DataFrame) -> pd.DataFrame:
    """물건 특성(면적·지목)이 설명하는 가격 변동만 제거한다.

    지역·시점 효과는 **일부러 남긴다** — 그게 우리가 측정하려는 대상이다.
    다만 특성 계수를 편향 없이 뽑으려면 회귀에는 지역·연도 고정효과를 넣어야 한다
    (큰 필지가 외곽에 몰려 있으면 면적 계수가 입지 효과를 흡수해버리기 때문).
    그래서 FE를 넣어 적합한 뒤, **특성 항의 기여분만** 반사실 예측으로 빼낸다.
    """
    cfg = settings()["panel"]
    df = trades.copy()
    df = df[(df["price_per_m2"] > 0) & (df["area_m2"] > 0)]
    if df.empty:
        return df.assign(adj_ln_price=np.nan)

    df["price_per_m2"] = df.groupby("kind", group_keys=False)["price_per_m2"].apply(
        lambda s: winsorize(s, cfg["winsorize_pct"])
    )
    df["ln_price"] = np.log(df["price_per_m2"])
    df["ln_area"] = np.log(df["area_m2"])
    df["land_use"] = df["land_use"].fillna("NA").replace("", "NA")

    adjusted = []
    for kind, group in df.groupby("kind"):
        group = group.copy()
        if len(group) < 200:
            # 표본이 적으면 보정하지 않는다 (과적합이 노이즈보다 해롭다)
            adjusted.append(group.assign(adj_ln_price=group["ln_price"]))
            print(f"  헤도닉[{kind}]: n={len(group):,} — 표본 부족, 보정 생략")
            continue

        terms = ["ln_area"]
        if group["land_use"].nunique() > 1:
            terms.append("C(land_use)")
        fe = [f"C({c})" for c in ("sigungu_cd", "deal_year")
              if c in group and group[c].nunique() > 1]
        model = smf.ols(f"ln_price ~ {' + '.join(terms + fe)}", data=group).fit()

        # 반사실: 모든 물건이 '평균 면적 · 최빈 지목'이었다면?
        baseline = group.assign(
            ln_area=group["ln_area"].mean(),
            land_use=group["land_use"].mode().iat[0],
        )
        char_effect = model.predict(group) - model.predict(baseline)
        group["adj_ln_price"] = group["ln_price"] - char_effect
        print(f"  헤도닉[{kind}]: n={len(group):,} R²={model.rsquared:.3f} "
              f"면적계수={model.params['ln_area']:.3f}")
        adjusted.append(group)

    return pd.concat(adjusted, ignore_index=True)


def traffic_by_group(traffic: pd.DataFrame) -> pd.DataFrame:
    """차종을 승용/화물/중형 그룹으로 접어 영업소×연도 단위로 만든다."""
    groups = settings()["vehicle_groups"]
    # 방향(입/출)은 합산 — 개방식 요금소는 방향 구분이 없는 경우가 많다
    base = traffic.groupby(["tollgate_id", "year", "vehicle_type"], as_index=False)["volume"].sum()

    def total_for(types: list[int]) -> pd.DataFrame:
        subset = base[base["vehicle_type"].isin(types)]
        return subset.groupby(["tollgate_id", "year"], as_index=False)["volume"].sum()

    out = base.groupby(["tollgate_id", "year"], as_index=False)["volume"].sum().rename(
        columns={"volume": "volume_total"}
    )
    for name, types in groups.items():
        part = total_for(types).rename(columns={"volume": f"volume_{name}"})
        out = out.merge(part, on=["tollgate_id", "year"], how="left")
    return out.fillna({f"volume_{n}": 0 for n in groups})


def build_panel(trades: pd.DataFrame, links: pd.DataFrame,
                traffic: pd.DataFrame, nearest_only: bool = True) -> pd.DataFrame:
    cfg = settings()["panel"]

    if nearest_only:
        links = links[links["is_nearest"]]

    priced = hedonic_adjust(trades[~trades["is_share_deal"].fillna(False)])
    if priced.empty:
        return pd.DataFrame()
    priced = priced.rename(columns={"deal_year": "year"})

    joined = priced.merge(links[["trade_id", "tollgate_id", "band"]], on="trade_id", how="inner")
    if joined.empty:
        return pd.DataFrame()

    cells = (
        joined.groupby(["tollgate_id", "year", "band", "kind"], as_index=False)
        .agg(
            n_trades=("trade_id", "count"),
            price_index=("adj_ln_price", "median"),
            sigungu_cd=("sigungu_cd", "first"),
        )
    )
    # 희소 셀은 노이즈. 행을 버리지 않고 결측 처리해 패널 구조는 유지한다.
    cells.loc[cells["n_trades"] < cfg["min_trades_per_cell"], "price_index"] = np.nan

    panel = cells.merge(traffic_by_group(traffic), on=["tollgate_id", "year"], how="left")
    panel = panel.sort_values(["tollgate_id", "band", "kind", "year"]).reset_index(drop=True)

    key = ["tollgate_id", "band", "kind"]
    panel["d_ln_price"] = panel.groupby(key)["price_index"].diff()

    lag = cfg["traffic_lag_years"]
    for col in [c for c in panel.columns if c.startswith("volume_")]:
        panel[f"ln_{col}"] = np.log(panel[col].where(panel[col] > 0))
        panel[f"d_ln_{col}"] = panel.groupby(key)[f"ln_{col}"].diff()
        panel[f"d_ln_{col}_lag{lag}"] = panel.groupby(key)[f"d_ln_{col}"].shift(lag)

    return panel
