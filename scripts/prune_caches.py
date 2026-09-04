"""Actions 캐시를 한도 아래로 줄인다.

run 23 이 12.35GB / 10GB (124%) 를 찍었다. 넘치면 GitHub 이 **오래된
것부터 조용히 지운다.** 무엇이 지워졌는지는 어디에도 안 남고, 다음
실행이 처음부터 다시 받기 시작할 때에야 드러난다. 지오코딩이 든 캐시가
그렇게 밀려나면 몇 시간을 다시 쓴다.

무엇을 잃을지 우연에 맡길 이유가 없다. 우리가 고른다.

안전장치 셋
-----------
1. **redt-data- 로 시작하는 것만** 본다. pip 캐시 같은 남의 것을 지우면
   매 실행이 다시 받는다.
2. **지금 도는 실행이 만든 것은 건드리지 않는다.** 지우면 그 실행이
   이어받으라고 방금 저장한 것을 스스로 없애는 셈이다.
3. **--dry-run 이 기본이 아니다.** 기본은 실제로 지운다. 다만 무엇을
   지울지 먼저 다 찍고 지운다 — 로그만 봐도 되짚을 수 있어야 한다.

남길 기준은 last_accessed_at 이다. 최근에 쓴 것이 지금 쓸모 있는
것이고, 지오코딩이 든 캐시가 대개 거기 있다.

  python scripts/prune_caches.py --keep 3
  python scripts/prune_caches.py --keep 3 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

GB = 2 ** 30
PREFIX = "redt-data-"


def api(repo: str, token: str, path: str, method: str = "GET"):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", method=method,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"})
    body = urllib.request.urlopen(req, timeout=20).read()
    return json.loads(body) if body else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=3,
                    help="최근 것 몇 개를 남길지 (기본 3)")
    ap.add_argument("--dry-run", action="store_true",
                    help="지우지 않고 무엇을 지울지만 보여준다")
    args = ap.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    run_id = os.environ.get("GITHUB_RUN_ID", "")

    caches = api(repo, token, "/actions/caches?per_page=100")["actions_caches"]
    total = sum(c["size_in_bytes"] for c in caches)
    print(f"캐시 {len(caches)}개 · {total / GB:.2f} GB / 10 GB "
          f"({total / (10 * GB):.0%})")

    ours = [c for c in caches if c["key"].startswith(PREFIX)]
    mine = [c for c in ours if run_id and run_id in c["key"]]
    others = [c for c in ours if not (run_id and run_id in c["key"])]
    others.sort(key=lambda c: c["last_accessed_at"], reverse=True)

    # 이번 실행이 만든 것도 '남긴 것' 으로 센다 — 그것이 가장 최신이다.
    keep = others[:max(0, args.keep - len(mine))]
    drop = others[len(keep):]

    print(f"  우리 것 {len(ours)}개 (이번 실행 {len(mine)}개는 안 건드림)")
    for c in mine + keep:
        print(f"    남김  {c['size_in_bytes'] / GB:5.2f} GB  {c['key']}"
              f"  ({c['last_accessed_at'][:10]})")
    if not drop:
        print("  지울 것이 없습니다.")
        return 0

    freed = 0
    for c in drop:
        line = (f"    {c['size_in_bytes'] / GB:5.2f} GB  {c['key']}"
                f"  ({c['last_accessed_at'][:10]})")
        if args.dry_run:
            print("    지울 예정" + line[4:])
            freed += c["size_in_bytes"]
            continue
        try:
            api(repo, token, f"/actions/caches/{c['id']}", method="DELETE")
            freed += c["size_in_bytes"]
            print("    지움  " + line[4:])
        except (urllib.error.URLError, OSError) as exc:
            print(f"    실패  {c['key']} — {type(exc).__name__}: {exc}")

    after = total - freed
    word = "지울 수 있는" if args.dry_run else "확보한"
    print(f"  {word} 용량 {freed / GB:.2f} GB → 남는 용량 {after / GB:.2f} GB "
          f"({after / (10 * GB):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
