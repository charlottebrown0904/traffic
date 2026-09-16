"""관 자료로 고속도로 선형을 얻을 수 있나 — 3번 길 (2026-09-16 지시).

  "1번으로 우선 표시하고 **3번을 계속 파고 들어갑니다.**
   저는 국가공간정보포털(브이월드)에서 정보를 찾고 있습니다."

OSM(1번)은 붙였다. 여기서는 **관이 가진 선형**만으로 같은 일을 할 수
있는지를 본다. 되면 ODbL 을 아예 안 밟아도 된다.

## 무엇이 달라졌나

앞선 탐침(run 16·17)은 도로중심선에서 '고속' 을 못 찾았는데, 두 번 다
**MAXFEATURES 상한에 걸려** 있었다. 넓은 상자든 좁은 상자든 이름 없는
동네 길이 먼저 자리를 채우면 고속도로는 아예 못 들어온다. 그래서 '없다'
가 아니라 '못 봤다' 였다.

두 가지를 바꾼다.

  1. **`lt_l_moctlink` (ITS 표준노드링크)** 를 같이 본다. 층 조사에서
     `rd_rank_h` 에 고속국도가 있다고 적어 뒀는데 정작 선형을 안 쟀다.
     이쪽이 노선 정보까지 붙어 오는 자리다.
  2. **상한을 넘기는 법**을 실제로 시험한다 — 걸러서 받거나(속성 필터),
     나눠서 받거나(STARTINDEX 쪽 넘기기). 하나라도 되면 3번이 열린다.

  python scripts/road_link_probe.py
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from collections import Counter, defaultdict

import requests

RELAY = os.environ.get("RELAY_URL", "").rstrip("/")
TOKEN = os.environ.get("RELAY_TOKEN", "")
VW_WFS = "https://api.vworld.kr/req/wfs"

# 경부고속도로가 지나는 자리 (안성 언저리).
BOX = (36.99, 127.25, 37.02, 127.29)


def relay(url: str, timeout: int = 120):
    if not RELAY:
        sys.exit("RELAY_URL 이 없습니다")
    return requests.get(f"{RELAY}/api/relay", timeout=timeout,
                        headers={"x-relay-token": TOKEN},
                        params={"target": url})


def wfs(layer: str, extra: dict | None = None, maxf: int = 1000):
    s, w, n, e = BOX
    q = {
        "SERVICE": "WFS", "VERSION": "1.1.0", "REQUEST": "GetFeature",
        "TYPENAME": layer, "OUTPUT": "application/json",
        "SRSNAME": "EPSG:4326", "MAXFEATURES": str(maxf),
        "BBOX": f"{s},{w},{n},{e}",
        "key": "__via_relay__", "DOMAIN": "https://toji.fyi",
    }
    q.update(extra or {})
    try:
        r = relay(f"{VW_WFS}?{urllib.parse.urlencode(q)}")
        return r.json(), None
    except Exception as exc:                            # noqa: BLE001
        return None, f"{type(exc).__name__} {exc}"


def coords(f):
    g = f.get("geometry") or {}
    co = g.get("coordinates") or []
    if g.get("type") == "MultiLineString":
        co = co[0] if co else []
    return co


def look(layer: str) -> list:
    print("=" * 72)
    print(f"{layer}")
    print("=" * 72)
    body, err = wfs(layer)
    if err:
        print(f"  ✗ 못 불렀다: {err}")
        return []
    feats = (body or {}).get("features") or []
    print(f"  길 {len(feats)}개" + ("  ← 상한에 걸림" if len(feats) >= 1000 else ""))
    if not feats:
        print(f"  응답: {str(body)[:260]}")
        return []
    props = sorted(feats[0].get("properties") or {})
    print(f"  칸 이름: {props}")

    # 어느 칸에 '고속' 이 들어 있나 — 칸을 추측해 고르면 '없다' 로 오판한다.
    hit = defaultdict(int)
    for f in feats:
        for k, v in (f.get("properties") or {}).items():
            if "고속" in str(v):
                hit[k] += 1
    print(f"  '고속' 이 들어 있는 칸: {dict(hit) or '없음'}")

    # 등급 칸이 있으면 분포를 본다 (rd_rank_h 에 고속국도가 있다고 적어 뒀다).
    for k in props:
        if k.lower() in ("rd_rank_h", "rdrank", "road_rank", "rdgrd", "rddv",
                         "road_name", "rd_name_h", "name", "rdnm"):
            c = Counter(str((f.get("properties") or {}).get(k)) for f in feats)
            print(f"    {k:12s} {' · '.join(f'{a!r}×{b}' for a, b in c.most_common(6))[:118]}")

    pts = sorted(len(coords(f)) for f in feats if coords(f))
    if pts:
        print(f"  꼭짓점: 가운데값 {pts[len(pts) // 2]}개 · 가장 많은 것 {pts[-1]}개"
              f" · 2개짜리 {sum(1 for x in pts if x <= 2)}개")
    return feats


def try_filters(layer: str, props: list) -> None:
    """**상한을 넘기는 법.** 하나라도 통하면 3번이 열린다."""
    print("\n" + "-" * 72)
    print(f"  {layer} — 걸러 받기 / 나눠 받기 시험")
    print("-" * 72)

    col = next((c for c in ("rd_rank_h", "road_rank", "rddv") if c in props), None)
    print(f"    거를 칸: {col}")

    # 1) 쪽 넘기기
    a, _ = wfs(layer, {"STARTINDEX": "0"}, maxf=5)
    b, _ = wfs(layer, {"STARTINDEX": "5"}, maxf=5)
    ida = [str((f.get("properties") or {}).get("ufid") or f.get("id"))
           for f in (a or {}).get("features", [])]
    idb = [str((f.get("properties") or {}).get("ufid") or f.get("id"))
           for f in (b or {}).get("features", [])]
    print(f"    STARTINDEX  {'같다 — 안 먹는다' if ida and ida == idb else '다르다 — 된다'}")

    if not col:
        return

    # 2) WFS 속성 필터. **앞서 5개가 왔다고 '된다' 로 읽을 뻔했다** —
    #    값을 보니 거르지 않은 것이 그대로 온 것이었다. 그래서 이제는
    #    돌아온 값이 실제로 걸러졌는지까지 본다.
    for key, val in (("attrFilter", f"{col}:like:고속"),
                     ("CQL_FILTER", f"{col} LIKE '%고속%'")):
        got, err = wfs(layer, {key: val}, maxf=5)
        if err:
            print(f"    {key:11s} ✗ {err[:50]}")
            continue
        fs = (got or {}).get("features") or []
        vals = {str((f.get("properties") or {}).get(col)) for f in fs}
        worked = bool(fs) and all("고속" in v for v in vals)
        print(f"    {key:11s} {len(fs)}개 · 값 {sorted(vals)[:3]}"
              f" → {'걸러졌다' if worked else '**안 걸러졌다** (무시됨)'}")

    # 3) **아직 안 해 본 길: 브이월드 데이터 API.**
    #    /req/wfs 와 /req/data 는 다른 문이다. attrFilter 는 원래 이쪽
    #    것이라, WFS 에서 무시된 것을 여기서는 받아 줄 수 있다.
    # **대조값을 내가 고르지 않는다.** 앞 실행에서 'rddv:like:도' 를
    # 반드시 걸릴 조건이라 여겼는데, rddv 값은 'RDD000' 같은 코드라
    # '도' 가 들어갈 리가 없었다. 0개가 온 것이 당연했고, 그걸 '거르기가
    # 안 된다' 로 읽을 뻔했다. 이제 **자료가 실제로 준 값**을 대조로 쓴다.
    seen = Counter(str((f.get("properties") or {}).get(col))
                   for f in (wfs(layer, maxf=50)[0] or {}).get("features", []))
    ctrl = next((v for v, _ in seen.most_common() if v and v != "None"), None)
    print(f"    자료에 실제로 있는 값: {[v for v, _ in seen.most_common(4)]}")

    print("\n    데이터 API (/req/data) — attrFilter 가 원래 사는 곳")
    s_, w_, n_, e_ = BOX
    KR = (33.0, 124.5, 38.7, 131.2)          # 전국 — 고속국도를 찾으러

    def ask(flt, box, label):
        bs, bw, bn, be = box
        q = {"service": "data", "request": "GetFeature", "format": "json",
             "data": layer.upper(), "geometry": "true", "size": "5",
             "crs": "EPSG:4326",
             "geomFilter": f"BOX({bw},{bs},{be},{bn})",
             "key": "__via_relay__", "domain": "https://toji.fyi"}
        if flt:
            q["attrFilter"] = flt
        try:
            body = relay("https://api.vworld.kr/req/data?"
                         + urllib.parse.urlencode(q)).json()
        except Exception as exc:                        # noqa: BLE001
            print(f"      {label:34s} ✗ {type(exc).__name__}")
            return
        resp = (body or {}).get("response") or {}
        feats = (((resp.get("result") or {}).get("featureCollection") or {})
                 .get("features") or [])
        vals = {str((f.get("properties") or {}).get(col)) for f in feats}
        print(f"      {label:34s} status={resp.get('status')} · {len(feats)}개"
              f" · 값 {sorted(vals)[:3]}")

    ask(None, BOX, "(안 거름) — 층이 있나")
    if ctrl:
        ask(f"{col}:=:{ctrl}", BOX, f"{col}:=:{ctrl} — 거르기가 먹나")
    # **진짜 묻고 싶은 것.** 전국에서 고속국도만 골라낼 수 있나.
    for flt in (f"{col}:=:101", f"{col}:like:고속", "name:like:고속"):
        ask(flt, KR, f"전국 · {flt}")


def rdd001() -> None:
    """**RDD001 이 정말 고속국도인가, 그리고 전국을 훑을 수 있나.**

    전국에 대고 name:like:고속 으로 물었더니 rddv 가 RDD001 인 줄이 왔다.
    안성 상자에는 없던 코드다. 그러나 '코드 하나가 한 번 보였다' 와
    '그 코드가 고속국도다' 는 다른 말이다 — 이름을 직접 읽어 확인한다.

    그리고 쪽 넘기기(page)가 먹어야 전국을 훑는다. 안 먹으면 상자를
    잘게 쪼개는 수밖에 없고, 그러면 비용이 통째로 달라진다.
    """
    print("\n" + "=" * 72)
    print("RDD001 이 고속국도인가 · 전국을 훑을 수 있나")
    print("=" * 72)
    KR = "BOX(124.5,33.0,131.2,38.7)"

    def ask(flt, size="10", page="1"):
        q = {"service": "data", "request": "GetFeature", "format": "json",
             "data": "LT_L_N3A0020000", "geometry": "true", "size": size,
             "page": page, "crs": "EPSG:4326", "geomFilter": KR,
             "key": "__via_relay__", "domain": "https://toji.fyi"}
        if flt:
            q["attrFilter"] = flt
        try:
            body = relay("https://api.vworld.kr/req/data?"
                         + urllib.parse.urlencode(q)).json()
        except Exception as exc:                        # noqa: BLE001
            print(f"  ✗ {type(exc).__name__}")
            return []
        resp = (body or {}).get("response") or {}
        res = resp.get("result") or {}
        feats = (res.get("featureCollection") or {}).get("features") or []
        pg = resp.get("page") or {}
        print(f"  {str(flt or '(안 거름)'):26s} status={resp.get('status')}"
              f" · {len(feats)}개 · 전체 {pg.get('total')} · 쪽 {pg.get('current')}/{pg.get('size')}")
        return feats

    # 1. RDD001 의 이름을 직접 읽는다 — 코드가 아니라 이름이 판정한다.
    print("\n  rddv=RDD001 인 길의 이름:")
    for f in ask("rddv:=:RDD001"):
        p_ = f.get("properties") or {}
        print(f"    {str(p_.get('name'))[:34]:36s} rdnu={p_.get('rdnu')}"
              f" · rdln={p_.get('rdln')}")

    # 2. 다른 코드와 견준다 — RDD001 만 고속이면 그 코드가 맞다.
    print("\n  견줌 — 다른 코드의 이름:")
    for code in ("RDD000", "RDD002", "RDD003"):
        names = {str((f.get("properties") or {}).get("name"))
                 for f in ask(f"rddv:=:{code}", size="5")}
        print(f"    {code} → {sorted(names)[:3]}")

    # 3. 쪽 넘기기 — 전국을 훑을 수 있나
    print("\n  쪽 넘기기 (전국 · 고속만):")
    a = ask("rddv:=:RDD001", size="5", page="1")
    b = ask("rddv:=:RDD001", size="5", page="2")
    ida = [str((f.get("properties") or {}).get("ufid")) for f in a]
    idb = [str((f.get("properties") or {}).get("ufid")) for f in b]
    print(f"    1쪽 vs 2쪽: {'같다 — 안 먹는다' if ida and ida == idb else '다르다 — 된다'}")


def main() -> None:
    print(f"상자: {BOX} (경부고속도로 언저리)\n")
    rdd001()
    for layer in ("lt_l_moctlink", "lt_l_n3a0020000"):
        feats = look(layer)
        if feats:
            try_filters(layer, sorted(feats[0].get("properties") or {}))
        print()
    print("=" * 72)
    print("무엇을 보고 판단하나")
    print("=" * 72)
    print("  · rd_rank_h 에 고속국도가 오면 **관 자료만으로 가려낼 수 있다**")
    print("  · 걸러 받기나 쪽 넘기기 중 하나가 되면 상한을 넘길 수 있다")
    print("  · 둘 다 되면 3번이 열린다 — ODbL 을 안 밟아도 된다")


if __name__ == "__main__":
    main()
