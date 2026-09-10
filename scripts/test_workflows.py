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

import yaml as _yaml

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
#
# 예외가 하나 있다. **일부러 라이브에 올리는 푸시**다. Vercel 이 main 만
# 프로덕션으로 배포하므로, 실행이 끝에서 main 을 따라오게 한다. 그것까지
# 막으면 사람이 매번 손으로 머지해야 하고, 그러다 19개 커밋이 라이브에
# 안 올라간 채로 하루가 지났다.
#
# 그래서 이름으로 봐주지 않고 **조건으로** 봐준다: fast-forward 인지
# 확인한 뒤에 미는 푸시만 허용한다. merge-base --is-ancestor 가 없는
# 푸시는 남의 커밋을 지울 수 있으므로 이름이 무엇이든 걸린다.
HARDCODED = re.compile(r"git\s+push\s+\S+\s+[\"']?HEAD:(?!\$)(\w+)")
GUARD = "merge-base --is-ancestor"

# 라이브 주소. 이사를 하면 여기 한 줄만 고치고, 검사가 나머지를 잡는다.
LIVE_ORIGIN = "https://toji.fyi"
DEAD_ORIGIN = "toji-gogo.pages.dev"      # 은퇴한 Cloudflare Pages


def _run_blocks(text: str) -> list[str]:
    """워크플로의 run 스크립트를 하나씩 꺼낸다.

    파일 전체를 한 덩어리로 보면 '한 단계의 안전장치' 가 '다른 단계의
    무모한 푸시' 를 덮어준다. 단계별로 봐야 그 착시가 없다.
    """
    try:
        doc = _yaml.safe_load(text) or {}
    except _yaml.YAMLError:
        return [text]
    blocks = []
    for job in (doc.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if isinstance(step, dict) and step.get("run"):
                blocks.append(str(step["run"]))
    return blocks or [text]


for path in sorted(WF.glob("*.yml")):
    text = path.read_text(encoding="utf-8")
    hits = [b for block in _run_blocks(text)
            for b in HARDCODED.findall(block) if GUARD not in block]
    check(not hits, f"{path.name} — 확인 없이 고정된 push 대상 {hits or '없음'}")

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
print("6. Actions 용량 — 3시간짜리를 매번 돌지 않는다")

# 실측(9월 3일간): Actions 최소 1,994분. 비공개 저장소 Free 한도가
# 월 2,000분이다. 그중 952분(48%)이 실패·취소로 날아갔고, 성공한
# run 21 도 3시간 11분이 걸렸다 — 그 대부분이 지오코딩이다.
#
#   지오코딩   2시간 58분   브이월드 하루 3만건에 묶여 있다
#   조인            9분
#   분석 + 화면     3분
#
# 화면 색 하나 고치는 데 필요한 것은 뒤의 12분뿐이다.
_wf = (ROOT / ".github/workflows/collect.yml").read_text(encoding="utf-8")
import yaml as _yamllib                                     # noqa: E402
_y = _yamllib.safe_load(_wf)
# YAML 1.1 은 on 을 **불리언 True** 로 읽는다. GitHub 워크플로의 가장
# 흔한 함정이라, _y["on"] 은 KeyError 가 난다.
_on = _y.get("on", _y.get(True))
_inputs = _on["workflow_dispatch"]["inputs"]
check("stage" in _inputs, "무엇까지 돌릴지 고를 수 있다 (stage)")
if "stage" in _inputs:
    _opts = _inputs["stage"].get("options") or []
    check("analyze" in _opts, f"분석만 돌리는 선택지가 있다 ({_opts})")
    # 화면 코드만 고쳤을 때를 위한 것 (요구사항 2026-09-08: "너무
    # 오래 걸리면 우선 테마부터 푸쉬하는 걸 추천합니다"). 라이브(main)는
    # 이 워크플로만 앞당기므로, CSS 한 줄에도 40분을 기다려야 했다.
    check("web" in _opts, f"화면만 돌리는 선택지가 있다 ({_opts})")

_steps = _y["jobs"]["collect"]["steps"]
_named = {s.get("name"): s for s in _steps if s.get("name")}
_geo = next((s for n, s in _named.items() if "지오코딩" in n), None)
check(_geo is not None and "stage == 'all'" in str(_geo.get("if", "")),
      "분석만 돌 때는 지오코딩을 건너뛴다")
_col = next((s for n, s in _named.items() if "실거래가 수집" in n), None)
check(_col is not None and "stage == 'all'" in str(_col.get("if", "")),
      "분석만 돌 때는 수집도 건너뛴다")

# web 이 실제로 가벼운가. 이름만 만들어 놓고 다 돌면 아무 뜻이 없다.
_HEAVY = ("공간 조인", "가설3 자료 적재", "분석 패널", "다섯 가설 판정",
          "필지 특성", "캐시 앞 정리")
_still = [n for n in _named
          if any(h in n for h in _HEAVY)
          and "stage != 'web'" not in str(_named[n].get("if", ""))]
check(not _still, f"web 은 무거운 단계를 건너뛴다 (아직 도는 것 {_still})")
# 점검(doctor)도 web 에서는 안 돈다. 캐시만 읽어 화면을 다시 뽑는 실행은
# 키도 네트워크도 안 쓴다. 그런데 run 58~60 은 여기서 실호출을 세 번
# 하다가 중계기 404 로 죽었고, **프런트 배포가 통째로 빨갛게** 됐다.
# 원인과 상관없는 곳에 빨간불이 켜지면 진짜 빨간불도 안 읽게 된다.
_doc = next((s2 for n, s2 in _named.items() if "점검" in n), None)
check(_doc is not None and "stage != 'web'" in str(_doc.get("if", "")),
      "web 은 키·네트워크 점검을 건너뛴다 (쓰지 않으므로)")

# 그런데 화면은 반드시 다시 만들어야 한다 — 안 그러면 낡은 JSON 이
# 새 코드와 함께 나간다.
_exp = next((s2 for n, s2 in _named.items() if "화면용 JSON" in n), None)
check(_exp is not None and "stage != 'web'" not in str(_exp.get("if", "")),
      "web 도 화면 JSON 은 다시 만든다")
_live = next((s2 for n, s2 in _named.items() if "라이브 반영" in n), None)
check(_live is not None and "stage != 'web'" not in str(_live.get("if", "")),
      "web 도 main 을 앞당긴다 (그게 목적이다)")

# 캐시는 한 번만 저장한다. 한 번이 2.36GB 인데 GitHub 한도는 10GB 라,
# 두 번씩 저장하면 실행 두 번치밖에 안 남는다. 넘치면 오래된 것부터
# 지워지고, 지오코딩 3시간이 든 캐시가 밀려나면 그 3시간을 다시 쓴다.
_saves = [s for s in _steps if "cache/save" in str(s.get("uses", ""))]
check(len(_saves) == 1, f"캐시 저장은 실행당 한 번이다 ({len(_saves)}회)")
if _saves:
    # **뭔가 산 실행은 반드시 저장한다.**
    #
    # 예전에는 stage=all 일 때만 저장했다. "분석만 도는 실행은 새로 산
    # 것이 없으므로" 라는 이유였고 그때는 맞았는데, 필지 특성과 관청
    # 좌표가 파이프라인에 들어오면서 틀린 말이 됐다. run 37~40 이
    # 3,000칸씩 훑고 네 번 다 버렸다.
    #
    # 그래서 "stage 를 절대 안 본다" 로 막아 뒀었는데, 그것은 규칙을
    # 너무 좁게 적은 것이다. 아무것도 안 사는 단계(web — 화면만 다시
    # 만든다)까지 2GB 를 다시 저장하면 10GB 한도가 그만큼 빨리 찬다.
    #
    # 진짜 규칙은 이것이다 — **저장을 건너뛰는 stage 에서는 사는 단계도
    # 하나도 안 돌아야 한다.** 그것을 실제로 계산해서 본다.
    def _runs_in(cond, stage):
        """이 조건이 그 stage 에서 참인가. 우리가 쓰는 세 모양만 푼다."""
        c = str(cond or "").strip()
        if not c:
            return True
        ok = True
        for part in c.split("&&"):
            part = part.strip()
            if part in ("always()", ""):
                continue
            if part.startswith("inputs.stage =="):
                ok = ok and (part.split("'")[1] == stage)
            elif part.startswith("inputs.stage !="):
                ok = ok and (part.split("'")[1] != stage)
            # 그 밖의 조건(landchar_tiles 등)은 stage 와 무관하므로 둔다
        return ok

    # 자료를 '사는' 단계. 이 중 하나라도 도는 stage 에서 저장을 건너뛰면
    # 그 실행이 산 것은 그대로 버려진다.
    BUYS = ("실거래가 수집", "지오코딩", "영업소 마스터", "영업소 보충",
            "교통량 적재", "전국 시군구 코드", "필지 특성", "관청 좌표")
    _save_if = _saves[0].get("if")
    _bad = []
    for stage in _opts:
        if _runs_in(_save_if, stage):
            continue
        for name, st in _named.items():
            if any(b in name for b in BUYS) and _runs_in(st.get("if"), stage):
                _bad.append(f"{stage}:{name}")
    check(not _bad,
          f"사는 단계가 도는 stage 에서는 반드시 저장한다 (버려지는 것 {_bad})")
    check("always()" in str(_saves[0].get("if", "")),
          "뒤 단계가 죽어도 산 것은 지킨다 (always)")

# 저장 자리는 두 가지를 **동시에** 만족해야 한다.
#   (1) 이번 실행이 산 것보다 뒤   — 안 그러면 산 것이 캐시에 안 들어간다
#   (2) 조인 결과를 뺀 뒤          — 1,961만 행을 이고 다니면 4.7GB 가 된다
_names = list(_named)
_compact = next((i for i, n in enumerate(_names) if "캐시 앞 정리" in n), None)
_save_i = next((i for i, n in enumerate(_names)
                if "cache/save" in str(_named[n].get("uses", ""))), None)
check(_compact is not None, "캐시 앞에 조인 결과를 빼는 단계가 있다")
if None not in (_compact, _save_i):
    check(_compact < _save_i,
          f"정리한 뒤에 저장한다 ({_compact} < {_save_i})")

# (1) 이 검사가 run 37~40 의 헛수고를 막는다. 자료를 사는 단계가
#     저장보다 앞에 있어야 한다 — 뒤에 있으면 산 것이 그대로 버려지고,
#     로그는 다음 실행에서 '아직 안 훑은 것 6,677개' 라고만 말한다.
for _buy in ("필지 특성", "관청 좌표 (", "지오코딩"):
    _i = next((i for i, n in enumerate(_names) if n.startswith(_buy)
               or _buy in n), None)
    check(_i is not None and _save_i is not None and _i < _save_i,
          f"'{_buy}' 로 산 것이 캐시에 들어간다 ({_i} < {_save_i})")

# 캐시는 조인 결과를 **일부러 비운 채** 저장된다(위 '캐시 앞 정리').
# 그러니 캐시에서 시작하는 모든 워크플로는 패널 앞에서 link 를 다시
# 돌려야 한다. analyze run 10 이 이것을 빠뜨려 '거래 0행' 으로 죽었다 —
# 조건(fill_tollgates)이 걸려 있었고, 그 전까지는 캐시에 연결이 남아
# 있어서 우연히 가려져 있었다.
_an = _yamllib.safe_load(
    (ROOT / ".github/workflows/analyze.yml").read_text(encoding="utf-8"))
_an_steps = _an["jobs"]["analyze"]["steps"]
_an_named = {str(st.get("name", "")): st for st in _an_steps}
_link = next((st for n, st in _an_named.items() if "재연결" in n), None)
check(_link is not None, "분석에도 거래↔영업소 재연결 단계가 있다")
if _link is not None:
    check("if" not in _link,
          "재연결에는 조건이 없다 (캐시의 연결은 언제나 0행이다)"
          f" — 지금 조건 {_link.get('if')!r}")
_an_names = [str(st.get("name", "")) for st in _an_steps]
_li = next((i for i, n in enumerate(_an_names) if "재연결" in n), None)
_pi = next((i for i, n in enumerate(_an_names) if "분석 패널" in n), None)
if None not in (_li, _pi):
    check(_li < _pi, f"재연결이 패널보다 먼저다 ({_li} < {_pi})")

# 점검은 **살아 있는 주소**를 두드려야 한다.
#
# 2026-09-10 까지 sitecheck 의 기본 주소가 은퇴한 Cloudflare Pages
# 주소였다. 점검은 초록으로 끝나는데 브이월드 타일만 전부 502·520 이라
# '브이월드가 죽었다' 로 읽혔다 — 실제로는 없는 집을 두드린 것이었다.
# 같은 시각 toji.fyi 는 같은 타일을 200·image/jpeg 로 줬다.
_sc = _yamllib.safe_load(
    (ROOT / ".github/workflows/sitecheck.yml").read_text(encoding="utf-8"))
_sc_on = _sc.get("on", _sc.get(True))
_sc_base = _sc_on["workflow_dispatch"]["inputs"]["base"].get("default", "")
check(_sc_base == LIVE_ORIGIN,
      f"점검이 라이브 주소를 본다 (지금 {_sc_base!r})")
# 은퇴한 주소가 어느 워크플로에도 남아 있으면 안 된다.
_dead = sorted(f.name for f in (ROOT / ".github/workflows").glob("*.yml")
               if DEAD_ORIGIN in f.read_text(encoding="utf-8"))
check(not _dead, f"은퇴한 주소가 남아 있지 않다 — {_dead}" if _dead
      else "은퇴한 주소가 남아 있지 않다")

# **모든 워크플로가 올바른 YAML 인가.**
#
# 2026-09-10: 탐침 워크플로 안에 heredoc 을 겹쳐 썼다가 YAML 이 깨졌고,
# 그것을 못 본 채 밀었다. GitHub 은 깨진 워크플로를 조용히 무시한다 —
# 목록에서 사라질 뿐 아무도 안 알려준다. 여기서 잡는다.
_broken = []
for _wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
    try:
        _doc = _yamllib.safe_load(_wf.read_text(encoding="utf-8"))
        if not isinstance(_doc, dict) or "jobs" not in _doc:
            _broken.append(f"{_wf.name} (jobs 가 없다)")
    except Exception as _exc:                                # noqa: BLE001
        _broken.append(f"{_wf.name} — {type(_exc).__name__}")
check(not _broken, f"워크플로가 전부 올바른 YAML 이다 — {_broken}" if _broken
      else "워크플로가 전부 올바른 YAML 이다")

# **저장소 파일을 부르면 checkout 이 있어야 한다.**
#
# sitecheck 은 오랫동안 curl 만 써서 checkout 이 없었다. 거기에
# scripts/live_probe.py 를 부르는 단계를 붙였더니 러너에 그 파일이
# 없어 죽었다 (run 11). 눈으로는 안 보이는 짝이라 검사로 묶는다.
for _wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
    _txt = _wf.read_text(encoding="utf-8")
    _uses_repo = ("scripts/" in _txt or "src/redt" in _txt
                  or "python -m redt" in _txt)
    if not _uses_repo:
        continue
    check("actions/checkout" in _txt,
          f"{_wf.name} 이 저장소 파일을 부르니 checkout 이 있다")

print()
print("7. 라이브 반영 — 브랜치에만 쌓이고 사이트는 그대로이던 것")

# Vercel 은 main 만 프로덕션으로 배포한다. 브랜치 푸시는 preview URL 만
# 만든다. 그래서 9월 3~4일 19개 커밋이 전부 라이브에 없었다 — 배포 목록에
# READY 로 떠 있는데도. 실행이 스스로 main 을 fast-forward 하게 했고,
# 여기서는 **그 자동화가 사고를 키우지 않는지**를 본다.
_ff = next((s for n, s in _named.items() if "라이브 반영" in n), None)
check(_ff is not None, "main 을 따라오게 하는 단계가 있다")

if _ff is not None:
    _run = str(_ff.get("run", ""))
    _if = str(_ff.get("if", ""))

    check("HEAD:main" in _run, "main 으로 민다")

    # 이것이 이 검사의 핵심이다. --force 가 들어가는 순간 남이 main 에
    # 올린 것을 실행이 조용히 지운다.
    check(not re.search(r"push[^\n]*(--force|--f\b|-f\b|\+HEAD)", _run),
          "강제 푸시를 하지 않는다 (--force 없음)")
    check("merge-base --is-ancestor" in _run,
          "fast-forward 인지 먼저 확인한다 (갈라져 있으면 안 민다)")

    # main 이 우리보다 앞선 경우를 '갈라졌다' 로 알리면 거짓 경보다.
    # 실행이 도는 동안 브랜치에 새 커밋이 올라가면 실제로 그렇게 된다.
    check("--is-ancestor HEAD origin/main" in _run,
          "main 이 이미 앞서 있으면 조용히 넘어간다 (거짓 경보를 안 만든다)")

    # 깨진 JSON 이 올라가면 브라우저가 조용히 탭을 끈다 — traffic.json 이
    # NaN 을 담아 순위 탭이 꺼져 있던 그 사고다. 오류도 안 난다.
    check("json.load" in _run,
          "화면 JSON 이 읽히는지 보고 민다 (깨진 것을 라이브로 안 보낸다)")

    check("github.ref_name != 'main'" in _if,
          f"main 에서 돌 때는 아무것도 안 한다 (if: {_if})")

    # 3시간 수집이 성공했는데 배포 한 줄 때문에 빨갛게 뜨면, 다음부터
    # 빨간 표시를 안 읽게 된다. 대신 요약칸에 적는다.
    check(_ff.get("continue-on-error") is True,
          "여기서 실패해도 수집 결과를 빨갛게 만들지 않는다")
    check("GITHUB_STEP_SUMMARY" in _run,
          "반영했는지/못 했는지를 실행 요약에 적는다 (휴대폰에서 맨 위)")

    # 데이터 커밋이 먼저 올라간 뒤에 밀어야 그 커밋까지 라이브에 간다.
    _commit_i = next((i for i, n in enumerate(_names) if "결과 커밋" in n), None)
    _ff_i = next((i for i, n in enumerate(_names) if "라이브 반영" in n), None)
    if None not in (_commit_i, _ff_i):
        check(_commit_i < _ff_i,
              f"결과 커밋 뒤에 민다 ({_commit_i} < {_ff_i})")

print()
print("7-2. 결과를 되돌려 놓을 때 생성물이 충돌하지 않는다")

# run 24 가 여기서 실패했다. 실행이 도는 동안 브랜치에 새 커밋이 올라가면
# 데이터 커밋을 그 위로 rebase 하게 되는데, 양쪽이 고치는 파일이 똑같다 —
# public/app/data/*.json 은 매 실행이 통째로 다시 쓴다.
#
# 충돌하면 그냥 실패로 끝나지 않는다. **작업 트리가 rebase 중간 상태로
# 남는다.** run 24 에서는 chart.json 이 빈 파일이 됐고, 뒤따르는 라이브
# 반영이 그것을 잡아냈다. 안전장치가 없었으면 빈 파일이 프로덕션에 나갔다.
_commit = next((s for n, s in _named.items() if n == "결과 커밋"), None)
check(_commit is not None, "결과 커밋 단계가 있다")
if _commit is not None:
    _cr = str(_commit.get("run", ""))
    check("--rebase" not in _cr,
          "생성물을 rebase 로 합치지 않는다 (충돌이 날 수밖에 없다)")
    check("reset --hard" in _cr,
          "브랜치 최신에 맞춘 뒤 생성물을 다시 놓는다")
    # 치워 두지 않고 reset --hard 하면 방금 만든 결과가 통째로 날아간다.
    check("mktemp -d" in _cr and "cp -r" in _cr,
          "reset 전에 생성물을 옆에 치워 둔다")
    check("git fetch origin" in _cr, "매 시도마다 브랜치를 다시 받는다")

print()
print("8. 캐시가 한도를 넘으면 스스로 줄인다")

# run 23 이 12.35GB / 10GB (124%) 를 찍었다. 넘치면 GitHub 이 **오래된
# 것부터 조용히 지운다.** 무엇이 지워졌는지는 어디에도 안 남고, 다음
# 실행이 처음부터 다시 받기 시작할 때에야 드러난다. 우연에 맡기지 않고
# 우리가 고른다.
_prune = next((s for n, s in _named.items() if "오래된 캐시 정리" in n), None)
check(_prune is not None, "수집이 끝에서 오래된 캐시를 지운다")
check(str(_y["permissions"].get("actions")) == "write",
      f"캐시를 지울 권한이 있다 (actions: {_y['permissions'].get('actions')})")

# 같은 로직을 두 군데 두면 한 곳만 고치게 된다. 이 저장소에서 이미 두 번
# 났던 사고라(_analysis_inputs, upsert preserve) 한 파일로 묶는다.
_script = ROOT / "scripts/prune_caches.py"
check(_script.exists(), "지우는 로직이 스크립트 한 곳에 있다")
_manual = WF / "cache-prune.yml"
check(_manual.exists(), "수집을 기다리지 않고 지금 돌릴 버튼이 있다")

_callers = [f.name for f in sorted(WF.glob("*.yml"))
            if "prune_caches.py" in f.read_text(encoding="utf-8")]
check(len(_callers) >= 2,
      f"두 워크플로가 같은 스크립트를 부른다 ({_callers})")
if _prune is not None:
    check("prune_caches.py" in str(_prune.get("run", "")),
          "수집도 그 스크립트를 부른다 (복사본이 아니다)")

if _script.exists():
    _src = _script.read_text(encoding="utf-8")
    check('method="DELETE"' in _src, "실제로 지운다")
    # 같은 실행의 캐시를 지우면 그 실행이 이어받을 것을 스스로 없앤다.
    check("GITHUB_RUN_ID" in _src and "run_id in c" in _src,
          "이번 실행이 만든 캐시는 건드리지 않는다")
    # pip 캐시 같은 남의 것을 지우면 매 실행이 다시 받는다.
    check('PREFIX = "redt-data-"' in _src and 'startswith(PREFIX)' in _src,
          "우리 캐시만 본다")
    check("last_accessed_at" in _src,
          "최근 쓴 것부터 남긴다 (지오코딩이 든 캐시를 지키기 위해)")
    check("--dry-run" in _src, "지우기 전에 무엇을 지울지 볼 수 있다")

_prune_i = next((i for i, n in enumerate(_names) if "오래된 캐시 정리" in n), None)
_report_i = next((i for i, n in enumerate(_names) if "용량 (캐시" in n), None)
if None not in (_prune_i, _report_i):
    check(_prune_i < _report_i,
          f"정리한 뒤에 용량을 찍는다 ({_prune_i} < {_report_i})")

print()
print("N. vercel.json — 배포를 통째로 막을 수 있는 파일")
# 2026-09-09 에 여기서 라이브가 두 시간 멈췄다.
#
# regions:["icn1"] 이 왜 있는지를 파일 안에 적어 두려고 "_regions_주석"
# 이라는 키를 넣었다. JSON 에 주석이 없으니 키로 대신한 것인데,
# **Vercel 은 모르는 최상위 키를 보면 배포 자체를 거부한다.**
#
#   The `vercel.json` schema validation failed with the following
#   message: should NOT have additional property `_regions_주석`
#
# 빌드 로그도 안 남는다 — 빌드가 시작되기 전에 잘리기 때문이다. 그래서
# 겉으로는 사이트가 멀쩡해 보인다. 예전 배포가 계속 서빙되기 때문이다.
# 커밋 다섯 개와 수집 세 번이 라이브에 안 올라간 채로 흘렀다.
#
# 교훈은 둘이다. **JSON 설정 파일에 설명을 키로 넣지 않는다.** 그리고
# **설명은 검사에 적는다** — 검사는 지우면 빨개지지만 주석은 조용히
# 지워진다.
_VERCEL_KEYS = {
    "$schema", "build", "buildCommand", "cleanUrls", "crons", "devCommand",
    "env", "framework", "functions", "git", "github", "headers", "images",
    "ignoreCommand", "installCommand", "outputDirectory", "public",
    "redirects", "regions", "rewrites", "routes", "trailingSlash",
    "functionFailoverRegions", "deploymentEnabled",
}
_vj = ROOT / "vercel.json"
check(_vj.exists(), "vercel.json 이 있다")
if _vj.exists():
    import json as _json
    try:
        _cfg = _json.loads(_vj.read_text(encoding="utf-8"))
    except ValueError as exc:
        check(False, f"올바른 JSON 이다 ({exc})")
        _cfg = {}
    _unknown = sorted(set(_cfg) - _VERCEL_KEYS)
    check(not _unknown,
          "Vercel 이 아는 최상위 키만 있다"
          + (f" — 모르는 키 {_unknown} 가 배포를 거부시킨다" if _unknown else ""))

    # **icn1(서울)은 장식이 아니라 이 제품이 도는 이유다.**
    # 한국 공공 API 가 해외 IP 를 막는다(docs/finding-geoblock.md).
    # 2026-09-09 에 Cloudflare Pages 로 옮겨 실측했더니 브이월드
    # (api.vworld.kr)가 502 로 거부했다 — 한국에서 열어도 마찬가지였다.
    # Cloudflare Workers 에는 리전 고정이 없다. 브이월드는 지오코딩·
    # 지적편집도·필지조회 셋에 다 쓰이므로 이 한 줄이 빠지면 제품의
    # 절반이 죽는다. (실측표: docs/cloudflare-migration.md)
    check(_cfg.get("regions") == ["icn1"],
          f"함수가 서울(icn1)에 고정돼 있다 (지금 {_cfg.get('regions')!r}) — "
          "한국 공공 API 가 해외 IP 를 막는다")

    # 들어오는 문은 **하나만** 둔다 (요구사항 2026-09-10:
    # "toji-gogo.vercel.app 주소 입력 시 연결 안되도록").
    #
    # ## 어떻게 막혔나 — 코드가 아니라 도메인을 뗐다
    #
    # 두 가지를 먼저 시도했고 둘 다 안 됐다. 러너(로그인 안 된 남)로
    # 실제로 재서 얻은 값이다.
    #
    #   ① vercel.json 리디렉션    /api/relay → 307   넘어갈 뿐 안 막힌다
    #   ② Vercel 인증에 맡기기    /api/relay → 200   **그대로 열렸다**
    #
    # ②가 뜻밖이었다. 설정에는 분명 벽이 켜져 있었다 —
    # ssoProtection: enabled=true, deploymentType=all_except_custom_domains.
    # 같은 배포가 toji.fyi 도 물고 있어서, 그 배포가 '커스텀 도메인이
    # 달린 배포' 로 분류돼 통째로 면제되는 것으로 보인다. deploymentType
    # 을 all 로 바꾸면 toji.fyi 까지 막히므로 그 길은 못 쓴다.
    #
    # 결국 Vercel 프로젝트 설정에서 **도메인 자체를 뗐다**. 그 뒤
    # 러너로 재니 404 DEPLOYMENT_NOT_FOUND — 화면도 /api/tile 도
    # /api/relay 도 전부 죽었다.
    #
    # **그래서 여기서는 리디렉션이 없는 것을 확인한다.** 이제 그 규칙은
    # 죽은 주소를 가리키는 죽은 코드고, 남겨 두면 다음 사람이 그것을
    # 방어선으로 착각한다. 진짜 방어선은 저장소 밖(Vercel 설정)에 있다.
    _reds = _cfg.get("redirects") or []
    _vercel_app = [r for r in _reds
                   if any(h.get("type") == "host"
                          and "vercel.app" in str(h.get("value", ""))
                          for h in (r.get("has") or []))]
    check(not _vercel_app,
          "vercel.app 리디렉션이 없다 — 도메인을 뗐으므로 죽은 규칙이다 "
          "(막는 것은 코드가 아니라 Vercel 설정이다)")

print()
print("O. 중계기 주소 — 문서가 코드와 어긋나면 수집이 통째로 멈춘다")
# 2026-09-10 실측. 시크릿을 문서가 적어 둔 대로 넣었더니 수집이
# 멈췄다. 코드는 도메인만 받아서 /api/relay 를 **자기가 붙이는데**,
# 문서에는 붙인 채로 적혀 있어 호출이 이렇게 됐다.
#
#   https://toji.fyi/api/relay/api/relay   → 404
#
# 상태코드만 보면 도메인이 죽은 404 와 구분이 안 된다. 그날 둘 다
# 겪었고, 응답 **본문**이 갈라 줬다 (DEPLOYMENT_NOT_FOUND 대
# The page could not be found).
#
# 그래서 문서와 코드가 다시 어긋나지 않게 여기서 맞물려 둔다.
_http = (ROOT / "src/redt/collect/http.py").read_text(encoding="utf-8")
check('f"{cfg.url}/api/relay"' in _http,
      "코드가 /api/relay 를 스스로 붙인다 (그러니 시크릿은 도메인만)")
_mig = ROOT / "docs/cloudflare-migration.md"
if _mig.exists():
    _txt = _mig.read_text(encoding="utf-8")
    check("REDT_RELAY_URL = https://toji.fyi\n" in _txt,
          "문서가 시크릿을 도메인만으로 적는다")
    check("`/api/relay` 를 붙이지 않습니다" in _txt,
          "왜 붙이면 안 되는지도 적혀 있다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
