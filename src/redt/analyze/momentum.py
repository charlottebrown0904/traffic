"""모멘텀 검증 — 주식식 '추세 지속' 이 땅값에도 있는가를 숫자로 본다.

주식의 모멘텀은 '지난 12개월 수익률 상위가 다음 몇 달도 앞선다' 는 횡단면
규칙이다 (Jegadeesh-Titman 1993). 그대로 옮기면 안 되는 까닭이 둘 있다.

1. **땅값은 지수가 아니라 거래 중앙값이다.** 얇은 칸의 중앙값은 잡음이 크고,
   잡음은 변화율에 **음의 자기상관**을 만든다 — 이번 해가 우연히 높으면
   지난 상승은 커 보이고 다음 상승은 작아 보인다. 이것이 '반전' 으로 읽힌다.
   표본(3,000건/년 추출)에서 실제로 rho -0.35 가 나왔고, 최근 1년을 형성
   기간에서 **건너뛰자** 0 근처가 됐다 (2026-09-14). 주식에서 마지막 한 달을
   빼는 '12-1' 규칙과 같은 처치다. 그래서 여기서는 건너뛴 창을 기본으로 둔다.
2. **거래량이 곧 유동성이다.** 주식은 거래량이 신호의 강도(확인)인데, 땅은
   거래량 자체가 앞서 움직인다는 문헌이 있다 (Stein 1995 · Genesove-Mayer
   2001: 하락기에 매도자가 버텨 거래가 먼저 준다). 그래서 거래량 변화를
   가격 추세와 **따로** 검증한다.

단위는 시군구 × 용도지역군, 주기는 연. 칸의 최소 건수(min_n)가 잡음의 크기를
정하므로 표에 같이 적는다. 결과는 스피어만 순위상관의 연도 평균과 양수
비율, 상위 1/3 − 하위 1/3 의 다음 기간 수익률 차이다.
"""
from __future__ import annotations

import math

import pandas as pd

from ..valuation import zone_group

# (이름, 형성 시작 y-a, 형성 끝 y-b, 다음 h년). b=0 이면 '지금' 까지 — 잡음
# 반전이 들어간다. b=1 이 '최근 1년 건너뜀' 이다.
SPECS = [
    ("raw_2_2",   2, 0, 2),
    ("raw_1_1",   1, 0, 1),
    ("skip_3_1_2", 3, 1, 2),
    ("skip_4_1_2", 4, 1, 2),
    ("skip_3_1_1", 3, 1, 1),
    ("long_6_1_2", 6, 1, 2),
    ("long_10_1_2", 10, 1, 2),
]


def index(con, since: int = 2006, min_n: int = 30) -> pd.DataFrame:
    """시군구 × 용도지역군 × 연 중앙 단가(ln)와 건수.

    지분·해제 거래는 빼고, 단가 상하 1% 를 잘라 극단값이 중앙값 자리를 흔들지
    않게 한다. 건수는 잘라내기 전 것을 센다 — 거래량은 있는 그대로가 뜻이다.
    """
    df = con.execute("""
        SELECT sigungu_cd, land_use, deal_year, price_per_m2
        FROM trade
        WHERE kind = 'land' AND price_per_m2 > 0 AND deal_year >= ?
          AND COALESCE(is_share_deal, FALSE) = FALSE AND COALESCE(is_cancelled, FALSE) = FALSE
          AND sigungu_cd IS NOT NULL AND land_use IS NOT NULL
    """, [since]).fetchdf()
    return index_from(df, min_n)


def index_from(df: pd.DataFrame, min_n: int = 30) -> pd.DataFrame:
    df = df.copy()
    df["zone"] = df["land_use"].map(zone_group)
    df = df.dropna(subset=["zone"])
    lo, hi = df["price_per_m2"].quantile([0.01, 0.99])
    df["ln_p"] = df["price_per_m2"].map(math.log)
    n_all = df.groupby(["sigungu_cd", "zone", "deal_year"]).size().rename("n")
    kept = df[(df["price_per_m2"] >= lo) & (df["price_per_m2"] <= hi)]
    med = kept.groupby(["sigungu_cd", "zone", "deal_year"])["ln_p"].median().rename("ln_med")
    out = pd.concat([med, n_all], axis=1).dropna().reset_index()
    out = out[out["n"] >= min_n]
    out["unit"] = out["sigungu_cd"].astype(str) + "|" + out["zone"]
    return out[["unit", "sigungu_cd", "zone", "deal_year", "ln_med", "n"]]


def _spearman(x: pd.Series, y: pd.Series) -> float:
    return float(x.rank().corr(y.rank()))


def cross_section(idx: pd.DataFrame, a: int, b: int, h: int, year: int, signal: str = "price") -> pd.DataFrame:
    """한 해의 횡단면 — 신호(형성 y-a → y-b)와 다음 h년 수익률."""
    p = idx.pivot(index="unit", columns="deal_year", values="ln_med")
    n = idx.pivot(index="unit", columns="deal_year", values="n")
    need = sorted({year - a, year - b, year, year + h})     # b=0 이면 두 칸이 같다 — 중복 열은 안 된다
    if any(c not in p.columns for c in need):
        return pd.DataFrame()
    rows = p[need].dropna()
    if signal == "price":
        sig = rows[year - b] - rows[year - a]
    else:
        nn = n.loc[rows.index, sorted({year - a, year - b})].dropna()
        rows = rows.loc[nn.index]
        sig = (nn[year - b] / nn[year - a]).map(math.log)
    fut = rows[year + h] - rows[year]
    return pd.DataFrame({"unit": rows.index, "signal": sig.values, "future": fut.values})


def evaluate(idx: pd.DataFrame, specs=SPECS, signal: str = "price", min_units: int = 20) -> list[dict]:
    """규격마다 연도별 스피어만을 내고 평균·양수 비율·1/3 스프레드를 돌려준다."""
    years = sorted(idx["deal_year"].unique())
    out = []
    for name, a, b, h in specs:
        by = []
        for y in years:
            cs = cross_section(idx, a, b, h, y, signal)
            if len(cs) < min_units:
                continue
            k = max(1, len(cs) // 3)
            s = cs.sort_values("signal")
            by.append({"year": int(y), "units": int(len(cs)),
                       "rho": _spearman(cs["signal"], cs["future"]),
                       "spread": float(s["future"].tail(k).mean() - s["future"].head(k).mean())})
        if not by:
            out.append({"spec": name, "signal": signal, "years": 0})
            continue
        out.append({"spec": name, "signal": signal, "years": len(by),
                    "mean_units": sum(r["units"] for r in by) / len(by),
                    "mean_rho": sum(r["rho"] for r in by) / len(by),
                    "share_pos": sum(1 for r in by if r["rho"] > 0) / len(by),
                    "spread_1_3": sum(r["spread"] for r in by) / len(by),
                    "by_year": by})
    return out


def describe(results: list[dict], min_n: int) -> str:
    lines = [f"모멘텀 검증 — 시군구 × 용도지역군 × 연 · 칸 최소 {min_n}건",
             "  규격         신호    연수  단위수  평균rho   rho>0   상위1/3−하위1/3"]
    for r in results:
        if not r.get("years"):
            lines.append(f"  {r['spec']:<12} {r['signal']:<6}  (표본 부족)")
            continue
        lines.append(f"  {r['spec']:<12} {r['signal']:<6} {r['years']:>4}  {r['mean_units']:>6.0f}  "
                     f"{r['mean_rho']:>+7.3f}  {r['share_pos']:>5.0%}  {r['spread_1_3']:>+9.3f}")
    lines.append("")
    lines.append("읽는 법: raw_* 는 최근 해까지 넣은 창 — 얇은 칸이면 잡음 반전(음수)이 나온다."
                 " skip_* 가 주식의 12-1 규칙에 해당한다. 양수이고 rho>0 비율이 2/3 를 넘어야 '추세가 있다'.")
    return "\n".join(lines)
