"""가려진 지번을 면적으로 되찾을 수 있는가 — 탐침.

요구사항(2026-09-19): "국토부실거래가 신고 내용은 정확한 지번 표시가 되지
않으나, 디스코, 밸류맵, 땅야 등의 사설 서비스는 정확한 지번을 표기하고
있다. 어떻게 표기할 수 있는 지 방법을 찾아주세요." → "1번 진행하고 2번은
정확도 목표를 80%로 합니다."

## 무엇이 문제인가

국토부 실거래가 API 가 **본번 뒷자리를 가려서** 줍니다.

    미양면 계륵리  1**      → 본번을 모른다
    사곡동        산7*      → 산, 본번을 모른다

전국 지번 11,793,406건 중 정규식이 통과하는 것 8,863건(0.1%). PNU 를 못
만들고, 연속지적도에서 그 필지를 골라낼 수도 없습니다.

## 그런데 모순이 하나 있습니다

필지 붙이기(cli.py `cmd_landchar`)는 대상을 이렇게 잡습니다.

    base = "t.geocode_level = 'parcel' AND t.lat IS NOT NULL ..."

지번 단위로 지오코딩된 거래만 붙입니다. 그런데 2,821,032건(23.9%)이 그
조건을 통과했습니다. **지번이 전부 가려져 있다면 불가능한 일입니다.**
가려지지 않은 지번이 상당수 있다는 뜻이고, 1절이 그것을 셉니다.

## 되찾는 방법 — 면적이 열쇠다

가려진 것은 본번 뒷자리**뿐**입니다. 나머지는 정확합니다.

    법정동 이름   정확
    지번 1**      본번 100~199 로 좁혀진다
    면적 ㎡       **소수점까지 정확**  ← 결정타
    지목·용도지역  정확

연속지적도는 그 법정동의 필지를 PNU·지번과 함께 줍니다. 같은 리(里) 안에서
면적이 일치하는 필지는 드뭅니다. 본번 범위까지 겹치면 거의 유일해집니다.

    후보 = 같은 법정동 필지 중
            산여부 일치 AND 본번이 마스킹 범위 안 AND 부번이 범위 안
            AND |필지면적 − 거래면적| 이 허용오차 안
    후보 1개  → 지번 확정
    후보 2개+ → 붙이지 않는다      ← 틀린 지번은 남의 땅을 가리킨다

## 이 탐침이 답할 것

    1절  가려짐이 어디에 몰려 있나 (연도·종류·좌표단위별)
    2절  법정동 이름 → 코드 대조표를 우리 자료로 만들 수 있나
    3절  연속지적도를 법정동 단위로 통째로 받을 수 있나 (필터가 먹나)
    4절  **유일 매칭률이 80% 를 넘나**   ← 목표

  python scripts/jibun_match_probe.py              # 안성시(41550), 법정동 5개
  python scripts/jibun_match_probe.py 41220 8      # 평택시, 법정동 8개
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402

from redt.collect.http import get_once                      # noqa: E402
from redt.config import DB_PATH                             # noqa: E402

DEFAULT_SIGUNGU = "41550"      # 안성시 — 필지 특성 실측을 한 곳
DEFAULT_UMD = 5                # 시범에 쓸 법정동 수
TARGET = 0.80                  # 요구사항(2026-09-19): 정확도 목표 80%
WFS = "https://api.vworld.kr/req/wfs"
LAYER = "lp_pa_cbnd_bubun"
MAXF = 1000

# 면적 허용오차를 하나만 쓰면 '그 값이라서 그렇다' 는 말을 못 막는다.
# 곡선을 찍어 두면 어디서 꺾이는지가 보인다.
TOLS = [0.001, 0.003, 0.005, 0.01, 0.02]      # 상대오차 0.1% ~ 2%


def head(n: str) -> None:
    print()
    print(n)
    print("-" * (len(n) + 12))


def jibun_range(jibun: str):
    """가려진 지번 → (산여부, 본번 범위, 부번 범위).

    `1**` → 본번 100~199.  `6*` → 60~69.  `산1*` → 산, 10~19.
    `123-4` 처럼 안 가려진 것은 범위가 한 점이다.

    **못 읽는 모양은 None 을 준다.** 억지로 넓은 범위를 만들면 후보가
    수백 개가 되고, 그러면 '유일 매칭' 이라는 말 자체가 의미를 잃는다.
    """
    if not jibun:
        return None
    s = str(jibun).strip()
    mount = "2" if s.startswith("산") else "1"
    s = s.lstrip("산").strip()
    parts = s.split("-")
    if len(parts) > 2:
        return None

    def rng(tok: str, empty_ok: bool = False):
        tok = tok.strip()
        if not tok:
            return (0, 0) if empty_ok else None
        if not re.fullmatch(r"[0-9*]{1,4}", tok):
            return None
        lo = int(tok.replace("*", "0"))
        hi = int(tok.replace("*", "9"))
        return (lo, hi)

    bon = rng(parts[0])
    bu = rng(parts[1], empty_ok=True) if len(parts) > 1 else (0, 0)
    if bon is None or bu is None:
        return None
    return mount, bon, bu


def ring_area_m2(ring) -> float:
    """위경도 고리 하나의 면적(㎡). 그 위도에서 평면으로 펴고 신발끈.

    필지는 수백 미터 규모라 지구 곡률로 생기는 오차는 0.01% 아래다.
    진짜 오차는 연속지적도 도형과 토지대장 면적의 차이인데, 그것은
    3절에서 우리 parcel 표의 면적과 견주어 **재 본다**.
    """
    if len(ring) < 4:
        return 0.0
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx = 111_320.0 * math.cos(math.radians(lat0))
    ky = 110_540.0
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0] * kx, ring[i][1] * ky
        x2, y2 = ring[i + 1][0] * kx, ring[i + 1][1] * ky
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def geom_area_m2(geom) -> float:
    """폴리곤/멀티폴리곤의 면적. 안쪽 고리(구멍)는 뺀다."""
    if not geom:
        return 0.0
    t = geom.get("type")
    cs = geom.get("coordinates") or []
    polys = [cs] if t == "Polygon" else (cs if t == "MultiPolygon" else [])
    total = 0.0
    for poly in polys:
        for i, ring in enumerate(poly):
            a = ring_area_m2(ring)
            total += a if i == 0 else -a
    return total


def fetch_umd(bjd10: str, cap: int = 6000):
    """한 법정동의 필지를 전부. 필터가 먹는지는 **받아 보고 정한다.**

    되돌려 주는 것: (필지 목록, 쓴 방법 이름, 호출 수, 마지막 응답 모양)
    """
    ways = [
        ("FILTER(PropertyIsLike) 2.0.0", "2.0.0", {
            "FILTER": ('<Filter><PropertyIsLike wildCard="*" singleChar="#" '
                       'escapeChar="!"><PropertyName>pnu</PropertyName>'
                       f'<Literal>{bjd10}*</Literal></PropertyIsLike></Filter>')}),
        ("FILTER(PropertyIsLike) 1.1.0", "1.1.0", {
            "FILTER": ('<Filter><PropertyIsLike wildCard="*" singleChar="#" '
                       'escapeChar="!"><PropertyName>pnu</PropertyName>'
                       f'<Literal>{bjd10}*</Literal></PropertyIsLike></Filter>')}),
        ("CQL_FILTER pnu LIKE", "1.1.0", {"CQL_FILTER": f"pnu LIKE '{bjd10}%'"}),
    ]
    for name, ver, extra in ways:
        params = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": ver,
                  "TYPENAME": LAYER, "SRSNAME": "EPSG:4326",
                  "OUTPUT": "application/json",
                  "DOMAIN": "https://toji.fyi/", **extra}
        params["MAXFEATURES" if ver == "1.1.0" else "COUNT"] = str(MAXF)
        r = get_once(WFS, params, timeout=60)
        try:
            feats = (r.json() or {}).get("features") or []
        except Exception:  # noqa: BLE001
            feats = []
        got = [f for f in feats
               if str(((f or {}).get("properties") or {}).get("pnu", "")
                      ).startswith(bjd10)]
        if not got:
            peek = re.sub(r"\s+", " ", (r.text or "")[:110])
            print(f"      {name:<30} {r.status_code} · 0건 · {peek}")
            continue
        # **걸러졌는지 확인한다.** 필터가 무시되면 전국 아무 필지나 1,000건이
        # 오는데, 그것을 '이 법정동 필지' 로 세면 매칭률이 통째로 거짓이 된다.
        if len(got) < len(feats):
            print(f"      {name:<30} 필터가 무시됐습니다 "
                  f"({len(got)}/{len(feats)}건만 이 법정동) — 버립니다")
            continue
        out, calls = list(got), 1
        # 한도에 닿았으면 이어 받는다. 2.0.0 만 STARTINDEX 를 받는다.
        while len(got) >= MAXF and ver == "2.0.0" and len(out) < cap:
            params["STARTINDEX"] = str(len(out))
            time.sleep(0.2)
            r = get_once(WFS, params, timeout=60)
            calls += 1
            try:
                feats = (r.json() or {}).get("features") or []
            except Exception:  # noqa: BLE001
                feats = []
            got = [f for f in feats
                   if str(((f or {}).get("properties") or {}).get("pnu", "")
                          ).startswith(bjd10)]
            if not got:
                break
            out += got
        return out, name, calls, ""
    return [], "(없음)", len(ways), "모든 필터가 실패"


def main() -> int:
    sigungu = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SIGUNGU
    n_umd = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_UMD

    print("=" * 68)
    print(f" 가려진 지번 되찾기 탐침 — 시군구 {sigungu} · 법정동 {n_umd}개")
    print(f" 목표 유일 매칭률 {TARGET:.0%}")
    print("=" * 68)

    if not DB_PATH.exists():
        print(f"  {DB_PATH} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")
        return 1
    con = duckdb.connect(str(DB_PATH), read_only=True)

    # ── 1. 가려짐이 어디에 몰려 있나 ────────────────────────────────
    head("1. 가려진 지번은 어디에 몰려 있나")
    masked = "jibun LIKE '%*%'"
    tot, msk = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE {masked}) FROM trade"
    ).fetchone()
    print(f"  전체 {tot:,}건 중 가려진 것 {msk:,}건 ({msk / max(tot, 1):.1%})")

    print("\n  좌표 단위 × 가려짐")
    print(f"    {'좌표단위':<12}{'가려짐':>12}{'온전':>12}{'가려짐 비율':>12}")
    for lvl, a, b in con.execute(f"""
            SELECT coalesce(geocode_level, '(없음)'),
                   count(*) FILTER (WHERE {masked}),
                   count(*) FILTER (WHERE NOT ({masked}) OR jibun IS NULL)
            FROM trade GROUP BY 1 ORDER BY 2 + 3 DESC""").fetchall():
        print(f"    {lvl:<12}{a:>12,}{b:>12,}{a / max(a + b, 1):>11.1%}")

    print("\n  종류 × 가려짐")
    for kind, a, b in con.execute(f"""
            SELECT kind, count(*) FILTER (WHERE {masked}),
                   count(*) FILTER (WHERE NOT ({masked}) OR jibun IS NULL)
            FROM trade GROUP BY 1 ORDER BY 2 + 3 DESC""").fetchall():
        print(f"    {kind:<12}{a:>12,}{b:>12,}{a / max(a + b, 1):>11.1%}")

    print("\n  연도 × 가려짐 (언제부터 가렸나)")
    for yr, a, b in con.execute(f"""
            SELECT deal_year, count(*) FILTER (WHERE {masked}),
                   count(*) FILTER (WHERE NOT ({masked}) OR jibun IS NULL)
            FROM trade GROUP BY 1 ORDER BY 1""").fetchall():
        bar = "█" * int(round(20 * a / max(a + b, 1)))
        print(f"    {yr:<12}{a:>12,}{b:>12,}{a / max(a + b, 1):>11.1%}  {bar}")

    print("\n  가려진 모양 (숫자는 #, 별은 그대로) — 많은 것부터")
    for pat, n in con.execute(f"""
            SELECT regexp_replace(jibun, '[0-9]', '#', 'g'), count(*)
            FROM trade WHERE {masked}
            GROUP BY 1 ORDER BY 2 DESC LIMIT 8""").fetchall():
        print(f"    {pat:<12}{n:>12,}")

    # ── 2. 법정동 이름 → 코드 대조표 ────────────────────────────────
    head("2. 법정동 이름 → 코드 대조표를 우리 자료로 만들 수 있나")
    print("  이미 필지에 붙은 거래(trade_parcel)가 이름과 PNU 를 나란히")
    print("  들고 있습니다. 그 둘을 모으면 대조표가 됩니다 — 호출 0.")
    con.execute("""
        CREATE OR REPLACE TEMP VIEW bjd AS
        SELECT sigungu_cd, umd, bjd10, n FROM (
          SELECT t.sigungu_cd, t.umd, substr(tp.pnu, 1, 10) AS bjd10,
                 count(*) AS n,
                 row_number() OVER (PARTITION BY t.sigungu_cd, t.umd
                                    ORDER BY count(*) DESC) AS rk
          FROM trade t JOIN trade_parcel tp USING (trade_id)
          WHERE t.umd IS NOT NULL AND length(tp.pnu) = 19
          GROUP BY 1, 2, 3)
        WHERE rk = 1
    """)
    n_all, n_sgg = con.execute(
        "SELECT (SELECT count(*) FROM bjd), "
        "(SELECT count(*) FROM bjd WHERE sigungu_cd = ?)", [sigungu]).fetchone()
    print(f"  대조 가능한 법정동 전국 {n_all:,}개 · 이 시군구 {n_sgg:,}개")
    if not n_sgg:
        print("  이 시군구에는 붙은 거래가 없어 대조표를 못 만듭니다.")
        return 1

    # 가려진 거래가 많은 법정동부터 — 시범의 값이 큰 곳이다.
    umds = con.execute(f"""
        SELECT b.umd, b.bjd10, count(*) AS masked
        FROM trade t JOIN bjd b
          ON b.sigungu_cd = t.sigungu_cd AND b.umd = t.umd
        WHERE t.sigungu_cd = ? AND t.kind = 'land' AND {masked}
          AND NOT coalesce(t.is_share_deal, FALSE)
          AND t.area_m2 IS NOT NULL
        GROUP BY 1, 2 ORDER BY 3 DESC LIMIT ?
    """, [sigungu, n_umd]).fetchall()
    print(f"\n  시범 대상 (가려진 거래가 많은 법정동 {len(umds)}개)")
    for umd, bjd10, m in umds:
        print(f"    {umd:<14}{bjd10}  가려진 거래 {m:,}건")

    # ── 3·4. 필지를 받아 맞춰 본다 ──────────────────────────────────
    head("3. 연속지적도를 법정동 단위로 받을 수 있나 · 4. 유일 매칭률")
    grand = {t: [0, 0, 0] for t in TOLS}       # 유일 / 여럿 / 없음
    area_gap: list[float] = []
    calls_total = 0

    for umd, bjd10, _m in umds:
        print(f"\n  ── {umd} ({bjd10})")
        feats, way, calls, err = fetch_umd(bjd10)
        calls_total += calls
        if not feats:
            print(f"      필지를 못 받았습니다 — {err or way}")
            continue
        print(f"      {way} · 호출 {calls}회 · 필지 {len(feats):,}개")

        cand = []
        for f in feats:
            p = f.get("properties") or {}
            pnu = str(p.get("pnu") or "")
            if len(pnu) != 19:
                continue
            a = geom_area_m2(f.get("geometry"))
            if a <= 0:
                continue
            cand.append((pnu, pnu[10], int(pnu[11:15]), int(pnu[15:19]),
                         a, p.get("jibun")))

        # 도형 면적이 토지대장 면적과 얼마나 다른가 — 허용오차의 근거.
        pn = {c[0]: c[4] for c in cand}
        for p_, a_db in con.execute(
                "SELECT pnu, area_m2 FROM parcel WHERE substr(pnu,1,10) = ? "
                "AND area_m2 > 0", [bjd10]).fetchall():
            if p_ in pn:
                area_gap.append(abs(pn[p_] - a_db) / a_db)

        rows = con.execute(f"""
            SELECT jibun, area_m2 FROM trade
            WHERE sigungu_cd = ? AND umd = ? AND kind = 'land' AND {masked}
              AND NOT coalesce(is_share_deal, FALSE) AND area_m2 > 0
        """, [sigungu, umd]).fetchall()

        local = {t: [0, 0, 0] for t in TOLS}
        for jb, area in rows:
            rg = jibun_range(jb)
            if rg is None:
                for t in TOLS:
                    local[t][2] += 1
                continue
            mount, (blo, bhi), (ulo, uhi) = rg
            near = [c for c in cand
                    if c[1] == mount and blo <= c[2] <= bhi and ulo <= c[3] <= uhi]
            for t in TOLS:
                hit = [c for c in near if abs(c[4] - area) <= area * t]
                k = 0 if len(hit) == 1 else (1 if len(hit) > 1 else 2)
                local[t][k] += 1
        n = len(rows)
        print(f"      가려진 거래 {n:,}건")
        print(f"      {'허용오차':<10}{'유일':>8}{'여럿':>8}{'없음':>8}{'유일률':>10}")
        for t in TOLS:
            u, m2, z = local[t]
            print(f"      {t:>7.1%}   {u:>8,}{m2:>8,}{z:>8,}{u / max(n, 1):>9.1%}")
            for i in range(3):
                grand[t][i] += local[t][i]

    # ── 판정 ────────────────────────────────────────────────────────
    head(f"판정 — 목표 {TARGET:.0%}")
    if area_gap:
        area_gap.sort()
        mid = area_gap[len(area_gap) // 2]
        p90 = area_gap[int(len(area_gap) * 0.9)]
        print(f"  도형 면적 vs 토지대장 면적 차이 ({len(area_gap):,}개 필지)")
        print(f"    중앙값 {mid:.2%} · 90분위 {p90:.2%}")
        print("    → 허용오차는 이 값보다 넉넉해야 합니다.")
    else:
        print("  도형 면적을 견줄 토지대장 면적이 없었습니다 (parcel 표가 빔)")

    total = sum(grand[TOLS[0]])
    print(f"\n  합계 {total:,}건 · WFS 호출 {calls_total}회")
    print(f"  {'허용오차':<10}{'유일':>10}{'여럿':>10}{'없음':>10}{'유일률':>10}")
    best = (0.0, None)
    for t in TOLS:
        u, m2, z = grand[t]
        rate = u / max(total, 1)
        mark = "  ← 목표 달성" if rate >= TARGET else ""
        print(f"  {t:>7.1%}   {u:>10,}{m2:>10,}{z:>10,}{rate:>9.1%}{mark}")
        if rate > best[0]:
            best = (rate, t)
    print()
    if best[0] >= TARGET:
        print(f"  ✅ 허용오차 {best[1]:.1%} 에서 {best[0]:.1%} — 목표를 넘습니다.")
        print("     전국으로 넓힐 값이 있습니다.")
    else:
        print(f"  ❌ 가장 좋은 것이 {best[0]:.1%} (허용오차 {best[1]:.1%}) — "
              f"목표 {TARGET:.0%} 에 못 미칩니다.")
        print("     '여럿' 이 많으면 지목·용도지역을 더 걸고, '없음' 이 많으면")
        print("     필지를 덜 받았거나 면적 기준이 어긋난 것입니다.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
