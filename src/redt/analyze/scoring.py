"""Step 4 — 영업소별 투자 스크리닝 스코어.

두 축으로 영업소를 4분면에 배치한다.
  X축: 교통량 모멘텀 (최근 N년 연평균 증가율)
  Y축: 가격 모멘텀   (최근 N년 헤도닉 가격지수 증가율)

  교통량↑ / 가격정체  →  저평가 후보   ← 투자자가 찾는 것
  교통량↑ / 가격↑     →  동반 상승
  교통량↓ / 가격↑     →  과열 주의
  교통량↓ / 가격↓     →  관망

⚠️ 이것은 **예측이 아니라 스크리닝 지표**다. 과거 데이터의 요약일 뿐이며
   미래 가격을 보장하지 않는다. UI 문구도 이 선을 지켜야 한다 (docs/legal-notes.md).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import primary_band

QUADRANTS = {
    (True, False): ("저평가 후보", "undervalued",
                    "통행량은 늘었는데 가격은 아직 따라오지 않은 구간"),
    (True, True):  ("동반 상승", "rising",
                    "통행량과 가격이 함께 오른 구간"),
    (False, True): ("과열 주의", "overheated",
                    "통행량 증가 없이 가격만 오른 구간"),
    (False, False): ("관망", "quiet",
                     "통행량과 가격 모두 정체된 구간"),
}


def cagr(series: pd.Series, years: pd.Series) -> float | None:
    """연평균 성장률. 값이 2개 미만이거나 0 이하면 계산하지 않는다."""
    frame = pd.DataFrame({"y": years, "v": series}).dropna().sort_values("y")
    frame = frame[frame["v"] > 0]
    if len(frame) < 2:
        return None
    span = frame["y"].iat[-1] - frame["y"].iat[0]
    if span <= 0:
        return None
    return float((frame["v"].iat[-1] / frame["v"].iat[0]) ** (1 / span) - 1)


def _percentile(values: pd.Series) -> pd.Series:
    """0~100 백분위. 절대값이 아니라 상대 순위로 보여줘야 오해가 적다."""
    return values.rank(pct=True) * 100


def build_scores(panel: pd.DataFrame, window: int = 3,
                 band: str | None = None, volume_col: str = "volume_freight",
                 min_years: int = 2) -> pd.DataFrame:
    """패널 → 영업소별 스코어 한 줄."""
    band = band or primary_band()
    required = {"tollgate_id", "year", "band", "price_index", volume_col}
    missing = required - set(panel.columns)
    if missing:
        raise KeyError(f"패널에 없는 컬럼: {sorted(missing)}")

    recent = panel[panel["year"] > panel["year"].max() - window - 1]
    near = recent[recent["band"] == band]
    if near.empty:
        raise ValueError(f"밴드 '{band}' 데이터가 없습니다. 사용 가능: "
                         f"{sorted(panel['band'].dropna().unique())}")

    rows = []
    for tollgate_id, group in near.groupby("tollgate_id"):
        # 가격지수는 로그값이므로 지수화해서 성장률을 계산한다
        price = group.groupby("year", as_index=False).agg(
            price_index=("price_index", "mean"), n_trades=("n_trades", "sum"))
        traffic = group.groupby("year", as_index=False)[volume_col].mean()

        price_cagr = cagr(np.exp(price["price_index"]), price["year"])
        traffic_cagr = cagr(traffic[volume_col], traffic["year"])
        rows.append({
            "tollgate_id": tollgate_id,
            "years_observed": int(group["year"].nunique()),
            "n_trades": int(group["n_trades"].fillna(0).sum()),
            "price_cagr": price_cagr,
            "traffic_cagr": traffic_cagr,
            "latest_volume": float(traffic[volume_col].iloc[-1]) if len(traffic) else None,
            "latest_price_per_m2": (float(np.exp(price["price_index"].dropna().iloc[-1]))
                                    if price["price_index"].notna().any() else None),
        })

    scores = pd.DataFrame(rows)
    scores = scores[scores["years_observed"] >= min_years]
    if scores.empty:
        return scores

    scores["traffic_score"] = _percentile(scores["traffic_cagr"])
    scores["price_score"] = _percentile(scores["price_cagr"])

    traffic_up = scores["traffic_score"] >= 50
    price_up = scores["price_score"] >= 50
    labels = [QUADRANTS[(t, p)] for t, p in zip(traffic_up, price_up)]
    scores["quadrant"] = [l[0] for l in labels]
    scores["quadrant_key"] = [l[1] for l in labels]
    scores["quadrant_note"] = [l[2] for l in labels]

    scores["confidence"] = _confidence(scores)
    return scores.sort_values("traffic_score", ascending=False).reset_index(drop=True)


def _confidence(scores: pd.DataFrame) -> pd.Series:
    """표본이 얇은 영업소의 스코어를 그대로 믿게 두면 안 된다."""
    level = pd.Series("낮음", index=scores.index)
    level[(scores["n_trades"] >= 30) & (scores["years_observed"] >= 3)] = "보통"
    level[(scores["n_trades"] >= 100) & (scores["years_observed"] >= 5)] = "높음"
    return level
