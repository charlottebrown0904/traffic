"""배포 크기 — Vercel Hobby 저장 한도(10GB)를 다시 넘기지 않는가 (2026-09-11).

배포 하나가 194MB 였고 그중 표준지 조각이 138MB 다. 브랜치 push 마다 미리보기가
만들어져 하루에 수십 개, 사본이 20.88GB 가 되어 배포가 멈췄다. 두 가지로 막는다:
  1. 표준지 조각은 배포에서 빼고(.vercelignore) 공개 저장소의 CDN 에서 받는다.
  2. 작업 브랜치는 미리보기 배포를 만들지 않는다 (vercel.json git.deploymentEnabled).

  실행: python scripts/test_deploy_size.py   (make test 에 포함)
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
fail = []


def check(ok, label, extra=""):
    print(f"  {'✓' if ok else '✗'} {label}" + (f" — {extra}" if extra and not ok else ""))
    if not ok:
        fail.append(label)


print("1. 표준지 조각은 배포에서 빠지고 CDN 에서 온다")
ign = (ROOT / ".vercelignore").read_text(encoding="utf-8")
check("/public/app/data/stdland-*.json" in ign, ".vercelignore 에 표준지 조각")
cfg = (ROOT / "public" / "app" / "config.js").read_text(encoding="utf-8")
check("stdlandBase" in cfg and "cdn.jsdelivr.net/gh/charlottebrown0904/traffic@main/public/app/data" in cfg,
      "config.js stdlandBase 가 jsDelivr 의 이 저장소 main 을 가리킨다")
app = (ROOT / "public" / "app" / "app.js").read_text(encoding="utf-8")
check("const urls = base ? [`${base}/stdland-${code}.json`, local] : [local];" in app,
      "앱은 CDN 먼저, 안 되면 같은 자리")
# 조각 파일 이름과 CDN 경로가 맞물린다 — 저장소에 실제로 그 이름으로 있어야 한다.
chunks = list((ROOT / "public" / "app" / "data").glob("stdland-*.json"))
check(len(chunks) >= 200 and all(len(c.stem) == len("stdland-41550") for c in chunks[:20]),
      f"저장소에 조각 {len(chunks)}개 · 이름 꼴 stdland-NNNNN.json")
big = [c for c in chunks if c.stat().st_size > 50 * 1024 * 1024]
check(not big, "jsDelivr 한도(파일당 50MB) 안", str(big[:3]))

print()
print("2. 작업 브랜치는 미리보기 배포를 만들지 않는다")
vj = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
de = vj.get("git", {}).get("deploymentEnabled", {})
check(de.get("claude/real-estate-traffic-correlation-liujkh") is False, "vercel.json git.deploymentEnabled")
check("main" not in de or de["main"] is True, "main 은 배포한다")

print()
print("3. 남는 배포 크기")
total = sum(f.stat().st_size for f in (ROOT / "public").rglob("*") if f.is_file())
kept = total - sum(c.stat().st_size for c in chunks)
print(f"   public/ {total / 1e6:,.0f}MB → 배포 {kept / 1e6:,.0f}MB")
check(kept < 100 * 1e6, "배포 하나가 100MB 아래")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
