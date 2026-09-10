"""필지 특성 수집 — 범위와 중간 저장.

요구사항(2026-09-08): "필지 특성 대상을 전국 전체로 넓혀 주세요."

두 가지가 함께 바뀌어야 한다.

  1. 대상을 넓힌다 — 밴드 밖도, 용도지역 전부도, 공장/창고도
  2. **받은 것을 중간중간 DB 에 넣는다** — 예전에는 다 받아서 끝에
     한 번에 넣었다. 밴드 안 세 용도지역(필지 434만)까지는 그래도
     됐지만 전국이면 그 몇 배가 메모리에 쌓여 러너가 죽는다.

2번이 없으면 1번은 그냥 고장이다. 그래서 검색만 흉내내고 나머지는
진짜로 돌린다 — SQL·칸 나누기·중간 저장·재개까지.
"""
import argparse
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
from redt import cli                                # noqa: E402
from redt.collect import landchar as lc             # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


# ── 자료 ──
# 네 건을 서로 다른 칸에 흩어 놓는다. 각각이 한 조건씩 밟는다.
# 좌표는 칸 **한가운데**로 둔다. 0.01도 격자라 x.x0 은 칸 경계에 딱
# 걸리고, 경계 위의 점은 광선 교차가 안팎을 가리지 못한다. 실제 거래가
# 경계에 정확히 떨어질 일은 드물지만, 검사가 그것 때문에 흔들리면 안 된다.
ROWS = [
    # 밴드 안 · 계획관리 · 토지         → core 부터 잡힌다
    dict(trade_id="A", kind="land", land_use="계획관리지역",
         lat=37.105, lon=127.105, band=True),
    # 밴드 안 · 농림   · 토지           → core 에서는 빠진다
    dict(trade_id="B", kind="land", land_use="농림지역",
         lat=37.205, lon=127.205, band=True),
    # 밴드 밖 · 계획관리 · 토지         → core 에서는 빠진다
    dict(trade_id="C", kind="land", land_use="계획관리지역",
         lat=37.305, lon=127.305, band=False),
    # 밴드 밖 · 공장                    → all 에서만 잡힌다
    dict(trade_id="D", kind="factory", land_use="계획관리지역",
         lat=37.405, lon=127.405, band=False),
]
trades = pd.DataFrame([
    dict(trade_id=r["trade_id"], kind=r["kind"], sigungu_cd="41550",
         sigungu="안성시", umd="공도읍", jibun="1", land_use=r["land_use"],
         lat=r["lat"], lon=r["lon"], geocode_level="parcel",
         deal_year=2025, price_per_m2=100000.0, area_m2=1000.0,
         is_cancelled=False)
    for r in ROWS
])
links = pd.DataFrame([
    dict(trade_id=r["trade_id"], tollgate_id="101", distance_km=2.0,
         band="1-3", is_nearest=True)
    for r in ROWS if r["band"]
])
with db.connect() as con:
    db.upsert(con, "trade", trades)
    db.upsert(con, "trade_tollgate_link", links)


def fake_fetch(box, pace):
    """칸 하나에 필지 하나. 그 칸을 통째로 덮는 사각형.

    **진짜 WFS 가 주는 모양 그대로** 만든다 (properties + geometry).
    우리 편한 모양으로 지어내면 match_tile 이 실제로 도는지 못 본다.
    """
    w, s_, e, n = box
    return ([{
        "type": "Feature",
        "properties": {
            "pnu": f"P{w:.3f}_{s_:.3f}", "ld_cpsg_code": "41550",
            "lndcgr_code_nm": "답", "prpos_area_1_nm": "계획관리",
            "lad_use_sittn_nm": "전", "lndpcl_ar": "1000",
            "road_side_code_nm": "세로한면(가)", "tpgrph_frm_code_nm": "부정형",
            "tpgrph_hg_code_nm": "평지", "pblntf_pclnd": "50000",
            "stdr_year": "2025",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[w, s_], [e, s_], [e, n], [w, n], [w, s_]]],
        },
    }], False)


lc.fetch_tile = fake_fetch


def run(scope, max_tiles=0, flush_every=400):
    cli.cmd_landchar(argparse.Namespace(
        tile=None, workers=1, max_tiles=max_tiles,
        scope=scope, flush_every=flush_every))


def linked():
    with db.connect(read_only=True) as con:
        return {r[0] for r in con.execute(
            "SELECT trade_id FROM trade_parcel").fetchall()}


print("1. core — 예전 기본값 (밴드 안 · 세 용도지역 · 토지만)")
run("core")
got = linked()
check(got == {"A"}, f"A 만 잡힌다 — {sorted(got)}")

print("\n2. land — 전국 · 용도지역 전부 · 토지만")
run("land")
got = linked()
check(got == {"A", "B", "C"}, f"밴드 밖·농림까지 잡고 공장은 아직 — {sorted(got)}")

print("\n3. all — 전국 · 토지+공장/창고 (새 기본값)")
run("all")
got = linked()
check(got == {"A", "B", "C", "D"}, f"공장까지 잡힌다 — {sorted(got)}")
# **넓혀도 이미 붙은 것을 다시 받지 않는다.** 안 그러면 범위를 넓힐
# 때마다 처음부터 다시 훑는다.
with db.connect(read_only=True) as con:
    n_tiles = con.execute("SELECT count(*) FROM parcel_tile").fetchone()[0]
check(n_tiles == 4, f"칸은 네 개만 훑었다 ({n_tiles})")

print("\n4. 중간에 DB 에 넣는다 (메모리를 비운다)")
# 전국으로 넓히면 필지가 수천만 개다. 끝에 한 번에 넣으면 러너가 죽는다.
# 칸을 하나 훑을 때마다 넣도록 해서, 도중에 끊겨도 남는지 본다.
with db.connect() as con:
    con.execute("DELETE FROM trade_parcel")
    con.execute("DELETE FROM parcel")
    con.execute("DELETE FROM parcel_tile")

flushed = {"n": 0}
_real = fake_fetch


def counting_fetch(box, pace):
    flushed["n"] += 1
    if flushed["n"] == 3:
        raise RuntimeError("여기서 러너가 죽었다고 치자")
    return _real(box, pace)


lc.fetch_tile = counting_fetch
run("all", flush_every=1)
lc.fetch_tile = _real
got = linked()
# 죽은 칸 하나만 빠지고 나머지는 남아야 한다.
check(len(got) == 3, f"도중에 죽어도 넣은 데까지 남는다 ({len(got)}건: {sorted(got)})")
with db.connect(read_only=True) as con:
    n_tiles = con.execute("SELECT count(*) FROM parcel_tile").fetchone()[0]
check(n_tiles == 3, f"성공한 칸만 기록된다 — 실패한 칸은 다음이 다시 한다 ({n_tiles})")

# 다시 돌리면 실패했던 칸만 집는다.
run("all")
check(linked() == {"A", "B", "C", "D"}, f"다음 실행이 못 받은 칸을 마저 받는다 — {sorted(linked())}")

print("\n9. 같은 칸 안에서 대상이 늘어나면 그 칸을 다시 훑는다")
# **run 44 가 여기서 반쪽만 붙였다.**
#
#     붙일 거래 1,484,720건
#     칸 7,520개 중 아직 안 훑은 것 1,168개   ← 나머지 6,352칸이 갇혔다
#
# 필지 도형은 저장하지 않는다 — 받는 자리에서 맞추고 버린다. 그래서
# 이미 훑은 칸 안에 **새로 대상이 된 거래**가 생기면, 그 칸을 다시
# 받지 않는 한 영영 못 붙인다.
#
# 앞의 검사들이 이것을 못 잡은 이유: 거래를 저마다 다른 칸에 흩어
# 놓아서 '같은 칸에 대상이 늘어나는' 상황을 한 번도 안 만들었다.
# 여기서는 **한 칸에 두 건**을 넣는다.
with db.connect() as con:
    con.execute("DELETE FROM trade")
    con.execute("DELETE FROM trade_tollgate_link")
    con.execute("DELETE FROM trade_parcel")
    con.execute("DELETE FROM parcel")
    con.execute("DELETE FROM parcel_tile")
    # 같은 0.01도 칸(127.10~127.11, 37.10~37.11) 안의 두 건.
    db.upsert(con, "trade", pd.DataFrame([
        dict(trade_id="SAME_core", kind="land", sigungu_cd="41550",
             sigungu="안성시", umd="공도읍", jibun="1",
             land_use="계획관리지역", lat=37.104, lon=127.104,
             geocode_level="parcel", deal_year=2025,
             price_per_m2=100000.0, area_m2=1000.0, is_cancelled=False),
        dict(trade_id="SAME_wide", kind="factory", sigungu_cd="41550",
             sigungu="안성시", umd="공도읍", jibun="2",
             land_use="농림지역", lat=37.106, lon=127.106,
             geocode_level="parcel", deal_year=2025,
             price_per_m2=100000.0, area_m2=1000.0, is_cancelled=False),
    ]))
    db.upsert(con, "trade_tollgate_link", pd.DataFrame([
        dict(trade_id="SAME_core", tollgate_id="101", distance_km=2.0,
             band="1-3", is_nearest=True)]))

lc.fetch_tile = fake_fetch
run("core")
check(linked() == {"SAME_core"}, f"core 로는 한 건만 — {sorted(linked())}")

# 넓힌다. 그 칸은 이미 '훑음' 으로 적혀 있지만 **범위가 좁았으므로**
# 다시 훑어야 한다.
run("all")
check(linked() == {"SAME_core", "SAME_wide"},
      f"넓히면 같은 칸의 새 거래도 붙는다 — {sorted(linked())}")
with db.connect(read_only=True) as con:
    sc = con.execute("SELECT scope FROM parcel_tile").fetchall()
check(all(r[0] == "all" for r in sc), f"칸에 지금 범위가 기록된다 — {sc}")

# 같은 범위로 다시 돌리면 이제는 건너뛴다. 안 그러면 넓힌 뒤로
# 매 실행이 전국을 처음부터 다시 훑는다.
before = len(linked())
run("all")
check(len(linked()) == before, "같은 범위로 다시 돌리면 건너뛴다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
