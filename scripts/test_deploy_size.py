"""배포 크기 — Vercel Hobby 저장 한도(10GB)를 다시 넘기지 않는가 (2026-09-11).

배포 하나가 194MB 였고 그중 표준지 조각이 138MB 다. 브랜치 push 마다 미리보기가
만들어져 하루에 수십 개, 사본이 20.88GB 가 되어 배포가 멈췄다. 두 가지로 막는다:
  1. 표준지 조각·격차율 표는 저장소·배포에서 빼고 Supabase 비공개 버킷에서 받는다
     (프리미엄 자물쇠, docs/membership-grades.md §3).
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


print("1. 프리미엄 파일은 공개 배포에 없다 (Supabase 비공개 버킷에서만)")
pub = ROOT / "public" / "app" / "data"
chunks = list(pub.glob("stdland-*.json"))
check(not chunks, f"public/ 에 표준지 조각 없음 — {len(chunks)}개", str(chunks[:2]))
check(not (pub / "valuation.json").exists(), "public/ 에 격차율 표 없음")
cfg = (ROOT / "public" / "app" / "config.js").read_text(encoding="utf-8")
check("jsdelivr" not in cfg and "stdlandBase" not in cfg, "공개 CDN 주소 없음")
app = (ROOT / "public" / "app" / "app.js").read_text(encoding="utf-8")
check("sb.storage.from('premium').download(name)" in app, "앱은 버킷에서 받는다")

print()
print("2. 작업 브랜치는 미리보기 배포를 만들지 않는다")
vj = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
de = vj.get("git", {}).get("deploymentEnabled", {})
check(de.get("claude/real-estate-traffic-correlation-liujkh") is False, "vercel.json git.deploymentEnabled")
check("main" not in de or de["main"] is True, "main 은 배포한다")

print()
print("3. 배포 크기")
total = sum(f.stat().st_size for f in (ROOT / "public").rglob("*") if f.is_file())
print(f"   public/ {total / 1e6:,.0f}MB")
check(total < 100 * 1e6, "배포 하나가 100MB 아래")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
