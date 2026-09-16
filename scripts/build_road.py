"""고속도로 층 — 계획·공사·개통을 한 파일로 모은다 (2026-09-16 지시).

  "개발에 고속도로 항목이 신설되는 것이 목표입니다."

세 자료를 합친다.

  계획   data/road/plan2.tsv        37건 (국토교통부고시 제2022-60호)
  공사   도로공사 공사현황 API       595건 (시공 233 · 준공 362)
  개통   이미 화면에 있는 영업소     — 여기서는 안 건드린다

## 좌표를 어떻게 붙이나

**자료가 주는 것은 이름 둘이다** ('안성JCT-동탄JCT', '속초-고성').
노선이 어떻게 지나가는지는 어디에도 없다. 그래서 두 끝만 찍고 그 사이를
잇는다 — 그리고 화면이 "실제 노선이 아니라 구간의 시작과 끝" 이라고
말한다.

이름에서 좌표로 가는 길은 셋이고, 전부 **우리가 이미 가진 파일**이다.

    영업소 명부   tollgates.json   554곳 — 'IC/JCT' 이름이 여기 걸린다
    시군구        regions.json     255곳 — '김해' '밀양'
    읍면동        places.json   17,430곳 — '퇴계원' '오창' '동이'

## 그런데 이름은 거짓말을 한다

'고성' 은 강원에도 경남에도 있다. 이름만 믿고 붙였더니 속초-고성이
**355.7km** 가 나왔다 (고시는 43.5km). 강원도에서 경상남도까지 가로지르는
선을 그릴 뻔했다.

그래서 **짝을 고를 때 연장을 쓴다.** 두 끝의 후보를 모두 만들어 놓고,
둘 사이 직선거리가 고시의 연장에 가장 가까운 짝을 고른다. 검산을 거름망
으로만 쓰지 않고 **고르는 자에 쓰는 것**이 요점이다 — 그러면 동음이의가
저절로 풀린다.

고르고 나서도 비(직선/연장)가 0.4~1.4 밖이면 **버린다.** 길은 굽으니
직선이 연장보다 짧은 것이 정상이고(비 < 1), 1.4 를 넘으면 엉뚱한 자리다.
그런 구간은 화면에 안 올린다 — 틀린 선은 없는 선보다 나쁘다.

  python scripts/build_road.py            계획만 (네트워크 없이)
  python scripts/build_road.py --work     공사현황까지 (중계기 필요)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "public" / "app" / "data"
PLAN = ROOT / "data" / "road" / "plan2.tsv"
OUT = WEB / "road.json"

# 비(직선거리 ÷ 고시연장)가 이 밖이면 엉뚱한 자리로 본다.
# 아래끝 0.4 — 길이 아주 굽으면 직선은 절반 아래로 떨어진다.
# 위끝 1.4 — 직선이 연장보다 길 수는 없으니 조금만 봐 준다.
RATIO_LO, RATIO_HI = 0.4, 1.4


def km(a, b) -> float:
    la1, lo1 = a
    la2, lo2 = b
    dla, dlo = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = (math.sin(dla / 2) ** 2
         + math.cos(math.radians(la1)) * math.cos(math.radians(la2))
         * math.sin(dlo / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def bucket_base() -> str:
    """화면 자료가 사는 공개 버킷 주소. 열쇠가 필요 없다."""
    sys.path.insert(0, str(ROOT / "src"))
    from redt import web_store as WS                    # noqa: PLC0415
    return WS.public_base()


def load_json(name):
    """이름 사전의 재료를 읽는다 — 없으면 **버킷에서 받는다.**

    public/app/data 는 .gitignore 다 (64MB 라 배포에서 빼고 버킷으로
    옮겼다 — web_store 머리글). 그래서 새 체크아웃에는 tollgates.json 도
    places.json 도 없다. 처음 이 스크립트를 러너에서 돌렸을 때 바로 그
    자리에서 FileNotFoundError 가 났다. 브라우저가 받는 그 주소로
    우리도 받으면 된다.
    """
    local = WEB / name
    if local.exists():
        return json.loads(local.read_text(encoding="utf-8"))
    import requests                                     # noqa: PLC0415
    url = f"{bucket_base()}/{name}"
    print(f"  {name} 이 없어 버킷에서 받는다")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.json()


def build_index():
    """이름 → [(출처, 좌표)] 후보 목록. 한 이름에 여럿일 수 있다."""
    idx = defaultdict(list)

    for r in load_json("tollgates.json"):
        if r.get("lat") and r.get("lon"):
            idx[r["name"]].append(("영업소", (r["lat"], r["lon"])))

    for r in load_json("regions.json"):
        if r.get("lat") and r.get("lon"):
            idx[r["name"]].append(("시군구", (r["lat"], r["lon"])))
            # '고성군' 을 '고성' 으로도 찾을 수 있게
            short = re.sub(r"(특별자치시|특별자치도|광역시|특별시|[시군구])$", "", r["name"])
            if short and short != r["name"]:
                idx[short].append(("시군구", (r["lat"], r["lon"])))

    # 읍면동은 리가 여럿이라 **읍·면 단위로 묶어 가운데를 쓴다.**
    # 리 하나를 집으면 그 읍의 끝자락이 될 수 있다.
    umd = defaultdict(list)
    for r in load_json("places.json")["places"]:
        head = r["n"].split()[0]                     # '오창읍 가곡리' → '오창읍'
        umd[(head, r["p"])].append((r["lat"], r["lon"]))
    for (head, _parent), pts in umd.items():
        c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        idx[head].append(("읍면동", c))
        short = re.sub(r"[읍면동]$", "", head)
        if short and short != head:
            idx[short].append(("읍면동", c))
    return idx


def candidates(idx, name: str):
    """그 이름으로 갈 수 있는 자리들. IC/JCT 꼬리를 떼고도 찾는다."""
    base = re.sub(r"(JCT|IC|분기점|나들목)$", "", name).strip()
    seen, out = set(), []
    for cand in (name, base, base + "IC", base + "분기점"):
        for src, pt in idx.get(cand, ()):
            key = (round(pt[0], 4), round(pt[1], 4))
            if key not in seen:
                seen.add(key)
                out.append((src, pt))
    return out


def pick_pair(idx, a: str, b: str, ext_km: float):
    """두 끝의 후보를 다 맞춰 보고 **연장에 가장 가까운 짝**을 고른다."""
    ca, cb = candidates(idx, a), candidates(idx, b)
    if not ca or not cb or not ext_km:
        return None
    best = None
    for sa, pa in ca:
        for sb, pb in cb:
            d = km(pa, pb)
            if d < 0.05:                      # 같은 점이면 선이 안 된다
                continue
            score = abs(d / ext_km - 1)
            if best is None or score < best[0]:
                best = (score, sa, pa, sb, pb, d)
    return best


def plan_rows(idx):
    rows = [r for r in PLAN.open(encoding="utf-8") if not r.startswith("#")]
    out, dropped = [], []
    for x in csv.DictReader(rows, delimiter="\t"):
        ext = float(x["km"])
        got = pick_pair(idx, x["from_pt"], x["to_pt"], ext)
        if not got:
            dropped.append((x["name"], "후보 없음"))
            continue
        _score, sa, pa, sb, pb, d = got
        ratio = d / ext
        if not (RATIO_LO <= ratio <= RATIO_HI):
            dropped.append((x["name"], f"비 {ratio:.2f}"))
            continue
        out.append({
            "stage": "계획",
            "kind": x["kind"],                      # 신설 / 확장
            "tier": x["tier"],                      # 중점 / 일반
            "axis": x["axis"], "line": x["line"],
            "name": x["name"], "km": ext,
            "lanes": x["lanes"] or None,
            "cost_eok": int(x["cost_eok"]),
            "category": x["category"],
            "a": [round(pa[0], 5), round(pa[1], 5)],
            "b": [round(pb[0], 5), round(pb[1], 5)],
            "src": f"{sa}/{sb}",
            "ratio": round(ratio, 2),
        })
    return out, dropped


def work_rows(idx):
    """도로공사 공사현황. 중계기가 있어야 한다.

    **쪽 넘기기는 자료가 말하는 count 를 따른다.** 예전에는 '한 쪽이
    100건보다 적으면 끝' 으로 봤는데, 그렇게 돌린 실행이 595건 중 198건
    에서 멈췄다. 마지막 쪽이 아닌데도 100건이 덜 온 것이다.
    """
    sys.path.insert(0, str(ROOT / "src"))
    from redt.collect.http import get                   # noqa: PLC0415
    EX = "https://data.ex.co.kr/openapi/safeDriving/hiwayCnstnPrss"
    out, dropped, cache = [], [], {}
    for cd, stage in (("C02", "공사중"), ("C03", "준공")):
        page, seen, total = 1, 0, None
        while True:
            r = get(EX, {"key": "__via_relay__", "type": "json",
                         "cmcnCstrClssCd": cd, "numOfRows": "100",
                         "pageNo": str(page), "pagingYN": "Y"}, timeout=60)
            body = r.json()
            if total is None:
                total = _int(body.get("count") or body.get("totalCount"))
            items = next((v for v in body.values()
                          if isinstance(v, list) and v and isinstance(v[0], dict)), [])
            if not items:
                break
            seen += len(items)
            for it in items:
                row, why = one_work(idx, it, stage, cache)
                (out.append(row) if row
                 else dropped.append((it.get("sectionName"), why)))
            if total and seen >= total:
                break
            if not total and len(items) < 100:
                break
            page += 1
            if page > 30:                              # 안전줄
                break
        print(f"  {stage}: 자료가 말하는 {total} · 받은 {seen}")
    return out, dropped


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def clean_addr(a: str) -> str:
    """측점(7+780) · '일원' · 짝 안 맞는 괄호를 떼어 낸다."""
    a = (a or "").strip()
    a = re.sub(r"\d+\s*\+\s*\d+", " ", a)          # 측점
    a = re.sub(r"[()\[\]]", " ", a)
    a = re.sub(r"일원|일대|부근|인근", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def umd_token(addr: str) -> str:
    """주소에서 **읍·면·동 마디**를 집는다.

    예전에는 마지막 마디만 봤다. 그런데 공사현황 주소는 '경기도 화성시
    동탄면 방교리' 처럼 **리까지** 오는 것이 가장 흔하다(198건 중 118건).
    우리 이름 사전은 읍·면을 묶어 가운데를 쓰므로 리는 아예 없다 —
    그래서 198건 중 15건밖에 안 붙었다. 뒤에서부터 훑어 읍·면·동으로
    끝나는 마디를 먼저 집고, 없으면 마지막 마디를 쓴다.
    """
    parts = (addr or "").split()
    for t in reversed(parts):
        if t.endswith(("읍", "면", "동")) and len(t) > 1:
            return t
    return parts[-1] if parts else ""


def geo_pair(cache: dict, a: str, b: str, ext_km: float):
    """명부로 못 찾으면 **지오코더에 물어본다** (중계기 경유).

    탐침이 이 길로 12건 중 대부분을 붙였고 비가 0.91~1.07 이었다
    (road_work_probe.py). 명부는 읍·면까지가 한계라 리·지번 주소는
    여기서만 풀린다.
    """
    try:
        from redt.collect.geocode import geocode_one    # noqa: PLC0415
    except Exception:                                   # noqa: BLE001
        return None
    pts = []
    for addr in (a, b):
        if addr not in cache:
            try:
                y, x = geocode_one(addr, kind="PARCEL")
            except Exception:                           # noqa: BLE001
                y = x = None
            if y is None:
                try:
                    y, x = geocode_one(addr, kind="ROAD")
                except Exception:                       # noqa: BLE001
                    y = x = None
            cache[addr] = (y, x) if y is not None else None
        pts.append(cache[addr])
    if not pts[0] or not pts[1]:
        return None
    d = km(pts[0], pts[1])
    if d < 0.05 or not ext_km:
        return None
    return (abs(d / ext_km - 1), "지오코더", pts[0], "지오코더", pts[1], d)


def one_work(idx, it: dict, stage: str, cache: dict | None = None):
    """(줄, 버린 까닭). 까닭을 돌려주는 것은 로그가 '좌표' 한 마디만
    남겨서 무엇을 고쳐야 할지 알 수 없었기 때문이다."""
    cache = {} if cache is None else cache
    ext = float(re.sub(r"[^0-9.]", "", str(it.get("cnstnExtns") or "")) or 0)
    a, b = clean_addr(it.get("cnstnStpntAddr")), clean_addr(it.get("cnstnEnpntAddr"))
    if not a or not b:
        return None, "주소 없음"
    if not ext:
        return None, "연장 없음"
    # 먼저 우리 명부(요금소·시군구·읍면동)로 — 부르지 않고 끝나면 제일 좋다.
    got = pick_pair(idx, umd_token(a), umd_token(b), ext)
    if got and RATIO_LO <= got[5] / ext <= RATIO_HI:
        pass
    else:
        got = geo_pair(cache, a, b, ext)
    if not got:
        return None, "좌표 못 얻음"
    _s, sa, pa, sb, pb, d = got
    ratio = d / ext
    if not (RATIO_LO <= ratio <= RATIO_HI):
        return None, f"비 {ratio:.2f}"
    return {
        "stage": stage, "kind": "공사",
        "route": it.get("routeName"), "section": it.get("sectionName"),
        "name": f"{it.get('routeName') or ''} {it.get('sectionName') or ''}".strip(),
        "biz": it.get("bizMgmtName"), "km": ext,
        "term": it.get("cnstnTerm"), "done_on": it.get("cmcnDate"),
        "a": [round(pa[0], 5), round(pa[1], 5)],
        "b": [round(pb[0], 5), round(pb[1], 5)],
        "src": f"{sa}/{sb}", "ratio": round(ratio, 2),
    }, ""


def snap_all(rows) -> None:
    """직선(a,b)을 **실제 노선 모양**(path)으로 바꾼다 — 되는 것만.

    2026-09-16 지시: "1번으로 우선 표시하고." 계획은 OSM 에 없다
    (탐침 run 17: proposed 0건). 그래서 여기서 바뀌는 것은 공사중·준공
    뿐이고, 계획 26건은 직선 그대로 남는다 — 두 끝밖에 모르는 구간에는
    그것이 정직한 그림이다.
    """
    import requests                                    # noqa: PLC0415
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import osm_geom as OG                              # noqa: PLC0415

    print("\nOSM 선형 받는 중 (남한 전체 motorway + construction)…")
    try:
        with requests.Session() as ses:
            ways = OG.fetch(ses)
    except Exception as exc:                           # noqa: BLE001
        print(f"  ✗ 못 받았다: {type(exc).__name__} {exc} — 직선 그대로 둔다")
        return
    routes = OG.build_routes(ways)
    built = sum(1 for w in ways if w["building"])
    print(f"  조각 {len(ways):,}개 (공사중 {built:,}) · 노선 {len(routes)}개")
    print(f"  노선 이름: {', '.join(sorted(routes)[:12])}…")

    ok = 0
    why = defaultdict(int)
    miss_name = defaultdict(int)
    for it in rows:
        # **확장 18건은 이미 있는 길을 넓히는 것이다** — 그 선형은 OSM 에
        # 있다. 그래서 단계로 자르지 않고 **노선 이름이 있느냐**로 가른다.
        # 신설 계획은 여기서 '노선 못 찾음' 으로 떨어지는 것이 맞다.
        name = it.get("route") or it.get("line") or ""
        if not name:
            why["노선명 없음"] += 1
            continue
        path, res = OG.snap(routes, name, it["a"], it["b"], it.get("km") or 0)
        if path:
            it["path"] = path
            it["path_ratio"] = round(res, 2)
            ok += 1
        else:
            why[res] += 1
            if res == "노선 못 찾음":
                miss_name[(name, OG.route_key(name))] += 1
    print(f"\n선형 붙임 {ok}/{len(rows)}")
    # 경로비는 값마다 한 줄이 되어 표를 뒤덮는다 — 한 줄로 묶는다.
    tidy = defaultdict(int)
    for w, n in why.items():
        tidy["경로비가 안 맞음" if str(w).startswith("경로비") else w] += n
    for w, n in sorted(tidy.items(), key=lambda kv: -kv[1]):
        print(f"   못 붙임 {w}: {n}건")

    # **어느 이름이 안 붙었는지 적는다.** '노선 못 찾음 116건' 만 보고는
    # 이름 규칙이 어긋난 것인지 그 노선이 OSM 에 없는 것인지 알 수 없다.
    if miss_name:
        top = sorted(miss_name.items(), key=lambda kv: -kv[1])[:12]
        print("\n   못 찾은 노선 이름 (우리 것 → 열쇠):")
        for (nm, key), n in top:
            print(f"     {nm} → {key} · {n}건")
        print(f"   OSM 이 아는 열쇠 {len(routes)}개: "
              f"{', '.join(sorted(routes)[:20])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", action="store_true", help="공사현황까지 받는다")
    ap.add_argument("--upload", action="store_true",
                    help="만든 뒤 공개 버킷에 올린다 (저장소에 커밋하지 않는다)")
    ap.add_argument("--osm", action="store_true",
                    help="OSM 선형에 스냅한다 (직선 대신 실제 노선 모양)")
    args = ap.parse_args()

    idx = build_index()
    print(f"이름 사전 {len(idx):,}개")

    plan, dropped = plan_rows(idx)
    print(f"\n계획  올림 {len(plan)}/37 · 버림 {len(dropped)}")
    for n, why in dropped:
        print(f"   버림 {n} — {why}")

    work, wdrop = [], []
    if args.work:
        try:
            work, wdrop = work_rows(idx)
        except Exception as exc:                       # noqa: BLE001
            print(f"\n공사  못 받았다: {type(exc).__name__} {exc}")
        else:
            print(f"\n공사  올림 {len(work)} · 버림 {len(wdrop)}")
            why = defaultdict(int)
            for _n, w in wdrop:
                why[re.sub(r"비 .*", "비가 안 맞음", w or "?")] += 1
            for w, n in sorted(why.items(), key=lambda kv: -kv[1]):
                print(f"   버린 까닭 {w}: {n}건")

    payload = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "plan_source": "국토교통부고시 제2022-60호 (2022-02-04) · 제2차 고속도로 건설계획(2021~2025)",
        "work_source": "한국도로공사 고속도로 공사현황",
        "note": "구간의 시작과 끝을 이은 선입니다 — 실제 노선 모양이 아닙니다.",
        "plan_total": 37,
        "items": plan + work,
    }
    if args.osm:
        snap_all(plan + work)

    if not args.work:
        # 공사 없이 돌렸으면 **이미 받아 둔 공사 줄을 지우지 않는다.**
        # 러너에는 예전 파일이 없으므로 버킷에 있는 것을 본다 — 그러지
        # 않으면 계획만 다시 만드는 실행이 공사 줄을 통째로 지운다.
        try:
            old = load_json("road.json")
        except Exception as exc:                       # noqa: BLE001
            print(f"\n(예전 road.json 을 못 읽었다: {type(exc).__name__})")
            old = {}
        keep = [x for x in old.get("items", []) if x.get("kind") == "공사"]
        if keep:
            payload["items"] = plan + keep
            print(f"\n(공사 {len(keep)}줄은 예전 것을 그대로 둔다)")
    # public/app/data 는 .gitignore 라 새 체크아웃에 **폴더 자체가 없다.**
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"\n{OUT.relative_to(ROOT)} · {len(payload['items'])}줄 · "
          f"{OUT.stat().st_size / 1024:.1f}KB")

    if args.upload:
        # **커밋이 아니라 버킷이다.** public/app/data 는 .gitignore 라
        # git add 가 통째로 막힌다 (첫 실행이 exit 128 로 끝난 자리).
        sys.path.insert(0, str(ROOT / "src"))
        from redt import web_store as WS                # noqa: PLC0415
        if not WS.configured():
            raise SystemExit("Supabase 설정이 없어 못 올립니다")
        if not WS.upload(OUT):
            raise SystemExit("버킷에 못 올렸습니다")
        # 올리기가 200 을 줬다는 것과 브라우저가 받는다는 것은 다른 말이다.
        if not WS.verify(("road.json",)):
            raise SystemExit("올라갔는데 공개 주소로 못 받습니다")
        print(f"버킷 {WS.BUCKET} 에 올렸습니다 · {WS.public_base()}/road.json")


if __name__ == "__main__":
    main()
