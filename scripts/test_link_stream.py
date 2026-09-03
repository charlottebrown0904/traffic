"""공간 조인이 메모리에 다 쌓지 않고 흘려 넣는지 검사한다.

run 17 이 여기서 죽었다. 수집 2시간 26분 + 지오코딩 1시간 58분을 끝낸
뒤, 조인 단계에서 러너가 통째로 사라졌다. 단계는 in_progress 인 채로
멈췄고 오류 메시지도 없었다 — 메모리 부족으로 러너가 죽으면 그렇게 된다.

러너가 죽으면 `if: always()` 인 캐시 저장조차 안 돈다. 4시간 30분이
같이 사라졌다.

원인은 두 겹이었다.
  1) 지오코딩이 전국 법정동에 거친 좌표를 써서 좌표 있는 거래가 수백만
     건이 됐다 (test_geocode_staged 4절에서 막는다)
  2) 조인이 결과를 전부 메모리에 쌓았다가 한 번에 넣었다 — 여기서 막는다

여기서 보는 것은 **거래를 나눠 읽고, 청크마다 DB 에 넣는가** 다.
한 번에 다 읽으면 좌표가 늘어나는 만큼 그대로 메모리가 늘어난다.
"""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

tmp = pathlib.Path(tempfile.mkdtemp()) / "test.duckdb"
from redt import config as cfg              # noqa: E402
cfg.DB_PATH = tmp
from redt import db                          # noqa: E402
db.DB_PATH = tmp
from redt import cli                         # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


# 영업소 하나, 그 반경 안 거래 여러 건
TG_LAT, TG_LON = 37.0, 127.0
N = 500
with db.connect() as con:
    con.execute("INSERT INTO tollgate (tollgate_id, name, lat, lon) "
                "VALUES ('001','시험',?,?)", [TG_LAT, TG_LON])
    for i in range(N):
        con.execute(
            "INSERT INTO trade (trade_id, sigungu, umd, jibun, kind, "
            "deal_year, lat, lon) VALUES (?,?,?,?,?,?,?,?)",
            [f"t{i:04d}", "41111", "동", f"{i}-1", "land", 2020,
             TG_LAT + (i % 20) * 0.002, TG_LON + (i % 20) * 0.002])

# 거래를 몇 번에 나눠 읽는지 센다.
reads = {"n": 0}
_orig = db.connect


class Spy:
    def __init__(self, con):
        self._c = con

    def execute(self, sql, *a, **k):
        if "FROM trade WHERE lat IS NOT NULL" in sql and "count(" not in sql:
            reads["n"] += 1
        return self._c.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return self._c.__exit__(*a)


db.connect = lambda *a, **k: Spy(_orig(*a, **k))

# 청크를 작게 해서 여러 번 나눠 읽게 만든다
cli.LINK_CHUNK = 100


class Args:
    pass


print("1. 조인이 끝까지 돈다")
try:
    cli.cmd_link(Args())
    check(True, "cmd_link 가 예외 없이 끝난다")
except Exception as exc:                     # noqa: BLE001
    check(False, f"터졌다: {exc!r}")
    import traceback
    traceback.print_exc()

print()
print("2. 거래를 한 번에 다 읽지 않는다")
# 500건을 100씩 → 5번 이상. 1번이면 통째로 읽은 것이다.
check(reads["n"] >= 5,
      f"거래를 나눠 읽는다 ({reads['n']}회 — 통째로 읽으면 1회)")

print()
print("3. 결과가 실제로 저장됐다 (나눠 넣어도 빠지지 않는다)")
db.connect = _orig
with db.connect() as con:
    n = con.execute("SELECT count(*) FROM trade_tollgate_link").fetchone()[0]
    uniq = con.execute(
        "SELECT count(DISTINCT trade_id) FROM trade_tollgate_link").fetchone()[0]
check(n > 0, f"조인 결과가 있다 ({n:,}쌍)")
check(uniq == N, f"모든 거래가 조인됐다 ({uniq}/{N})")

print()
print("4. 다시 돌려도 중복이 쌓이지 않는다")
cli.cmd_link(Args())
with db.connect() as con:
    n2 = con.execute("SELECT count(*) FROM trade_tollgate_link").fetchone()[0]
check(n2 == n, f"재실행해도 같은 수 ({n:,} → {n2:,})")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
