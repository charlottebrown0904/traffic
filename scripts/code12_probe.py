"""시도코드 '12' 27곳 · 거래 130만 건의 정체 — 규명.

지시(2026-09-19): "추가로 '12'코드 정체 규명도 진행하고요."

## 무엇이 이상한가

시군구 커버리지를 재다가 나온 것이다.

    시도    시군구      통거래       가진 필지
    12       27     1,298,617            0

한국 시도코드에 **12는 없다** (서울 11 · 부산 26 · … · 전남 46 · 광주 29).
그런데 27곳에 거래 130만 건, 전체의 14%다. 그리고 목록에서 **전남(22곳)과
광주(5곳)가 통째로 빠져 있다.** 22 + 5 = 27 이다.

우연으로 보기 어렵다. 그러나 우연이 아니라고 단정하지도 않는다 — 코드를
직접 뽑아 보고, 좌표가 실제로 어디에 떨어지는지 본다.

## 어떻게 가리나

이름과 좌표는 서로 다른 길로 들어온 값이라 서로를 검산한다.

  1절  '12' 로 시작하는 코드를 전부 뽑는다 — 몇 개이고 각각 몇 건인가
  2절  그 거래의 **읍면동 이름**을 본다. 이름이 전남·광주 것이면 답이다
  3절  **좌표**가 어디에 떨어지는가. 이름과 좌표가 같은 곳을 가리키면
       확실하다 (좌표는 지오코더가, 이름은 실거래 API 가 준 것이다)
  4절  region_umd(행정표준코드 명부)에 그 코드가 있는가
  5절  화면에 나가는 자료(trade_tollgate_link · panel)에 섞여 있는가 —
       이것이 '지금 서비스가 틀렸나' 를 가른다

  python scripts/code12_probe.py
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402

from redt.config import DB_PATH                             # noqa: E402

# 시도 코드 → 이름. 좌표가 가리키는 곳과 견주려고 둔다.
SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
    "43": "충북", "44": "충남", "45": "전북", "46": "전남", "47": "경북",
    "48": "경남", "50": "제주", "51": "강원", "52": "전북",
}
# 시도별 대략의 네모 (좌표가 어느 도에 떨어지는지 거칠게 가르려고).
BOXES = {
    "전남": (125.0, 33.9, 127.9, 35.5), "광주": (126.6, 35.0, 127.0, 35.3),
    "전북": (126.4, 35.3, 127.9, 36.2), "경남": (127.5, 34.5, 129.3, 35.9),
    "경북": (127.8, 35.6, 129.6, 37.2), "충남": (125.9, 35.9, 127.6, 37.1),
    "충북": (127.2, 36.0, 128.6, 37.3), "강원": (127.0, 37.0, 129.4, 38.6),
    "경기": (126.3, 36.8, 127.9, 38.3), "제주": (126.1, 33.1, 126.98, 33.6),
}


def arg(name, default=None):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def head(t):
    print(f"\n{t}\n" + "-" * (len(t) + 12))


def where_is(lat, lon):
    if lat is None or lon is None:
        return "—"
    hit = [nm for nm, (w, s, e, n) in BOXES.items()
           if w <= lon <= e and s <= lat <= n]
    return " / ".join(hit) if hit else "어느 상자에도 없음"


def main() -> int:
    db = pathlib.Path(arg("--db", str(DB_PATH)))
    if not db.exists():
        print(f"  {db} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")
        return 1
    con = duckdb.connect()
    con.execute(f"ATTACH '{db}' AS src (READ_ONLY)")

    print("=" * 72)
    print(" 시도코드 '12' — 27곳 · 거래 130만 건의 정체")
    print("=" * 72)

    # ── 1. 코드를 전부 뽑는다 ─────────────────────────────────────
    head("1. '12' 로 시작하는 시군구 코드")
    rows = con.execute("""
        SELECT sigungu_cd, count(*) AS n,
               min(deal_year), max(deal_year),
               avg(lat), avg(lon),
               count(*) FILTER (WHERE lat IS NOT NULL) AS n_xy
        FROM src.trade
        WHERE sigungu_cd LIKE '12%'
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    print(f"  코드 {len(rows)}개 · 거래 {sum(r[1] for r in rows):,}건")
    print(f"\n  {'코드':<8}{'거래':>10}{'기간':>14}{'좌표 있음':>10}  좌표가 가리키는 곳")
    for cd, n, y0, y1, la, lo, nxy in rows:
        print(f"  {cd:<8}{n:>10,}{f'{y0}~{y1}':>14}{nxy:>10,}  "
              f"{where_is(la, lo)} ({la if la is None else round(la, 3)}, "
              f"{lo if lo is None else round(lo, 3)})")

    # ── 2. 읍면동 이름 ────────────────────────────────────────────
    head("2. 읍면동 이름 — 이름은 실거래 API 가 준 값이다")
    for cd, _n, *_ in rows[:8]:
        umds = con.execute(f"""
            SELECT umd, count(*) FROM src.trade
            WHERE sigungu_cd = '{cd}' AND umd IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC LIMIT 5
        """).fetchall()
        print(f"  {cd}  " + " · ".join(f"{u}({n:,})" for u, n in umds))

    # ── 3. 명부에 있는가 ──────────────────────────────────────────
    head("3. 행정표준코드 명부(region_umd)에 그 코드가 있는가")
    known = con.execute("""
        SELECT count(*) FROM src.region_umd WHERE sigungu_cd LIKE '12%'
    """).fetchone()[0]
    print(f"  명부에 '12' 로 시작하는 법정동 {known:,}개")
    if known == 0:
        print("  → 명부에 없는 코드입니다. 실거래 쪽에서만 쓰는 값입니다.")

    # 이름으로 되짚어 본다. 이름이 명부에 있으면 진짜 코드를 알 수 있다.
    print("\n  이름으로 명부를 되짚으면")
    back = con.execute("""
        SELECT r.sigungu_cd, any_value(r.sigungu), count(DISTINCT t.umd) AS k,
               sum(1) AS n
        FROM src.trade t JOIN src.region_umd r ON r.umd = t.umd
        WHERE t.sigungu_cd LIKE '12%'
        GROUP BY 1 ORDER BY 4 DESC LIMIT 12
    """).fetchall()
    for cd, nm, k, n in back:
        print(f"    {cd} {SIDO.get(cd[:2], cd[:2])} {nm or '':<12} "
              f"법정동 {k:>4}개 · 거래 {n:>9,}")

    # ── 4. 전남·광주가 정말 없는가 ────────────────────────────────
    head("4. 전남(46)·광주(29) 는 정말 비어 있는가")
    for pre, nm in (("46", "전남"), ("29", "광주"), ("12", "?")):
        n = con.execute(f"""
            SELECT count(*) FROM src.trade WHERE sigungu_cd LIKE '{pre}%'
        """).fetchone()[0]
        k = con.execute(f"""
            SELECT count(DISTINCT sigungu_cd) FROM src.trade
            WHERE sigungu_cd LIKE '{pre}%'
        """).fetchone()[0]
        print(f"  {pre} {nm:<4} 거래 {n:>10,} · 시군구 {k:>3}곳")

    # ── 5. 화면에 나가는 자료에 섞여 있는가 ───────────────────────
    head("5. 화면에 나가는 자료에 이 거래가 들어 있는가")
    print("  여기가 '지금 서비스가 틀렸나' 를 가릅니다.")
    for tbl, col in (("trade_parcel", "trade_id"),
                     ("trade_tollgate_link", "trade_id"),
                     ("trade_zone_link", "trade_id")):
        try:
            n = con.execute(f"""
                SELECT count(*) FROM src.{tbl} x
                JOIN src.trade t USING (trade_id)
                WHERE t.sigungu_cd LIKE '12%'
            """).fetchone()[0]
            tot = con.execute(f"SELECT count(*) FROM src.{tbl}").fetchone()[0]
            print(f"    {tbl:<24}{n:>10,} / {tot:>10,}")
        except Exception as exc:                             # noqa: BLE001
            print(f"    {tbl:<24}못 셌습니다 — {type(exc).__name__}")

    head("정리")
    print("""  1·2·3절이 같은 곳을 가리키면 답이 난 것입니다. 이름과 좌표는
  서로 다른 길로 들어온 값이라, 둘이 맞으면 우연이 아닙니다.

  고칠 자리는 코드가 만들어지는 곳입니다 — 실거래 수집이 시군구 코드를
  어디서 가져오는지(collect/rtms.py) 를 봅니다. 자료를 고치기 전에
  들어오는 길을 먼저 막아야 같은 일이 다시 안 생깁니다.""")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
