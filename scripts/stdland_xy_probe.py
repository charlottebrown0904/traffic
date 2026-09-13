"""표준지 좌표 — 연속지적도에서 **묶어서** 받을 수 있나 (2026-09-13 탐침).

std_land 60만 필지에 좌표가 없다. 좌표가 없어 같은 인근지역에서 비교표준지를
고르지 못하고, 그 빈자리를 개별공시지가로 메우다 전국 검산에서 적중이 떨어졌다
(docs/radar-and-current-value.md §8). 좌표를 얻는 길은 셋이다:

  A. 연속지적도 SHP 전국 276개 파일(약 7GB)을 내려받아 PNU 로 잇는다.
     — 사람이 로그인해 받아 드라이브에 올려야 하고, 용량이 크다.
  B. 지번 60만 건을 지오코더에 묻는다 — 초당 12건이면 14시간, 한도에 걸리면 며칠.
     게다가 지오코더는 건물 없는 땅의 지번을 모른다 (scripts/pnu_probe.py).
  C. **이 탐침.** 우리가 이미 쓰는 연속지적도 WFS 를 PNU 로 거르되, OGC 필터의
     <Or> 로 **여러 PNU 를 한 번에** 묻는다. 되면 60만 ÷ 묶음 크기 만큼만 부른다.

무엇을 재는가: 묶음 크기 k 마다 (1·10·50·100·200) 몇 개가 돌아오는지, 몇 초
걸리는지, 요청한 PNU 와 정확히 같은 것이 오는지. 필터가 조용히 무시되면
엉뚱한 필지가 오므로 **PNU 를 맞대어 본다** — pnu_probe.py 에서 배운 것이다.

서울 중계기(api/relay)를 거친다. 키는 중계기에만 있고, 응답에 섞여 나오는
키 비슷한 것은 로그로 나가기 전에 지운다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE", "https://toji.fyi")
TOKEN = os.environ.get("TOKEN", "")
WFS = "https://api.vworld.kr/req/wfs"
TYPENAME = "lp_pa_cbnd_bubun"
SIZES = [int(x) for x in os.environ.get("SIZES", "1,10,50,100,200").split(",")]
# 비우거나 all 이면 전국에서 섞어 뽑는다. **all 을 문자로 받는 이유**: 깃헙
# 액션의 `A == B && '' || C` 는 빈 문자열이 거짓이라 C 로 떨어진다 — 그래서
# SGG 에 'all' 이 그대로 들어와 `LIKE 'all%'` 로 0건이 됐다 (run 34764942521).
SAMPLE_SGG = os.environ.get("SGG", "").strip()
if SAMPLE_SGG.lower() in ("all", "*", "전국"):
    SAMPLE_SGG = ""

HIDE = re.compile(r'(?i)((?:key|apikey|servicekey)=)[^&"\s<]+')


def show(text: str, n: int = 400) -> str:
    return " ".join(HIDE.sub(r"\1(가림)", text)[:n].split())


def relay(target: str, timeout: int = 120) -> tuple[int, str]:
    url = f"{BASE}/api/relay?target={urllib.parse.quote(target, safe='')}"
    req = urllib.request.Request(url, headers={"x-relay-token": TOKEN} if TOKEN else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:                    # noqa: PERF203
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:                                 # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def wfs_url(pnus: list[str]) -> str:
    """PNU 여럿을 <Or> 로 묶은 OGC 필터. 하나면 <Or> 없이 (그래야 옛 길과 같다)."""
    eq = "".join(f"<PropertyIsEqualTo><PropertyName>pnu</PropertyName>"
                 f"<Literal>{p}</Literal></PropertyIsEqualTo>" for p in pnus)
    inner = eq if len(pnus) == 1 else f"<Or>{eq}</Or>"
    params = {
        "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "1.1.0",
        "TYPENAME": TYPENAME, "FILTER": f"<Filter>{inner}</Filter>",
        "SRSNAME": "EPSG:4326", "OUTPUT": "application/json",
        # 도형은 필요 없다 — 가운데 점만 쓴다. 그래도 WFS 는 도형을 준다.
        "MAXFEATURES": str(max(len(pnus) * 2, 4)), "RESULTTYPE": "results",
        "DOMAIN": os.environ.get("VWORLD_REFERER", "https://toji.fyi/"),
    }
    return WFS + "?" + urllib.parse.urlencode(params)


def center(geom: dict) -> tuple[float, float] | None:
    w = s = 1e9
    e = n = -1e9
    def walk(v):
        nonlocal w, s, e, n
        if isinstance(v, (list, tuple)):
            if len(v) >= 2 and all(isinstance(x, (int, float)) for x in v[:2]):
                w, e = min(w, v[0]), max(e, v[0])
                s, n = min(s, v[1]), max(n, v[1])
                return
            for x in v:
                walk(x)
    walk((geom or {}).get("coordinates"))
    if w > 1e8 or n < -1e8:
        return None
    return round((s + n) / 2, 6), round((w + e) / 2, 6)


def pnus_from_db(limit: int) -> list[str]:
    """std_land 에서 실제 표준지 PNU 를 뽑는다 (러너에 복원된 DB).

    한 시군구를 주면 그 안에서, 안 주면 전국에서 섞어 뽑는다 — 묶음 조회가
    한 시군구 안에서만 되는지(도면 경계) 전국을 섞어도 되는지가 갈린다.
    """
    sys.path.insert(0, "src")
    from redt import db                                    # noqa: PLC0415
    if SAMPLE_SGG:
        sql = ("SELECT pnu FROM std_land WHERE pnu IS NOT NULL "
               f"AND sigungu_cd LIKE '{SAMPLE_SGG}%' LIMIT {limit}")
    else:
        sql = ("SELECT pnu FROM std_land WHERE pnu IS NOT NULL "
               f"USING SAMPLE reservoir({limit} ROWS) REPEATABLE (11)")
    with db.connect(read_only=True) as con:
        rows = con.execute(sql).fetchall()
    return [str(r[0]) for r in rows if r[0]]


def main() -> int:
    need = max(SIZES) * 2
    try:
        pool = pnus_from_db(need)
    except Exception as e:                                 # noqa: BLE001
        print(f"std_land 을 못 읽었습니다 ({type(e).__name__}: {e}) — 캐시 복원이 먼저입니다")
        return 2
    print(f"BASE={BASE} · 표본 PNU {len(pool)}개"
          + (f" · 시군구 {SAMPLE_SGG}" if SAMPLE_SGG else " · 전국에서 섞어 뽑음"))
    if not pool:
        print("표본이 없습니다 — std_land 이 비었습니다")
        return 2
    print()
    ok_sizes = []
    for k in SIZES:
        want = pool[:k]
        if len(want) < k:
            print(f"  묶음 {k:>3}  표본 부족 — 건너뜀")
            continue
        t0 = time.time()
        code, body = relay(wfs_url(want))
        dt = time.time() - t0
        try:
            data = json.loads(body)
            feats = data.get("features") or []
        except Exception:                                  # noqa: BLE001
            print(f"  묶음 {k:>3}  http={code} {dt:.1f}초 — JSON 이 아닙니다: {show(body, 200)}")
            continue
        got = {str((f.get("properties") or {}).get("pnu") or "") for f in feats}
        hit = len(got & set(want))
        stray = len(got - set(want))
        xy = center((feats[0] or {}).get("geometry")) if feats else None
        print(f"  묶음 {k:>3}  http={code} {dt:>5.1f}초 · 받은 필지 {len(feats):>3}개"
              f" · 요청과 맞은 것 {hit:>3}개 · 엉뚱한 것 {stray}개"
              f" · 응답 {len(body) / 1024:,.0f}KB"
              + (f" · 첫 필지 중심 {xy}" if xy else ""))
        if hit == k and stray == 0:
            ok_sizes.append((k, dt, len(body)))
    print()
    if not ok_sizes:
        print("판정: 묶음 조회가 안 됩니다 — SHP 내려받기(A) 나 지오코딩(B) 로 갑니다.")
        return 0
    best, dt, size = max(ok_sizes, key=lambda x: x[0])
    total = int(os.environ.get("TOTAL", "600000"))
    calls = (total + best - 1) // best
    print(f"판정: 한 번에 {best}개까지 정확히 옵니다.")
    print(f"  표준지 {total:,}필지 → 호출 {calls:,}번 · 한 번 {dt:.1f}초")
    print(f"  1줄이면 {calls * dt / 3600:.1f}시간 · 8줄 나란히면 {calls * dt / 3600 / 8:.1f}시간")
    print(f"  받는 양 약 {calls * size / 1e9:.1f}GB (도형까지 오므로 — 우리는 중심점만 남깁니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
