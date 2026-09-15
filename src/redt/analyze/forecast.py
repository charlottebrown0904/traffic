"""2년 뒤 예측 — 1% 라도 있으면 쓴다, 대신 **모르는 해에 대고 맞혀 본다**.

2026-09-15 지시: "(5년, 10년, 15년, 20년)간의 실거래 데이터와 31가지의
인자들을 봤을 때 상관 관계가 1%(1.01)이라도 있으면 그 추세로 2년 뒤
가격이 이렇게 될 것이다... 라는 예측 기준으로 검토해서 갑시다."

## 문턱을 1% 로 내리면 무엇이 달라지나

유의성 문턱(p<0.05)은 **'이 인자가 진짜인가'** 를 묻는다. 지시는 다른
것을 묻는다 — **'맞히기만 하면 되지 않나'**. 옳은 물음이고, 장사에는
이쪽이 맞다. 다만 지표가 210종이라 1% 문턱은 **우연만으로 절반이
통과한다** (상관이 0 인 세상에서도 |r| ≥ 0.01 일 확률은 거의 1 이다).
그러니 통과 여부로 판정하면 안 된다.

그래서 통과시킨 뒤, 그것들로 실제 예측을 만들어 **학습에 안 쓴 해**에
대고 맞혀 본다. 문턱이 옳은지는 맞는 정도가 말하게 둔다.

## 어떻게 재나 (구르는 기준점 · rolling origin)

    창 L년:  [t0-L+1 … t0]        ← 여기까지만 보고
    대상:    t0+2                  ← 이 해를 맞힌다 (학습에 한 번도 안 썼다)

    학습 짝: 기준점 s ∈ [t0-L+1 … t0-2]
             y_s = ln P(s+2) − ln P(s)      2년 변화 (이미 벌어진 것)
             x_s = Δln(지표)(s)             그 해까지 알 수 있던 것

    t0 에서 x_{t0} 을 넣어 ŷ 를 얻고, 실제 y_{t0} 와 견준다.

**시점을 안 흘린다.** 학습에는 s+2 ≤ t0 인 짝만 쓴다 — t0 시점에 실제로
알 수 있었던 것만으로 배운다. 이걸 어기면(전체 기간으로 학습하면) 성적이
좋아지지만 그건 답을 보고 푼 것이다.

## 인자를 어떻게 섞나

1% 를 넘은 지표가 수십 종이면 회귀에 다 넣을 수 없다 (칸보다 인자가
많아진다). 그래서 **한 줄로 접는다**:

    점수(s) = Σ_m r_m · z(Δln x_m(s)) ÷ Σ_m |r_m|

r_m 은 **학습 창 안에서만** 잰 상관이고, z 는 학습 창 안의 표준화다.
1% 를 넘은 모든 지표가 제 상관만큼 목소리를 낸다 — 지시의 "1% 라도
있으면 쓴다" 를 그대로 옮긴 것이다. 그 다음 ŷ = a + b·점수 하나만
맞춘다. 칸이 모자라 무너지는 일이 없다.

## 무엇과 견주나 (기준선 셋)

    무변화     ŷ = 0                     "2년 뒤에도 그대로"
    창 평균    ŷ = 학습 창 전체 평균       "요새 전국이 이만큼 올랐다"
    동네 추세  ŷ = 그 시군구의 창 안 평균   "이 동네가 이만큼 올라 왔다"

인자 모형이 이 셋을 **못 이기면 인자는 값어치가 없다.** 셋 중 가장 센
것보다 오차가 작아야 비로소 "인자를 보고 예측한다" 고 말할 수 있다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HORIZON = 2             # 몇 해 뒤를 맞히나 — 지시: 2년
WINDOWS = (5, 10, 15, 20)   # 지시: 5·10·15·20년
MIN_R = 0.01            # **지시의 1%.** 학습 창 상관이 이만큼만 되면 쓴다
MIN_TRAIN = 60          # 학습 짝이 이만큼은 있어야 그 기준점을 잰다
MIN_TEST = 30           # 맞혀 볼 칸이 이만큼은 있어야 성적을 적는다
MIN_METRIC_OBS = 40     # 지표 하나가 학습 창에서 이만큼은 겹쳐야 상관을 잰다


def price_panel(trades: pd.DataFrame, min_n: int = 5) -> pd.DataFrame:
    """시군구 × 연 중앙 ln 단가. 칸에 min_n 건이 안 되면 버린다."""
    need = {"sigungu_cd", "deal_year", "price_per_m2"}
    if trades is None or len(trades) == 0 or not need.issubset(trades.columns):
        return pd.DataFrame(columns=["sigungu_cd", "year", "ln_price", "n"])
    t = pd.DataFrame(trades)
    t = t[pd.to_numeric(t["price_per_m2"], errors="coerce") > 0].copy()
    t["ln_price"] = pd.to_numeric(t["price_per_m2"]).map(math.log)
    g = (t.groupby(["sigungu_cd", "deal_year"])
         .agg(ln_price=("ln_price", "median"), n=("ln_price", "size")).reset_index())
    g = g[g["n"] >= min_n].rename(columns={"deal_year": "year"})
    return g[["sigungu_cd", "year", "ln_price", "n"]].sort_values(["sigungu_cd", "year"])


def targets(price: pd.DataFrame, horizon: int = HORIZON) -> pd.DataFrame:
    """기준점마다 '2년 뒤까지의 변화' 를 붙인다. 두 해가 다 있어야 짝이 된다.

    **연도를 더해서 잇는다.** shift(-2) 로 하면 칸이 빈 해를 건너뛰어
    2003→2008 을 '2년' 으로 세는 수가 있다.
    """
    if price is None or len(price) == 0:
        return pd.DataFrame(columns=["sigungu_cd", "year", "y"])
    p = pd.DataFrame(price)[["sigungu_cd", "year", "ln_price"]]
    fut = p.rename(columns={"ln_price": "ln_future"}).copy()
    fut["year"] = fut["year"] - horizon          # t+2 의 값을 t 줄에 붙인다
    m = p.merge(fut, on=["sigungu_cd", "year"], how="inner")
    m["y"] = m["ln_future"] - m["ln_price"]
    return m[["sigungu_cd", "year", "y"]].sort_values(["sigungu_cd", "year"])


def deltas(long: pd.DataFrame) -> pd.DataFrame:
    """지표마다 Δln. 여기서도 **연도를 더해서** 바로 앞 해와만 뺀다."""
    if long is None or len(long) == 0:
        return pd.DataFrame(columns=["sigungu_cd", "year", "metric", "d_x"])
    b = pd.DataFrame(long)[["sigungu_cd", "year", "metric", "value"]].copy()
    b = b[pd.to_numeric(b["value"], errors="coerce") > 0]
    if b.empty:
        return pd.DataFrame(columns=["sigungu_cd", "year", "metric", "d_x"])
    b["ln_x"] = pd.to_numeric(b["value"]).map(math.log)
    prev = b[["sigungu_cd", "year", "metric", "ln_x"]].rename(columns={"ln_x": "ln_prev"})
    prev["year"] = prev["year"] + 1
    m = b.merge(prev, on=["sigungu_cd", "year", "metric"], how="inner")
    m["d_x"] = m["ln_x"] - m["ln_prev"]
    return m[["sigungu_cd", "year", "metric", "d_x"]]


def _pick(train: pd.DataFrame, wide: pd.DataFrame, min_r: float) -> dict[str, float]:
    """학습 창 안에서만 상관을 재고, **1% 를 넘은 것만** 무게와 함께 돌려준다."""
    keep: dict[str, float] = {}
    y = train["y"].to_numpy()
    for col in wide.columns:
        v = wide[col].to_numpy()
        m = np.isfinite(v) & np.isfinite(y)
        if int(m.sum()) < MIN_METRIC_OBS:
            continue
        a, b = v[m], y[m]
        if a.std() == 0 or b.std() == 0:
            continue
        r = float(np.corrcoef(a, b)[0, 1])
        if not np.isfinite(r) or abs(r) < min_r:
            continue
        keep[col] = r
    return keep


def _score(wide: pd.DataFrame, keep: dict[str, float],
           mu: pd.Series, sd: pd.Series) -> np.ndarray:
    """1% 를 넘은 지표를 제 상관만큼의 목소리로 한 줄에 접는다.

    지표마다 덮개가 달라 빈칸이 많다 — **있는 것끼리만** 무게 평균한다
    (빈칸을 0 으로 채우면 '변화가 없었다' 는 거짓말이 된다)."""
    if not keep:
        return np.zeros(len(wide))
    num = np.zeros(len(wide))
    den = np.zeros(len(wide))
    for col, r in keep.items():
        s = sd.get(col, 0.0)
        if not s or not np.isfinite(s):
            continue
        z = (wide[col].to_numpy() - mu.get(col, 0.0)) / s
        ok = np.isfinite(z)
        num[ok] += r * z[ok]
        den[ok] += abs(r)
    out = np.zeros(len(wide))
    hit = den > 0
    out[hit] = num[hit] / den[hit]
    return out


def _origin(tgt: pd.DataFrame, dx_wide: pd.DataFrame, t0: int, window: int,
            horizon: int, min_r: float) -> dict | None:
    """기준점 하나. 학습은 [t0-L+1 … t0-2], 맞히는 것은 t0 (대상 t0+2)."""
    lo = t0 - window + 1
    tr = tgt[(tgt["year"] >= lo) & (tgt["year"] <= t0 - horizon)]
    te = tgt[tgt["year"] == t0]
    if len(tr) < MIN_TRAIN or len(te) < MIN_TEST:
        return None

    trx = tr.merge(dx_wide, on=["sigungu_cd", "year"], how="left")
    tex = te.merge(dx_wide, on=["sigungu_cd", "year"], how="left")
    cols = [c for c in dx_wide.columns if c not in ("sigungu_cd", "year")]
    if not cols:
        return None
    keep = _pick(trx, trx[cols], min_r)

    mu = trx[cols].mean()
    sd = trx[cols].std()
    s_tr = _score(trx[cols], keep, mu, sd)
    s_te = _score(tex[cols], keep, mu, sd)

    y_tr = trx["y"].to_numpy()
    # 점수 하나에 대고 직선 하나. 칸보다 인자가 많아지는 일이 없다.
    if np.std(s_tr) > 0:
        b = float(np.cov(s_tr, y_tr, ddof=0)[0, 1] / np.var(s_tr))
        a = float(y_tr.mean() - b * s_tr.mean())
    else:
        a, b = float(y_tr.mean()), 0.0
    pred = a + b * s_te

    # 기준선 셋.
    base_flat = np.zeros(len(tex))
    base_mean = np.full(len(tex), float(y_tr.mean()))
    own = trx.groupby("sigungu_cd")["y"].mean()
    base_own = tex["sigungu_cd"].map(own).fillna(float(y_tr.mean())).to_numpy()

    actual = tex["y"].to_numpy()
    mae = lambda v: float(np.mean(np.abs(actual - v)))
    hit = lambda v: float(np.mean(np.sign(v) == np.sign(actual))) if len(actual) else float("nan")
    return {
        "기준점": int(t0), "창": int(window), "학습": int(len(tr)), "맞힘": int(len(te)),
        "쓴 지표": int(len(keep)), "후보 지표": int(len(cols)),
        "기울기": round(b, 4),
        "MAE 인자": round(mae(pred), 4), "MAE 무변화": round(mae(base_flat), 4),
        "MAE 창평균": round(mae(base_mean), 4), "MAE 동네추세": round(mae(base_own), 4),
        "방향 인자": round(hit(pred), 3), "방향 동네추세": round(hit(base_own), 3),
        "실제 평균": round(float(actual.mean()), 4),
    }


def backtest(price: pd.DataFrame, long: pd.DataFrame, windows=WINDOWS,
             horizon: int = HORIZON, min_r: float = MIN_R) -> pd.DataFrame:
    """창 길이마다 기준점을 굴려 가며 2년 뒤를 맞혀 본다."""
    tgt = targets(price, horizon)
    dx = deltas(long)
    if tgt.empty or dx.empty:
        return pd.DataFrame()
    dx_wide = dx.pivot_table(index=["sigungu_cd", "year"], columns="metric",
                             values="d_x").reset_index()
    dx_wide.columns.name = None
    years = sorted(tgt["year"].unique())
    rows = []
    for w in windows:
        for t0 in years:
            if t0 - w + 1 < min(years):
                continue
            r = _origin(tgt, dx_wide, int(t0), int(w), horizon, min_r)
            if r:
                rows.append(r)
    return pd.DataFrame(rows)


def summary(bt: pd.DataFrame) -> pd.DataFrame:
    """창 길이마다 성적을 접는다. **'이겼나' 가 결론이다.**"""
    if bt is None or bt.empty:
        return pd.DataFrame()
    g = (bt.groupby("창")
         .agg(기준점=("기준점", "size"), 쓴지표=("쓴 지표", "mean"),
              MAE인자=("MAE 인자", "mean"), MAE무변화=("MAE 무변화", "mean"),
              MAE창평균=("MAE 창평균", "mean"), MAE동네추세=("MAE 동네추세", "mean"),
              방향인자=("방향 인자", "mean"), 방향동네추세=("방향 동네추세", "mean"))
         .reset_index())
    g["최고 기준선"] = g[["MAE무변화", "MAE창평균", "MAE동네추세"]].min(axis=1)
    # 이득 = 가장 센 기준선 대비 오차가 몇 % 줄었나. 음수면 **졌다**.
    g["이득%"] = ((g["최고 기준선"] - g["MAE인자"]) / g["최고 기준선"] * 100).round(2)
    g["이겼나"] = g["이득%"] > 0
    for c in ("쓴지표", "MAE인자", "MAE무변화", "MAE창평균", "MAE동네추세",
              "최고 기준선", "방향인자", "방향동네추세"):
        g[c] = g[c].round(4)
    return g.sort_values("창")


def verdict(sm: pd.DataFrame) -> str:
    """문. 이기지 못하면 숫자를 안 낸다 — 다른 마디와 같은 규칙이다."""
    if sm is None or sm.empty:
        return "산출 보류 — 맞혀 볼 칸이 모자랍니다"
    win = sm[sm["이겼나"]]
    if win.empty:
        best = sm.loc[sm["이득%"].idxmax()]
        return (f"산출 보류 — 어느 창에서도 기준선을 못 이깁니다"
                f" (가장 나은 창 {int(best['창'])}년도 {best['이득%']:+.2f}%)")
    best = win.loc[win["이득%"].idxmax()]
    if float(best["이득%"]) < 2.0:
        return (f"산출 보류 — 이겼지만 이득이 {best['이득%']:+.2f}% 뿐입니다"
                f" (창 {int(best['창'])}년). 해마다 뒤집힐 크기입니다")
    return (f"창 {int(best['창'])}년 · 기준선 대비 오차 {best['이득%']:+.2f}%"
            f" · 방향 적중 {best['방향인자']:.1%}")
