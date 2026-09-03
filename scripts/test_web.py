"""배포 전 public/ 정합성 검사.

두 번 크게 물린 곳을 고정한다.
  1. trailingSlash:false 라 /guide, /app 은 뒤 슬래시 없이 열린다. 상대경로를 쓰면
     브라우저가 한 단계 위에서 찾아 CSS·스크립트·링크가 전부 404 가 된다.
  2. .vercelignore 는 gitignore 문법이라 앞에 / 가 없으면 깊이를 가리지 않는다.
     'data/' 한 줄이 public/app/data/ 까지 배포에서 제외시켰다.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
REF = re.compile(r'(?:href|src)="([^"]+)"')
REQUIRED_DATA = ["meta.json", "series.json", "tollgates.json", "trades.json",
                 "traffic.json"]

fail = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fail.append(msg)


def resolves(url: str) -> bool:
    rel = url.lstrip("/").split("#")[0].split("?")[0]
    if not rel:
        return (PUBLIC / "index.html").is_file()
    return any(
        p.is_file()
        for p in (PUBLIC / rel, PUBLIC / (rel + ".html"), PUBLIC / rel / "index.html")
    )


print("1. 상대경로 없음 (뒤 슬래시 없이 열려도 깨지지 않아야 한다)")
for html in sorted(PUBLIC.rglob("*.html")):
    rels = [
        u
        for u in REF.findall(html.read_text(encoding="utf-8"))
        if not u.startswith(("/", "http://", "https://", "//", "#", "data:", "mailto:"))
    ]
    check(not rels, f"{html.relative_to(ROOT)} 상대경로 {len(rels)}개 {rels[:3]}")

print("2. 절대경로 링크가 실제 파일로 연결된다")
for html in sorted(PUBLIC.rglob("*.html")):
    dead = [
        u
        for u in REF.findall(html.read_text(encoding="utf-8"))
        if u.startswith("/") and not u.startswith("//") and not resolves(u)
    ]
    check(not dead, f"{html.relative_to(ROOT)} 깨진 링크 {dead}")

print("3. .vercelignore 가 public/ 을 제외하지 않는다")
for i, raw in enumerate((ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    check(
        line.startswith("/") or line.startswith("*"),
        f".vercelignore:{i} '{line}' — 앞에 / 를 붙여 최상위로 한정할 것",
    )

print("4. 모든 페이지에 아이콘·manifest 가 걸려 있다")
BRAND = [
    '<link rel="icon" href="/favicon.ico"',
    '<link rel="icon" href="/favicon.svg"',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
    '<link rel="manifest" href="/site.webmanifest">',
    '<meta name="theme-color"',
]
for html in sorted(PUBLIC.rglob("*.html")):
    text = html.read_text(encoding="utf-8")
    missing = [tag for tag in BRAND if tag not in text]
    check(not missing, f"{html.relative_to(ROOT)} 빠진 태그 {missing}")
for name in ("favicon.ico", "favicon.svg", "icon.svg", "apple-touch-icon.png",
             "site.webmanifest", "brand/icon-192.png", "brand/icon-512.png",
             "brand/icon-maskable-512.png"):
    check((PUBLIC / name).is_file(), f"public/{name}")

print("5. 앱 데이터 파일이 존재한다")
for name in REQUIRED_DATA:
    check((PUBLIC / "app" / "data" / name).is_file(), f"public/app/data/{name}")

print()
print("화면 데이터가 **브라우저 기준으로** 올바른 JSON인가")

# 파이썬 json 은 기본으로 NaN·Infinity 를 읽고 씁니다. 브라우저의
# JSON.parse 는 거부합니다. 그래서 파일은 멀쩡해 보이고 파이썬 검사도
# 통과하는데 화면만 죽습니다.
#
# run 21 이 정확히 그랬습니다. 명부에서 영업소 119곳을 새로 등재했는데
# 그중 41곳이 시도·시군구를 아직 모릅니다(좌표를 못 받아 지역을 못
# 되짚었습니다). 그 NaN 이 traffic.json 에 실려 파일이 JSON 이 아니게
# 됐고, 배포된 화면의 순위 탭이 통째로 꺼졌습니다.
#
# 그래서 이 검사는 **엄격 모드**로 읽습니다 — 브라우저와 같은 기준입니다.
import json as _json                                            # noqa: E402
from pathlib import Path as _Path                               # noqa: E402


def _strict(text):
    """NaN·Infinity 를 만나면 터진다 (브라우저와 같은 동작)."""
    def boom(c):
        raise ValueError(f"JSON 이 아닌 값: {c}")
    return _json.loads(text, parse_constant=boom)


_web = _Path(__file__).resolve().parents[1] / "public" / "app" / "data"
_files = sorted(_web.glob("*.json"))
check(len(_files) >= 5, f"화면 데이터가 있다 ({len(_files)}개)")
for _f in _files:
    try:
        _strict(_f.read_text(encoding="utf-8"))
        check(True, f"{_f.name} 이 브라우저가 읽을 수 있는 JSON 이다")
    except ValueError as exc:
        check(False, f"{_f.name} 이 브라우저가 읽을 수 있는 JSON 이다 — {exc}")

# 내보내기가 NaN 을 만나면 조용히 흘려보내지 않는지. 벽이 실제로 서 있는지
# 확인하는 것이라, 되짚어 실패하는 것까지 봐야 의미가 있습니다.
import math as _math                                            # noqa: E402
from redt import webexport as _wx                               # noqa: E402

_clean = _wx._finite({"a": _math.nan, "b": [1.0, _math.inf], "c": {"d": -_math.inf}})
check(_clean == {"a": None, "b": [1.0, None], "c": {"d": None}},
      f"NaN·Infinity 를 None 으로 바꾼다 ({_clean})")
check(_wx._text(_math.nan) == "" and _wx._text("경기도") == "경기도",
      "NaN 은 참이라 `or` 를 통과한다 — 문자열인지 직접 본다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
