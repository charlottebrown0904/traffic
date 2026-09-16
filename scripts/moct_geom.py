"""관 자료 고속도로 선형 — 브이월드 **데이터 API** (2026-09-16 지시).

  "갈아끼워주세요."

OSM 으로 먼저 붙였고(1번), 관 자료 길이 열리는지 계속 팠다(3번).
열렸으므로 갈아끼운다.

## 왜 갈아끼우나

    · 관이 만든 선형이다 — 더 정확하다
    · **차로수·제한속도·노선번호**가 딸려 온다
    · ODbL 을 아예 안 밟는다 (OSM 은 파생 데이터베이스 조항이 걸린다)
    · **f_node/t_node 가 있다** — 그래프를 꿰맬 필요가 없다.
      OSM 은 교차로마다 쪼개진 조각을 우리가 직접 이어야 했다.

## 문을 잘못 두드리고 있었다

브이월드에는 문이 둘인데 우리는 막힌 쪽만 두드렸다.

    /req/wfs    BBOX 만 먹는다. 쪽 넘기기(STARTINDEX)도 걸러 받기
                (attrFilter·CQL_FILTER)도 **무시된다.** 5개를 돌려주기에
                통한 줄 알았는데 값을 보니 안 걸러진 것이 그대로 왔다.
                1000개 상한 + 도로망은 시·군도가 압도적이라 고속도로는
                영영 안 들어온다.

    /req/data   **열려 있다.** attrFilter 가 실제로 먹고 page 도 먹는다.

실측(탐침 run 22):

    전국 · rd_rank_h:like:고속   status=OK · 값 ['고속국도']
    rddv:=:RDD001  전체 6,379 · 쪽 1/5 과 2/5 가 다르다 → 쪽 넘기기 된다

값이 말 그대로 '고속국도' 라 코드를 짐작할 일이 없다.

  python scripts/build_road.py --moct
"""
from __future__ import annotations

import sys
import urllib.parse

DATA = "https://api.vworld.kr/req/data"
LAYER = "LT_L_MOCTLINK"
# 남한 전체. 데이터 API 는 geomFilter 로 자른다.
KR_BOX = "BOX(124.5,33.0,131.2,38.7)"
PER = 1000                  # 데이터 API 한 쪽의 최대
MAX_PAGES = 80              # 안전줄 — 8만 개면 고속국도로는 넉넉하다


def fetch(log=print) -> list[dict]:
    """전국 고속국도 링크를 쪽을 넘겨 가며 받는다."""
    sys.path.insert(0, str(__import__("pathlib").Path(__file__)
                           .resolve().parent.parent / "src"))
    from redt.collect.http import get                   # noqa: PLC0415

    out, page, total = [], 1, None
    while page <= MAX_PAGES:
        q = {
            "service": "data", "request": "GetFeature", "format": "json",
            "data": LAYER, "geometry": "true", "crs": "EPSG:4326",
            "size": str(PER), "page": str(page),
            "attrFilter": "rd_rank_h:like:고속",
            "geomFilter": KR_BOX,
            "key": "__via_relay__", "domain": "https://toji.fyi",
        }
        r = get(f"{DATA}?{urllib.parse.urlencode(q)}", {}, timeout=120)
        body = r.json()
        resp = (body or {}).get("response") or {}
        if resp.get("status") == "NOT_FOUND":
            break
        feats = (((resp.get("result") or {}).get("featureCollection") or {})
                 .get("features") or [])
        if not feats:
            break
        if total is None:
            total = _int((resp.get("page") or {}).get("total"))
            # **total 을 건수로 믿지 않는다.** 첫 실행에서 total=32 가 왔고
            # 받은 것은 1,000개였다 — 32는 건수가 아니라 **쪽 수**다. 그걸
            # 건수로 읽는 바람에 1쪽에서 멈췄고, 전국의 3%로 스냅을 시도해
            # 성적이 171 → 60 으로 떨어졌다.
            #
            # 그래서 끝나는 조건은 **받은 것이 한 쪽보다 적으면 끝** 하나만
            # 쓴다. 이건 뜻이 하나뿐이라 헷갈릴 자리가 없다. total 은 쪽
            # 수로 보이므로 참고로만 찍는다.
            log(f"  page.total={total} (쪽 수로 보인다 — 건수로 쓰지 않는다)")
        for f in feats:
            row = _one(f)
            if row:
                out.append(row)
        if len(feats) < PER:
            break
        page += 1
    log(f"  받은 링크 {len(out):,}개 · {page}쪽")
    return out


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _one(f: dict):
    p = f.get("properties") or {}
    g = f.get("geometry") or {}
    co = g.get("coordinates") or []
    if g.get("type") == "MultiLineString":
        co = co[0] if co else []
    if len(co) < 2:
        return None
    nm = str(p.get("road_name") or "").strip()
    no = str(p.get("road_no") or "").strip()
    if not nm or nm == "-":
        nm = no                       # 이름이 없으면 번호로라도 모은다
    if not nm:
        return None
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import osm_geom as OG                               # noqa: PLC0415
    return {
        "key": OG.route_key(nm),
        "name": nm,
        "ref": no,
        "lanes": _int(p.get("lanes")),
        "building": False,            # 관 자료에는 공사중이 없다
        "src": "관",
        # **마디 이름이 이미 있다.** 좌표를 반올림해 꿰맬 필요가 없다.
        "a": str(p.get("f_node") or "") or None,
        "b": str(p.get("t_node") or "") or None,
        # 브이월드는 [경도, 위도] 로 준다 — 우리는 (위도, 경도) 로 쓴다.
        "pts": [(float(c[1]), float(c[0])) for c in co
                if isinstance(c, (list, tuple)) and len(c) >= 2],
    }
