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
    for col in ("jimok", "land_use", "building_use"):
        if col in df:
            df[col] = df[col].fillna("NA").replace("", "NA")
    # 건물이 없는 나대지는 0 → log 불가. 건물유무 더미와 log면적을 함께 넣는다.
    if "building_area_m2" in df:
        has_bldg = df["building_area_m2"].fillna(0) > 0
        df["has_building"] = has_bldg.astype(int)
        df["ln_building_area"] = np.log(df["building_area_m2"].where(has_bldg)).fillna(0)

    adjusted = []
    for kind, group in df.groupby("kind"):
        group = group.copy()
        if len(group) < 200:
            # 표본이 적으면 보정하지 않는다 (과적합이 노이즈보다 해롭다)
            adjusted.append(group.assign(adj_ln_price=group["ln_price"]))
            print(f"  헤도닉[{kind}]: n={len(group):,} — 표본 부족, 보정 생략")
            continue

        terms = ["ln_area"]
        for col in ("jimok", "land_use", "building_use"):
            if col in group and group[col].nunique() > 1:
                terms.append(f"C({col})")
        if "has_building" in group and group["has_building"].nunique() > 1:
            terms += ["has_building", "ln_building_area"]
        fe = [f"C({c})" for c in ("sigungu_cd", "deal_year")
              if c in group and group[c].nunique() > 1]
        model = smf.ols(f"ln_price ~ {' + '.join(terms + fe)}", data=group).fit()

        # 반사실: 모든 물건이 '평균 면적 · 최빈 지목'이었다면?
        overrides = {"ln_area": group["ln_area"].mean()}
        for col in ("jimok", "land_use", "building_use"):
            if col in group:
                overrides[col] = group[col].mode().iat[0]
        for col in ("has_building", "ln_building_area"):
            if col in group:
                overrides[col] = group[col].mean()
        baseline = group.assign(**overrides)
        char_effect = model.predict(group) - model.predict(baseline)
        group["adj_ln_price"] = group["ln_price"] - char_effect
        print(f"  헤도닉[{kind}]: n={len(group):,} R²={model.rsquared:.3f} "
              f"면적계수={model.params['ln_area']:.3f}")
        adjusted.append(group)

    return pd.concat(adjusted, ignore_index=True)


def pick_traffic_source(traffic: pd.DataFrame) -> pd.DataFrame:
    """영업소마다 우선순위가 가장 높은 소스 하나만 남긴다.

    TCS(영업소 진출입)와 AADT(본선 지점)는 성격이 다르므로 섞으면 안 된다.
    영업소별로 커버 연수가 긴 쪽을 쓰고 싶다면 settings 의 우선순위를 조정한다.
    """
    if "source" not in traffic.columns:
        return traffic
    priority = settings().get("traffic_source_priority") or ["tcs", "aadt"]
    rank = {name: i for i, name in enumerate(priority)}
    df = traffic.copy()
    df["_rank"] = df["source"].map(lambda s: rank.get(s, len(priority)))

    best = (df.groupby("tollgate_id")["_rank"].min().rename("_best").reset_index())
    df = df.merge(best, on="tollgate_id")
    kept = df[df["_rank"] == df["_best"]].drop(columns=["_rank", "_best"])

    chosen = kept.groupby("source")["tollgate_id"].nunique().to_dict()
    print(f"  교통량 소스 선택: {chosen}")
    return kept


def traffic_by_group(traffic: pd.DataFrame) -> pd.DataFrame:
    """차종을 승용/화물/중형 그룹으로 접어 영업소×연도 단위로 만든다.

    값은 **일평균(avg_daily)** 을 쓴다. 연 합계는 관측일수가 해마다 다르면
    실제 교통량 변화가 아닌 집계 커버리지 변화를 β 로 잡아낸다.
    """
    groups = settings()["vehicle_groups"]
    traffic = pick_traffic_source(traffic)

    value = "avg_daily" if "avg_daily" in traffic.columns else "volume"
    # 컬럼이 있는데 값이 전부 비어 있으면 합계가 0 이 되어, 교통량이 없는 것과
    # 구분할 수 없게 된다. 실제로 그렇게 되어 β 가 통째로 안 나온 적이 있다.
    if traffic[value].notna().sum() == 0:
        alt = "volume" if value == "avg_daily" else "avg_daily"
        if alt in traffic.columns and traffic[alt].notna().sum() > 0:
            print(f"  ⚠️ '{value}' 가 전부 비어 있어 '{alt}' 로 대체합니다. "
                  "일평균이 아니면 관측일수 차이가 β 에 섞입니다 — 원인을 확인하세요.")
            value = alt
        else:
            raise ValueError(
                f"교통량 값이 전부 비어 있습니다 ('{value}'). 적재를 확인하세요."
            )
    # 방향(입/출)은 합산 — 개방식 요금소는 방향 구분이 없는 경우가 많다
    base = traffic.groupby(["tollgate_id", "year", "vehicle_type"],
                           as_index=False)[value].sum()

    out = (base.groupby(["tollgate_id", "year"], as_index=False)[value].sum()
           .rename(columns={value: "volume_total"}))

    has_vtype = base["vehicle_type"].nunique() > 1
    if not has_vtype:
        print("  ⚠️ 차종 구분이 없는 자료입니다 — 화물/승용 분해(H4) 불가")

    for name, types in groups.items():
        subset = base[base["vehicle_type"].isin(types)]
        part = (subset.groupby(["tollgate_id", "year"], as_index=False)[value].sum()
                .rename(columns={value: f"volume_{name}"}))
        out = out.merge(part, on=["tollgate_id", "year"], how="left")
    return out.fillna({f"volume_{n}": 0 for n in groups})


def filter_land_use(trades: pd.DataFrame) -> pd.DataFrame:
    """설정한 용도지역만 남긴다. 비어 있으면 전부 통과.

    부분일치로 본다. API 가 '계획관리' 로도 '계획관리지역' 으로도 주기 때문에
    정확일치로 걸면 한쪽이 통째로 사라진다 — 그러면 표본이 줄어든 이유가
    필터인지 자료인지 알 수 없다.
    """
    wanted = settings().get("land_use_filter") or []
    if not wanted or "land_use" not in trades.columns:
        return trades

    col = trades["land_use"].fillna("").astype(str)
    hit = col.str.contains("|".join(wanted), regex=True, na=False)
    before = len(trades)
    out = trades[hit]
    print(f"  용도지역 필터 {wanted}: {before:,} → {len(out):,}건")
    if out.empty:
        top = col[col != ""].value_counts().head(10).to_dict()
        print(f"  ⚠ 남은 거래가 없습니다. 실제 값 상위: {top}")
    elif len(out) < before * 0.02:
        print(f"  ⚠ 2% 미만만 남았습니다. 용도지역 표기를 확인하세요.")
    return out


def build_panel(trades: pd.DataFrame, links: pd.DataFrame,
                traffic: pd.DataFrame, nearest_only: bool = True) -> pd.DataFrame:
    cfg = settings()["panel"]

    if nearest_only:
        links = links[links["is_nearest"]]

    keep = ~trades["is_share_deal"].fillna(False)
    if cfg.get("exclude_cancelled", True) and "is_cancelled" in trades:
        keep &= ~trades["is_cancelled"].fillna(False)
    if cfg.get("exclude_direct_deals", False) and "deal_type" in trades:
        keep &= trades["deal_type"].fillna("") != "직거래"
    dropped = int((~keep).sum())
    if dropped:
        print(f"  제외: 지분/해제/직거래 {dropped:,}건")

    kept = trades[keep]
    kept = filter_land_use(kept)
    priced = hedonic_adjust(kept)
    if priced.empty:
        return pd.DataFrame()
    priced = priced.rename(columns={"deal_year": "year"})

    joined = priced.merge(links[["trade_id", "tollgate_id", "band"]], on="trade_id", how="inner")
    if joined.empty:
        return pd.DataFrame()

    # 법정동 중심점 좌표는 근거리 밴드에서 신뢰할 수 없다 (오차 ±1~2km)
    strict = settings()["spatial"].get("require_parcel_bands") or []
    if strict and "geocode_level" in joined:
        bad = joined["band"].isin(strict) & (joined["geocode_level"] != "parcel")
        if bad.any():
            print(f"  근거리 밴드에서 법정동단위 좌표 {int(bad.sum()):,}건 제외 "
                  f"(대상 밴드: {strict})")
            joined = joined[~bad]

        # 걸러내고 나면 **밴드마다 좌표 정밀도가 달라진다.** 근거리는 지번
        # 100%, 대조 밴드에는 법정동 중심점이 섞인다. 법정동 중심점은 ±1~2km
        # 라, 참 거리 4km 인 거래가 대조로 새어 들어오고 10km 밖 거래가
        # 대조에 끌려 들어온다. 앞은 위약 계수를 올리고 뒤는 0 으로 희석해
        # 방향이 정해지지 않는다.
        #
        # 위약 밴드는 이 시스템에서 인과를 주장할 수 있는 유일한 근거다.
        # 그것이 무엇으로 만들어졌는지 모르는 채 통과를 읽으면 안 되므로,
        # 섞인 비율을 매번 찍는다. 조용히 다르면 그 차이는 결론으로 굳는다.
        mix = (joined.assign(_p=joined["geocode_level"].eq("parcel"))
               .groupby("band")["_p"].agg(["size", "mean"]))
        coarse = mix[mix["mean"] < 1.0]
        if not coarse.empty:
            print("  밴드별 좌표 정밀도 (지번 비율):")
            for band, row in mix.iterrows():
                note = "" if row["mean"] == 1.0 else "  ← 법정동 중심점 섞임"
                print(f"    {band:<6} {int(row['size']):>7,}건  "
                      f"지번 {row['mean']:.0%}{note}")

    # 차트가 쓸 거래 단위 자료를 내보낸다. 헤도닉 보정은 무겁고 결과가 하나뿐이라
    # 여기서 한 번만 만들고, 익스포트는 그것을 읽는다. 두 번 계산하면 화면과
    # 분석이 다른 값을 보게 될 여지가 생긴다.
    build_panel.last_priced = joined[[
        c for c in ("trade_id", "tollgate_id", "year", "band", "kind",
                    "land_use", "jimok", "adj_ln_price", "sigungu_cd",
                    "geocode_level")
        if c in joined.columns
    ]].copy()

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
