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
from redt.collect.http import visible                           # noqa: E402
from redt.config import RAW, relay                              # noqa: E402

OUT = RAW / "reb"

# 한 페이지의 최대 건수. 1,000 을 넘기면 오류 336 이다.
PAGE = 1000


def reach() -> int:
    """직접 부르기와 중계기 부르기를 나란히 재 본다. **키가 없어도 된다.**

    왜 이것을 재는가. 인증키를 Vercel(중계기)에 두는 것이 맞는지, GitHub
    Secrets 에 두고 러너가 직접 부르는 것이 한도에 유리한지가 갈리는
    지점은 하나다 — **www.reb.or.kr 이 미국 IP 에 응답하는가.**

      · 응답한다 → 러너가 직접 부를 수 있다. Vercel 함수 호출도, Fast
        Origin Transfer 도 0 이다. 키는 GitHub Secrets 로 간다.
      · 응답하지 않는다 → 중계기 말고 길이 없다. 키는 Vercel 에 둔다.

    키가 없어도 판정됩니다. 키가 틀리면 R-ONE 은 **HTTP 200 + 코드 290**
    으로 답합니다 — 그 응답이 왔다는 것 자체가 '닿았다' 는 증거입니다.
    반대로 data.go.kr 은 TCP 연결조차 완성되지 않았습니다
    (docs/finding-geoblock.md).
    """
    import time

    import requests

    url = reb.TBL
    q = {"Type": "json", "pIndex": 1, "pSize": 5}

    print("■ 직접 (러너 IP 에서 바로)")
    t0 = time.time()
    try:
        # 중계기를 타지 않도록 requests 를 그대로 쓴다.
        r = requests.get(url, params=q, timeout=20,
                         headers={"User-Agent": "redt-research/0.1"})
        dt = time.time() - t0
        print(f"   HTTP {r.status_code} · {dt:.2f}초 · {len(r.content):,}바이트")
        print(f"   {visible(r.text)}")
        direct_ok = True
    except Exception as exc:
        dt = time.time() - t0
        print(f"   실패 ({dt:.1f}초) — {type(exc).__name__}: {str(exc)[:160]}")
        direct_ok = False
        # **개발 상자에서 돌리면 프록시가 막습니다 — 지오블록이 아닙니다.**
        # 이 둘을 헷갈리면 '해외에서는 안 된다' 는 틀린 결론을 내립니다.
        proxied = isinstance(exc, requests.exceptions.ProxyError) or "roxy" in str(exc)
        if proxied:
            print("   ⚠ 이것은 이 상자의 egress 차단입니다(프록시). 지오블록이 아닙니다.")
            print("     판정은 **GitHub Actions 러너**에서만 유효합니다 —")
            print("     Actions → '지가변동률 수집' → mode: reach 로 다시 재십시오.")
            direct_ok = None

    print("\n■ 중계기 (서울 icn1 경유)")
    if not relay().enabled:
        print("   중계기 설정이 없습니다 (REDT_RELAY_URL · REDT_RELAY_TOKEN)")
        relay_ok = None
    else:
        t0 = time.time()
        try:
            resp = reb.get_raw(url, q)
            dt = time.time() - t0
            print(f"   HTTP {resp.status_code} · {dt:.2f}초 · {len(resp.content):,}바이트")
            print(f"   {visible(resp.text)}")
            relay_ok = True
        except Exception as exc:
            dt = time.time() - t0
            print(f"   실패 ({dt:.1f}초) — {type(exc).__name__}: {str(exc)[:160]}")
            relay_ok = False

    print("\n■ 판정")
    if direct_ok is None:
        print("   아직 판정할 수 없습니다 — 러너에서 재야 합니다(위 ⚠).")
        print("   그때까지는 키를 Vercel(REB_KEY)에 두는 지금 방식이 맞습니다.")
        return 0
    if direct_ok:
        print("   직접 부르기가 **됩니다.** 대량 backfill 은 러너가 직접 부르는 쪽이")
        print("   낫습니다 — Vercel 함수 호출 0회, Fast Origin Transfer 0바이트.")
        print("   키는 GitHub Secrets(REB_KEY)에 두고, 없으면 중계기로 물러납니다.")
    else:
        print("   직접 부르기가 **안 됩니다.** 중계기 말고 길이 없습니다.")
        print("   키는 Vercel(REB_KEY)에 둡니다. 대신 받는 양을 끊어 받습니다")
        print("   (--pull 은 --max-pages 로 막습니다).")
    if relay_ok is False and direct_ok:
        print("   중계기가 실패한 것은 REB_KEY 미설정일 수 있습니다 — 직접 길이 있으니 문제 없습니다.")
    return 0


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


def pull(name: str, start: str | None, end: str | None, max_pages: int = 40) -> int:
    sid = reb.TABLES.get(name)
    if not sid:
        print(f"이름을 모릅니다: {name}\n쓸 수 있는 이름:", file=sys.stderr)
        for k in reb.TABLES:
            print(f"  {k}", file=sys.stderr)
        return 2
    direct = bool(reb.keys().reb)
    print(f"길: {'직접 (러너 IP)' if direct else '중계기 (서울 icn1 경유)'}"
          f" · 한 장 {PAGE:,}건 · 최대 {max_pages}장")
    rows = reb.data(sid, start=start, end=end, max_pages=max_pages)
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

    # 한도 계산. 중계기를 탄 경우 이 숫자가 곧 Vercel 사용량이다 —
    # 한 장이 함수 호출 한 번이고, 받은 바이트가 Fast Origin Transfer 다.
    import json as _json
    wire = len(_json.dumps(rows, ensure_ascii=False).encode())
    calls = (len(rows) + PAGE - 1) // PAGE
    print(f"  이번 호출: {calls}장 · 약 {wire / 1e6:.1f}MB")
    if not direct:
        print(f"  → Vercel 함수 호출 {calls}회 · Fast Origin Transfer 약 "
              f"{wire / 1e6:.1f}MB 를 썼습니다 (한도 1M회 / 10GB per month)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reach", action="store_true",
                    help="직접/중계기 두 길을 나란히 재 본다 (키 없어도 됨)")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--items", metavar="STATBL_ID")
    ap.add_argument("--pull", metavar="이름")
    ap.add_argument("--from", dest="start", metavar="YYYYMM")
    ap.add_argument("--to", dest="end", metavar="YYYYMM")
    ap.add_argument("--max-pages", type=int, default=40,
                    help="안전장치. 중계기를 타면 한 장이 함수 호출 한 번이다")
    a = ap.parse_args()
    if a.reach:
        return reach()
    if a.probe:
        return probe()
    if a.items:
        return items(a.items)
    if a.pull:
        return pull(a.pull, a.start, a.end, a.max_pages)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
