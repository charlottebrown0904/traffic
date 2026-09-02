"""지시 3 — IC 를 교통량 순으로 세우고, 주변 지가를 동일 기준으로 비교한다.

기존 분석(correlation.py)과 무엇이 다른가
-----------------------------------------
기존 L2 는 **같은 IC 안에서 시간에 따른 변화**를 본다. 영업소 고정효과가
들어가므로 "교통량이 많은 IC 주변이 비싼가" 라는 질문에는 아예 답하지 않는다.
지시 3 은 그 반대 질문이다 — IC 들을 한 줄로 세워 서로 비교한다.

'동일 기준' 을 어떻게 맞추는가
------------------------------
그냥 IC 주변 평균 실거래가를 비교하면 비교가 아니라 착시가 된다. 네 가지를
맞춘 뒤에 비교한다.

  1. 같은 연도      — 해마다 시장이 다르다
  2. 같은 거리      — 기본 0~5km (0-1·1-3·3-5 밴드), IC 마다 같은 반경
  3. 같은 물건      — 용도지역 필터를 통과한 토지, 헤도닉으로 면적·지목 보정
  4. 같은 표본조건  — IC 당 최소 거래건수를 못 채우면 순위에 넣지 않는다

교란은 숨기지 않고 같이 보고한다
--------------------------------
교통량이 많은 IC 는 대개 서울에 가깝다. 서울에 가까우면 땅값도 비싸다.
그래서 '교통량이 많아서 비싸다' 와 '서울 가까워서 둘 다 크다' 는 이 자료로
분리되지 않는다. 아래 셋을 나란히 찍어 어느 쪽인지 눈으로 보게 한다.

  raw          ln(지가) ~ ln(교통량)
  +서울거리    ln(지가) ~ ln(교통량) + ln(서울까지 거리)
  시도내       시도 고정효과를 넣어 같은 시도 안에서만 비교

서울거리를 넣었을 때 교통량 계수가 거의 사라지면, 그 상관은 IC 효과가 아니라
입지 효과다. 그 경우 그렇게 쓴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# 서울시청. 수도권 접근성 대리변수로만 쓴다.
SEOUL = (37.5665, 126.9780)
NEAR_BANDS = ("0-1", "1-3", "3-5")
MIN_TRADES = 30          # IC 당 이만큼은 있어야 중앙값이 의미가 있다


def _km_to_seoul(lat: pd.Series, lon: pd.Series) -> pd.Series:
    r = 6371.0
    p1 = np.radians(SEOUL[0])
    p2 = np.radians(lat.astype(float))
    dp = p2 - p1
    dl = np.radians(lon.astype(float) - SEOUL[1])
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def build(panel: pd.DataFrame, tollgates: pd.DataFrame,
          year: int | None = None, kind: str = "land",
          volume_col: str = "volume_total",
          bands: tuple[str, ...] = NEAR_BANDS,
          min_trades: int = MIN_TRADES) -> pd.DataFrame:
    """IC 한 줄 = 한 행. 교통량과 주변 지가를 같은 연도·같은 반경으로 맞춘다."""
    df = panel[panel["kind"] == kind].copy()
    df = df[df["band"].isin(bands)]
    if year is None:
        # 가격지수가 실제로 있는 해 중 가장 최근 — 최신 연도가 비어 있을 수 있다
        usable = df.dropna(subset=["price_index"])
        if usable.empty:
            return pd.DataFrame()
        year = int(usable["year"].max())
    df = df[df["year"] == year]

    # 밴드 여러 개를 IC 하나로 접는다. 거래건수로 가중해 IC 대표 지가를 만든다.
    df = df.dropna(subset=["price_index"])
    if df.empty:
        return pd.DataFrame()
    df["_w"] = df["n_trades"]
    grouped = df.groupby("tollgate_id").apply(
        lambda g: pd.Series({
            "n_trades": int(g["n_trades"].sum()),
            "ln_price": float(np.average(g["price_index"], weights=g["_w"])),
            volume_col: float(g[volume_col].max()),   # 밴드마다 같은 값
            "sigungu_cd": g["sigungu_cd"].iloc[0],
        }),
        include_groups=False,
    ).reset_index()

    out = grouped.merge(
        tollgates[["tollgate_id", "name", "sido", "sigungu", "lat", "lon"]],
        on="tollgate_id", how="left")
    out = out[out["n_trades"] >= min_trades]
    out = out[out[volume_col] > 0]
    if out.empty:
        return out

    out["year"] = year
    out["ln_traffic"] = np.log(out[volume_col])
    out["price_per_m2"] = np.exp(out["ln_price"])
    out["km_seoul"] = _km_to_seoul(out["lat"], out["lon"])
    out["ln_km_seoul"] = np.log(out["km_seoul"].clip(lower=1.0))

    out = out.sort_values(volume_col, ascending=False).reset_index(drop=True)
    out["교통량순위"] = np.arange(1, len(out) + 1)
    out["지가순위"] = out["price_per_m2"].rank(ascending=False, method="min").astype(int)
    out["순위차"] = out["지가순위"] - out["교통량순위"]
    return out


def fit(table: pd.DataFrame, volume_col: str = "volume_total") -> pd.DataFrame:
    """같은 자료에 세 가지 통제를 걸어 계수가 어떻게 변하는지 나란히 본다."""
    rows = []
    if len(table) < 12:
        return pd.DataFrame(columns=["모형", "n", "beta", "se", "t", "p", "r2"])

    specs = [("raw", "ln_price ~ ln_traffic"),
             ("+서울거리", "ln_price ~ ln_traffic + ln_km_seoul")]
    if table["sido"].nunique() > 1:
        specs.append(("시도내", "ln_price ~ ln_traffic + C(sido)"))

    for label, formula in specs:
        try:
            model = smf.ols(formula, data=table).fit(cov_type="HC1")
        except Exception as exc:                   # noqa: BLE001
            rows.append({"모형": label, "n": len(table), "note": str(exc)[:60]})
            continue
        rows.append({
            "모형": label, "n": int(model.nobs),
            "beta": model.params.get("ln_traffic"),
            "se": model.bse.get("ln_traffic"),
            "t": model.tvalues.get("ln_traffic"),
            "p": model.pvalues.get("ln_traffic"),
            "r2": model.rsquared,
        })
    return pd.DataFrame(rows)


def report(panel: pd.DataFrame, tollgates: pd.DataFrame,
           year: int | None = None, kind: str = "land",
           volume_col: str = "volume_total", top: int = 25) -> None:
    table = build(panel, tollgates, year=year, kind=kind, volume_col=volume_col)
    print(f"\n=== 지시3 · IC 교통량 순위 대비 주변 지가 ({kind}, {volume_col}) ===")
    if table.empty:
        print("  비교할 IC 가 없습니다. 밴드 안 거래가 IC 당 "
              f"{MIN_TRADES}건을 못 채웠습니다.")
        return

    y = int(table["year"].iloc[0])
    print(f"  기준연도 {y} · 반경 0~5km · IC {len(table)}개 "
          f"(IC 당 거래 {MIN_TRADES}건 이상)")

    show = table.head(top)[["교통량순위", "name", "sigungu", volume_col,
                            "price_per_m2", "지가순위", "순위차",
                            "n_trades", "km_seoul"]].copy()
    show[volume_col] = show[volume_col].round(0)
    show["price_per_m2"] = show["price_per_m2"].round(0)
    show["km_seoul"] = show["km_seoul"].round(0)
    print(show.to_string(index=False))
    if len(table) > top:
        print(f"  … 외 {len(table) - top}개")

    rho = table["교통량순위"].corr(table["지가순위"], method="spearman")
    print(f"\n  순위 상관 (Spearman) {rho:+.3f}  "
          "— 1에 가까울수록 교통량 순위와 지가 순위가 같은 방향")

    fits = fit(table, volume_col=volume_col)
    print("\n  ln(지가) ~ ln(교통량) — 통제를 더해가며")
    print(fits.to_string(index=False))

    if len(fits) >= 2 and "beta" in fits.columns:
        raw = fits.loc[fits["모형"] == "raw", "beta"]
        ctl = fits.loc[fits["모형"] == "+서울거리", "beta"]
        if len(raw) and len(ctl) and pd.notna(raw.iloc[0]) and pd.notna(ctl.iloc[0]):
            shrink = 1 - (ctl.iloc[0] / raw.iloc[0]) if raw.iloc[0] else np.nan
            print(f"\n  해석: 서울거리를 넣자 교통량 계수가 "
                  f"{raw.iloc[0]:+.3f} → {ctl.iloc[0]:+.3f} "
                  f"({shrink:.0%} 줄었습니다).")
            if shrink > 0.5:
                print("  절반 넘게 줄었습니다. 이 상관의 큰 몫은 IC 효과가 아니라"
                      " 수도권 접근성입니다. 교통량 순위만으로 저평가를 판정하면 안 됩니다.")
            else:
                print("  거리로 설명되지 않는 몫이 남았습니다. 다만 횡단 비교라"
                      " 인과로 읽을 수는 없습니다 — 지시 2 의 개통 전후 비교가 그 몫입니다.")
