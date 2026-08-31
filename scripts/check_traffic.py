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

    # 개통연도 표 (scripts/tollgate_events.py 가 만든다). 없으면 빈 표로 둔다 —
    # 검사가 안 도는 것보다 설명 없이 경고하는 편이 낫다.
    events: dict[int, int] = {}
    ev_path = RAW / "tollgate_events.csv"
    if ev_path.exists():
        ev = pd.read_csv(ev_path, encoding="utf-8-sig")
        ev = ev[ev["개통판정"] == "개통"]
        events = dict(zip(ev["영업소코드"].astype(int),
                          ev["첫관측월"].astype(str).str[:4].astype(int)))
        print(f"개통연도 {len(events)}개 영업소 반영 (tollgate_events.csv)\n")
    else:
        print("tollgate_events.csv 가 없습니다 — 먼저 scripts/tollgate_events.py "
              "를 돌리면 신설 영업소를 설명할 수 있습니다.\n")
    if not annual:
        print("검사할 연간 파일이 없습니다.")
        return 0

    print("1. 각 해가 12개월을 다 담고 있는가")
    for y, df in sorted(monthly.items()):
        ym = df["연월"].astype(str)
        # 파일 이름의 연도와 다른 연도가 섞여 있는지부터 본다. 예전에 날짜
        # 형식 때문에 2023-01 이 통째로 '1970-01' 이 된 적이 있는데, 뒤 두
        # 자리만 보고 개월 수를 세면 그것도 1월로 세어져 12개월 '정상' 이
        # 되어버린다. 연도까지 봐야 잡힌다.
        stray = sorted(set(ym.str[:4]) - {str(y)})
        say(not stray, f"{y}년 파일에 다른 연도 {stray}" if stray
            else f"{y}년 파일에 다른 연도 섞임 없음")
        months = sorted(ym[ym.str[:4] == str(y)].str[-2:].unique())
        say(len(months) == 12, f"{y}년 {len(months)}개월" +
            ("" if len(months) == 12 else f" — 있는 달 {months}"))
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
        # 개통 시점을 아는 영업소는 '설명된 것' 으로 분리한다. 설명되지 않은
        # 폭증만 남겨야 진짜 이상치가 눈에 띈다.
        # a 년 '중' 개통이면 a 년 합계가 몇 달치뿐이라 a→b 증감이 무의미하다.
        # 조건은 '> a' 가 아니라 '>= a' 다. 2024년 12월 개통을 2024→2025
        # 비교에서 빼야 하는데, '>' 로 두면 하나도 안 걸러진다.
        explained = {c for c in wild.index if events.get(c, -1) >= a}
        rest = sorted(set(wild.index) - explained)
        if explained:
            print(f"  --   {a}→{b} 증감률 500% 초과 {len(wild)}개 중 "
                  f"{len(explained)}개는 {a}년 연중 개통으로 설명됩니다 "
                  f"{sorted(explained)[:5]}")
        say(not rest,
            f"{a}→{b} 설명되지 않는 증감률 500% 초과 {len(rest)}개" +
            ("" if not rest else f" {rest[:5]} — 원본을 확인하세요"))

    print()
    if problems:
        print(f"확인이 필요한 항목 {len(problems)}건")
        return 1
    print("이상 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
