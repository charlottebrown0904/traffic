"""법정동에 인구가 안 붙는 이유를 자료로 가른다.

요구사항 2026-09-10: "법정동에 아직 인구가 표시 안된 곳이 많습니다."

## 내보낸 파일만으로 여기까지는 이미 알아냈다 (2026-09-10)

    칸 종류      인구 붙음      비율
    면·동         480 / 2,606   18.4%
    리              0 / 14,810    0.0%   ← 상위 면·동은 99.4% 가 있다

    인구가 안 붙은 면·동 2,126 중 **2,060(97%)이 '동' 으로 끝난다.**

읍·면은 행정동 이름과 법정동 이름이 같아서 붙고, 도시의 **동**은 다르다.
'달천동'(법정동)은 KOSIS 에 없고 그 자리에 '농소1동'(행정동)이 있다.

## 이 탐침이 답할 것

내보낸 파일에는 **맞은 이름만** 실려 있어서, KOSIS 가 그 시군구에서
어떤 이름을 주는지는 DB(umd_pop)를 봐야 안다. 세 가지를 잰다.

  1) 우리 법정동 이름이 KOSIS 행정동 이름의 **앞자락**인 경우가 얼마나 되나.
     '성산동' → '성산1동'·'성산2동'. 이 규칙만으로 몇 %를 되찾나.
  2) 되찾을 때 한 법정동에 행정동이 여럿 걸리면 어떻게 되나 (합칠지 나눌지).
  3) 그래도 안 붙는 것은 몇 %이고, 그것은 외부 대조표가 있어야만 되나.

**규칙으로 되찾은 인구는 근사다.** 행정동 하나가 법정동 여럿을 덮으면
그 인구를 어느 쪽에 얼마나 줄지 자료가 말해주지 않는다. 그래서 이
탐침은 고치지 않고 **얼마나 되찾을 수 있는지만** 재고, 판단은 사람이
한다.

  실행: PYTHONPATH=src python scripts/umd_pop_probe.py
"""
from __future__ import annotations

import collections
import re
import sys

from redt import db


def head(name: str) -> str:
    """'금남면 국곡리' → '금남면'. 리 이름은 KOSIS 에 없다."""
    return str(name).split(" ")[0]


def kind(name: str) -> str:
    last = str(name).split(" ")[-1]
    if " " in str(name) and last.endswith("리"):
        return "리"
    if last.endswith("읍"):
        return "읍"
    if last.endswith("면"):
        return "면"
    if last.endswith("동") or last.endswith("가"):
        return "동"
    return "기타"


# '성산1동' 에서 '성산' 을 떼는 자.
#
# **꼬리는 숫자만이다.** 처음에 [가-힣]?\d+ 도 허용했더니 '성산1동' 이
# '성' 이 됐다 — 게으른 .+? 가 '성' 만 잡고 '산1' 을 꼬리로 먹었다.
# 한글 한 글자를 꼬리에 넣을 이유가 없다.
# 꼬리에 '6·7' 처럼 여러 번호가 붙기도 한다 (상계6·7동).
STEM = re.compile(r"^(.*?)(?:제?[\d·,\s]*\d)?동$")


def stem(name: str) -> str:
    m = STEM.match(str(name))
    if not m:
        return str(name)
    # '제1동' 처럼 앞자락이 통째로 없어지면 규칙이 성립하지 않는다.
    # 빈 앞자락으로 묶으면 그 시군구의 온갖 동이 한 칸에 뭉친다.
    return m.group(1) or str(name)


def main() -> int:
    with db.connect(read_only=True) as con:
        year = con.execute("SELECT max(year) FROM umd_pop").fetchone()[0]
        if year is None:
            print("umd_pop 이 비어 있습니다 — 먼저 umd-pop 을 돌리세요.")
            return 1
        pop = con.execute(
            "SELECT sigungu_cd, umd, pop FROM umd_pop WHERE year = ?",
            [year]).fetchall()
        ours = con.execute(
            "SELECT sigungu_cd, umd, level FROM region_umd").fetchall()

    print(f"KOSIS {year}년 · 행정동 {len(pop):,}줄 · 우리 법정동 {len(ours):,}줄")

    theirs = collections.defaultdict(dict)      # 시군구 → {행정동: 인구}
    for sg, nm, p in pop:
        theirs[str(sg)][str(nm)] = int(p)

    # 시군구별로 행정동 이름을 앞자락으로 묶어 둔다.
    by_stem = {sg: collections.defaultdict(list) for sg in theirs}
    for sg, names in theirs.items():
        for nm in names:
            by_stem[sg][stem(nm)].append(nm)

    tally = collections.Counter()
    recovered = collections.Counter()
    multi = []
    still = []
    for sg, nm, _lvl in ours:
        sg = str(sg)
        nm = str(nm)
        k = kind(nm)
        tally[k] += 1
        if k == "리":
            # 리는 KOSIS 가 아예 안 준다. 상위 면·동이 있는지만 본다.
            if head(nm) in theirs.get(sg, {}):
                recovered["리→상위 면·동"] += 1
            else:
                still.append((sg, nm, "상위 면·동도 없음"))
            continue
        if nm in theirs.get(sg, {}):
            recovered["이름 그대로"] += 1
            continue
        cand = by_stem.get(sg, {}).get(stem(nm) if k == "동" else nm, [])
        if len(cand) == 1:
            recovered["앞자락 하나"] += 1
        elif len(cand) > 1:
            recovered["앞자락 여럿"] += 1
            if len(multi) < 15:
                multi.append((sg, nm, cand))
        else:
            still.append((sg, nm, "행정동에 비슷한 이름 없음"))

    print("\n우리 칸 종류")
    for k, n in tally.most_common():
        print(f"  {k:5s} {n:7,}")

    total = sum(tally.values())
    print(f"\n되찾는 길 (전체 {total:,}칸)")
    for k, n in recovered.most_common():
        print(f"  {k:14s} {n:7,}  ({n / total:5.1%})")
    print(f"  {'끝내 못 붙음':14s} {len(still):7,}  ({len(still) / total:5.1%})")

    print("\n한 법정동에 행정동이 여럿 걸린 예 (인구를 어떻게 나눌지 자료가 없다)")
    for sg, nm, cand in multi:
        print(f"  {sg} {nm:10s} → {', '.join(cand)}")

    print("\n끝내 못 붙는 것 상위 20")
    for sg, nm, why in still[:20]:
        print(f"  {sg} {nm:14s} {why}")

    # 시군구 하나를 통째로 펼쳐 본다 — 규칙이 왜 되고 왜 안 되는지
    # 눈으로 확인할 수 있어야 한다.
    sample = "31200"
    print(f"\n{sample} 시군구를 펼쳐 봅니다")
    print("  KOSIS 행정동:",
          ", ".join(sorted(theirs.get(sample, {}))[:25]) or "없음")
    mine = sorted(nm for sg, nm, _ in ours if str(sg) == sample)
    print("  우리 법정동 :", ", ".join(mine[:25]) or "없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
