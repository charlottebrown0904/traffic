"""워크플로가 결과를 잃지 않는지 검사한다.

run 13 이 여기서 죽었다. 2시간 33분 걸린 전국 수집이 전 단계 성공으로
끝나고, 마지막 '결과 커밋' 에서만 실패했다. 두 가지가 겹쳤다.

  1. 얕은 클론  actions/checkout 은 기본이 depth 1 이다. 원격 브랜치와의
     공통 조상을 모르는 상태에서 rebase 하면 git 이 모든 파일을 '양쪽이
     각자 새로 만든 파일' 로 보고 add/add 충돌을 낸다. 40개 파일이 전부
     충돌했다.
  2. 대상 브랜치 고정  브랜치에서 돌렸는데 push 는 main 으로 하고 있었다.
     설령 충돌이 없었어도 그 브랜치의 코드 변경이 통째로 main 에 올라갔다.

둘 다 로그를 열어보기 전에는 초록/빨강만으로 구별되지 않는 종류라 검사로
못박아 둔다.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows"

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 결과를 되돌려 놓는 브랜치를 고정하지 않는다")
# 'HEAD:main' 처럼 브랜치 이름을 박아 넣으면 어느 브랜치에서 돌리든
# main 으로 간다. github.ref_name 을 써야 실행한 자리로 돌아간다.
HARDCODED = re.compile(r"git\s+push\s+\S+\s+[\"']?HEAD:(?!\$)(\w+)")
for path in sorted(WF.glob("*.yml")):
    text = path.read_text(encoding="utf-8")
    hits = HARDCODED.findall(text)
    check(not hits, f"{path.name} — 고정된 push 대상 {hits or '없음'}")

print()
print("2. rebase 하는 워크플로는 전체 이력을 받는다")
for path in sorted(WF.glob("*.yml")):
    text = path.read_text(encoding="utf-8")
    if "--rebase" not in text:
        continue
    check("fetch-depth: 0" in text,
          f"{path.name} — rebase 를 하는데 fetch-depth: 0 이 있는가")

print()
print("3. 오래 도는 수집은 커밋이 막혀도 결과물을 남긴다")
# 커밋 실패가 곧 결과 손실이 되면, 몇 시간짜리 실행을 처음부터 다시 돌려야 한다.
collect = (WF / "collect.yml").read_text(encoding="utf-8")
check("upload-artifact" in collect, "collect.yml — 화면 데이터 아티팩트 업로드")
check(re.search(r"upload-artifact[\s\S]{0,200}?path: public/app/data", collect)
      is not None, "collect.yml — 올리는 대상이 public/app/data")

print()
print("4. 분석이 읽는 파일은 저장소에 실제로 들어 있다")
# 러너는 매번 새로 체크아웃한다. gitignore 에 걸린 파일은 거기에 없고,
# 코드가 조용히 넘어가면 로그에도 안 남는다. run 13 이 그렇게 돌았다 —
# tollgate_succession.csv 가 없어 코드 승계 영업소를 처치군에서 못 뺐다.
import subprocess

NEEDED = [
    "data/raw/tollgate_events.csv",       # 개통 판정
    "data/raw/tollgate_succession.csv",   # 승계 제외 (없으면 처치군 오염)
    "data/raw/PROVENANCE.md",             # 연도별 검증 기록
]

# 영업소 명부는 파일 이름에 날짜가 붙으므로 목록이 아니라 유형으로 본다.
# 교통량 파일에는 영업소명이 없어서, 좌표를 이름으로 찾을 때 이것이
# 유일한 원천이다. 무시되면 러너가 못 읽고 신설 영업소는 이름 없이 남는다.
import glob as _glob
_master = _glob.glob(str(ROOT / "data/raw/tollgate_master_*.csv"))
tracked = set(subprocess.run(
    ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split())
for rel in NEEDED:
    check(rel in tracked, f"{rel} 이 저장소에 추적되고 있다")
if _master:
    rel = [str(Path(f).relative_to(ROOT)) for f in _master]
    check(all(r in tracked for r in rel),
          f"영업소 명부가 추적되고 있다 ({len(rel)}개)")
else:
    check(False, "영업소 명부(tollgate_master_*.csv)가 없습니다")

# 전국 공장등록현황도 같은 함정에 걸린다. data/raw/* 가 통째로 무시되므로
# .gitignore 에 되살리는 줄이 없으면 러너에는 파일이 아예 없다. 명부와
# 승계표에서 이미 두 번 당했다.
_freg = _glob.glob(str(ROOT / "data/raw/factory_registry_*.csv.gz"))
if _freg:
    rel = [str(Path(f).relative_to(ROOT)) for f in _freg]
    check(all(r in tracked for r in rel),
          f"공장등록현황이 추적되고 있다 ({len(rel)}개)")

# 교통량 연간 CSV 는 한 해라도 빠지면 그 해가 통째로 사라진다.
import glob
years = sorted(int(Path(f).stem.split("_")[-1])
               for f in glob.glob(str(ROOT / "data/raw/tcs_annual_*.csv"))
               if Path(f).stem.split("_")[-1].isdigit())
for y in years:
    for kind in ("annual", "monthly"):
        rel = f"data/raw/tcs_{kind}_{y}.csv"
        check(rel in tracked or not (ROOT / rel).exists(),
              f"{rel} 이 추적되고 있다")

print()
print("5. 지오코딩이 반경 안을 먼저 붙인다")

# 브이월드 하루 한도는 4,000건인데 좌표 없는 거래는 329만 건이다. 앞에서부터
# 눈감고 붙이면 822번을 돌려야 하고, 그중 대부분은 영업소에서 멀어 어느
# 밴드에도 못 들어간다. 근거리 밴드는 지번 좌표만 받으므로
# (settings.spatial.require_parcel_bands) 반경 밖에 쓴 호출은 표에 한 건도
# 보태지 못한다. 눈감은 geocode 로 되돌아가면 이 손실이 조용히 돌아온다.
collect = (WF / "collect.yml").read_text()
steps = [ln.strip() for ln in collect.splitlines()
         if "redt.cli geocode" in ln]
check(bool(steps), "수집에 지오코딩 단계가 있다")
check(all("geocode-staged" in ln for ln in steps),
      "수집이 눈감은 geocode 가 아니라 geocode-staged 를 쓴다")

# 2단계가 성립하려면 영업소 반경이 설정에 있어야 한다.
import yaml as _yaml
_cfg = _yaml.safe_load((ROOT / "config" / "settings.yaml").read_text())
check(_cfg.get("spatial", {}).get("max_link_km") is not None,
      "반경을 가릴 max_link_km 이 설정에 있다")
check(bool(_cfg.get("spatial", {}).get("require_parcel_bands")),
      "근거리 밴드가 지번 좌표만 받도록 돼 있다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
