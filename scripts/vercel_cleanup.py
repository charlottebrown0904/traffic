"""Vercel 배포 일괄 삭제 — 저장 한도(Hobby 10GB)를 넘겨 배포가 멈췄을 때 (2026-09-11).

미리보기(target 이 production 이 아닌 것)는 전부, production 은 최근 KEEP 개만 남기고
지운다. 현재 alias(toji.fyi)가 붙은 배포는 절대 지우지 않는다.

토큰은 환경변수 VERCEL_TOKEN 으로만 받는다 (GitHub 시크릿). 코드·로그에 적지 않는다.

  python scripts/vercel_cleanup.py            # 실제 삭제
  DRY_RUN=1 python scripts/vercel_cleanup.py  # 지울 목록만
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

TEAM = os.environ.get("VERCEL_TEAM_ID", "team_5gFHeBHQYHcerHC13Nh5X5dY")
PROJECT = os.environ.get("VERCEL_PROJECT_ID", "prj_uDmnQhEC6xjFL9gpnDlL7YiJ5Xx4")
KEEP = int(os.environ.get("KEEP_PRODUCTION", "2"))
DRY = os.environ.get("DRY_RUN", "") not in ("", "0", "false")
TOKEN = os.environ.get("VERCEL_TOKEN", "")


def call(method: str, path: str, params: dict | None = None):
    q = urllib.parse.urlencode({**(params or {}), "teamId": TEAM})
    req = urllib.request.Request(f"https://api.vercel.com{path}?{q}", method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if body else {}


def list_all() -> list[dict]:
    out, until = [], None
    while True:
        params = {"projectId": PROJECT, "limit": 100}
        if until:
            params["until"] = until
        page = call("GET", "/v6/deployments", params)
        deps = page.get("deployments", [])
        out.extend(deps)
        nxt = (page.get("pagination") or {}).get("next")
        if not deps or not nxt:
            return out
        until = nxt


def main() -> int:
    if not TOKEN:
        print("VERCEL_TOKEN 이 없습니다 — GitHub 시크릿에 넣어야 합니다")
        return 2
    deps = list_all()
    deps.sort(key=lambda d: d.get("created", 0), reverse=True)
    prod = [d for d in deps if d.get("target") == "production"]
    prev = [d for d in deps if d.get("target") != "production"]
    # alias 가 붙은 것(지금 toji.fyi 가 가리키는 것)은 남긴다.
    keep_ids = {d["uid"] for d in prod[:KEEP]} | {d["uid"] for d in deps if d.get("aliasAssigned") or d.get("alias")}
    victims = [d for d in deps if d["uid"] not in keep_ids]
    print(f"전체 {len(deps)} · production {len(prod)} · 미리보기 {len(prev)} · 남김 {len(keep_ids)} · 지울 것 {len(victims)}")
    for d in victims[:10]:
        print("  ", d["uid"], d.get("target") or "preview", (d.get("meta") or {}).get("githubCommitRef", ""),
              time.strftime("%m-%d %H:%M", time.gmtime(d.get("created", 0) / 1000)))
    if len(victims) > 10:
        print(f"   … 외 {len(victims) - 10}개")
    if DRY:
        print("DRY_RUN — 지우지 않았습니다")
        return 0
    done = failed = 0
    for d in victims:
        try:
            call("DELETE", f"/v13/deployments/{d['uid']}")
            done += 1
        except Exception as e:                      # noqa: BLE001
            failed += 1
            print("  실패", d["uid"], str(e)[:100])
        time.sleep(0.3)                             # 초당 요청 한도를 피한다
    print(f"지움 {done} · 실패 {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
