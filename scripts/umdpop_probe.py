"""읍·면·동 인구를 KOSIS 에서 받을 수 있는가 — 탐침.

사장님 지시(2026-09-09): "읍면동 인구를 KOSIS 에서 따로 받아올 수
있습니다 — 다음 건으로 잡을까요?" 에 대해 "적용합니다".

## 왜 탐침부터인가

지금 인구는 **시군구까지**입니다(DT_1B040A3). 그래서 땅값 글자 옆의
(XX만)이 시·도와 시·군·구에만 붙고 읍·면·동에는 안 붙습니다.
없는 것을 시군구 값으로 채우면 리 하나가 20만인 것처럼 읽히므로
비워 둔 것입니다.

읍면동 표의 ID 를 **기억으로 적으면 안 됩니다.** 이 저장소는 레이어
이름을 세 번 틀렸고 공시지가 원천도 추측으로 시작했다가 헛돌았습니다.
KOSIS 검색으로 **찾아서** 씁니다.

## 무엇을 확인하는가

  1. '읍면동' 인구 표가 검색에 잡히는가 — orgId·tblId 를 받아 적는다
  2. 그 표가 우리 창(2006~2025)을 덮는가
  3. 실제로 한 해를 받아 보면 무엇이 오는가 — 코드 자릿수가 관건이다

**코드 자릿수가 급소입니다.** 우리 거래는 법정동 **이름**만 갖고
있습니다(umd). KOSIS 가 행정동 코드로 주면 법정동과 짝이 안 맞습니다 —
행정동 '중앙동' 하나가 법정동 여럿을 덮는 일이 흔합니다. 이름으로
붙일 수 있는지까지 봐야 '된다' 고 말할 수 있습니다.

  python scripts/umdpop_probe.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect import kosis                              # noqa: E402
from redt.config import relay                               # noqa: E402

TERMS = [
    "행정구역(읍면동)별 인구",
    "읍면동별 주민등록인구",
    "행정구역별 주민등록인구",
    "읍면동",
]

# 우리가 쓰는 창. 이보다 짧으면 최근 것만 쓰거나 포기해야 한다.
WANT_FROM, WANT_TO = "2006", "2025"


def head(t: str) -> None:
    print()
    print(t)
    print("-" * len(t))


def main() -> int:
    print("=" * 68)
    print(" 읍·면·동 인구 탐침 (KOSIS)")
    print("=" * 68)
    print(f"  중계기 {'경유' if relay().enabled else '없음 (직접 호출)'}")

    head("1. 검색 — 읍면동 인구 표가 있는가")
    found: dict[str, dict] = {}
    for term in TERMS:
        try:
            rows = kosis.search(term)
        except Exception as exc:                            # noqa: BLE001
            print(f"  · '{term}' 실패 — {type(exc).__name__}: {str(exc)[:120]}")
            continue
        print(f"  · '{term}' → {len(rows)}건")
        for r in rows:
            name = str(r.get("TBL_NM") or r.get("tblNm") or "")
            org = str(r.get("ORG_ID") or r.get("orgId") or "")
            tbl = str(r.get("TBL_ID") or r.get("tblId") or "")
            if not (org and tbl):
                continue
            # 읍면동이 이름에 있고 인구/세대 얘기인 것만 추린다.
            if "읍면동" not in name:
                continue
            if not any(w in name for w in ("인구", "세대")):
                continue
            found[f"{org}|{tbl}"] = {
                "org": org, "tbl": tbl, "name": name,
                "from": str(r.get("PRD_DE_S") or r.get("prdDeS") or ""),
                "to": str(r.get("PRD_DE_E") or r.get("prdDeE") or ""),
            }
    if not found:
        print("\n  ⛔ 읍면동 인구 표를 못 찾았습니다.")
        print("     검색어를 바꿔 다시 돌리거나, KOSIS 화면에서 직접")
        print("     찾아 orgId·tblId 를 알려 주십시오.")
        return 0

    head("2. 찾은 표 — 우리 창(2006~2025)을 덮는가")
    for v in found.values():
        span = f"{v['from']}~{v['to']}" if v["from"] else "기간 미상"
        ok = (v["from"] and v["from"][:4] <= WANT_FROM
              and v["to"] and v["to"][:4] >= WANT_TO)
        mark = "✓" if ok else ("?" if not v["from"] else "△")
        print(f"  {mark} {v['org']}/{v['tbl']}  {span}")
        print(f"      {v['name']}")

    head("3. 표에 무엇을 물어야 하는가 — 분류축과 항목을 먼저 받는다")
    print("  지난 탐침이 200 에 실려 온 오류를 성공으로 읽었다 —")
    print("  '1행 · 코드 자릿수 [0]' 이 그것이었다. 이제는 err 를 잡는다.")
    print()
    print("  읍면동 표는 축이 둘 이상이다(지역 × 5세별). objL1 만 보내면")
    print("  '필수요청변수값이 누락되었습니다 (objL)' 로 막힌다. 축 이름을")
    print("  기억으로 적지 않고 **물어본다.**")

    picked = None
    for v in list(found.values())[:4]:
        print(f"\n  · {v['org']}/{v['tbl']}  {v['name'][:40]}")
        try:
            objs = kosis.fetch_meta(v["org"], v["tbl"], "OBJ")
        except Exception as exc:                            # noqa: BLE001
            print(f"      분류축 못 받음 — {type(exc).__name__}: {str(exc)[:120]}")
            continue
        # 축 이름(objL1/objL2…)과 그 축의 코드 몇 개.
        axes: dict[str, list[tuple[str, str]]] = {}
        for r in objs:
            ax = str(r.get("OBJ_ID") or r.get("objId") or "")
            code = str(r.get("ITM_ID") or r.get("OBJ_ITM_ID")
                       or r.get("objItmId") or r.get("C1") or "")
            name = str(r.get("OBJ_ITM_NM") or r.get("objItmNm")
                       or r.get("ITM_NM") or "")
            if ax:
                axes.setdefault(ax, []).append((code, name))
        for ax, vals in axes.items():
            head3 = " · ".join(f"{c}={n}" for c, n in vals[:3])
            print(f"      {ax}  {len(vals)}개  {head3}")
        try:
            itms = kosis.fetch_meta(v["org"], v["tbl"], "ITM")
            names = [str(r.get("ITM_NM") or r.get("itmNm") or "") for r in itms]
            ids = [str(r.get("ITM_ID") or r.get("itmId") or "") for r in itms]
            print(f"      항목 {len(itms)}개: "
                  + " · ".join(f"{i2}={n}" for i2, n in list(zip(ids, names))[:5]))
            # 총인구를 고른다. 없으면 첫 항목.
            tot = next((i2 for i2, n in zip(ids, names) if "총인구" in n), None)
            if picked is None and axes:
                picked = {"v": v, "axes": axes, "itm": tot or (ids[0] if ids else "ALL")}
        except Exception as exc:                            # noqa: BLE001
            print(f"      항목 못 받음 — {type(exc).__name__}: {str(exc)[:120]}")

    head("4. 축을 채워 한 조각만 받아 본다 — 코드가 무엇으로 오는가")
    print("  **자릿수가 급소다.** 우리 거래에는 법정동 '이름' 만 있다.")
    print("  KOSIS 가 행정동 코드로 주면 짝이 안 맞는다 — 행정동 '중앙동'")
    print("  하나가 법정동 여럿을 덮는 일이 흔하다.")
    if not picked:
        print("\n  ⛔ 분류축을 못 받아 여기서 멈춥니다.")
        return 0

    v = picked["v"]
    axes = picked["axes"]
    ax_names = sorted(axes)
    print(f"\n  고른 표: {v['org']}/{v['tbl']}")
    print(f"  축 {ax_names} · 항목 {picked['itm']}")

    # 첫 축은 지역이다. **전국을 한 번에 부르면 4만 셀을 넘긴다** —
    # 지난 탐침의 err 31 이 그것이었다. 지역 코드 하나만 넣어 본다.
    first_ax = ax_names[0]
    region_codes = [c for c, _ in axes[first_ax] if c]
    tries = region_codes[:2] or ["ALL"]
    for rc in tries:
        obj = {ax: "ALL" for ax in ax_names[1:]}
        print(f"\n  · {first_ax}={rc} · " + " · ".join(f"{k}={x}" for k, x in obj.items()))
        try:
            rows = kosis.fetch_table(v["org"], v["tbl"], "2024", "2024",
                                     obj_l1=rc, itm_id=picked["itm"],
                                     obj=obj, quiet=True)
        except Exception as exc:                            # noqa: BLE001
            print(f"      막힘 — {type(exc).__name__}: {str(exc)[:200]}")
            continue
        print(f"      {len(rows):,}행")
        for r in rows[:5]:
            print("      " + " | ".join(
                f"{k}={r.get(k)}" for k in ("C1", "C1_NM", "C2", "C2_NM",
                                            "ITM_NM", "DT") if r.get(k)))
        lens = sorted({len(str(r.get("C1") or "")) for r in rows})
        lens2 = sorted({len(str(r.get("C2") or "")) for r in rows})
        print(f"      C1 자릿수 {lens} · C2 자릿수 {lens2}")

    print()
    print("=" * 68)
    print(" 읽는 법")
    print("=" * 68)
    print("  1절이 비면        → 검색어를 바꾼다. 없는 것이 아니라 못 찾은 것이다.")
    print("  2절이 △ 면        → 최근 몇 해만 쓴다. 옛 해는 시군구로 남긴다.")
    print("  3절이 막히면      → 그 표는 못 쓴다. 다음 후보로 간다.")
    print("  4절 C1 이 10자리  → 법정동코드다. 그대로 붙는다.")
    print("  4절 C1 이 7~8자리 → 행정동코드다. 법정동과 1:1 이 아니다 —")
    print("                      이름으로 붙이되 못 붙는 것을 세어 밝힌다.")
    print("  4절이 err 31 이면 → 아직 크다. 축을 더 잘게 쪼갠다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
