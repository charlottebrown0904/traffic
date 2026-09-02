"""지시 2 — 새로 생긴 영업소 주변 땅값이 개통 뒤에 올랐는가.

왜 이 비교가 다른 것보다 낫나
-----------------------------
횡단 비교(cross.py)는 "교통량 많은 IC 주변이 비싸다" 까지만 말할 수 있다.
비싼 곳에 IC 를 놓았을 수도 있기 때문이다. 개통은 그 순서를 뒤집는다 —
IC 가 **나중에** 생겼으므로, 개통 전후 차이는 IC 쪽에서 온 것으로 읽을 여지가
생긴다(docs/literature.md 4번).

설계
----
이중차분(DiD).

  처치군  개통 영업소가 '가장 가까운 영업소' 이고 3km 안인 거래
  대조군  같은 시군구에 있으면서, 가장 가까운 영업소가 개통 전부터 있던 곳인 거래
  결과    헤도닉 보정 ln(㎡단가)
  식      ln(P) ~ 처치 × 개통후 + 연도FE + 시군구FE, 영업소 클러스터 SE

거리 배정은 **현재 지형으로 고정**한다. 개통 전에는 그 IC 가 없었으니 '그때의
최근접' 은 다른 곳이지만, 처치 여부가 시간에 따라 바뀌면 그것 자체가 결과에
반응하는 변수가 되어 DiD 가 성립하지 않는다.

반드시 확인하는 것
------------------
개통 **전** 추세가 두 군에서 같았는지(평행추세). 개통 전부터 처치군이 더
빨리 오르고 있었다면, 개통 후 차이는 IC 가 만든 게 아니다. 연도별 계수를
같이 찍어 그것을 눈으로 보게 한다. 사전 추세가 유의하면 그렇게 쓴다.

좌측절단 주의: 자료 첫 달부터 보이는 영업소는 '그때 개통' 이 아니라 '그전
사정을 모름' 이다. scripts/tollgate_events.py 가 이미 갈라 놓았고, 여기서는
'개통' 으로 판정된 것만 처치군으로 쓴다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from ..config import RAW
from ..ids import canon_series

EVENTS_CSV = RAW / "tollgate_events.csv"
SUCCESSION_CSV = RAW / "tollgate_succession.csv"
TREAT_BANDS = ("0-1", "1-3")      # 3km 안
PRE_YEARS, POST_YEARS = 2, 2
MIN_TREATED = 60                  # 이보다 적으면 계수를 내지 않는다


def load_events() -> pd.DataFrame:
    """개통이 확인된 영업소와 그 개통연도. 좌측절단·판정보류는 뺀다."""
    if not EVENTS_CSV.exists():
        return pd.DataFrame(columns=["tollgate_id", "open_year"])
    ev = pd.read_csv(EVENTS_CSV, encoding="utf-8-sig")
    ev = ev[ev["개통판정"] == "개통"].copy()

    # 중간에 오래 쉬었다 돌아온 영업소는 처치군에서 뺀다. 재개통은 신규
    # 개통과 다른 사건이고, 그 '개통 전' 기간은 영업소가 있으면서 쉬고
    # 있던 기간이라 대조군과 비교가 성립하지 않는다.
    #
    # 2016년 자료를 붙이자 681(장안본선)이 51개월 휴지 뒤 재개였음이
    # 드러났다. 그전에는 '2021년 신규 개통' 으로 보여 처치군에 있었다.
    # 코드가 쪼개져 새로 생긴 것은 신규 개통이 아니다.
    #
    # 2014-10 가락(246)이 -1,004k 떨어지면서 29(가락(개))·596(가락2)이
    # 나타났다. 합이 993k 로 거의 일치한다. 그 자리에 원래 IC 가 있었으므로
    # '새로 뚫린 IC' 가 아니다. 처치군에 넣으면 개통 효과를 재는 표본 자체가
    # 오염된다.
    #
    # 이름까지 이어지는 것만 뺀다. 월 합계만 맞는 것은 진짜 개통과 코드
    # 승계가 같은 달에 겹쳤을 수 있어(동충주가 그랬다) 빼지 않는다 —
    # 진짜 개통을 잘못 빼면 표본만 줄어든다.
    if SUCCESSION_CSV.exists():
        suc = pd.read_csv(SUCCESSION_CSV, encoding="utf-8-sig")
        if len(suc) and "판정" in suc.columns:
            sure = set(pd.to_numeric(
                suc.loc[suc["판정"] == "이름일치", "신규코드"], errors="coerce").dropna())
            hit = pd.to_numeric(ev["영업소코드"], errors="coerce").isin(sure)
            if hit.any():
                names = ", ".join(
                    f"{r.신규코드} {r.신규명}(←{r.선행명})"
                    for r in suc[suc["판정"] == "이름일치"].itertuples())
                print(f"  코드 승계로 생긴 영업소 {int(hit.sum())}개를 처치군에서 뺍니다: {names}")
                ev = ev[~hit]

    if "최장휴지개월" in ev.columns:
        paused = ev["최장휴지개월"].fillna(0) >= 6
        if paused.any():
            print(f"  중간에 6개월 이상 쉰 영업소 {int(paused.sum())}개를 처치군에서 뺍니다"
                  f" (재개통은 신규 개통과 다른 사건입니다)")
            ev = ev[~paused]
    ev["tollgate_id"] = canon_series(ev["영업소코드"])
    ev["open_year"] = ev["첫관측월"].astype(str).str[:4].astype(int)
    # 첫 해는 몇 달치뿐이라 '개통 후' 로 온전히 세면 안 된다. 첫 온전연도부터
    # 개통후로 본다.
    ev["post_from"] = ev["첫온전연도"].astype(int)
    return ev[["tollgate_id", "open_year", "post_from"]]


def build(trades: pd.DataFrame, links: pd.DataFrame,
          kind: str = "land") -> pd.DataFrame:
    """거래 한 건 = 한 행. 처치·개통후·상대연도를 붙인다.

    trades 는 헤도닉 보정을 마친 것(adj_ln_price 보유)을 받는다.
    """
    ev = load_events()
    if ev.empty:
        return pd.DataFrame()

    # is_nearest 는 DB 에서 오면 결측이 섞일 수 있다. NaN 을 그대로 & 하면
    # 전부 걸러져 '표본 없음' 이 되는데, 그건 자료가 없는 것과 구분되지 않는다.
    nearest = links["is_nearest"].fillna(False).astype(bool)
    near = links[nearest & links["band"].isin(TREAT_BANDS)]
    df = trades[trades["kind"] == kind].merge(
        near[["trade_id", "tollgate_id", "distance_km"]], on="trade_id", how="inner")
    if df.empty:
        return df

    df = df.rename(columns={"deal_year": "year"})
    df = df.merge(ev, on="tollgate_id", how="left")
    df["treated"] = df["open_year"].notna().astype(int)

    # 대조군은 '개통 이력이 없는' 영업소 주변. 처치군 시군구 안에서만 쓴다 —
    # 전국을 대조군으로 삼으면 지역 추세 차이가 통째로 들어온다.
    treat_sigungu = set(df.loc[df["treated"] == 1, "sigungu_cd"].dropna())
    df = df[df["sigungu_cd"].isin(treat_sigungu)]
    if df.empty:
        return df

    # 처치군의 개통연도를 시군구 대표 이벤트연도로 삼아, 대조군에도 같은
    # 시점을 붙인다. 대조군에 시점이 없으면 전후를 나눌 수 없다.
    ref = (df[df["treated"] == 1].groupby("sigungu_cd")["post_from"].min()
           .rename("ref_post_from"))
    df = df.merge(ref, on="sigungu_cd", how="left")
    df["post_from"] = df["post_from"].fillna(df["ref_post_from"])
    df = df.dropna(subset=["post_from"])
    df["rel_year"] = df["year"] - df["post_from"]
    df["post"] = (df["rel_year"] >= 0).astype(int)

    df = df[df["rel_year"].between(-PRE_YEARS, POST_YEARS)]
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return (df.groupby(["treated", "post"])
            .agg(거래=("trade_id", "count"),
                 영업소=("tollgate_id", "nunique"),
                 시군구=("sigungu_cd", "nunique"),
                 평균ln단가=("adj_ln_price", "mean"))
            .reset_index())


def did(df: pd.DataFrame):
    """ln(P) ~ 처치×개통후 + 연도FE + 시군구FE."""
    need = ["adj_ln_price", "treated", "post", "year", "sigungu_cd", "tollgate_id"]
    data = df.dropna(subset=need)
    if data["sigungu_cd"].nunique() > 1:
        formula = "adj_ln_price ~ treated * post + C(year) + C(sigungu_cd)"
    else:
        formula = "adj_ln_price ~ treated * post + C(year)"
    return smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["tollgate_id"]})


def event_study(df: pd.DataFrame):
    """상대연도별 계수. -1 을 기준으로 두고 사전 추세를 본다."""
    data = df.dropna(subset=["adj_ln_price", "treated", "rel_year",
                             "year", "sigungu_cd", "tollgate_id"]).copy()
    data["rel"] = data["rel_year"].astype(int).astype(str)
    fe = " + C(sigungu_cd)" if data["sigungu_cd"].nunique() > 1 else ""
    formula = (f"adj_ln_price ~ treated * C(rel, Treatment(reference='-1'))"
               f" + C(year){fe}")
    return smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["tollgate_id"]})


def report(trades: pd.DataFrame, links: pd.DataFrame, kind: str = "land") -> None:
    print(f"\n=== 지시2 · 신규 개통 영업소 주변 지가 (이중차분, {kind}) ===")
    ev = load_events()
    if ev.empty:
        print(f"  {EVENTS_CSV} 가 없습니다. scripts/tollgate_events.py 를 먼저 돌리세요.")
        return
    print(f"  개통이 확인된 영업소 전국 {len(ev)}개 "
          f"(개통연도 {int(ev['open_year'].min())}~{int(ev['open_year'].max())})")

    df = build(trades, links, kind=kind)
    if df.empty:
        print("  우리가 받은 거래 권역 안에 개통 영업소 주변 거래가 없습니다.")
        return

    summary = summarize(df)
    print("\n  표본")
    print(summary.to_string(index=False))

    treated_n = int(df["treated"].sum())
    treat_tg = sorted(df.loc[df["treated"] == 1, "tollgate_id"].unique())
    print(f"\n  처치 영업소 {len(treat_tg)}개 · 처치 거래 {treated_n:,}건")

    if treated_n < MIN_TREATED:
        print(f"  ⚠ 처치 거래가 {MIN_TREATED}건에 못 미쳐 계수를 내지 않습니다. "
              "숫자를 내면 표본이 아니라 우연을 읽게 됩니다.")
        return
    if df.loc[df["treated"] == 1, "post"].nunique() < 2:
        print("  ⚠ 처치군에 개통 전 또는 후 한쪽만 있습니다. 전후 비교가 불가능합니다.")
        return

    model = did(df)
    coef = "treated:post"
    if coef not in model.params:
        print(f"  ⚠ 교차항이 추정되지 않았습니다: {list(model.params.index)[:6]}")
        return
    beta, se = model.params[coef], model.bse[coef]
    print(f"\n  DiD  처치×개통후 = {beta:+.4f} (se {se:.4f}, "
          f"t {model.tvalues[coef]:+.2f}, p {model.pvalues[coef]:.4f})")
    print(f"       → 개통 뒤 주변 ㎡단가가 대조군 대비 "
          f"{np.expm1(beta):+.1%} 변했다는 뜻입니다.")

    try:
        es = event_study(df)
    except Exception as exc:                        # noqa: BLE001
        print(f"  상대연도별 추정 실패: {exc}")
        return

    rows = []
    for name in es.params.index:
        if name.startswith("treated:C(rel"):
            label = name.split("T.")[-1].rstrip("]")
            rows.append({"상대연도": label, "계수": es.params[name],
                         "se": es.bse[name], "p": es.pvalues[name]})
    if not rows:
        return
    table = pd.DataFrame(rows)
    table["_k"] = pd.to_numeric(table["상대연도"], errors="coerce")
    table = table.sort_values("_k").drop(columns="_k")
    print("\n  상대연도별 (기준 = 개통 직전 해, -1)")
    print(table.to_string(index=False))

    pre = table[pd.to_numeric(table["상대연도"], errors="coerce") < 0]
    if len(pre) and (pre["p"] < 0.1).any():
        print("  ⚠ 개통 **전** 계수가 유의합니다. 평행추세가 깨졌습니다 — "
              "개통 후 차이를 IC 효과로 읽을 수 없습니다.")
    elif len(pre):
        print("  개통 전 계수는 유의하지 않습니다. 평행추세 가정이 이 표본에서는"
              " 버팁니다(표본이 작으면 검정력이 낮다는 점은 감안해야 합니다).")
