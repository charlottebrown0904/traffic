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

        # 중간에 오래 쉰 영업소를 찾는다.
        #
        # 2016년을 붙이자 681(장안본선)이 드러났다. 2016-01~11 운영 → 51개월
        # 휴지 → 2021-03 재개. 자료가 2017년부터였을 때는 '2021년 신규 개통'
        # 으로 보여 H1 처치군에 들어가 있었다. 재개통은 신규 개통과 다른
        # 사건이고, 그 '개통 전' 기간은 영업소가 있으면서 쉬고 있던 기간이다.
        #
        # 탄력성 회귀에도 해롭다. 휴지 전후를 이으면 교통량이 0 에서 튀어
        # 오른 것처럼 보이는데, 그건 수요 변화가 아니라 영업 재개다.
        own = sorted(df.loc[df["영업소코드"] == code, "연월"].unique())
        span = pd.period_range(own[0], own[-1], freq="M").astype(str)
        # 전국 공백이 낀 휴지는 **한 번의 휴지**다.
        #
        # 예전에는 전국 공백 달을 '빠진 달' 목록에서만 빼고, 세는 동안에는
        # 관측된 달처럼 취급해 run 을 0 으로 되돌렸다. 그래서 공백을 사이에
        # 둔 휴지가 둘로 쪼개졌다. 동김천(130)은 2006-02~2012-08 을 79개월
        # 내내 쉬었는데, 그 안에 든 2010-10 때문에 56개월로 보고됐다.
        #
        # 56 도 6 이상이라 130 은 어차피 제외됐지만, 공백 양쪽에 4개월씩
        # 쉰 영업소는 4 로 보고돼 기준(6)을 통과해 버린다.
        own_set, hole_set = set(own), set(holes)
        longest, run = 0, 0
        for month in span:
            if month in hole_set:
                continue                  # 그 영업소가 쉰 것이 아니다. 이어서 센다.
            if month in own_set:
                run = 0
            else:
                run += 1
                longest = max(longest, run)

        rows.append({"영업소코드": code, "첫관측월": f, "마지막관측월": l,
                     "개통판정": status, "종료판정": end,
                     "첫해개월수": months_in_first_year,
                     "첫온전연도": first_full,
                     "최장휴지개월": longest})

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
    # 오래 쉬었다 돌아온 영업소. 신규 개통과 섞으면 안 된다.
    paused = out[out["최장휴지개월"] >= 6].sort_values("최장휴지개월", ascending=False)
    if not paused.empty:
        print(f"\n중간에 6개월 이상 쉰 영업소 {len(paused)}개")
        print("  재개통은 신규 개통과 다른 사건입니다. 탄력성 회귀에서도 휴지 전후를")
        print("  이으면 '교통량 급증' 으로 보이는데 실은 영업 재개입니다.")
        print(paused[["영업소코드", "첫관측월", "마지막관측월", "개통판정",
                      "최장휴지개월"]].head(20).to_string(index=False))

    closed = out[out["종료판정"] == "폐쇄"]
    if not closed.empty:
        print(f"\n폐쇄가 확인된 {len(closed)}개")
        print(closed[["영업소코드", "마지막관측월"]].to_string(index=False))

    print(f"\n→ {OUT}")
    print("  증감률을 낼 때 '첫온전연도' 이전은 빼야 합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
