"""지번 추론 엔진을 **정답지를 아는 모형**으로 채점한다.

요구사항(2026-09-19): "2번은 정확도 목표를 80%로 합니다."

실제 자료에는 정답지가 없다. 그래서 엔진이 얼마나 맞히는지는 **심어 둔
정답**으로만 잴 수 있다. 여기서 재지 않으면 '유일하게 특정됐다' 와
'맞았다' 를 구분할 방법이 영영 없다 — 앞 탐침이 정확히 그 함정에 빠졌다.

## 모형을 일부러 어렵게 만든다

쉬운 모형은 100%가 나온다(면적이 전부 제각각이면 언제나 유일하다).
실제를 닮게 하려면 **틀릴 구실**을 넣어야 한다.

    면적이 흔한 값에 몰린다   30%    330·495·661.2·991.7 … 같은 값이 반복
    필지 표에 구멍            35%    실제 parcel 표는 일부만 훑었다
    산 지번                  12%
    분할 필지                25%    한 본번 아래 부번 2~4개
    일부 거래                15%    면적이 필지와 다르다 — **정답이 없다**
    충돌 짝                   4%    같은 달·같은 면적 — 어느 쪽인지 알 수 없다

마지막 것이 특히 중요하다. 필지 일부만 거래되면 면적이 안 맞아 못 찾는
것이 **정상**이다. 그것까지 찾았다고 하면 그게 거짓이다.

## 채점

    정확도  맞게 찾은 것 / 찾은 것      ← 목표 80%
    재현율  맞게 찾은 것 / 풀 수 있는 것

정확도가 먼저다. 틀린 지번은 남의 땅을 가리키므로, 적게 찾더라도 맞는
것만 붙여야 한다.

  python scripts/test_jibun_infer.py
"""
from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import sys
import tempfile

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_PRECISION = 0.80
MIN_RECALL = 0.40          # 이보다 적게 찾으면 쓸모가 없다

JIMOK = ["전", "답", "대", "임야", "공장용지"]
LAND_USE = ["계획관리", "생산관리", "자연녹지", "농림"]
# 실제 토지 면적은 이런 값에 몰린다 (평 단위에서 온 반올림)
COMMON = [330.0, 495.0, 661.2, 991.7, 1322.3, 1652.9, 3305.8, 6611.6]


def build(db_path: str, seed: int = 23):
    random.seed(seed)
    con = duckdb.connect(db_path)
    con.execute("""CREATE TABLE trade(trade_id VARCHAR, kind VARCHAR,
      sigungu_cd VARCHAR, umd VARCHAR, jibun VARCHAR, deal_year INT,
      deal_month INT, area_m2 DOUBLE, price_per_m2 DOUBLE, price_krw DOUBLE,
      jimok VARCHAR, land_use VARCHAR, is_share_deal BOOLEAN,
      is_cancelled BOOLEAN, lat DOUBLE, lon DOUBLE, geocode_level VARCHAR)""")
    con.execute("CREATE TABLE trade_parcel(trade_id VARCHAR, pnu VARCHAR)")
    con.execute("""CREATE TABLE parcel(pnu VARCHAR, sigungu_cd VARCHAR,
      jimok VARCHAR, land_use VARCHAR, use_situation VARCHAR, area_m2 DOUBLE,
      road_side VARCHAR, shape VARCHAR, slope VARCHAR, official_price DOUBLE,
      stdr_year INT)""")

    def area():
        if random.random() < 0.30:
            return random.choice(COMMON)
        return round(random.uniform(80, 12000), 1)

    umds = [(f"리{i}", f"41550250{30 + i:02d}") for i in range(5)]
    allp = {}
    for _nm, b in umds:
        for bon in range(1, 1201):
            nsub = 1 if random.random() < 0.75 else random.randint(2, 4)
            for bu in range(nsub):
                mount = "2" if random.random() < 0.12 else "1"
                allp[f"{b}{mount}{bon:04d}{bu:04d}"] = (
                    area(), JIMOK[bon % 5], LAND_USE[bon % 4] + "지역")
    par = [(p, "41550", jm, lu, None, a, "소로한면", None, None, 120000.0, 2025)
           for p, (a, jm, lu) in allp.items()]

    tr, tp, truth, k = [], [], {}, 0
    for nm, b in umds:
        mine = [x for x in allp if x.startswith(b)]
        for pnu in random.sample(mine, 700):
            a, jm, lu = allp[pnu]
            bon, mount = int(pnu[11:15]), pnu[10]
            s = str(bon)
            mask = ("산" if mount == "2" else "") + s[0] + "*" * (len(s) - 1)
            part = random.random() < 0.15        # 필지 일부만 거래 — 정답 없음
            ta = round(a * random.uniform(0.2, 0.8), 1) if part else a
            yy, mm = random.randint(2006, 2026), random.randint(1, 12)
            k += 1
            tid = f"t{k}"
            tr.append((tid, "land", "41550", nm, mask, yy, mm, ta,
                       300000.0, 9e7, jm, lu.replace("지역", ""), part, False,
                       37.0 + k * 1e-5, 127.2, "parcel"))
            # 지금 저장소에 들어 있는 것과 같은 모양의 **틀린** 링크.
            # 대조표(umd → 법정동코드)는 이것으로 만들어지므로 있어야 한다.
            tp.append((tid, f"{b}1{1:04d}0000"))
            truth[tid] = None if part else pnu

            # **충돌을 일부러 만든다.** 같은 달·같은 법정동에 면적·마스크가
            # 똑같은 거래를 하나 더 둔다. 그 거래의 진짜 필지는 표에 없다.
            # 엔진이 순서대로 확정하면 먼저 본 쪽에 지번을 붙여 버리는데,
            # 그것은 맞힌 것이 아니라 줄을 먼저 선 것이다 — **둘 다 버려야**
            # 한다. 실제 안성시 자료에서 이 자리가 터졌다(StopIteration).
            if not part and random.random() < 0.04:
                k += 1
                tid2 = f"t{k}"
                tr.append((tid2, "land", "41550", nm, mask, yy, mm, ta,
                           300000.0, 9e7, jm, lu.replace("지역", ""), False,
                           False, 37.0 + k * 1e-5, 127.2, "parcel"))
                tp.append((tid2, f"{b}1{1:04d}0000"))
                truth[tid2] = None

    con.executemany("INSERT INTO trade VALUES (" + ",".join(["?"] * 17) + ")", tr)
    con.executemany("INSERT INTO trade_parcel VALUES (?,?)", tp)
    # **필지 표에 구멍을 낸다.** 실제 parcel 표는 전국을 다 훑지 않았다.
    keep = random.sample(par, int(len(par) * 0.65))
    con.executemany("INSERT INTO parcel VALUES (" + ",".join(["?"] * 11) + ")",
                    keep)
    con.close()
    return truth, len(par), len(keep), len(tr)


def main() -> int:
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "fixture.duckdb")
    found_csv = os.path.join(tmp, "found.csv")
    truth, n_par, n_keep, n_tr = build(db)

    print("모형")
    print(f"  필지 전체 {n_par:,}개 중 표에 든 것 {n_keep:,}개 "
          f"({n_keep / n_par:.0%})")
    print(f"  거래 {n_tr:,}건 · 그중 정답이 없는 것(일부거래·충돌 짝) "
          f"{sum(1 for v in truth.values() if v is None):,}건")

    env = dict(os.environ, PYTHONPATH="src")
    r = subprocess.run(
        [sys.executable, "scripts/jibun_infer.py", "41550",
         "--db", db, "--out", found_csv],
        cwd=ROOT, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-2000:])
        print("엔진이 죽었습니다")
        return 1

    rows = list(csv.DictReader(open(found_csv, encoding="utf-8")))
    solvable = [t for t, v in truth.items() if v]
    ok = sum(1 for x in rows if truth.get(x["trade_id"]) == x["pnu"])
    wrong = sum(1 for x in rows
                if truth.get(x["trade_id"]) not in (None, x["pnu"]))
    ghost = sum(1 for x in rows if truth.get(x["trade_id"]) is None)
    prec = ok / max(len(rows), 1)
    rec = ok / max(len(solvable), 1)

    print("\n채점")
    print(f"  찾은 것 {len(rows):,}건 · 맞음 {ok:,} · 틀린 필지 {wrong:,} "
          f"· 일부거래에 붙임 {ghost:,}")
    print(f"  정확도 {prec:.1%}  (목표 {TARGET_PRECISION:.0%})")
    print(f"  재현율 {rec:.1%}  (최소 {MIN_RECALL:.0%})")

    fail = []
    if prec < TARGET_PRECISION:
        fail.append(f"정확도 {prec:.1%} < {TARGET_PRECISION:.0%}")
    if rec < MIN_RECALL:
        fail.append(f"재현율 {rec:.1%} < {MIN_RECALL:.0%}")
    # 정답이 없는 거래에 지번을 붙이면 그것은 **없는 사실을 만든 것**이다.
    if ghost > len(rows) * 0.02:
        fail.append(f"정답 없는 거래에 붙인 것 {ghost:,}건이 너무 많다")
    print()
    if fail:
        print("실패: " + " · ".join(fail))
        return 1
    print("통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
