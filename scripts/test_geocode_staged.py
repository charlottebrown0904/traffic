"""2단계 지오코딩이 실제로 도는지 검사한다.

geocode-staged 는 코드와 단위검사는 있었지만 **한 번도 실행된 적이 없다.**
수집 워크플로에서 이 단계는 continue-on-error 가 아니라, 여기서 터지면
link·panel·export 까지 통째로 못 돈다. 5시간짜리 실행이 지오코딩 한 줄에
죽는 것을 러너에서 처음 알게 되면 안 된다.

네트워크는 부르지 않는다. 부르는 자리를 가짜로 바꾸고, 그 뒤의 SQL 이
도는지 — 특히 UPDATE ... FROM 두 개가 DuckDB 에서 성립하는지 — 를 본다.
틀린 SQL 은 예외를 던지지만, 조건이 어긋난 SQL 은 조용히 0행을 고친다.
그래서 행이 실제로 바뀌었는지까지 센다.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 진짜 DB 를 건드리면 안 된다. 임시 파일로 갈아끼운 뒤에 redt 를 들인다.
tmp = Path(tempfile.mkdtemp()) / "test.duckdb"
os.environ["REDT_DB_PATH"] = str(tmp)

from redt import config as cfg          # noqa: E402
cfg.DB_PATH = tmp
from redt import db                     # noqa: E402
db.DB_PATH = tmp
from redt.collect import geocode as gc  # noqa: E402
from redt import cli                    # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


# --- 자료를 심는다 -------------------------------------------------------
# 영업소 한 곳. 반경 안 법정동 하나, 반경 밖 법정동 하나.
TG_LAT, TG_LON = 37.0000, 127.0000
NEAR = (37.0100, 127.0100)     # 약 1.4km
FAR = (37.5000, 127.5000)      # 약 70km

with db.connect() as con:
    con.execute(
        "INSERT INTO tollgate (tollgate_id, name, lat, lon) VALUES (?,?,?,?)",
        ["001", "시험영업소", TG_LAT, TG_LON])
    rows = [
        # (trade_id, sigungu, umd, jibun)
        ("t1", "41111", "가까운동", "1-1"),
        ("t2", "41111", "가까운동", "1-2"),
        ("t3", "41111", "먼동", "9-9"),
    ]
    for tid, sgg, umd, jibun in rows:
        con.execute(
            "INSERT INTO trade (trade_id, sigungu, umd, jibun, land_use, "
            "kind, deal_year) VALUES (?,?,?,?,?,?,?)",
            [tid, sgg, umd, jibun, "계획관리지역", "land", 2020])

# --- 네트워크를 부르는 자리를 가짜로 -------------------------------------
called = {"umd": 0, "parcel": 0}


def fake_umd(pairs, cache=None, limit=None):
    called["umd"] += 1
    out = {}
    for sgg, umd in pairs:
        out[(sgg, umd)] = NEAR if umd == "가까운동" else FAR
    return out


def fake_parcel(rows, cache=None, limit=None):
    called["parcel"] += 1
    # 반경 밖 법정동이 여기까지 오면 2단계가 거르지 못한 것이다.
    fake_parcel.seen = list(rows)
    return {(s, u, j): (NEAR[0] + 0.001, NEAR[1] + 0.001) for s, u, j in rows}


fake_parcel.seen = []
gc.geocode_umd = fake_umd
gc.geocode_parcel = fake_parcel
cli.gc = gc


class Args:
    umd_limit = None
    limit = 4000
    all = False


print("1. 2단계 지오코딩이 예외 없이 끝난다")
try:
    cli.cmd_geocode_staged(Args())
    check(True, "geocode-staged 가 끝까지 돈다")
except Exception as exc:                              # noqa: BLE001
    check(False, f"geocode-staged 가 터졌다: {exc!r}")
    import traceback
    traceback.print_exc()

print()
print("2. 반경 밖은 지번을 부르지 않는다")
seen_umds = {u for _, u, _ in fake_parcel.seen}
check("먼동" not in seen_umds,
      "반경 밖 법정동의 지번은 호출 대상에서 빠진다")
check("가까운동" in seen_umds, "반경 안 법정동의 지번은 호출된다")

print()
print("3. SQL 이 실제로 행을 고친다 (조용한 0행이 아니다)")
with db.connect() as con:
    got = con.execute(
        "SELECT trade_id, lat, lon, geocode_level FROM trade ORDER BY trade_id"
    ).fetchall()
by_id = {r[0]: r for r in got}
check(all(r[1] is not None for r in got), "세 건 모두 좌표가 붙었다")
check(by_id["t1"][3] == "parcel", "반경 안은 지번단위로 기록된다")
check(by_id["t3"][3] == "umd", "반경 밖은 법정동단위로 기록된다")

print()
print("4. 거친 좌표가 정밀 좌표를 덮지 않는다")
# 법정동 UPDATE 는 lat IS NULL 인 행만 건드려야 한다. t1 은 지번으로
# 이미 채워졌으므로 법정동 중심점(NEAR)과 달라야 한다.
check(by_id["t1"][1] != NEAR[0],
      "지번으로 채운 행이 법정동 중심점으로 덮이지 않았다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
