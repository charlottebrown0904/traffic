"""재수집이 지오코딩 결과를 지우지 않는지 검사한다.

run 16 에서 거래가 119만 → 1,164만 건으로 늘었는데 지도에 찍히는 거래는
674 → 387 건으로 **줄었다.** 자료가 10배 늘었는데 표시가 줄어드는 것은
말이 안 된다.

원인은 db.upsert 의 INSERT OR REPLACE 였다. 실거래가 API 응답에는 좌표
칸이 없으므로 재수집하면 lat/lon 이 NULL 로 들어오고, REPLACE 는 행을
통째로 갈아끼운다. 하루 4,000건 한도로 붙여둔 좌표가 재수집 한 번에
날아간다. 예외도 경고도 안 난다 — 표만 얇아진다.

같은 모양이 영업소에도 있다. 도로공사 마스터에는 민자고속도로 좌표가
없어서 fill-tollgates 가 이름으로 찾아 채우는데, 다음 실행의 '영업소
마스터' 단계가 그것을 다시 지운다.
"""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

tmp = pathlib.Path(tempfile.mkdtemp()) / "test.duckdb"
from redt import config as cfg                      # noqa: E402
cfg.DB_PATH = tmp
from redt import db                                 # noqa: E402
db.DB_PATH = tmp
import pandas as pd                                 # noqa: E402
from redt.cli import GEOCODE_COLS, TOLLGATE_FILLED  # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


def trade_row(**kw):
    base = {"trade_id": "T1", "sigungu": "41111", "umd": "가", "jibun": "1-1",
            "kind": "land", "deal_year": 2020, "lat": None, "lon": None,
            "geocode_level": None}
    base.update(kw)
    return pd.DataFrame([base])


print("1. 재수집이 지오코딩 결과를 지우지 않는다")
with db.connect() as con:
    db.upsert(con, "trade", trade_row(), preserve=GEOCODE_COLS)
    con.execute("UPDATE trade SET lat=37.1, lon=127.1, geocode_level='parcel'")
    # 같은 거래가 다시 수집된다 (응답에 좌표 칸이 없다)
    db.upsert(con, "trade", trade_row(), preserve=GEOCODE_COLS)
    got = con.execute(
        "SELECT lat, lon, geocode_level FROM trade").fetchone()
check(got == (37.1, 127.1, "parcel"),
      f"좌표가 살아남는다 (받은 값: {got})")

print()
print("2. 값이 실제로 들어오면 덮는다 (갱신은 정상 동작이다)")
with db.connect() as con:
    db.upsert(con, "trade", trade_row(lat=38.0, lon=128.0,
                                      geocode_level="umd"),
              preserve=GEOCODE_COLS)
    got = con.execute("SELECT lat, lon, geocode_level FROM trade").fetchone()
check(got == (38.0, 128.0, "umd"),
      f"새 좌표가 들어오면 그것으로 바뀐다 (받은 값: {got})")

print()
print("3. 지키라고 안 한 칸은 그대로 덮는다")
with db.connect() as con:
    db.upsert(con, "trade", trade_row(deal_year=2021), preserve=GEOCODE_COLS)
    year = con.execute("SELECT deal_year FROM trade").fetchone()[0]
check(year == 2021, f"거래연도는 새 값으로 갱신된다 (받은 값: {year})")

print()
print("4. 새 행은 그냥 들어간다")
with db.connect() as con:
    db.upsert(con, "trade", trade_row(trade_id="T2"), preserve=GEOCODE_COLS)
    n = con.execute("SELECT count(*) FROM trade").fetchone()[0]
check(n == 2, f"기존 행이 없으면 그대로 삽입된다 ({n}건)")

print()
print("5. 영업소 — 민자 좌표 보충이 마스터 재적재에 지워지지 않는다")
with db.connect() as con:
    con.execute("INSERT INTO tollgate (tollgate_id, name) VALUES ('999','민자')")
    con.execute("UPDATE tollgate SET lat=36.5, lon=127.5, sido='충북' "
                "WHERE tollgate_id='999'")
    master = pd.DataFrame([{"tollgate_id": "999", "name": "민자",
                            "lat": None, "lon": None, "sido": None}])
    db.upsert(con, "tollgate", master, preserve=TOLLGATE_FILLED)
    got = con.execute(
        "SELECT lat, lon, sido FROM tollgate WHERE tollgate_id='999'").fetchone()
check(got == (36.5, 127.5, "충북"),
      f"이름으로 채운 좌표가 살아남는다 (받은 값: {got})")

print()
print("5-2. 명부 등재가 좌표를, 이름검색이 운영기관코드를 안 지운다")
# 이제 영업소 표를 세 곳이 쓴다. 어느 하나도 남의 칸을 갖고 있지 않다.
#
#   도로공사 API   좌표·노선은 있고, 운영기관코드가 없다
#   명부 CSV       이름·노선·운영기관코드는 있고, 좌표가 없다
#   이름검색(POI)  좌표만 있고, 나머지가 전부 없다
#
# 지키지 않으면 단계를 하나 돌 때마다 서로의 값을 지운다. 마도(805)가
# 좌표를 받아도 다음 실행의 명부 등재가 그것을 지우면 지도에서 다시
# 사라진다 — 같은 사고를 이미 거래 좌표에서 한 번 냈다.
with db.connect() as con:
    con.execute("DELETE FROM tollgate")
    # 1) 명부가 먼저 등재한다 — 이름·운영기관코드만 있다
    db.upsert(con, "tollgate", pd.DataFrame([{
        "tollgate_id": "805", "name": "마도", "route_no": "400",
        "operator_cd": "48"}]),
        preserve=["lat", "lon", "sido", "sigungu", "sigungu_cd", "is_open_type"])
    # 2) 이름검색이 좌표를 채운다 — 운영기관코드가 없다
    db.upsert(con, "tollgate", pd.DataFrame([{
        "tollgate_id": "805", "name": "마도", "route_no": None,
        "lat": 37.15, "lon": 126.75, "src": "poi"}]),
        preserve=["operator_cd", "route_no"])
    got = con.execute("SELECT lat, operator_cd, route_no FROM tollgate "
                      "WHERE tollgate_id='805'").fetchone()
check(got == (37.15, "48", "400"),
      f"좌표를 채워도 운영기관코드·노선이 남는다 (받은 값: {got})")

with db.connect() as con:
    # 3) 다음 실행의 명부 등재가 좌표를 지우지 않는다
    db.upsert(con, "tollgate", pd.DataFrame([{
        "tollgate_id": "805", "name": "마도", "route_no": "400",
        "operator_cd": "48"}]),
        preserve=["lat", "lon", "sido", "sigungu", "sigungu_cd", "is_open_type"])
    got = con.execute("SELECT lat, lon FROM tollgate "
                      "WHERE tollgate_id='805'").fetchone()
check(got == (37.15, 126.75),
      f"명부를 다시 실어도 좌표가 살아남는다 (받은 값: {got})")

print()
print("6. preserve 를 안 주면 예전 동작 그대로다")
# 이 검사가 없으면 preserve 가 전역 동작을 바꿔버렸는지 알 수 없다.
with db.connect() as con:
    con.execute("DELETE FROM trade")
    db.upsert(con, "trade", trade_row(lat=37.1))
    db.upsert(con, "trade", trade_row())
    got = con.execute("SELECT lat FROM trade").fetchone()[0]
check(got is None, f"preserve 없이는 예전처럼 덮어쓴다 (받은 값: {got})")

print()
print("7. 기본키가 없으면 조용히 넘어가지 않는다")
# 지키라고 적었는데 못 지키는 상황에서 옛 동작으로 돌아가면, 지워진 것을
# 아무도 모른다. 말하고 멈추는 편이 낫다.
with db.connect() as con:
    con.execute("CREATE TABLE nopk (a VARCHAR, lat DOUBLE)")
    try:
        db.upsert(con, "nopk", pd.DataFrame([{"a": "x", "lat": None}]),
                  preserve=["lat"])
        check(False, "기본키가 없으면 오류를 낸다")
    except ValueError as exc:
        check("기본키" in str(exc), f"기본키가 없으면 오류를 낸다 ({exc})")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
