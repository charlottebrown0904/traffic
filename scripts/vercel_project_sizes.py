"""프로젝트마다 배포가 몇 개인가 — 26.76GB 가 어디서 오는지."""
import json, os, sys, urllib.request, urllib.parse
TEAM="team_5gFHeBHQYHcerHC13Nh5X5dY"
TOKEN=os.environ.get("VERCEL_TOKEN","")
PROJECTS={"toji-gogo":"prj_uDmnQhEC6xjFL9gpnDlL7YiJ5Xx4",
          "rokaf-lmp":"prj_NQigobATO9WAjEGw74Jq7Th9g2lD",
          "quant":"prj_X3oMjsBjULvmC06W8paRu4g3WXQv",
          "first":"prj_ynNWhOdDuLDHvCeLKX9WIHiBDXL9",
          "chart":"prj_orBJLbDA8lF8klcUd9GwOeC4v5Xs"}
def call(path, params=None):
    q=urllib.parse.urlencode({**(params or {}),"teamId":TEAM})
    r=urllib.request.Request(f"https://api.vercel.com{path}?{q}",
                             headers={"Authorization":f"Bearer {TOKEN}"})
    with urllib.request.urlopen(r, timeout=60) as f:
        return json.loads(f.read().decode())
if not TOKEN:
    print("VERCEL_TOKEN 없음"); sys.exit(2)
tot=0
for name,pid in PROJECTS.items():
    n=0; until=None
    while True:
        p={"projectId":pid,"limit":100}
        if until: p["until"]=until
        page=call("/v6/deployments",p)
        d=page.get("deployments",[])
        n+=len(d)
        nxt=(page.get("pagination") or {}).get("next")
        if not d or not nxt: break
        until=nxt
    tot+=n
    print(f"  {name:<12s} 배포 {n:>5,}개")
print(f"\n  합계 {tot:,}개")
