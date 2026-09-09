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

    head("3. 무엇을 어디로 보내야 하는가 — 조합을 하나씩 두드린다")
    print("  run 68 에서 메타 엔드포인트도 err 20 을 냈다. 이름을 한 번 더")
    print("  추측하는 대신 **후보를 다 두드려 보고 답하는 것을 쓴다.**")

    top = list(found.values())[:1]
    if not top:
        print("\n  ⛔ 볼 표가 없습니다.")
        return 0
    v = top[0]
    print(f"\n  대상: {v['org']}/{v['tbl']}  {v['name'][:44]}")

    print("\n  (가) 메타 엔드포인트 후보")
    meta_ok = None
    for url in kosis.META_URLS:
        for kind in ("OBJ", "ITM"):
            try:
                rows = kosis.fetch_meta(v["org"], v["tbl"], kind, url=url)
            except Exception as exc:                        # noqa: BLE001
                print(f"      {url.rsplit('/', 1)[-1]:<28} {kind}  "
                      f"{type(exc).__name__}: {str(exc)[:70]}")
                continue
            print(f"      {url.rsplit('/', 1)[-1]:<28} {kind}  ✓ {len(rows)}건")
            if rows:
                print(f"          칸: {sorted(rows[0])[:10]}")
                print(f"          첫 줄: {dict(list(rows[0].items())[:6])}")
            if kind == "OBJ" and rows and meta_ok is None:
                meta_ok = (url, rows)

    print("\n  (나) 자료 요청 — 축을 몇 개까지 채워야 통과하는가")
    # err 20 은 '축이 모자라다', err 31 은 '너무 크다'. **둘은 다른 말이다** —
    # 31 이 나오면 파라미터는 맞은 것이고 범위만 줄이면 된다.
    combos = [
        ({}, "objL1 만"),
        ({"objL2": "ALL"}, "objL1+objL2"),
        ({"objL2": "ALL", "objL3": "ALL"}, "objL1+2+3"),
        ({"objL2": "ALL", "objL3": "ALL", "objL4": "ALL"}, "objL1+2+3+4"),
    ]
    passed = None
    for obj, label in combos:
        try:
            rows = kosis.fetch_table(v["org"], v["tbl"], "2024", "2024",
                                     obj=obj, quiet=True)
        except Exception as exc:                            # noqa: BLE001
            print(f"      {label:<14} {type(exc).__name__}: {str(exc)[:80]}")
            continue
        print(f"      {label:<14} ✓ {len(rows):,}행")
        passed = (obj, rows)
        break

    head("4. 축의 코드를 받아 범위를 줄인다")
    # run 69 가 답을 줬다 —
    #   objL1 만     err 20  축이 모자라다
    #   objL1+objL2  err 31  **4만 셀 초과** ← 파라미터는 맞았다
    #   objL1+2+3    err 21  잘못된 요청 변수 ← 축은 정확히 둘
    #
    # 그러니 남은 일은 범위를 줄이는 것뿐이다. 연령 축(objL2)을 '계'
    # 하나로 고정하면 읍면동 5천 × 1 × 1 이라 4만 아래로 내려온다.
    # **그 '계' 코드를 기억으로 적지 않는다** — 목록을 받아 고른다.
    print("  축은 둘이고(지역 × 연령) objL1+objL2 가 맞는 조합이다.")
    print("  남은 일은 4만 셀 아래로 줄이는 것 — 연령을 '계' 하나로 고정한다.")

    print("\n  (다) 분류·항목 목록 — statisticsData.do 가 답한 그것")
    try:
        rows = kosis.fetch_meta(v["org"], v["tbl"], "ITM",
                                url="https://kosis.kr/openapi/statisticsData.do")
    except Exception as exc:                                # noqa: BLE001
        print(f"      못 받음 — {type(exc).__name__}: {str(exc)[:120]}")
        return 0
    axes: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        ax = str(r.get("OBJ_ID") or "")
        code = str(r.get("ITM_ID") or "")
        name = str(r.get("ITM_NM") or r.get("ITM_NM_ENG") or "")
        axes.setdefault(ax or "(ITM)", []).append((code, name))
    for ax, vals in axes.items():
        print(f"      {ax or '(항목)':<10} {len(vals):>6,}개  "
              + " · ".join(f"{c}={n}" for c, n in vals[:4]))

    # '계' 로 읽히는 코드를 고른다. 이름에 계·전체·합계·Total 이 든 것.
    def is_total(name: str) -> bool:
        return any(w in name for w in ("계", "전체", "합계", "Total", "total"))

    print("\n  (라) '계' 로 보이는 코드")
    totals: dict[str, list[tuple[str, str]]] = {}
    for ax, vals in axes.items():
        hit = [(c, n) for c, n in vals if is_total(n)][:5]
        if hit:
            totals[ax] = hit
            print(f"      {ax or '(항목)':<10} "
                  + " · ".join(f"{c}={n}" for c, n in hit))
    if not totals:
        print("      없음 — 이름으로는 못 고릅니다. 목록을 눈으로 보셔야 합니다.")

    print("\n  (마) 그 코드로 실제 호출 — 4만 셀 아래로 내려오는가")
    # 항목은 Population(T2) 하나로 고정한다. 연령 축의 '계' 후보를
    # 하나씩 넣어 본다.
    itm = next((c for ax, vals in axes.items() for c, n in vals
                if "Population" in n or n == "인구"), "T2")
    cands = [c for ax, hit in totals.items() for c, _ in hit][:4] or ["ALL"]
    for c2 in cands:
        try:
            got = kosis.fetch_table(v["org"], v["tbl"], "2024", "2024",
                                    obj_l1="ALL", itm_id=itm,
                                    obj={"objL2": c2}, quiet=True)
        except Exception as exc:                            # noqa: BLE001
            print(f"      objL2={c2:<12} {type(exc).__name__}: {str(exc)[:70]}")
            continue
        print(f"      objL2={c2:<12} ✓ {len(got):,}행")
        for r in got[:5]:
            print("          " + " | ".join(
                f"{k}={r.get(k)}" for k in ("C1", "C1_NM", "C2", "C2_NM",
                                            "ITM_NM", "PRD_DE", "DT")
                if r.get(k) is not None))
        lens = sorted({len(str(r.get("C1") or "")) for r in got})
        print(f"          C1 자릿수 {lens}")
        break

    print()
    print("=" * 68)
    print(" 읽는 법")
    print("=" * 68)
    print("  1절이 비면        → 검색어를 바꾼다. 없는 것이 아니라 못 찾은 것이다.")
    print("  2절이 △ 면        → 최근 몇 해만 쓴다. 옛 해는 시군구로 남긴다.")
    print("  3-나 가 err 31 이면 → **파라미터는 맞았다.** 범위만 줄이면 된다.")
    print("  4-마 가 통과하면   → 그 조합으로 수집기를 쓴다.")
    print("  4절 C1 이 10자리   → 법정동코드다. 그대로 붙는다.")
    print("  4절 C1 이 7~8자리  → 행정동코드다. 법정동과 1:1 이 아니다 —")
    print("                       이름으로 붙이되 못 붙는 것을 세어 밝힌다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
