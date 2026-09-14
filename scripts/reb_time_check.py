"""지가변동률이 시점수정 표로 이어졌는지 본다 — reb-stats.yml 의 load 뒤에.

못 이은 지역 이름이 여기 찍힌다. 그것이 valuation.match_region 의 이름 규칙을
고칠 근거다 — 짐작으로 잇지 않는다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from redt import db, valuation as V  # noqa: E402

with db.connect(read_only=True) as con:
    got = V.time_rates_for_web(con)
m = got["meta"]
print(f"시점수정 칸 {m.get('n', 0):,}개 · {m.get('first')}~{m.get('last')} · 지역 표 {m.get('regions')}곳")
if m.get("note"):
    print("  ", m["note"])
print("못 이은 지역:", m.get("unmatched"))
print("  그 GRP_ID 표본:", m.get("unmatched_ids"))
for k in ("41550|녹지지역", "41550|계획관리지역", "41550|*", "41|녹지지역", "*|녹지지역", "*|*"):
    print(" ", k, got["rates"].get(k))
