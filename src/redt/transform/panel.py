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


def _fit_sample(group: pd.DataFrame, cat_cols: list[str],
                fit_max: int, seed: int) -> pd.DataFrame:
    """모든 범주 수준이 최소 몇 행씩 들어간 적합 표본을 뽑는다.

    그냥 무작위로 뽑으면 안 된다. 거래가 몇 건뿐인 시군구는 30만 행 표본에
    안 들어갈 수 있고, 그 계수를 모르는 채로 전수를 예측하면 patsy 가
    죽는다 — run 21 이 정확히 그렇게 죽었다:

        PatsyError: observation with value '11290' does not match
                    any of the expected levels

    적합은 표본으로, 예측은 전수로 하기로 한 이상 **표본이 전수의 모든
    수준을 덮는 것**은 선택이 아니라 요건이다. 그래서 수준마다 먼저
    per_level 행을 확보하고, 남은 자리만 무작위로 채운다.
    """
    if len(group) <= fit_max:
        return group

    per_level = 20
    keep = pd.Index([], dtype=group.index.dtype)
    for col in cat_cols:
        keep = keep.union(group.groupby(col, observed=True).head(per_level).index)

    # 수준이 너무 많아 의무 표본만으로 상한을 넘으면 그대로 쓴다. 수준을
    # 버려서 상한을 맞추면 예측이 다시 죽으므로, 상한이 양보한다.
    if len(keep) >= fit_max:
        return group.loc[keep]

    rest = group.index.difference(keep)
    fill = fit_max - len(keep)
    if len(rest) > fill:
        rest = pd.Index(
            pd.Series(rest).sample(fill, random_state=seed).to_numpy(),
            dtype=group.index.dtype)
    return group.loc[keep.union(rest)]


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

    # 건물 나이 — 공장에만 걸리는 통제다.
    #
    # 공장 실거래에는 건물이 붙어 있고 건물은 낡는다. 그것을 안 빼면
    # 교통량 계수에 감가상각이 섞인다. 도시 근처 공장이 더 오래됐다면
    # '낡은 정도' 가 '교통량이 많은 정도' 와 얽혀, 계수를 어느 쪽으로든
    # 밀어버린다. 미리 어느 쪽인지 알 수 없으므로 빼 두어야 한다.
    #
    # 나이는 제곱항까지 넣는다. 새 건물은 처음 몇 해에 빠르게 값이
    # 떨어지고 그 뒤로는 완만하다 — 직선 하나로는 그 굽이를 못 따라간다.
    #
    # 토지는 건물이 없어 나이가 전부 결측이고, 아래 nunique() > 1 검사에
    # 걸려 식에 안 들어간다. 즉 토지 결과는 이 변경 전과 **똑같다.**
    if "build_year" in df and "deal_year" in df:
        age = pd.to_numeric(df["deal_year"], errors="coerce") - \
            pd.to_numeric(df["build_year"], errors="coerce")
        # 미래에 지어진 건물, 200년 된 공장은 입력 오류다. 그런 값 하나가
        # 제곱항을 통해 계수를 통째로 끌고 간다.
        age = age.where(age.between(0, 100))
        df["has_age"] = age.notna().astype(int)
        df["bldg_age"] = age.fillna(0)
        df["bldg_age2"] = df["bldg_age"] ** 2

    # 회귀에 쓸 표본 상한. 이것이 없으면 러너가 죽는다.
    #
    # 이 회귀는 C(jimok)·C(sigungu_cd)·C(deal_year) 을 넣는다. patsy 가
    # 그것을 **빽빽한(dense) 더미 행렬**로 편다. 시군구 255 + 연도 20 +
    # 지목·용도지역이면 열이 300개쯤 된다.
    #
    #   거래 600만 × 300열 × 8바이트 = 14GB
    #
    # 러너 메모리가 16GB 다. run 18 이 정확히 여기서 죽었다(exit 143).
    # run 16 까지는 좌표 있는 거래가 387건뿐이라 이 문제가 안 보였다 —
    # 지오코딩을 고쳐 789만 건이 되자 바로 터졌다. **앞을 고치니 뒤가
    # 드러난 것**이지 새로 생긴 문제가 아니다.
    #
    # 계수는 표본을 늘려도 거의 안 변한다. 30만 건이면 면적 계수의 표준
    # 오차가 소수점 셋째 자리다. 반면 예측은 전수에 해야 하므로 나눠서
    # 한다 — 예측은 계수를 곱하는 것뿐이라 나눠도 값이 같다.
    fit_max = int(cfg.get("hedonic_fit_max", 300_000))
    chunk = 100_000

    adjusted = []
    for kind, group in df.groupby("kind"):
        group = group.copy()
        if len(group) < 200:
            # 표본이 적으면 보정하지 않는다 (과적합이 노이즈보다 해롭다)
            adjusted.append(group.assign(adj_ln_price=group["ln_price"]))
            print(f"  헤도닉[{kind}]: n={len(group):,} — 표본 부족, 보정 생략")
            continue

        terms = ["ln_area"]
        cat_cols: list[str] = []
        for col in ("jimok", "land_use", "building_use"):
            if col in group and group[col].nunique() > 1:
                terms.append(f"C({col})")
                cat_cols.append(col)
        if "has_building" in group and group["has_building"].nunique() > 1:
            terms += ["has_building", "ln_building_area"]
        # 나이가 실제로 다양할 때 넣는다.
        #
        # 두 조건을 따로 본다. 처음에는 has_age 하나만 보고 둘 다 넣었는데,
        # **모든 건이 나이를 알면** has_age 가 전부 1 이라 값이 하나뿐이고,
        # 그 검사에 걸려 bldg_age 까지 통째로 빠졌다. 나이를 가장 잘 아는
        # 경우에 나이를 안 쓰는 셈이었다 (검사 33절이 잡았다).
        #
        # has_age 는 나이를 아는 건과 모르는 건이 **섞여 있을 때만** 쓴다.
        # 그것이 없으면 0 으로 채운 '모름' 이 '새 건물' 로 읽힌다.
        if "bldg_age" in group and group["bldg_age"].nunique() > 1:
            terms += ["bldg_age", "bldg_age2"]
            if group["has_age"].nunique() > 1:
                terms.append("has_age")

        # ── 도로 접함 · 형상 · 지세 ──
        #
        # 사장님 지시(2026-09-07): "도로를 접하는 가가 제일 중요합니다."
        # 실측이 그 말을 숫자로 확인했다 — 세로(불) → 세로(가) 계단이
        # 남이천 +66%, 안성 +67% 로 같았다.
        #
        # **차 진입 여부를 따로 넣는다.** 도로접면 더미만 넣어도 그 정보가
        # 들어 있지만, 등급이 여럿이라 계수가 흩어진다. 두 표본에서 같은
        # 크기로 확인된 그 한 계단은 따로 세우는 편이 읽기도 쉽고 표본이
        # 얇을 때도 버틴다.
        #
        # **도로접면은 범주로 넣는다.** 등급을 선형으로 넣으려 했다가
        # 안성 실측에서 깨졌다 — 중로가 광대로보다 비싸고 맹지가
        # 세로(불)보다 비쌌다. 큰길이 늘 좋은 것은 아니다.
        #
        # 형상은 순서가 없으므로 그냥 범주다. 지세도 같다.
        if "road_side" in group:
            from ..usage import road_car_ok
            car = group["road_side"].map(road_car_ok)
            # 모르는 것을 0(못 들어감)으로 채우면 조사가 안 된 땅이
            # 맹지로 셈해진다. 더미를 따로 세워 표본을 지킨다.
            group["has_road"] = car.notna().astype(int)
            group["road_car_ok"] = car.fillna(0).astype(int)
            if group["road_car_ok"].nunique() > 1:
                terms.append("road_car_ok")
                if group["has_road"].nunique() > 1:
                    terms.append("has_road")
        for col in ("road_side", "parcel_shape", "parcel_slope"):
            if col in group and group[col].fillna("NA").nunique() > 1:
                group[col] = group[col].fillna("NA").replace("", "NA")
                terms.append(f"C({col})")
                cat_cols.append(col)
        fe = []
        for col in ("sigungu_cd", "deal_year"):
            if col in group and group[col].nunique() > 1:
                fe.append(f"C({col})")
                cat_cols.append(col)
        formula = f"ln_price ~ {' + '.join(terms + fe)}"
        # 적합은 표본으로, 예측은 전수로. 표본을 뽑을 때 씨앗을 고정한다 —
        # 실행할 때마다 계수가 흔들리면 화면 값이 이유 없이 달라진다.
        # 층화해서 뽑는 이유는 _fit_sample 주석에 있다.
        fit_on = _fit_sample(group, cat_cols, fit_max, seed=20260903)
        model = smf.ols(formula, data=fit_on).fit()

        # 반사실: 모든 물건이 '평균 면적 · 최빈 지목'이었다면?
        #
        # 기준값은 **적합에 쓴 표본**에서 뽑는다. 전수에서 뽑으면 표본을
        # 바꿀 때마다 기준이 함께 움직여, 계수가 같아도 보정값이 달라진다.
        overrides = {"ln_area": fit_on["ln_area"].mean()}
        # 범주는 최빈값으로. 새로 붙은 도로접·형상·지세도 여기 든다 —
        # 빼먹으면 그 항의 기여분이 안 빠져서 '보정' 이 반쪽이 된다.
        #
        # 다만 **열이 있다고 값이 있는 건 아니다.** 필지 특성은 전국을
        # 조금씩 나눠 모으는 중이라, 아직 안 훑은 지역만 들어온 kind 에서는
        # road_side·형상·지세가 통째로 빈 값일 수 있다. 그때
        # `.mode()` 는 빈 Series 를 돌려주고 `.iat[0]` 이 터진다
        # (run 37 이 그렇게 죽었다). 그런 열은 위에서 항으로도 안 들어갔으니
        # 기준값도 필요 없다 — 조용히 건너뛴다.
        for col in ("jimok", "land_use", "building_use",
                    "road_side", "parcel_shape", "parcel_slope"):
            if col not in group:
                continue
            mode = fit_on[col].mode()
            if len(mode):
                overrides[col] = mode.iat[0]
        for col in ("has_building", "ln_building_area",
                    "has_age", "bldg_age", "bldg_age2",
                    "road_car_ok", "has_road"):
            if col not in group:
                continue
            mean = fit_on[col].mean()
            # 전부 빈 값이면 평균도 NaN 이다. 그걸 기준값으로 넣으면
            # 예측이 통째로 NaN 이 되어 보정가격이 사라진다.
            if pd.notna(mean):
                overrides[col] = mean

        # 나눠서 예측한다. 한 번에 하면 여기서 다시 600만 × 300 을 만든다.
        parts = []
        for start in range(0, len(group), chunk):
            block = group.iloc[start:start + chunk]
            parts.append(model.predict(block)
                         - model.predict(block.assign(**overrides)))
        char_effect = pd.concat(parts) if parts else pd.Series(dtype=float)
        group["adj_ln_price"] = group["ln_price"] - char_effect
        note = "" if fit_on is group else f" (적합 표본 {len(fit_on):,})"
        print(f"  헤도닉[{kind}]: n={len(group):,}{note} R²={model.rsquared:.3f} "
              f"면적계수={model.params['ln_area']:.3f}")

        # 도로접 계수를 찍는다. 사장님 지시(2026-09-07): "도로를 접하는
        # 가가 제일 중요합니다."
        #
        # **실측과 다른 숫자다.** 남이천 +66% · 안성 +67% 는 그냥 평균을
        # 나눈 값이라 시군구·연도·지목·면적이 다 섞여 있다. 여기 계수는
        # 그것을 다 통제한 뒤에 남는 몫이다. 둘이 다르면 그 차이가
        # '도로 때문' 과 '도로가 좋은 동네라서' 를 가른다 — 스크리닝에
        # 쓸 수 있는 것은 앞의 것뿐이다.
        if "road_car_ok" in model.params.index:
            b = float(model.params["road_car_ok"])
            se = float(model.bse["road_car_ok"])
            print(f"    도로접(차 진입 가능) {np.exp(b) - 1:+.1%}"
                  f"  (계수 {b:+.3f} · 표준오차 {se:.3f}"
                  f" · 95% {np.exp(b - 1.96 * se) - 1:+.1%}"
                  f"~{np.exp(b + 1.96 * se) - 1:+.1%})")
            known = int(group["has_road"].sum()) if "has_road" in group else 0
            print(f"    조사된 거래 {known:,} / {len(group):,}"
                  f" ({known / max(len(group), 1):.0%})")
        for term in [t for t in model.params.index
                     if t.startswith("C(road_side)")][:12]:
            level = term.split("[T.")[-1].rstrip("]")
            b = float(model.params[term])
            print(f"      {level:<12} {np.exp(b) - 1:+7.1%}")
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

    # **용도지역 칸이 아예 없는 물건 종류는 거를 수 없다.**
    #
    # 토지(LandTrade)는 용도지역을 주지만 공장·창고(InduTrade)는 주지
    # 않는다. fillna("") 를 거치면 그런 거래는 전부 '안 맞음' 이 되어
    # 통째로 사라진다 — 필터를 통과 못 한 것이 아니라 **물어볼 칸이
    # 없었던 것**인데, 로그에는 그냥 건수가 줄어든 것으로만 보인다.
    #
    # '이 종류는 용도지역을 모른다' 와 '이 종류는 조건에 안 맞는다' 는
    # 다르다. 앞은 필터가 적용 불가능한 것이므로 통과시킨다.
    if "kind" in trades.columns:
        for kind, grp in trades.groupby("kind"):
            has_any = (col[grp.index] != "").any()
            if not has_any and len(grp):
                print(f"  용도지역이 없는 종류 '{kind}' {len(grp):,}건 — "
                      f"필터 적용 대상이 아니므로 통과시킵니다 "
                      f"(이 API 는 용도지역을 주지 않습니다)")
                hit.loc[grp.index] = True

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
