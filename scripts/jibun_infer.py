"""가려진 지번을 되찾는다 — 추론 엔진 (안성시 견본).

요구사항(2026-09-19): "국토부실거래 신고 내용과 지금 가지고 있는 모든
정보를 이용해서 실거래 지번을 추측해 내는 로직을 만들어 봅시다."
→ "안성시만 견본으로 시작해 주세요. 2006년~2026년 모든 실거래"

## 앞 시범이 6.0% 에서 멈춘 이유

세 가지였고 셋 다 고칠 수 있는 것이었다.

  ① 필지를 1,000개에서 잘라 받았다 — '없음' 91% 의 대부분
  ② **도형 면적**(중앙값 오차 1.48%)으로 맞췄다
  ③ 지목·용도지역·전역제약을 안 썼다

②가 핵심이었다. 연속지적도(`lp_pa_cbnd_bubun`)의 도형에서 면적을 계산했는데,
**토지특성 WFS(`dt_d194`)가 토지대장 면적을 그대로 준다.**

    FIELDS = {"pnu": "pnu", "area_m2": "lndpcl_ar",
              "jimok": "lndcgr_code_nm", "land_use": "prpos_area_1_nm",
              "official_price": "pblntf_pclnd", ...}

거래면적은 대장면적과 **같아야 하는 값**이다. 도형 면적은 지적도 축척
오차를 안고 있어 ±1.5% 다. 이 차이가 '유일하게 특정되는가' 를 가른다.

## 쓰는 신호

    본번 범위      1** → 100~199          하드
    산여부        지번 접두 '산'           하드
    **대장 면적**  lndpcl_ar               **하드 — 결정타**
    지목          거래 ↔ 필지              소프트 (시간에 따라 변함)
    용도지역       거래 ↔ 필지              소프트
    공시지가 배수   단가 / pblntf_pclnd     소프트
    **전역 제약**  한 필지는 같은 달에 한 번만 팔린다   ← 아무도 안 쓰던 것
    묶음 거래      같은 본번의 부번 면적 합   재현율

전역 제약이 크다. 거래 A 의 후보가 {P1}, 거래 B 의 후보가 {P1,P2} 면
A→P1 이 확정되는 순간 B→P2 다. **개별로는 '여럿' 인 것이 전체로 보면
유일해진다.** 스도쿠를 푸는 것과 같은 전파를 돌린다.

## 어림셈 — 왜 될 것 같은가

리 하나에 필지 3,000개, `1**` 마스크면 본번 100개 구간에 약 600 후보.
면적을 ±0.1% 로 걸면 그 600개 중 겹치는 것의 기대값은 0.3개 미만이다.

## 앞에서 제가 틀린 것

`*`·`산*` 를 "원리적으로 불가능" 이라 했는데 **반대다** — 본번이 0~9 라
후보가 가장 적어서 가장 쉽다. 어려운 것은 `#***`(본번 1,000개) 다.

## 검산

붙인 것이 맞는지 직접 확인할 길이 없다(정답지가 없다). 대신 **거짓
양성률**을 잰다 — 같은 규칙을 일부러 **틀린 법정동**에 적용해서 몇 %가
'유일' 하다고 나오는지 본다. 그것이 우연히 맞은 몫의 상한이다.

  python scripts/jibun_infer.py              # 안성시, 있는 필지로
  python scripts/jibun_infer.py 41550 --fetch  # 필지를 먼저 채우고
"""
from __future__ import annotations

import math
import os
import pathlib
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402
import pandas as pd                                         # noqa: E402

from redt.config import DB_PATH, INTERIM                     # noqa: E402


def arg(name, default=None):
    """--이름 값 을 읽는다. 없으면 default."""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default

SIGUNGU = "41550"                 # 안성시
TOLS = [0.0005, 0.001, 0.005, 0.01]     # 면적 상대오차 후보
TILE_DEG = 0.01
PAD_DEG = 0.02


def head(n: str) -> None:
    print()
    print(n)
    print("-" * (len(n) + 14))


def jibun_range(jibun):
    """가려진 지번 → (산여부, 본번 lo, 본번 hi). 못 읽으면 None."""
    if not jibun:
        return None
    s = str(jibun).strip()
    mount = "2" if s.startswith("산") else "1"
    tok = s.lstrip("산").strip().split("-")[0].strip()
    if not tok or len(tok) > 4:
        return None
    if any(c not in "0123456789*" for c in tok):
        return None
    return mount, int(tok.replace("*", "0")), int(tok.replace("*", "9"))


# ── 필지 채우기 (토지특성 WFS) ──────────────────────────────────────
def fetch_parcels(box, out_path):
    """시군구 네모를 칸으로 훑어 토지특성을 받는다. landchar 과 같은 길."""
    from redt.collect import landchar as lc
    w, s, e, n = box
    cfg = lc._cfg()
    pace = lc._Pace(cfg["calls_per_sec"])
    nx = max(1, int(math.ceil((e - w) / TILE_DEG)))
    ny = max(1, int(math.ceil((n - s) / TILE_DEG)))
    print(f"  네모 {w:.3f},{s:.3f} ~ {e:.3f},{n:.3f} · 칸 {nx}×{ny}={nx * ny:,}개")
    boxes = [(w + i * TILE_DEG, s + j * TILE_DEG,
              w + (i + 1) * TILE_DEG, s + (j + 1) * TILE_DEG)
             for i in range(nx) for j in range(ny)]

    def one(bx):
        try:
            feats, _ = lc.fetch_tile(bx, pace)
        except Exception as exc:                            # noqa: BLE001
            print(f"    칸 실패 {lc.tile_key(bx)} — {type(exc).__name__}")
            return []
        return [lc._row((f or {}).get("properties") or {}) for f in feats]

    # 한 칸씩 줄 서서 받으면 1,400칸에 30분이 넘는다 — 러너가 먼저 죽는다.
    # 워커를 여럿 쓰되 **속도는 Pace 가 합쳐서 잡는다**(초당 N건). 브이월드
    # 한도를 넘기지 않으면서 벽시계만 줄이는 길이다.
    rows, t0, done = [], time.monotonic(), 0
    with ThreadPoolExecutor(max_workers=cfg["workers"]) as ex:
        for got in ex.map(one, boxes):
            rows += got
            done += 1
            if done % 100 == 0:
                el = time.monotonic() - t0
                print(f"    {done:,}/{len(boxes):,}칸 · 필지 {len(rows):,}개 "
                      f"· {el / 60:.1f}분", flush=True)
    df = pd.DataFrame(rows).drop_duplicates("pnu")
    df.to_parquet(out_path)
    print(f"  받은 필지 {len(df):,}개 → {out_path}")
    return df


def main() -> int:
    sgg = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else SIGUNGU
    do_fetch = "--fetch" in sys.argv
    # 시험은 제 DB 를 씁니다. 진짜 수집분을 건드리지 않으려고.
    db_path = pathlib.Path(arg("--db", str(DB_PATH)))

    print("=" * 70)
    print(f" 가려진 지번 추론 엔진 — 시군구 {sgg} · 2006~2026 전 기간")
    print("=" * 70)
    if not db_path.exists():
        print(f"  {db_path} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")
        return 1

    # 읽기 전용 파일을 메모리 DB 에 붙인다. 임시 표를 자유롭게 만들려고.
    con = duckdb.connect()
    con.execute(f"ATTACH '{db_path}' AS src (READ_ONLY)")

    # ── 0. 준비 ────────────────────────────────────────────────────
    head("0. 준비 — 거래와 대조표")
    con.execute(f"""
        CREATE TABLE bjd AS
        SELECT sigungu_cd, umd, bjd10 FROM (
          SELECT t.sigungu_cd, t.umd, substr(tp.pnu, 1, 10) AS bjd10,
                 row_number() OVER (PARTITION BY t.sigungu_cd, t.umd
                                    ORDER BY count(*) DESC) AS rk
          FROM src.trade t JOIN src.trade_parcel tp USING (trade_id)
          WHERE t.sigungu_cd = '{sgg}' AND t.umd IS NOT NULL
            AND length(tp.pnu) = 19
          GROUP BY 1, 2, 3)
        WHERE rk = 1
    """)
    con.execute(f"""
        CREATE TABLE tr AS
        SELECT t.trade_id, t.kind, t.umd, b.bjd10, t.jibun, t.area_m2,
               t.jimok, t.land_use, t.deal_year, t.deal_month,
               t.price_per_m2, t.is_share_deal
        FROM src.trade t JOIN bjd b
          ON b.sigungu_cd = t.sigungu_cd AND b.umd = t.umd
        WHERE t.sigungu_cd = '{sgg}'
          AND NOT coalesce(t.is_cancelled, FALSE)
          AND t.area_m2 > 0 AND t.jibun IS NOT NULL
    """)
    n_umd, n_tr, n_all = con.execute(f"""
        SELECT (SELECT count(*) FROM bjd), (SELECT count(*) FROM tr),
               (SELECT count(*) FROM src.trade WHERE sigungu_cd = '{sgg}')
    """).fetchone()
    print(f"  거래 {n_all:,}건 중 다룰 수 있는 것 {n_tr:,}건 "
          f"(법정동 코드가 있고 면적·지번이 있는 것)")
    print(f"  대조표 법정동 {n_umd:,}개")
    yr = con.execute("SELECT min(deal_year), max(deal_year) FROM tr").fetchone()
    print(f"  기간 {yr[0]}~{yr[1]}")

    # 지번 범위를 파이썬에서 풀어 표로 만든다 (SQL 로는 읽기 어렵다)
    jb = con.execute("SELECT trade_id, jibun FROM tr").fetchdf()
    rg = [jibun_range(j) for j in jb["jibun"]]
    jb["mount"] = [r[0] if r else None for r in rg]
    jb["bon_lo"] = [r[1] if r else None for r in rg]
    jb["bon_hi"] = [r[2] if r else None for r in rg]
    jb = jb.dropna(subset=["mount"])
    con.register("_jb", jb)
    con.execute("CREATE TABLE rng AS SELECT * FROM _jb")
    print(f"  지번 범위를 읽어낸 것 {len(jb):,}건 "
          f"({len(jb) / max(n_tr, 1):.1%})")

    # ── 1. 필지 커버리지 ───────────────────────────────────────────
    head("1. 필지를 얼마나 들고 있나")
    have = con.execute(
        f"SELECT count(*) FROM src.parcel WHERE sigungu_cd = '{sgg}'"
    ).fetchone()[0]
    print(f"  parcel 표의 이 시군구 필지 {have:,}개")
    cache = INTERIM / f"landchar_{sgg}.parquet"
    extra = None
    if do_fetch:
        if cache.exists():
            extra = pd.read_parquet(cache)
            print(f"  받아 둔 것을 씁니다 — {len(extra):,}개 ({cache.name})")
        else:
            box = con.execute(f"""
                SELECT min(lon) - {PAD_DEG}, min(lat) - {PAD_DEG},
                       max(lon) + {PAD_DEG}, max(lat) + {PAD_DEG}
                FROM src.trade WHERE sigungu_cd = '{sgg}' AND lat IS NOT NULL
            """).fetchone()
            if box and box[0] is not None:
                extra = fetch_parcels(box, cache)
    if extra is not None and len(extra):
        con.register("_ex", extra)
        con.execute("CREATE TABLE par AS "
                    "SELECT pnu, jimok, land_use, area_m2, official_price "
                    "FROM _ex WHERE pnu IS NOT NULL AND area_m2 > 0")
        con.execute(f"""
            INSERT INTO par
            SELECT p.pnu, p.jimok, p.land_use, p.area_m2, p.official_price
            FROM src.parcel p
            WHERE p.sigungu_cd = '{sgg}' AND p.area_m2 > 0
              AND p.pnu NOT IN (SELECT pnu FROM par)
        """)
    else:
        con.execute(f"""
            CREATE TABLE par AS
            SELECT pnu, jimok, land_use, area_m2, official_price
            FROM src.parcel WHERE sigungu_cd = '{sgg}' AND area_m2 > 0
        """)
    n_par = con.execute("SELECT count(*) FROM par").fetchone()[0]
    print(f"  맞출 때 쓸 필지 {n_par:,}개")

    print("\n  법정동별 — 필지가 얼마나 있나 (거래가 많은 곳부터)")
    print(f"    {'법정동':<14}{'거래':>8}{'필지':>9}")
    for umd, ntr, npa in con.execute("""
            SELECT t.umd, count(*) AS ntr,
                   (SELECT count(*) FROM par p
                    WHERE substr(p.pnu, 1, 10) = t.bjd10) AS npa
            FROM tr t GROUP BY t.umd, t.bjd10
            ORDER BY 2 DESC LIMIT 8""").fetchall():
        flag = "  ← 필지가 거의 없음" if npa < ntr else ""
        print(f"    {umd:<14}{ntr:>8,}{npa:>9,}{flag}")

    # ── 2. 후보 생성 ───────────────────────────────────────────────
    head("2. 후보 만들기 — 본번 범위 × 산여부 × 대장 면적")
    con.execute("""
        CREATE TABLE t2 AS
        SELECT tr.*, r.mount, CAST(r.bon_lo AS INT) AS bon_lo,
               CAST(r.bon_hi AS INT) AS bon_hi
        FROM tr JOIN rng r USING (trade_id)
    """)
    print(f"  {'면적 허용오차':<14}{'후보 0개':>11}{'유일':>10}"
          f"{'여럿':>10}{'유일률':>10}")
    best_tol, best_rate = TOLS[0], -1.0
    for tol in TOLS:
        con.execute("DROP TABLE IF EXISTS cand")
        con.execute(f"""
            CREATE TABLE cand AS
            SELECT t.trade_id, p.pnu, p.area_m2 AS p_area, p.jimok AS p_jimok,
                   p.land_use AS p_lu, p.official_price,
                   t.bjd10, t.deal_year, t.deal_month, t.jimok, t.land_use,
                   t.price_per_m2
            FROM t2 t JOIN par p
              ON substr(p.pnu, 1, 10) = t.bjd10
             AND substr(p.pnu, 11, 1) = t.mount
             AND CAST(substr(p.pnu, 12, 4) AS INT) BETWEEN t.bon_lo AND t.bon_hi
             AND abs(p.area_m2 - t.area_m2) <= greatest(t.area_m2 * {tol}, 0.05)
        """)
        z, u, m = con.execute("""
            WITH k AS (SELECT t.trade_id, count(c.pnu) AS n
                       FROM t2 t LEFT JOIN cand c USING (trade_id)
                       GROUP BY 1)
            SELECT count(*) FILTER (WHERE n = 0), count(*) FILTER (WHERE n = 1),
                   count(*) FILTER (WHERE n > 1) FROM k""").fetchone()
        tot = z + u + m
        rate = u / max(tot, 1)
        print(f"    {tol:>8.2%}    {z:>11,}{u:>10,}{m:>10,}{rate:>9.1%}")
        if rate > best_rate:
            best_rate, best_tol = rate, tol
    print(f"\n  → 허용오차 {best_tol:.2%} 로 이어 갑니다")
    con.execute("DROP TABLE IF EXISTS cand")
    con.execute(f"""
        CREATE TABLE cand AS
        SELECT t.trade_id, p.pnu, p.area_m2 AS p_area, p.jimok AS p_jimok,
               p.land_use AS p_lu, p.official_price,
               t.bjd10, t.deal_year, t.deal_month, t.jimok, t.land_use,
               t.price_per_m2
        FROM t2 t JOIN par p
          ON substr(p.pnu, 1, 10) = t.bjd10
         AND substr(p.pnu, 11, 1) = t.mount
         AND CAST(substr(p.pnu, 12, 4) AS INT) BETWEEN t.bon_lo AND t.bon_hi
         AND abs(p.area_m2 - t.area_m2) <= greatest(t.area_m2 * {best_tol}, 0.05)
    """)

    # ── 3. 좁히기 ──────────────────────────────────────────────────
    head("3. 좁히기 — 지목·용도지역")
    print("  지목·용도지역은 시간에 따라 바뀝니다. 그래서 **여럿일 때만**")
    print("  가려내는 데 씁니다 — 후보가 하나뿐이면 건드리지 않습니다.")
    con.execute("""
        CREATE TABLE cand2 AS
        WITH n AS (SELECT trade_id, count(*) AS k FROM cand GROUP BY 1),
        s AS (
          SELECT c.*, n.k,
                 (c.jimok IS NOT NULL AND c.p_jimok IS NOT NULL
                  AND c.jimok = c.p_jimok) AS jimok_ok,
                 (c.land_use IS NOT NULL AND c.p_lu IS NOT NULL
                  AND (c.p_lu LIKE c.land_use || '%'
                       OR c.land_use LIKE c.p_lu || '%')) AS lu_ok
          FROM cand c JOIN n USING (trade_id))
        SELECT * FROM s
        WHERE k = 1
           OR (jimok_ok AND lu_ok)
           OR NOT EXISTS (SELECT 1 FROM s s2
                          WHERE s2.trade_id = s.trade_id
                            AND s2.jimok_ok AND s2.lu_ok)
    """)
    z, u, m = con.execute("""
        WITH k AS (SELECT t.trade_id, count(c.pnu) AS n
                   FROM t2 t LEFT JOIN cand2 c USING (trade_id) GROUP BY 1)
        SELECT count(*) FILTER (WHERE n = 0), count(*) FILTER (WHERE n = 1),
               count(*) FILTER (WHERE n > 1) FROM k""").fetchone()
    print(f"\n  좁힌 뒤 — 없음 {z:,} · 유일 {u:,} · 여럿 {m:,} "
          f"(유일률 {u / max(z + u + m, 1):.1%})")

    # ── 4. 전역 할당 ───────────────────────────────────────────────
    head("4. 전역 할당 — 한 필지는 같은 달에 한 번만 팔린다")
    print("  후보가 하나뿐인 거래를 확정하고, 그 필지를 같은 달의 다른")
    print("  거래 후보에서 뺍니다. 더 이상 줄지 않을 때까지 되풀이합니다.")
    cc = con.execute("SELECT trade_id, pnu, bjd10, deal_year, deal_month "
                     "FROM cand2").fetchdf()
    cands = defaultdict(set)
    group = {}
    for r in cc.itertuples(index=False):
        cands[r.trade_id].add(r.pnu)
        group[r.trade_id] = (r.bjd10, r.deal_year, r.deal_month)
    by_group = defaultdict(list)
    for tid, g in group.items():
        by_group[g].append(tid)

    fixed, clash, rounds = {}, set(), 0
    while True:
        rounds += 1
        changed = False
        for g, tids in by_group.items():
            solo = [t for t in tids if t not in fixed and len(cands[t]) == 1]
            # 같은 달·같은 법정동에서 **같은 필지**를 유일 후보로 가진
            # 거래가 둘 이상이면 모순이다. 둘 중 하나는 반드시 틀렸는데
            # 어느 쪽인지 알 길이 없으므로 **둘 다 버린다.** 먼저 본 것을
            # 확정하면 순서가 답을 정하게 되고, 그것은 추측이 아니라
            # 우연이다.
            claim = defaultdict(list)
            for t in solo:
                claim[next(iter(cands[t]))].append(t)
            for p, ts in claim.items():
                if len(ts) > 1:
                    for t in ts:
                        cands[t].clear()
                        clash.add(t)
                    changed = True
                    continue
                t = ts[0]
                fixed[t] = p
                for o in tids:
                    if o != t and p in cands[o]:
                        cands[o].discard(p)
                        changed = True
        if not changed or rounds > 40:
            break
    still_multi = sum(1 for t in cands if t not in fixed and len(cands[t]) > 1)
    empt = sum(1 for t in cands if t not in fixed and not cands[t])
    print(f"\n  전파 {rounds}바퀴 · 확정 {len(fixed):,}건")
    print(f"  아직 여럿 {still_multi:,}건 · 후보가 비어 버린 것 {empt:,}건")
    print(f"  같은 달에 같은 필지를 가리켜 **둘 다 버린 것** {len(clash):,}건")

    # ── 5. 결과 ────────────────────────────────────────────────────
    head("5. 결과")
    out = pd.DataFrame({"trade_id": list(fixed), "pnu": list(fixed.values())})
    # 찾은 것을 파일로 남긴다. 다음 단계(적재·검산)가 이것을 읽고,
    # 모형 시험은 정답과 견준다.
    for i, a in enumerate(sys.argv):
        if a == "--out" and i + 1 < len(sys.argv):
            out.to_csv(sys.argv[i + 1], index=False)
            print(f"  찾은 지번 {len(out):,}건 → {sys.argv[i + 1]}")
    con.register("_fx", out)
    con.execute("CREATE TABLE got AS SELECT * FROM _fx")
    tot = con.execute("SELECT count(*) FROM t2").fetchone()[0]
    print(f"  다룬 거래 {tot:,}건 · 지번을 찾은 것 {len(out):,}건 "
          f"({len(out) / max(tot, 1):.1%})")

    print("\n  연도별")
    print(f"    {'연도':<8}{'거래':>9}{'찾음':>9}{'비율':>9}")
    for y, a, b in con.execute("""
            SELECT t.deal_year, count(*),
                   count(*) FILTER (WHERE g.trade_id IS NOT NULL)
            FROM t2 t LEFT JOIN got g USING (trade_id)
            GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"    {y:<8}{a:>9,}{b:>9,}{b / max(a, 1):>8.1%}")

    print("\n  마스크 모양별 (본번 후보가 적을수록 쉽다)")
    print(f"    {'모양':<10}{'거래':>9}{'찾음':>9}{'비율':>9}")
    for pat, a, b in con.execute("""
            SELECT regexp_replace(t.jibun, '[0-9]', '#', 'g'), count(*),
                   count(*) FILTER (WHERE g.trade_id IS NOT NULL)
            FROM t2 t LEFT JOIN got g USING (trade_id)
            GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall():
        print(f"    {pat:<10}{a:>9,}{b:>9,}{b / max(a, 1):>8.1%}")

    # ── 6. 검산 — 거짓 양성률 ──────────────────────────────────────
    head("6. 검산 — 틀린 법정동에 같은 규칙을 걸면")
    print("  정답지가 없으니 '맞았다' 는 직접 확인할 수 없습니다. 대신")
    print("  **일부러 틀린 법정동**으로 같은 규칙을 돌립니다. 거기서")
    print("  나오는 '유일' 은 전부 거짓입니다 — 그것이 거짓 양성률입니다.")
    con.execute("""
        CREATE TABLE t3 AS
        WITH b AS (SELECT DISTINCT bjd10 FROM t2),
        shuf AS (SELECT bjd10,
                        lead(bjd10) OVER (ORDER BY bjd10) AS other FROM b)
        SELECT t.* EXCLUDE (bjd10),
               coalesce(s.other, (SELECT min(bjd10) FROM b)) AS bjd10
        FROM t2 t JOIN shuf s ON s.bjd10 = t.bjd10
    """)
    # 거짓 후보 수를 **거래마다** 남긴다. 연도·산여부로 쪼개 재려면
    # 전체 한 숫자로는 안 된다.
    con.execute(f"""
        CREATE TABLE fk AS
        WITH c AS (
          SELECT t.trade_id, p.pnu
          FROM t3 t JOIN par p
            ON substr(p.pnu, 1, 10) = t.bjd10
           AND substr(p.pnu, 11, 1) = t.mount
           AND CAST(substr(p.pnu, 12, 4) AS INT) BETWEEN t.bon_lo AND t.bon_hi
           AND abs(p.area_m2 - t.area_m2) <= greatest(t.area_m2 * {best_tol}, 0.05))
        SELECT t.trade_id, t.deal_year, t.mount, count(c.pnu) AS n
        FROM t3 t LEFT JOIN c USING (trade_id) GROUP BY 1, 2, 3
    """)
    # 맞는 법정동 쪽도 같은 규칙(좁히기·전파 이전)으로 세어 나란히 놓는다.
    con.execute("""
        CREATE TABLE rk AS
        SELECT t.trade_id, t.deal_year, t.mount,
               coalesce(t.is_share_deal, FALSE) AS share, count(c.pnu) AS n
        FROM t2 t LEFT JOIN cand c USING (trade_id) GROUP BY 1, 2, 3, 4
    """)
    fz, fu, fm = con.execute(
        "SELECT count(*) FILTER (WHERE n = 0), count(*) FILTER (WHERE n = 1), "
        "count(*) FILTER (WHERE n > 1) FROM fk").fetchone()
    ftot = fz + fu + fm
    print(f"\n  틀린 법정동 — 없음 {fz:,} · 유일 {fu:,} · 여럿 {fm:,}")
    print(f"  거짓 양성률 {fu / max(ftot, 1):.2%}")
    real = len(out) / max(tot, 1)
    print(f"\n  맞는 법정동 유일률 {real:.1%}  vs  틀린 법정동 {fu / max(ftot, 1):.2%}")
    if fu / max(ftot, 1) > 0:
        print(f"  → 신호 대 잡음 약 {real / (fu / max(ftot, 1)):.0f}배")

    # ── 7. 연도별 정확도 추정 ──────────────────────────────────────
    head("7. 연도별 정확도 — 옛 거래일수록 면적이 어긋나는가")
    print("""  지시(2026-09-19): "임야의 현재 면적과 예전 거래된 면적이 달라서
  일 수도 있습니다. 거래 후 개발 및 증여에 따른 지분 쪼개기 등이
  이루어진다." — 그렇다면 **옛 거래일수록** 정답이 표에 없고, 그러면
  남는 '유일' 중 우연의 몫이 커져 정확도가 떨어져야 합니다.

  연도마다 맞는 법정동과 틀린 법정동을 나란히 세워 이렇게 풉니다.

    없는비율 = 후보0(맞는) / 후보0(틀린)      정답이 아예 없는 몫
    거짓유일 = 없는비율 × 유일(틀린)          우연히 하나만 걸린 몫
    정확도   = (유일 − 거짓유일) / 유일

  잰 값이 아니라 **추정**입니다. 실자료에는 정답지가 없습니다.""")

    def band(sql_extra=""):
        rows = con.execute(f"""
            SELECT r.deal_year,
                   count(*) AS n,
                   count(*) FILTER (WHERE r.n = 0) AS rz,
                   count(*) FILTER (WHERE r.n = 1) AS ru,
                   count(*) FILTER (WHERE f.n = 0) AS fz,
                   count(*) FILTER (WHERE f.n = 1) AS fu
            FROM rk r JOIN fk f USING (trade_id)
            WHERE 1 = 1 {sql_extra}
            GROUP BY 1 ORDER BY 1
        """).fetchall()
        out = []
        for y, n, rz, ru, fz_, fu_ in rows:
            if not n or not ru:
                continue
            p0 = fz_ / n                      # 틀린 동에서 후보가 0일 확률
            absent = min((rz / n) / p0, 1.0) if p0 > 0 else 1.0
            false_u = absent * (fu_ / n)
            prec = max(0.0, (ru / n - false_u)) / (ru / n)
            out.append((y, n, ru / n, absent, prec))
        return out

    # 지분 거래는 **신고 면적이 필지 전체가 아니라 판 지분의 면적**이다.
    # 면적으로는 원리적으로 못 맞히므로, 섞어 두면 재현율은 낮아 보이고
    # 정확도는 부풀 수 있다(지분거래에 붙은 것은 거의 다 우연이다).
    # 갈라서 따로 잰다 — 이 표가 '지분거래를 버릴까' 를 결정한다.
    for title, extra in (("전체", ""), ("산 지번", " AND r.mount = '2'"),
                         ("일반 지번", " AND r.mount = '1'"),
                         ("통거래만", " AND NOT r.share"),
                         ("지분거래만", " AND r.share"),
                         ("산 · 통거래", " AND r.mount = '2' AND NOT r.share"),
                         ("산 · 지분거래", " AND r.mount = '2' AND r.share")):
        rows = band(extra)
        if not rows:
            continue
        print(f"\n  [{title}]")
        print(f"    {'연도':<7}{'거래':>8}{'유일률':>9}{'정답없음':>10}"
              f"{'추정 정확도':>13}")
        for y, n, u_r, absent, prec in rows:
            mark = "  ←" if prec < 0.80 else ""
            print(f"    {y:<7}{n:>8,}{u_r:>8.1%}{absent:>10.1%}"
                  f"{prec:>12.1%}{mark}")

    # ── 8. 쪼개기 가설을 직접 검정한다 ─────────────────────────────
    head("8. 쪼개기 가설 — 한 필지가 여럿으로 갈라졌는가")
    print("""  거래 뒤에 필지가 갈라졌다면, 그때 판 한 덩어리는 지금 **여러
  필지의 합**으로 남아 있어야 합니다. 그래서 후보가 하나도 없는
  거래를 놓고, 같은 본번 아래 부번들의 **면적 합**이 거래면적과
  맞는지 봅니다. 맞는다면 가설이 사실이고, 옛 거래일수록 더 많이
  맞아야 합니다.""")
    con.execute(f"""
        CREATE TABLE bong AS
        SELECT substr(pnu, 1, 10) AS bjd10, substr(pnu, 11, 1) AS mount,
               CAST(substr(pnu, 12, 4) AS INT) AS bon,
               sum(area_m2) AS sum_area, count(*) AS n_bu
        FROM par GROUP BY 1, 2, 3 HAVING count(*) > 1
    """)
    con.execute(f"""
        CREATE TABLE sumhit AS
        SELECT t.trade_id, t.deal_year, t.mount, count(*) AS n_hit,
               max(g.n_bu) AS n_bu
        FROM t2 t
        JOIN rk r USING (trade_id)
        JOIN bong g
          ON g.bjd10 = t.bjd10 AND g.mount = t.mount
         AND g.bon BETWEEN t.bon_lo AND t.bon_hi
         AND abs(g.sum_area - t.area_m2)
             <= greatest(t.area_m2 * {best_tol}, 0.05)
        WHERE r.n = 0
        GROUP BY 1, 2, 3
    """)
    print(f"\n    {'연도':<7}{'후보0':>9}{'합이 맞음':>11}{'그중 유일':>11}"
          f"{'되찾는 몫':>11}")
    for y, z_n, hit, uniq in con.execute("""
            SELECT r.deal_year, count(*) AS z_n,
                   count(s.trade_id) AS hit,
                   count(*) FILTER (WHERE s.n_hit = 1) AS uniq
            FROM rk r LEFT JOIN sumhit s USING (trade_id)
            WHERE r.n = 0 GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"    {y:<7}{z_n:>9,}{hit:>11,}{uniq:>11,}"
              f"{uniq / max(z_n, 1):>10.1%}")
    sz, sh, su = con.execute("""
        SELECT count(*), count(s.trade_id),
               count(*) FILTER (WHERE s.n_hit = 1)
        FROM rk r LEFT JOIN sumhit s USING (trade_id) WHERE r.n = 0""").fetchone()
    print(f"\n  후보 0개 {sz:,}건 중 본번 합이 맞는 것 {sh:,}건 "
          f"· 그중 유일한 본번 {su:,}건 ({su / max(sz, 1):.1%})")
    print("\n  산/일반으로 나누면")
    for mt, z_n, uniq in con.execute("""
            SELECT r.mount, count(*),
                   count(*) FILTER (WHERE s.n_hit = 1)
            FROM rk r LEFT JOIN sumhit s USING (trade_id)
            WHERE r.n = 0 GROUP BY 1 ORDER BY 1""").fetchall():
        nm = "산 지번" if mt == "2" else "일반 지번"
        print(f"    {nm:<10}후보0 {z_n:>8,} · 합으로 되찾음 {uniq:>7,} "
              f"({uniq / max(z_n, 1):.1%})")

    # 본번 합 규칙도 **새 규칙**이다. 쓰기 전에 거짓 양성률을 잰다 —
    # 틀린 법정동에 같은 규칙을 걸어서 몇 %가 '유일' 로 나오는지.
    fs = con.execute(f"""
        WITH h AS (
          SELECT t.trade_id, count(*) AS n_hit
          FROM t3 t JOIN fk f USING (trade_id)
          JOIN bong g
            ON g.bjd10 = t.bjd10 AND g.mount = t.mount
           AND g.bon BETWEEN t.bon_lo AND t.bon_hi
           AND abs(g.sum_area - t.area_m2)
               <= greatest(t.area_m2 * {best_tol}, 0.05)
          WHERE f.n = 0
          GROUP BY 1)
        SELECT count(*) FILTER (WHERE n_hit = 1) FROM h""").fetchone()[0]
    fz0 = con.execute("SELECT count(*) FROM fk WHERE n = 0").fetchone()[0]
    print(f"\n  검산 — 틀린 법정동에 같은 합 규칙을 걸면 "
          f"{fs:,}/{fz0:,} ({fs / max(fz0, 1):.2%})")
    print(f"  맞는 법정동 {su / max(sz, 1):.1%} vs 틀린 법정동 "
          f"{fs / max(fz0, 1):.2%}")

    # ── 9. 산은 왜 못 찾나 — 지분 거래인가 ────────────────────────
    head("9. 산은 왜 못 찾나 — 지분 거래를 의심한다")
    print("""  7절이 뜻밖의 것을 말했습니다. 산 지번은 **정확도가 오히려 높고**
  (찾으면 맞는다) 재현율만 낮습니다. 8절은 그 이유가 쪼개기가
  아니라고 말합니다 — 산의 본번 합 회수는 바닥값에 가깝습니다.

  남는 설명은 **지분 거래**입니다. 산은 상속·증여로 지분이 잘게
  나뉘고, 그때 신고되는 면적은 필지 전체가 아니라 **판 지분의
  면적**입니다. 그러면 필지 면적과 안 맞는 것이 당연합니다.

  거래 표의 is_share_deal 칸으로 직접 봅니다.""")
    print(f"\n    {'구분':<20}{'거래':>9}{'후보0':>9}{'정답없음':>10}")
    for mt, sh, n, z_n in con.execute("""
            SELECT t.mount, coalesce(t.is_share_deal, FALSE),
                   count(*), count(*) FILTER (WHERE r.n = 0)
            FROM t2 t JOIN rk r USING (trade_id)
            GROUP BY 1, 2 ORDER BY 1, 2""").fetchall():
        nm = ("산" if mt == "2" else "일반") + (" · 지분거래" if sh else " · 통거래")
        print(f"    {nm:<20}{n:>9,}{z_n:>9,}{z_n / max(n, 1):>9.1%}")
    print("\n  연도별 지분거래 비중 (산)")
    print(f"    {'연도':<8}{'산 거래':>9}{'지분거래':>10}{'비중':>9}")
    for y, n, sh in con.execute("""
            SELECT deal_year, count(*),
                   count(*) FILTER (WHERE coalesce(is_share_deal, FALSE))
            FROM t2 WHERE mount = '2' GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"    {y:<8}{n:>9,}{sh:>10,}{sh / max(n, 1):>8.1%}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
