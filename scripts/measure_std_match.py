#!/usr/bin/env python3
"""평가사가 고른 비교표준지가 대상과 **무엇을** 맞추고 있나 (2026-09-17 지시).

지시: "현재 가치 분석 시 최대한 인근 표준지 중 (최대한 유사한 용도지역,
도로 조건, 지목, 경사도)로 선정될 수 있도록 검토."

선정 규칙의 무게(valuation.PEN_*)를 **지어내지 않고 원장에서 읽는다.**
평가사가 실제로 고른 표준지가 대상과 얼마나 같은지를 세면, 그 비율이 곧
그 항목이 선정에서 갖는 무게다. 100% 에 가까우면 거를 것이고, 절반쯤이면
선정 조건이 아니라 격차율로 메울 것이다.

**정규화는 저장소 함수를 그대로 쓴다.** 여기서 규칙을 새로 지으면 재는
것과 화면이 쓰는 것이 갈라져, 맞춘 무게가 실제로는 안 맞는다.

자료 만들기 — 평가서 원장은 Supabase 에 있고 지번·주소가 섞여 있으므로
**이 저장소에 커밋하지 않는다.** 아래 SQL 의 결과(JSON 배열)를 임시
파일로 내려받아 경로를 넘긴다. 같은 읍·면·동 여부는 SQL 에서 참/거짓으로
바꿔 주소 자체는 안 들고 온다.

    select jsonb_agg(to_jsonb(x)) from (
      select jimok, land_use, use_situation, road, shape, slope,
             std_jimok, std_land_use, std_use_situation, std_road,
             std_shape, std_slope,
             (std_addr is not null and umd is not null
                and position(btrim(umd) in std_addr) > 0) as same_umd,
             official_price, std_price
      from public.appraisal_case) x;

실행:  python scripts/measure_std_match.py <내려받은.json>
결과는 docs/appraisal-standard.md §2-6 에 적는다.
"""
import collections
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redt.usage import road_grade                                  # noqa: E402
from redt.valuation import (zone_group, use_group, shape_index,    # noqa: E402
                            slope_index, price_level_penalty)


def main(path: str) -> int:
    rows = json.load(io.open(path, encoding="utf-8"))
    if isinstance(rows, dict):          # {"jsonb_agg": [...]} 꼴도 받는다
        rows = next(iter(rows.values()))

    def pair(a, b, f):
        """둘 다 있고 둘 다 정규화되는 건만 센다. 한쪽이 비면 '다름' 이 아니라 '모름'."""
        if a in (None, "") or b in (None, ""):
            return None
        x, y = f(a), f(b)
        return None if x is None or y is None else x == y

    tally = collections.OrderedDict()

    def add(k, v):
        t = tally.setdefault(k, [0, 0])
        if v is None:
            return
        t[1] += 1
        if v:
            t[0] += 1

    roaddiff = collections.Counter()
    ratios = []
    for r in rows:
        add("용도지역군 (자연녹지/계획관리 …)", pair(r["land_use"], r["std_land_use"], zone_group))
        add("용도지역 앞 4글자", pair(r["land_use"], r["std_land_use"], lambda s: str(s)[:4]))
        add("지목군", pair((r["jimok"], r["use_situation"]),
                         (r["std_jimok"], r["std_use_situation"]),
                         lambda t: use_group(t[0], t[1])))
        add("지목 글자 그대로", pair(r["jimok"], r["std_jimok"], lambda s: str(s).strip()))
        add("도로접면 등급", pair(r["road"], r["std_road"], road_grade))
        add("형상", pair(r["shape"], r["std_shape"], shape_index))
        add("지세(경사)", pair(r["slope"], r["std_slope"], lambda s: slope_index(s, "*")))
        add("같은 읍·면·동", r.get("same_umd"))
        g1, g2 = road_grade(r["road"]), road_grade(r["std_road"])
        if g1 is not None and g2 is not None:
            roaddiff[abs(g1 - g2)] += 1
        _, k = price_level_penalty(r["official_price"], r["std_price"])
        if k:
            ratios.append(k)

    print("평가서 원장 %d건 — 평가사가 고른 표준지가 대상과 일치한 비율\n" % len(rows))
    print("%-28s %8s %8s %8s" % ("항목", "일치", "잰 건수", "비율"))
    for k, (hit, n) in tally.items():
        print("%-28s %8d %8d %7.0f%%" % (k, hit, n, 100 * hit / n if n else 0))

    # 도로접면은 '다르다' 만으로는 부족하다 — 한 단 차와 두 단 차는 다른 일이다.
    print("\n도로접면 등급 차 분포 (0 = 같음)")
    tot = sum(roaddiff.values()) or 1
    for d in sorted(roaddiff):
        print("  %d단 차  %4d건  %5.0f%%" % (d, roaddiff[d], 100 * roaddiff[d] / tot))

    if ratios:
        ratios.sort()
        def q(p):
            return ratios[int(len(ratios) * p)]
        print("\n표준지 공시지가 ÷ 대상 개별공시지가  (%d건)" % len(ratios))
        print("  중앙 %.2f · 사분위 %.2f~%.2f · PRICE_BAND(0.5~2.0) 안 %.0f%%"
              % (q(.5), q(.25), q(.75),
                 100 * sum(1 for x in ratios if 0.5 <= x <= 2.0) / len(ratios)))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
