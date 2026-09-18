"""공개 저장소에 두면 안 되는 것이 추적 파일에 들어왔는지 본다.

**저장소를 public 으로 바꾸면 되돌릴 수 없다.** 한 번 공개된 커밋은
남이 복제해 갈 수 있고, 다시 private 으로 바꿔도 그 복제본은 사라지지
않는다. 그래서 '나중에 지우면 된다' 가 성립하지 않는다.

secret-scan 워크플로가 키를 보고, 이 검사가 **개인정보**를 본다. 둘을
가른 이유는 다르게 다뤄야 하기 때문이다 — 키는 재발급하면 끝나지만
남의 전화번호는 재발급이 없다.

  실행: python scripts/test_privacy.py   (make test 에 포함)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

fail = []


def check(ok, label):
    print(("  통과  " if ok else "  실패  ") + label)
    if not ok:
        fail.append(label)


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True).stdout
    return [f for f in out.splitlines() if f]


# 하이픈이 있는 것만 본다. 하이픈 없는 11자리는 좌표·면적·코드와
# 구별이 안 돼 거짓 경보만 늘린다. 실제 자료의 연락처는 하이픈이 있었다.
PHONE = re.compile(r"\b0(?:2|[3-6][1-5]|1[016-9]|70)-\d{3,4}-\d{4}\b")
RRN = re.compile(r"\b\d{6}-[1-4]\d{6}\b")

# 검사·문서에 일부러 적은 자리표시자. 진짜 번호가 아니다.
SAFE = re.compile(r"0(00|1)0?-?0000-0000|000-0000|1544-|1588-")

files = tracked()
print(f"1. 추적 파일 {len(files):,}개에 개인정보가 있는가")

hits_phone, hits_rrn = [], []
for f in files:
    p = ROOT / f
    if not p.is_file():
        continue
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    for m in PHONE.finditer(text):
        if SAFE.search(m.group(0)):
            continue
        hits_phone.append((f, text[:m.start()].count("\n") + 1, m.group(0)))
    for m in RRN.finditer(text):
        hits_rrn.append((f, text[:m.start()].count("\n") + 1, m.group(0)))

check(not hits_phone, f"전화번호가 없다 ({len(hits_phone)}건)")
for f, line, val in hits_phone[:15]:
    print(f"          {f}:{line}  {val}")
check(not hits_rrn, f"주민등록번호 모양이 없다 ({len(hits_rrn)}건)")
for f, line, val in hits_rrn[:15]:
    print(f"          {f}:{line}  {val}")

print()
print("2. 연락처 칸을 받자마자 버리는가 (다음 수집이 되살리지 않게)")
# 파일에서 지우기만 하면 다음 수집이 그대로 다시 넣는다. 받는 자리에서
# 버려야 한 번 고친 것이 계속 유지된다.
_ud = (ROOT / "src/redt/collect/urban_dev.py").read_text(encoding="utf-8")
check("PERSONAL_COLS" in _ud, "도시개발 수집기가 연락처 칸 목록을 갖고 있다")
check("df.drop(columns=drop)" in _ud, "받은 표에서 실제로 지운다")

print()
print("3. 이력에 남은 키 — public 전환 전 재발급이 필요한 것")
# working tree 만 깨끗해도 소용없다. public 이 되면 **과거 커밋 전부**가
# 공개된다. 여기서는 '알고 있다' 는 것만 확인한다 — 이력은 다시 쓸 수
# 없으므로 검사가 할 수 있는 일은 잊지 않게 하는 것뿐이다.
_doc = (ROOT / "docs/api-keys.md").read_text(encoding="utf-8")
check("25292d8" in _doc,
      "노출된 커밋을 문서가 지목하고 있다 (docs/api-keys.md)")
check("재발급" in _doc, "재발급이 필요하다고 적혀 있다")

print()
print("4. 저장소가 공개다 — 사람을 가리키는 호칭이 남지 않게")
# 2026-09-10 요청. F12 로 app.js 를 열면 주석이 그대로 보이고, 저장소는
# 공개라 GitHub 에서는 검색까지 된다. 그때 코드에 사람을 부르는 호칭이
# 붙은 지시문이 294곳 있었다.
#
# **주석을 지우자는 것이 아니다.** 주석의 값어치는 '왜 이렇게 했는가' 에
# 있고, 그것이 있어야 같은 것을 두 번 안 깨뜨린다. 값어치가 없는 것은
# **누가 시켰는가** 다. 호칭만 걷어내고 근거는 남긴다.
# **호칭을 조각으로 만든다.** 여기에 통째로 적으면 이 검사 파일 자신이
# 걸린다. 검사가 자기를 잡고 영원히 빨간 것은 검사가 아니다.
_HONORIFICS = tuple(a + "님" for a in ("사장", "대표", "회장", "부장"))
_SCAN_EXT = {".py", ".js", ".css", ".html", ".yml", ".yaml", ".md", ".json"}
_SKIP_DIR = {".git", "node_modules", "public/app/data", "data/processed",
             "data/interim"}
_found = []
for _p in sorted(ROOT.rglob("*")):
    if not _p.is_file() or _p.suffix not in _SCAN_EXT:
        continue
    _rel = _p.relative_to(ROOT).as_posix()
    if any(_rel == d or _rel.startswith(d + "/") for d in _SKIP_DIR):
        continue
    try:
        _t = _p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for _h in _HONORIFICS:
        if _h in _t:
            _found.append(f"{_rel} ({_t.count(_h)}회 '{_h}')")
            break
check(not _found, f"사람을 가리키는 호칭이 없다 ({len(_found)}개 파일)")
for _f in _found[:15]:
    print(f"          {_f}")


# ── 5. F12 로 우리 대화가 보이지 않는다 (2026-09-17 지시) ─────────────
#
# "서비스 페이지에서 F12 누르면 우리의 대화와 지시 판단들이 들어 있습니다 …
#  바이럴 코딩한 노하우를 공개로 보여주기가 싫습니다."
#
# 내려가는 파일의 주석은 **누구나 본다.** 짧은 이름표는 그대로 두고, 글은
# 번호로 바꿔 관리자 화면(0018 code_note)으로 옮겼다. 이 검사는 글이 다시
# 기어들어오는 것을 막는다 — 한 번 지우는 것은 쉽고, 안 돌아오게 하는 것이
# 어렵다. 판정 규칙은 scripts/strip_notes.py 한 곳에만 있다.
print()
print("5. 내려가는 파일에 서술형 주석이 없다 (F12 로 다 보인다)")
sys.path.insert(0, str(ROOT / "scripts"))
import strip_notes as _SN                                        # noqa: E402

_prose = []
for _f in _SN.files():
    _src, _hits = _SN.scan_file(_f)
    if _hits:
        _prose.append((Path(_f).relative_to(ROOT).as_posix(), len(_hits)))
check(not _prose, f"서술형 주석이 없다 ({len(_prose)}개 파일)")
for _rel, _n in _prose[:15]:
    print(f"          {_rel} ({_n}개) — python scripts/strip_notes.py --apply")

# 번호는 남아 있어야 한다. 통째로 지우면 왜 그렇게 했는지 되찾을 길이 없다.
_marked = sum(1 for _f in _SN.files()
              if re.search(r"N\d{4}", Path(_f).read_text(encoding="utf-8")))
check(_marked > 20, f"번호는 남아 있다 ({_marked}개 파일)")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
