"""교통량 자료 정합성 검사 — 연도를 새로 넣을 때마다 돌린다.

2026-08-31 에 이런 일이 있었다. 2024년(일별 원본)과 2025년(직접 합친 엑셀)을
나란히 놓았더니 거의 모든 영업소가 균일하게 10% 씩 줄어 있었다. 실제 교통량은
그렇게 움직이지 않는다 — 자료가 어긋난 것이었다. 눈으로 겨우 잡았다.

**균일한 이동은 신호가 아니라 사고다.** 영업소마다 사정이 다른데 중앙값이
한쪽으로 크게 쏠렸다면, 교통이 변한 게 아니라 집계 범위나 정의가 달라진 것이다.
그대로 두면 모든 영업소에 가짜 증감이 실리고 β 가 통째로 오염된다.

  python scripts/check_traffic.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

# 연도 간 총교통량 변화의 상식적 범위. 코로나(2020)처럼 실제로 크게 움직인
# 해가 있으므로 넉넉히 잡되, 넘으면 반드시 사람이 확인하게 한다.
TOTAL_SHIFT_WARN = 0.07      # 전체 합계 ±7%
MEDIAN_SHIFT_WARN = 0.05     # 영업소별 증감률 중앙값 ±5%

problems: list[str] = []


def say(ok: bool, msg: str) -> None:
    print(("  ok   " if ok else "  ⚠    ") + msg)
    if not ok:
        problems.append(msg)


def load(pattern: str) -> dict[int, pd.DataFrame]:
    out = {}
    for p in sorted(RAW.glob(pattern)):
        m = re.search(r"(\d{4})", p.stem)
        if m:
            out[int(m.group(1))] = pd.read_csv(p, encoding="utf-8-sig")
    return out


def main() -> int:
    annual = load("tcs_annual_*.csv")
    monthly = load("tcs_monthly_*.csv")
    if not annual:
        print("검사할 연간 파일이 없습니다.")
        return 0

    print("1. 각 해가 12개월을 다 담고 있는가")
    for y, df in sorted(monthly.items()):
        months = sorted(df["연월"].astype(str).str[-2:].unique())
        say(len(months) == 12, f"{y}년 {len(months)}개월" +
            ("" if len(months) == 12 else f" — 빠진 달 있음 {months}"))
    for y in sorted(set(annual) - set(monthly)):
        say(False, f"{y}년: 월별 파일이 없어 개월 수를 확인할 수 없습니다 "
                   f"(일별 원본에서 다시 만드는 것이 안전)")

    print("\n2. 해가 바뀔 때 균일하게 움직이지 않았는가")
    years = sorted(annual)
    for a, b in zip(years, years[1:]):
        if b - a != 1:
            print(f"  --   {a}년과 {b}년 사이가 비어 있어 비교를 건너뜁니다")
            continue
        pa = annual[a].groupby("영업소코드")["교통량"].sum()
        pb = annual[b].groupby("영업소코드")["교통량"].sum()
        common = pa.index.intersection(pb.index)
        if len(common) < 10:
            say(False, f"{a}→{b}: 공통 영업소가 {len(common)}개뿐이라 비교 불가")
            continue

        total = pb[common].sum() / pa[common].sum() - 1
        med = (pb[common] / pa[common] - 1).median()
        say(abs(total) <= TOTAL_SHIFT_WARN,
            f"{a}→{b} 총교통량 {total:+.1%} (공통 {len(common)}개 영업소)")
        say(abs(med) <= MEDIAN_SHIFT_WARN,
            f"{a}→{b} 영업소별 증감률 중앙값 {med:+.1%}" +
            ("" if abs(med) <= MEDIAN_SHIFT_WARN else
             " — 균일한 이동입니다. 교통 변화가 아니라 집계가 어긋났을 가능성이"
             " 큽니다. 두 해가 같은 원본·같은 정의인지 확인하세요."))

    print("\n3. 영업소 명단이 해마다 얼마나 달라지는가")
    for a, b in zip(years, years[1:]):
        if b - a != 1:
            continue
        sa = set(annual[a]["영업소코드"])
        sb = set(annual[b]["영업소코드"])
        new, gone = sb - sa, sa - sb
        print(f"  --   {a}→{b}: 신설 {len(new)}개, 사라짐 {len(gone)}개")
        if new:
            print(f"         신설 코드 {sorted(new)[:10]}"
                  + (" …" if len(new) > 10 else ""))
        # 신설 영업소는 증감률이 무한대에 가깝게 튄다. 반드시 걸러야 한다.
        pa = annual[a].groupby("영업소코드")["교통량"].sum()
        pb = annual[b].groupby("영업소코드")["교통량"].sum()
        common = pa.index.intersection(pb.index)
        growth = (pb[common] / pa[common] - 1)
        wild = growth[growth > 5]          # 500% 초과
        say(wild.empty,
            f"{a}→{b} 증감률 500% 초과 {len(wild)}개" +
            ("" if wild.empty else
             f" {sorted(wild.index)[:5]} — 연중 개통이면 그 해는 빼야 합니다"))

    print()
    if problems:
        print(f"확인이 필요한 항목 {len(problems)}건")
        return 1
    print("이상 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
