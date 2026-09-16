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
    """도로공사 공사현황. 중계기가 있어야 한다."""
    sys.path.insert(0, str(ROOT / "src"))
    from redt.collect.http import get                   # noqa: PLC0415
    EX = "https://data.ex.co.kr/openapi/safeDriving/hiwayCnstnPrss"
    out, dropped = [], []
    for cd, stage in (("C02", "공사중"), ("C03", "준공")):
        page = 1
        while True:
            r = get(EX, {"key": "__via_relay__", "type": "json",
                         "cmcnCstrClssCd": cd, "numOfRows": "100",
                         "pageNo": str(page), "pagingYN": "Y"}, timeout=60)
            body = r.json()
            items = next((v for v in body.values()
                          if isinstance(v, list) and v and isinstance(v[0], dict)), [])
            if not items:
                break
            for it in items:
                row = one_work(idx, it, stage)
                (out if row else dropped).append(row or (it.get("sectionName"), "좌표"))
            if len(items) < 100:
                break
            page += 1
    return out, dropped


def clean_addr(a: str) -> str:
    """측점(7+780) · '일원' · 짝 안 맞는 괄호를 떼어 낸다."""
    a = (a or "").strip()
    a = re.sub(r"\d+\s*\+\s*\d+", " ", a)          # 측점
    a = re.sub(r"[()\[\]]", " ", a)
    a = re.sub(r"일원|일대|부근|인근", " ", a)
    return re.sub(r"\s+", " ", a).strip()


def one_work(idx, it: dict, stage: str):
    ext = float(re.sub(r"[^0-9.]", "", str(it.get("cnstnExtns") or "")) or 0)
    a, b = clean_addr(it.get("cnstnStpntAddr")), clean_addr(it.get("cnstnEnpntAddr"))
    if not a or not b or not ext:
        return None
    # 주소의 마지막 두 마디(읍면동·리)로 우리 명부에서 찾는다 —
    # 지오코더를 안 부르고도 대부분 걸린다.
    got = pick_pair(idx, a.split()[-1], b.split()[-1], ext)
    if not got:
        return None
    _s, sa, pa, sb, pb, d = got
    ratio = d / ext
    if not (RATIO_LO <= ratio <= RATIO_HI):
        return None
    return {
        "stage": stage, "kind": "공사",
        "route": it.get("routeName"), "section": it.get("sectionName"),
        "name": f"{it.get('routeName') or ''} {it.get('sectionName') or ''}".strip(),
        "biz": it.get("bizMgmtName"), "km": ext,
        "term": it.get("cnstnTerm"), "done_on": it.get("cmcnDate"),
        "a": [round(pa[0], 5), round(pa[1], 5)],
        "b": [round(pb[0], 5), round(pb[1], 5)],
        "src": f"{sa}/{sb}", "ratio": round(ratio, 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", action="store_true", help="공사현황까지 받는다")
    ap.add_argument("--upload", action="store_true",
                    help="만든 뒤 공개 버킷에 올린다 (저장소에 커밋하지 않는다)")
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

    payload = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "plan_source": "국토교통부고시 제2022-60호 (2022-02-04) · 제2차 고속도로 건설계획(2021~2025)",
        "work_source": "한국도로공사 고속도로 공사현황",
        "note": "구간의 시작과 끝을 이은 선입니다 — 실제 노선 모양이 아닙니다.",
        "plan_total": 37,
        "items": plan + work,
    }
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
