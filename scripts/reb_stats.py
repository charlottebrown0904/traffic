#!/usr/bin/env python3
"""R-ONE Open API — 있는지 보고, 받아서 저장한다.

    python scripts/reb_stats.py --probe                 # 표가 있나 · 키가 도나
    python scripts/reb_stats.py --items A_2024_00007    # 그 표의 항목 ID
    python scripts/reb_stats.py --pull 지가변동률_용도지역_월 --from 201001 --to 202609

이 상자에서는 www.reb.or.kr 로 직접 나갈 수 없다(egress 차단). 서울
중계기를 거친다 — 인증키는 중계기의 `REB_KEY` 에만 있고 이쪽에는 없다.

--probe 를 먼저 돌린다. 명세서에 주기코드(DTACYCLE_CD) 표가 없어서,
틀린 값을 넣으면 오류가 아니라 '자료 없음(200)' 이 온다. 그러면 자료가
없는 것으로 오해한다. --probe 가 목록에서 주기코드를 읽어 찍는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt.collect import reb                                    # noqa: E402
from redt.config import RAW, relay                              # noqa: E402

OUT = RAW / "reb"


def probe() -> int:
    if not relay().enabled:
        print("중계기 설정이 없습니다 (REDT_RELAY_URL · REDT_RELAY_TOKEN).", file=sys.stderr)
        return 2
    print(f"{'이름':<26} {'STATBL_ID':<18} {'주기':<10} {'기간':<12} 공개  통계표명")
    bad = 0
    for name, sid in reb.TABLES.items():
        rows = reb.tables(sid)
        if not rows:
            print(f"{name:<26} {sid:<18} — 목록에 없습니다")
            bad += 1
            continue
        r = rows[0]
        cyc = f"{r.get('DTACYCLE_CD', '')}({r.get('DTACYCLE_NM', '')})"
        span = f"{r.get('DATA_START_YY', '')}~{r.get('DATA_END_YY', '')}"
        print(f"{name:<26} {sid:<18} {cyc:<10} {span:<12} "
              f"{r.get('OPEN_STATE', ''):<4} {r.get('STATBL_NM', '')}")
    print(f"\n확인 {len(reb.TABLES) - bad} / {len(reb.TABLES)}")
    return 1 if bad else 0


def items(statbl_id: str) -> int:
    rows = reb.items(statbl_id)
    print(f"{statbl_id} — 항목 {len(rows)}개")
    for r in rows:
        print(f"  {str(r.get('ITM_ID', '')):>8}  {r.get('ITM_NM', ''):<24} "
              f"{r.get('UI_NM', ''):<10} {r.get('ITM_FULLNM', '')}")
    return 0


COLUMNS = ["STATBL_ID", "WRTTIME_IDTFR_ID", "GRP_ID", "GRP_NM", "CLS_ID", "CLS_NM",
           "ITM_ID", "ITM_NM", "DTA_VAL", "UI_NM", "GRP_FULLNM", "CLS_FULLNM",
           "ITM_FULLNM", "WRTTIME_DESC"]


def pull(name: str, start: str | None, end: str | None) -> int:
    sid = reb.TABLES.get(name)
    if not sid:
        print(f"이름을 모릅니다: {name}\n쓸 수 있는 이름:", file=sys.stderr)
        for k in reb.TABLES:
            print(f"  {k}", file=sys.stderr)
        return 2
    rows = reb.data(sid, start=start, end=end)
    if not rows:
        print(f"{name}({sid}) — 0행. 시점 범위와 주기코드를 --probe 로 확인하세요.")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}_{start or 'all'}_{end or 'all'}.tsv"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(str(r.get(c, "")).replace("\t", " ") for c in COLUMNS) + "\n")
    times = sorted({str(r.get("WRTTIME_IDTFR_ID", "")) for r in rows})
    cls = sorted({str(r.get("CLS_NM", "")) for r in rows})
    print(f"{path} — {len(rows)}행")
    print(f"  시점 {len(times)}개 ({times[0]} ~ {times[-1]})")
    print(f"  분류 {len(cls)}개: {', '.join(cls[:12])}{' …' if len(cls) > 12 else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--items", metavar="STATBL_ID")
    ap.add_argument("--pull", metavar="이름")
    ap.add_argument("--from", dest="start", metavar="YYYYMM")
    ap.add_argument("--to", dest="end", metavar="YYYYMM")
    a = ap.parse_args()
    if a.probe:
        return probe()
    if a.items:
        return items(a.items)
    if a.pull:
        return pull(a.pull, a.start, a.end)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
