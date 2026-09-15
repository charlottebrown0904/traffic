"""31개 인자 교차 분석 — 무엇이 땅값과 같이 움직이고, 무엇끼리 겹치는가.

2026-09-15 지시: "변수 31가지에 대한 교차 분석도 진행해 봅시다."

docs/future-value-indicators.md 가 57개 후보를 층·단위·선후·접근으로 갈라
적어 두었고, 그중 우리가 실제로 **받아서 DB 에 넣은 것**만 여기서 잰다.
안 받은 것은 상관을 낼 수 없으니 '없음' 으로 적는다 — 빈칸을 0 으로
채우지 않는다.

## 무엇을 재는가

셋을 따로 낸다. 셋이 다른 물음이다.

    수준        ln(지표) ↔ ln(단가)          "비싼 동네가 그 지표도 높은가"
    변화(within) Δln(지표) ↔ Δln(단가)       "그 동네 안에서 같이 움직이는가"
    시차        Δln(지표)_{t-k} ↔ Δln(단가)_t  "지표가 먼저 움직이는가"

**수준 상관은 거의 늘 크게 나온다.** 서울이 인구도 전력도 땅값도 높기
때문이다. 그것은 인자가 아니라 도시 크기다. 그래서 **변화**를 본다 —
같은 시군구 안에서 지표가 오른 해에 땅값도 올랐는가.

시차가 이 표의 값어치다. 동행하는 지표는 예측에 못 쓴다 (그때 가서야
안다). k=1,2 에서 살아남는 것만 미래 가치에 쓸 후보다.

## 인자끼리도 본다

땅값과의 상관만 보면 같은 것을 재는 지표 셋을 다 넣게 된다. 전력·고용·
사업체는 '공장이 도는가' 하나를 세 번 재는 것일 수 있다. |r| 이 큰 쌍을
따로 적어, 회귀에 같이 넣을지 고를 수 있게 한다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

MIN_SGG = 30            # 시군구가 이만큼은 있어야 적는다
MIN_OBS = 200           # 관측(시군구×연)이 이만큼은 있어야 적는다
MAX_LAG = 2             # 몇 해 앞서는지까지 본다
DUP_R = 0.80            # 이보다 크면 '같은 것을 재는 쌍' 으로 적는다


def price_panel(trades: pd.DataFrame, min_n: int = 5) -> pd.DataFrame:
    """시군구 × 연 중앙 ln 단가. 셀에 min_n 건이 안 되면 버린다."""
    need = {"sigungu_cd", "deal_year", "price_per_m2"}
    if trades is None or len(trades) == 0 or not need.issubset(trades.columns):
        return pd.DataFrame()
    t = pd.DataFrame(trades)
    t = t[pd.to_numeric(t["price_per_m2"], errors="coerce") > 0].copy()
    t["ln_price"] = pd.to_numeric(t["price_per_m2"]).map(math.log)
    g = (t.groupby(["sigungu_cd", "deal_year"])
         .agg(ln_price=("ln_price", "median"), n=("ln_price", "size")).reset_index())
    g = g[g["n"] >= min_n].rename(columns={"deal_year": "year"})
    return g[["sigungu_cd", "year", "ln_price", "n"]]


def to_year(series: pd.DataFrame) -> pd.DataFrame:
    """region_series(월·분기 섞임) → 시군구 × 연. 같은 해 값은 **합이 아니라
    평균**이다 — 달수가 덜 찬 해가 작아 보이면 그것이 곧 가짜 감소다."""
    if series is None or len(series) == 0:
        return pd.DataFrame(columns=["sigungu_cd", "year", "metric", "value"])
    s = pd.DataFrame(series).copy()
    s["year"] = pd.to_numeric(s["period"].astype(str).str[:4], errors="coerce")
    s = s.dropna(subset=["year"])
    s["year"] = s["year"].astype(int)
    out = (s.groupby(["sigungu_cd", "year", "metric"])["value"]
           .mean().reset_index())
    return out


def coverage(long: pd.DataFrame) -> pd.DataFrame:
    """지표마다 시군구 몇 곳 · 몇 해 · 관측 몇 개인가. **재기 전에 이 표다.**"""
    if long.empty:
        return pd.DataFrame()
    g = (long.groupby("metric")
         .agg(시군구=("sigungu_cd", "nunique"), 관측=("value", "size"),
              처음=("year", "min"), 끝=("year", "max")).reset_index())
    g["해"] = g["끝"] - g["처음"] + 1
    g["쓸만"] = (g["시군구"] >= MIN_SGG) & (g["관측"] >= MIN_OBS)
    return g.sort_values(["쓸만", "관측"], ascending=[False, False])


def _within(df: pd.DataFrame, col: str) -> pd.Series:
    """시군구 평균을 뺀다 — '큰 도시라서' 를 지운다."""
    return df[col] - df.groupby("sigungu_cd")[col].transform("mean")


def _corr(a: pd.Series, b: pd.Series) -> tuple[float | None, int]:
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    n = int(m.sum())
    if n < MIN_OBS or a[m].std() == 0 or b[m].std() == 0:
        return None, n
    return round(float(np.corrcoef(a[m], b[m])[0, 1]), 3), n


def against_price(long: pd.DataFrame, price: pd.DataFrame,
                  max_lag: int = MAX_LAG) -> pd.DataFrame:
    """지표마다 수준·변화·시차 상관. **변화가 본론이고 수준은 참고다.**"""
    if long.empty or price.empty:
        return pd.DataFrame()
    rows = []
    p = price.sort_values(["sigungu_cd", "year"]).copy()
    p["d_price"] = p.groupby("sigungu_cd")["ln_price"].diff()
    for metric, blk in long.groupby("metric"):
        b = blk[["sigungu_cd", "year", "value"]].copy()
        b = b[pd.to_numeric(b["value"], errors="coerce") > 0]
        if b.empty:
            continue
        b["ln_x"] = pd.to_numeric(b["value"]).map(math.log)
        b = b.sort_values(["sigungu_cd", "year"])
        b["d_x"] = b.groupby("sigungu_cd")["ln_x"].diff()
        row = {"metric": metric}
        m = p.merge(b, on=["sigungu_cd", "year"], how="inner")
        if len(m) < MIN_OBS or m["sigungu_cd"].nunique() < MIN_SGG:
            row["n"] = int(len(m))
            row["시군구"] = int(m["sigungu_cd"].nunique()) if len(m) else 0
            row["얇음"] = True
            rows.append(row)
            continue
        row["시군구"] = int(m["sigungu_cd"].nunique())
        row["얇음"] = False
        row["수준"], row["n"] = _corr(m["ln_x"], m["ln_price"])
        row["수준(동네 안)"], _ = _corr(_within(m, "ln_x"), _within(m, "ln_price"))
        row["변화"], _ = _corr(m["d_x"], m["d_price"])
        for k in range(1, max_lag + 1):
            bk = b.copy()
            bk["year"] = bk["year"] + k          # k해 전 지표를 올해에 붙인다
            mk = p.merge(bk[["sigungu_cd", "year", "d_x"]], on=["sigungu_cd", "year"])
            row[f"시차{k}"], _ = _corr(mk["d_x"], mk["d_price"])
        rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["세기"] = out.get("변화").abs() if "변화" in out else None
    return out.sort_values(["얇음", "세기"], ascending=[True, False])


def among_factors(long: pd.DataFrame, keep: list[str] | None = None) -> pd.DataFrame:
    """인자끼리 겹치는 쌍. **변화**끼리 본다 — 수준은 도시 크기로 다 붙는다."""
    if long.empty:
        return pd.DataFrame()
    b = long[["sigungu_cd", "year", "metric", "value"]].copy()
    b = b[pd.to_numeric(b["value"], errors="coerce") > 0]
    if keep:
        b = b[b["metric"].isin(keep)]
    if b.empty:
        return pd.DataFrame()
    b["ln_x"] = pd.to_numeric(b["value"]).map(math.log)
    b = b.sort_values(["sigungu_cd", "year"])
    b["d_x"] = b.groupby(["sigungu_cd", "metric"])["ln_x"].diff()
    wide = b.pivot_table(index=["sigungu_cd", "year"], columns="metric", values="d_x")
    cols = [c for c in wide.columns if wide[c].notna().sum() >= MIN_OBS]
    rows = []
    for i, a in enumerate(cols):
        for c in cols[i + 1:]:
            r, n = _corr(wide[a], wide[c])
            if r is not None and abs(r) >= DUP_R:
                rows.append({"가": a, "나": c, "r": r, "n": n})
    return pd.DataFrame(rows).sort_values("r", key=lambda s: s.abs(), ascending=False) \
        if rows else pd.DataFrame()
