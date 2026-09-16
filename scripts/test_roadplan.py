"""제2차 고속도로 건설계획 37건이 고시 원문과 같은가 (2026-09-16).

관보 스캔본에 글자층이 없어 **눈으로 읽어 옮긴** 자료다. 그래서 옮겨
적다 틀릴 수 있다. 다행히 고시가 **소계와 총계를 같이 적어 뒀다** —
우리가 더한 값과 그것이 맞으면 한 줄도 안 틀렸다는 뜻이다.

옮겨 적기는 한 번이지만 검산은 매번 돈다. 나중에 누가 한 줄을 고치면
여기서 걸린다.

  python scripts/test_roadplan.py
"""
from __future__ import annotations

import csv
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "road" / "plan2.tsv"

failed = 0


def check(ok: bool, name: str, detail: str = "") -> None:
    global failed
    print(f"  {'통과' if ok else '실패'}  {name}{'' if ok or not detail else ' — ' + detail}")
    if not ok:
        failed += 1


# 고시가 적어 둔 값 (관보 제20181호 3·4쪽)
WANT = {
    ("신설", "중점"): (8, 323.9, 215_375),
    ("신설", "일반"): (11, 446.5, 250_489),
    ("신설", None): (19, 770.4, 465_864),
    ("확장", "중점"): (5, 83.6, 19_963),
    ("확장", "일반"): (13, 265.5, 64_187),
    ("확장", None): (18, 349.1, 84_150),
}


def main() -> None:
    print("제2차 고속도로 건설계획 — 고시 원문과 대조")
    print()
    rows = [r for r in SRC.open(encoding="utf-8") if not r.startswith("#")]
    d = list(csv.DictReader(rows, delimiter="\t"))
    check(len(d) == 37, "사업이 37건이다", f"{len(d)}건")

    for (kind, tier), (n0, km0, c0) in WANT.items():
        s = [x for x in d if x["kind"] == kind and (tier is None or x["tier"] == tier)]
        km = round(sum(float(x["km"]) for x in s), 1)
        c = sum(int(x["cost_eok"]) for x in s)
        label = f"{kind} {tier or '총계'}"
        check((len(s), km, c) == (n0, km0, c0), f"{label} 건수·연장·사업비",
              f"{len(s)}건 {km}km {c:,}억 (고시 {n0}건 {km0}km {c0:,}억)")

    # 사업명을 '-' 로 가른 두 끝이 실제로 사업명과 맞는가.
    bad = [x["name"] for x in d
           if not x["name"].startswith(x["from_pt"])
           or x["to_pt"] not in x["name"]]
    check(not bad, "두 끝(from_pt·to_pt)이 사업명과 어긋나지 않는다", str(bad[:3]))

    # 확장에는 차로수가 있고 신설에는 없다 — 고시 표가 그렇게 생겼다.
    n_new = [x for x in d if x["kind"] == "신설" and x["lanes"]]
    n_ext = [x for x in d if x["kind"] == "확장" and not x["lanes"]]
    check(not n_new and not n_ext, "차로수는 확장에만 있다",
          f"신설에 있는 것 {len(n_new)} · 확장에 없는 것 {len(n_ext)}")

    # 분류(추진과제)가 한 줄도 안 빠졌는가. 본문 부록에만 있는 칸이라
    # 고시문만 보고 옮기면 통째로 빠진다.
    cats = {x["category"] for x in d}
    check(cats <= {"①균형", "②혼잡", "③물류", "④미래"} and "?" not in cats,
          "분류가 네 가지 안에 있고 빠진 줄이 없다", str(sorted(cats)))
    ext_cat = {x["category"] for x in d if x["kind"] == "확장"}
    check(ext_cat == {"②혼잡"}, "확장 18건은 전부 혼잡 과제다", str(sorted(ext_cat)))

    # 출처를 파일이 스스로 밝히는가 — 계획은 개정된다.
    head = SRC.read_text(encoding="utf-8")[:1200]
    check("제2022-60호" in head and "2022-02-04" in head and "도로법 제6조" in head,
          "파일이 고시 번호·날짜·근거를 적고 있다")

    print()
    print(f"실패 {failed}건" if failed else "모두 통과")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
