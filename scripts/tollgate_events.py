"""영업소 개통·폐쇄 시점을 월별 교통량에서 찾아낸다.

도로공사 API 는 개통일자를 주지 않는다(unitCode·unitName·xValue·yValue 뿐).
대신 일별 원본에 **교통량이 처음 잡히는 달**이 곧 실제 개통 시점이다. 계획
고시일이 아니라 차가 실제로 다니기 시작한 달이라, 오히려 이쪽이 정확하다.

왜 필요한가.
  2024년 452개 → 2025년 475개로 영업소가 23개 늘었다. 이걸 모르고 증감률을
  내면 "교통량이 3,695,611% 늘었다" 같은 값이 나온다. 교통이 는 게 아니라
  없던 영업소가 생긴 것이다. 개통 연도는 증감 계산에서 빼야 한다.

그리고 개통은 **자연실험**이다. 같은 지역에서 개통 전후를 비교하면 지역
고유의 요인이 상당히 상쇄된다(docs/literature.md 4번의 이중차분).

좌측절단(left censoring)에 주의한다. 자료가 2024년부터면 2024-01 에 처음
보이는 영업소는 "2024년에 개통" 이 아니라 "그전부터 있었는데 자료가 없을 뿐"
이다. 이 둘을 반드시 구분한다 — 섞으면 오래된 영업소가 전부 신설로 둔갑한다.

  python scripts/tollgate_events.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = RAW / "tollgate_events.csv"


def load_monthly() -> pd.DataFrame:
    frames = []
    for p in sorted(RAW.glob("tcs_monthly_*.csv")):
        frames.append(pd.read_csv(p, encoding="utf-8-sig"))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    return (df.groupby(["영업소코드", "연월"], as_index=False)["교통량"].sum()
              .query("교통량 > 0"))


def main() -> int:
    df = load_monthly()
    if df.empty:
        print("월별 파일이 없습니다. 먼저 convert_tcs_daily.py 로 만드세요.")
        return 1

    covered = sorted(df["연월"].unique())
    print(f"자료 범위 {covered[0]} ~ {covered[-1]} ({len(covered)}개월)")

    # 자료가 끊긴 구간이 있으면 '그 달에 없었다' 와 '자료가 없다' 를 구분할 수 없다.
    idx = pd.period_range(covered[0], covered[-1], freq="M").astype(str)
    gaps = [m for m in idx if m not in set(covered)]
    if gaps:
        print(f"  ⚠ 빠진 달 {len(gaps)}개 {gaps[:6]}{' …' if len(gaps) > 6 else ''}")
        print("    빠진 달 직후에 처음 보이는 영업소는 개통인지 자료 공백인지"
              " 가릴 수 없어 '판정보류' 로 둡니다.")
    holes = set(gaps)

    first = df.groupby("영업소코드")["연월"].min()
    last = df.groupby("영업소코드")["연월"].max()
    rows = []
    for code in sorted(first.index):
        f, l = first[code], last[code]
        prev = str(pd.Period(f, freq="M") - 1)
        nxt = str(pd.Period(l, freq="M") + 1)

        if f == covered[0]:
            # 자료 첫 달부터 있었다 → 그전 사정을 알 수 없다
            status = "좌측절단"
        elif prev in holes:
            status = "판정보류"
        else:
            status = "개통"

        if l == covered[-1]:
            end = "운영중"
        elif nxt in holes:
            end = "판정보류"
        else:
            end = "폐쇄"

        # 개통 첫 해는 몇 달치뿐이라 연간 합계가 낮다. 그대로 증감을 내면
        # 이듬해가 폭증한 것처럼 보인다. 첫 '온전한' 해를 따로 표시한다.
        y = int(f[:4])
        months_in_first_year = df[(df["영업소코드"] == code)
                                  & (df["연월"].str[:4] == f[:4])]["연월"].nunique()
        first_full = y if months_in_first_year == 12 else y + 1

        rows.append({"영업소코드": code, "첫관측월": f, "마지막관측월": l,
                     "개통판정": status, "종료판정": end,
                     "첫해개월수": months_in_first_year,
                     "첫온전연도": first_full})

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    print()
    print(out["개통판정"].value_counts().rename("영업소 수").to_string())
    opened = out[out["개통판정"] == "개통"]
    if not opened.empty:
        print(f"\n개통이 확인된 {len(opened)}개")
        print(opened.sort_values("첫관측월")
              [["영업소코드", "첫관측월", "첫해개월수", "첫온전연도"]]
              .head(30).to_string(index=False))
    closed = out[out["종료판정"] == "폐쇄"]
    if not closed.empty:
        print(f"\n폐쇄가 확인된 {len(closed)}개")
        print(closed[["영업소코드", "마지막관측월"]].to_string(index=False))

    print(f"\n→ {OUT}")
    print("  증감률을 낼 때 '첫온전연도' 이전은 빼야 합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
