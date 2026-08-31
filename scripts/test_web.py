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
REQUIRED_DATA = ["meta.json", "series.json", "tollgates.json", "trades.json"]

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
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
