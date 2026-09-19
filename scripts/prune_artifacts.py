"""Actions 아티팩트를 무료 저장 한도 아래로 줄인다.

2026-09-19 에 **Actions 가 통째로 멈췄다.** 실행이 2초 만에 죽고
단계는 하나도 안 돌았다.

    The job was not started because recent account payments have
    failed or your spending limit needs to be increased.

분을 다 쓴 줄 알았는데 아니었다. 공개 저장소는 표준 러너가 무료라
청구된 분이 0 이다. 세어 보니 걸린 것은 **저장**이었다.

    web-data      90개   594.7 MB
    나머지 18종  102개     4.3 MB
    ──────────────────────────────
    합계         192개   599.0 MB     Free 플랜 무료 저장 500 MB

594.7MB 는 전부 `public/app/data` 의 사본이다. 같은 내용이 매 실행
main 에 커밋되는데 아티팩트로 한 번 더 올라갔고, 그것이 90번 쌓였다.

왜 눈에 안 띄었나 — **보관일수를 아무도 안 걸어 뒀다.** 22곳 중 1곳만
retention-days 가 있었고 나머지는 기본 90일이었다. 하루 몇 번 도는
워크플로에 90일이면 수백 개가 남는다.

캐시(10GB)와 헷갈리지 말 것. 둘은 다른 통이다.

    캐시       10 GB    공개·비공개 무관, 요금 없음, 7일 미사용 시 삭제
    아티팩트  500 MB    Free 플랜 무료분. 넘으면 **유료** → 지금 사고

그래서 두 겹으로 막는다.

    1. 워크플로마다 retention-days   — 애초에 오래 안 남게 (예방)
    2. 이 스크립트를 주마다           — 그래도 새는 것을 걷어냄 (청소)

prune_caches.py 와 같은 모양으로 둔다. 둘이 하는 일이 같아서, 한쪽만
고치는 사고를 막으려면 읽는 사람이 나란히 놓고 볼 수 있어야 한다.

  python scripts/prune_artifacts.py --days 7
  python scripts/prune_artifacts.py --days 7 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.request

MB = 2 ** 20
LIMIT_MB = 500          # Free 플랜의 무료 Actions 저장
WARN_AT = 0.8           # 이 비율을 넘으면 로그에 경고를 남긴다


def api(repo: str, token: str, path: str, method: str = "GET"):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"})
    body = urllib.request.urlopen(req, timeout=20).read()
    return json.loads(body) if body else None


def fetch_all(repo: str, token: str) -> list[dict]:
    out, page = [], 1
    while page <= 10:
        d = api(repo, token, f"/actions/artifacts?per_page=100&page={page}")
        rows = d.get("artifacts", [])
        if not rows:
            break
        # 만료된 것은 이미 용량을 안 쓴다. 세지도 지우지도 않는다.
        out += [a for a in rows if not a.get("expired")]
        page += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7,
                    help="이 날수보다 오래된 것을 지운다 (기본 7)")
    ap.add_argument("--dry-run", action="store_true",
                    help="지우지 않고 무엇을 지울지만 보여준다")
    args = ap.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    run_id = os.environ.get("GITHUB_RUN_ID", "")

    arts = fetch_all(repo, token)
    total = sum(a["size_in_bytes"] for a in arts)
    print(f"아티팩트 {len(arts)}개 · {total / MB:.1f} MB / {LIMIT_MB} MB "
          f"({total / (LIMIT_MB * MB):.0%})")
    if total > LIMIT_MB * MB * WARN_AT:
        print("  ⚠ 무료 저장분의 80% 를 넘었습니다. 넘기면 **Actions 가")
        print("    통째로 멈춥니다** — 2026-09-19 에 그렇게 멈췄습니다.")

    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    keep, drop = [], []
    for a in arts:
        made = dt.datetime.strptime(
            a["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc)
        # 지금 도는 실행이 방금 올린 것은 건드리지 않는다. prune_caches.py
        # 와 같은 이유다 — 이 실행이 남기려던 것을 스스로 지우는 셈이 된다.
        mine = run_id and str((a.get("workflow_run") or {}).get("id")) == run_id
        if made > cut or mine:
            keep.append(a)
        else:
            drop.append(a)

    print(f"  {args.days}일 안쪽 {len(keep)}개는 남깁니다.")
    if not drop:
        print("  지울 것이 없습니다.")
        return 0

    freed = 0
    for a in sorted(drop, key=lambda x: -x["size_in_bytes"]):
        line = (f"{a['size_in_bytes'] / MB:7.1f} MB  {a['name']}"
                f"  ({a['created_at'][:10]})")
        if args.dry_run:
            print("    지울 예정  " + line)
            freed += a["size_in_bytes"]
            continue
        try:
            api(repo, token, f"/actions/artifacts/{a['id']}", method="DELETE")
            freed += a["size_in_bytes"]
            print("    지움  " + line)
        except (urllib.error.URLError, OSError) as exc:
            print(f"    실패  {a['name']} — {type(exc).__name__}: {exc}")

    after = total - freed
    word = "지울 수 있는" if args.dry_run else "확보한"
    print(f"  {word} 용량 {freed / MB:.1f} MB → 남는 사용량 {after / MB:.1f} MB "
          f"({after / (LIMIT_MB * MB):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
