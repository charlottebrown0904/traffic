"""지번 추론을 어느 시군구부터 돌 것인가 — 순서를 정한다.

지시(2026-09-19): "그 방법 밖에 없다면 서울/경기부터해서 시군구 순서를
짜주세요."

## 무엇을 기준으로 줄을 세우나

시도 순서는 지시대로 **서울 → 경기 → 인천** 을 앞에 둔다. 그 안에서는
**거래 건수**로 줄을 세운다. 같은 하루를 써도 거래가 많은 곳을 먼저 돌면
그날 되찾는 지번이 더 많다.

거래 건수는 **지분 거래를 뺀 것**으로 센다. 지분 거래는 엔진이 다루지
않으므로 세어 봐야 얻을 게 없다.

## 비용도 같이 센다

시군구마다 드는 브이월드 호출 수는 **거래가 퍼져 있는 네모의 넓이**로
정해진다 (0.01도 칸으로 훑는다). 넓은 군은 좁은 구보다 몇 배 든다.
그래서 건수만 보지 않고 '호출 한 번에 몇 건을 얻는가' 도 함께 찍는다.

  python scripts/sigungu_order.py            # 표로 본다
  python scripts/sigungu_order.py --out a.json  # 워크플로가 읽을 목록
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402

from redt.config import DB_PATH                             # noqa: E402

TILE_DEG = 0.01
PAD_DEG = 0.02
# 지시대로 앞에 두는 시도. 나머지는 이 뒤에 거래 건수 순으로 붙는다.
HEAD = ["11", "41", "28"]          # 서울 · 경기 · 인천
SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
    "43": "충북", "44": "충남", "45": "전북", "46": "전남", "47": "경북",
    "48": "경남", "50": "제주", "51": "강원", "52": "전북",
}


def arg(name, default=None):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main() -> int:
    db = pathlib.Path(arg("--db", str(DB_PATH)))
    if not db.exists():
        print(f"  {db} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")
        return 1
    con = duckdb.connect()
    con.execute(f"ATTACH '{db}' AS src (READ_ONLY)")

    rows = con.execute("""
        SELECT t.sigungu_cd,
               count(*) AS n,
               min(t.lat), max(t.lat), min(t.lon), max(t.lon),
               count(*) FILTER (WHERE t.lat IS NOT NULL) AS n_xy
        FROM src.trade t
        WHERE NOT coalesce(t.is_cancelled, FALSE)
          AND NOT coalesce(t.is_share_deal, FALSE)
          AND t.area_m2 > 0 AND t.jibun IS NOT NULL
          AND t.sigungu_cd IS NOT NULL
        GROUP BY 1
    """).fetchall()

    name = dict(con.execute("""
        SELECT sigungu_cd, any_value(sigungu) FROM src.region_umd
        WHERE sigungu IS NOT NULL AND sigungu <> '' GROUP BY 1
    """).fetchall())

    # **이미 갖고 있는 것을 먼저 센다.** 다시 받을 이유가 없으면 안 받는다.
    have = dict(con.execute("""
        SELECT sigungu_cd, count(*) FROM src.parcel
        WHERE sigungu_cd IS NOT NULL AND area_m2 > 0 GROUP BY 1
    """).fetchall())

    out = []
    for sgg, n, la0, la1, lo0, lo1, n_xy in rows:
        if not n_xy or la0 is None:
            tiles = None
        else:
            w, s = lo0 - PAD_DEG, la0 - PAD_DEG
            e, nn = lo1 + PAD_DEG, la1 + PAD_DEG
            tiles = (max(1, math.ceil((e - w) / TILE_DEG))
                     * max(1, math.ceil((nn - s) / TILE_DEG)))
        out.append({
            "sigungu_cd": sgg,
            "sido": SIDO.get(sgg[:2], sgg[:2]),
            "name": name.get(sgg, ""),
            "trades": int(n),
            "parcels_have": int(have.get(sgg, 0)),
            "tiles": tiles,
            "per_call": round(n / tiles, 2) if tiles else None,
        })

    # 지시한 시도를 앞에, 그 안에서는 거래 많은 곳부터.
    def key(r):
        p = HEAD.index(r["sigungu_cd"][:2]) if r["sigungu_cd"][:2] in HEAD else len(HEAD)
        return (p, -r["trades"])

    out.sort(key=key)
    for i, r in enumerate(out, 1):
        r["order"] = i

    tot_t = sum(r["trades"] for r in out)
    tot_c = sum(r["tiles"] or 0 for r in out)
    print("=" * 74)
    print(" 지번 추론 순서 — 서울 · 경기 · 인천 먼저, 그 안에서는 거래 많은 곳부터")
    print("=" * 74)
    print(f"\n  시군구 {len(out)}곳 · 통거래 {tot_t:,}건 · 브이월드 칸 {tot_c:,}개")
    for cap in (4000, 10000, 100000):
        print(f"    하루 {cap:,}건이면 {math.ceil(tot_c / cap):,}일")

    tot_h = sum(r["parcels_have"] for r in out)
    print(f"  **이미 받아 둔 필지 {tot_h:,}개** — 이것부터 쓰고 모자란 것만 받습니다")

    print(f"\n  {'#':>4} {'코드':<7}{'시도':<5}{'시군구':<12}{'통거래':>9}"
          f"{'가진 필지':>10}{'필지/거래':>10}{'칸':>8}  누적일(4천)")
    run = 0
    for r in out[:60]:
        run += r["tiles"] or 0
        ratio = r["parcels_have"] / r["trades"] if r["trades"] else 0
        print(f"  {r['order']:>4} {r['sigungu_cd']:<7}{r['sido']:<5}"
              f"{(r['name'] or '')[:11]:<12}{r['trades']:>9,}"
              f"{r['parcels_have']:>10,}{ratio:>10.1f}"
              f"{(r['tiles'] or 0):>8,}{math.ceil(run / 4000):>10,}")
    if len(out) > 60:
        print(f"  … 외 {len(out) - 60}곳")

    print("\n  시도별 묶음")
    print(f"    {'시도':<6}{'시군구':>7}{'통거래':>11}{'가진 필지':>12}"
          f"{'칸':>10}{'일(4천)':>10}")
    agg = {}
    for r in out:
        a = agg.setdefault(r["sido"], [0, 0, 0, 0])
        a[0] += 1
        a[1] += r["trades"]
        a[2] += r["tiles"] or 0
        a[3] += r["parcels_have"]
    for sd in sorted(agg, key=lambda s: -agg[s][1]):
        c, t, k, h = agg[sd]
        print(f"    {sd:<6}{c:>7,}{t:>11,}{h:>12,}{k:>10,}"
              f"{math.ceil(k / 4000):>10,}")

    # 가진 것이 얼마나 되나 — 필지 표가 왜 성긴지까지 같이 본다.
    print("""
  가진 필지가 왜 적은가
    landchar 의 tiles_for() 는 **거래 좌표가 있는 칸만** 만듭니다.
    그런데 그 거래 좌표는 가려진 지번을 지오코딩한 것이라, 한 법정동의
    거래 수백 건이 서로 다른 점 아홉 개로 뭉쳐 있었습니다. 그래서 그
    아홉 점 둘레만 받았습니다 — 빠진 곳이 고르게 빠진 것이 아닙니다.""")
    print(f"    {'시군구':<12}{'통거래':>9}{'가진 필지':>11}{'필지/거래':>10}")
    worst = sorted([r for r in out if r["trades"] >= 500],
                   key=lambda r: r["parcels_have"] / max(r["trades"], 1))[:12]
    for r in worst:
        print(f"    {(r['name'] or r['sigungu_cd'])[:11]:<12}{r['trades']:>9,}"
              f"{r['parcels_have']:>11,}"
              f"{r['parcels_have'] / max(r['trades'], 1):>10.1f}")

    dst = arg("--out")
    if dst:
        pathlib.Path(dst).write_text(
            json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n  → {dst}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
