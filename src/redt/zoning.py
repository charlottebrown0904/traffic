"""개발 한도 — 법의 범위와 시군구 조례의 값 (C1).

docs/dev-constraints-and-costs.md §1: 법(국토계획법 시행령 §84·§85)은 용도지역별
**상한 범위**를 주고, 시·군 **도시계획조례**가 그 안의 값을 정한다. 개발행위허가
문턱(경사도·표고·입목축적)은 시행령 §56 별표 1의2 가 "조례로 정하는 기준" 이라고만
해 값은 전부 조례에 있다.

이 모듈은 두 원천을 한 표로 묶는다.

  LAW              시행령 상한 (용도지역 21개). 손으로 적었고 조문 번호를 달았다.
  data/ordinance/  §9 에서 받은 전국 도시계획조례 204건의 요약 (index.json).

그리고 **시군구 코드에 붙인다**. 조례는 기관 이름으로 오고 필지는 PNU(법정동
코드)로 오므로, regions.json(우리 시군구 이름표)으로 잇는다.

  · 도 아래 시·군            → 그 시·군 조례 (수원시 장안구 → 수원시)
  · 특별시·광역시 자치구·군  → 광역시 조례. 자치구 조례는 건폐율 조문이 없다
                                (§9: 33곳 관심 조문 0). 값이 있으면 자치구가 이긴다.
  · 세종·제주                → 시도 조례 (단층제 · 행정시)

산출: config/zoning_limits.yaml (사람이 읽고 고치는 곳 — 출처·확인일이 줄마다)
      public/app/data/zoning-limits.json (화면이 읽는 곳 — 같은 내용, 작게)

값은 정규식으로 뽑은 **첫 값**이다. 완화·강화 단서는 원문 조문에 있다 —
화면도 그렇게 적는다.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .config import ROOT

ORDINANCE = ROOT / "data" / "ordinance" / "index.json"
REGIONS = ROOT / "public" / "app" / "data" / "regions.json"
YAML_OUT = ROOT / "config" / "zoning_limits.yaml"
WEB_OUT = ROOT / "public" / "app" / "data" / "zoning-limits.json"

# 국토의 계획 및 이용에 관한 법률 시행령 §84①(건폐율 상한) · §85①(용적률 범위).
# 단위 %. 조례는 이 범위 안에서 정한다 — 조례 값이 이 밖이면 우리가 잘못 읽은 것이다.
LAW: dict[str, dict] = {
    "제1종전용주거": {"bcr_max": 50, "far_min": 50, "far_max": 100},
    "제2종전용주거": {"bcr_max": 50, "far_min": 50, "far_max": 150},
    "제1종일반주거": {"bcr_max": 60, "far_min": 100, "far_max": 200},
    "제2종일반주거": {"bcr_max": 60, "far_min": 100, "far_max": 250},
    "제3종일반주거": {"bcr_max": 50, "far_min": 100, "far_max": 300},
    "준주거": {"bcr_max": 70, "far_min": 200, "far_max": 500},
    "중심상업": {"bcr_max": 90, "far_min": 200, "far_max": 1500},
    "일반상업": {"bcr_max": 80, "far_min": 200, "far_max": 1300},
    "근린상업": {"bcr_max": 70, "far_min": 200, "far_max": 900},
    "유통상업": {"bcr_max": 80, "far_min": 200, "far_max": 1100},
    "전용공업": {"bcr_max": 70, "far_min": 150, "far_max": 300},
    "일반공업": {"bcr_max": 70, "far_min": 150, "far_max": 350},
    "준공업": {"bcr_max": 70, "far_min": 150, "far_max": 400},
    "보전녹지": {"bcr_max": 20, "far_min": 50, "far_max": 80},
    "생산녹지": {"bcr_max": 20, "far_min": 50, "far_max": 100},
    "자연녹지": {"bcr_max": 20, "far_min": 50, "far_max": 100},
    "보전관리": {"bcr_max": 20, "far_min": 50, "far_max": 80},
    "생산관리": {"bcr_max": 20, "far_min": 50, "far_max": 80},
    "계획관리": {"bcr_max": 40, "far_min": 50, "far_max": 100},
    "농림": {"bcr_max": 20, "far_min": 50, "far_max": 80},
    "자연환경보전": {"bcr_max": 20, "far_min": 50, "far_max": 80},
}
LAW_SOURCE = "국토의 계획 및 이용에 관한 법률 시행령 제84조제1항(건폐율) · 제85조제1항(용적률) · 제56조 별표 1의2(개발행위허가 기준은 조례 위임)"
# 조례 요약에 있는 용도지역 (비도시 8개). 도시지역 값은 아직 안 뽑았다 — 그쪽은 LAW 만.
ZONES = ("보전관리", "생산관리", "계획관리", "보전녹지", "생산녹지", "자연녹지", "농림", "자연환경보전")
LAW_URL = "https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq="


def zone_key(land_use: str | None) -> str:
    """'계획관리지역' → '계획관리', '제1종일반주거지역' → '제1종일반주거'."""
    s = str(land_use or "").strip()
    return s[:-2] if s.endswith("지역") else s


def _num(v):
    try:
        return int(v) if str(v).strip() else None
    except (TypeError, ValueError):
        return None


def _ordinance_row(r: dict) -> dict:
    bcr = {z: _num(r.get(f"건폐율_{z}")) for z in ZONES}
    far = {z: _num(r.get(f"용적률_{z}")) for z in ZONES}
    return {
        "org": r["org"], "name": r["name"], "effective": r.get("effective") or None,
        "mst": str(r["mst"]), "url": LAW_URL + str(r["mst"]),
        "bcr": {z: v for z, v in bcr.items() if v is not None},
        "far": {z: v for z, v in far.items() if v is not None},
        "slope_deg": _num(r.get("경사도_도")), "elev_m": _num(r.get("표고_m")),
        "forest_pct": _num(r.get("입목축적_pct")),
    }


def _sanity(o: dict) -> list[str]:
    """조례 값이 시행령 범위 밖이면 우리가 잘못 읽은 것 — 그 값은 버리고 이유를 남긴다."""
    dropped = []
    for z, v in list(o["bcr"].items()):
        if v > LAW[z]["bcr_max"]:
            dropped.append(f"{o['org']} 건폐율 {z} {v}% > 시행령 {LAW[z]['bcr_max']}%")
            del o["bcr"][z]
    for z, v in list(o["far"].items()):
        if not (LAW[z]["far_min"] <= v <= LAW[z]["far_max"]):
            dropped.append(f"{o['org']} 용적률 {z} {v}% ∉ 시행령 {LAW[z]['far_min']}~{LAW[z]['far_max']}%")
            del o["far"][z]
    return dropped


def match(ordinances: list[dict], regions: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """시군구 코드 → 조례. (표, 못 붙인 코드 목록)."""
    by_org: dict[tuple[str, str], dict] = {}
    for r in ordinances:
        parts = r["org"].split()
        sido, sg = parts[0], (parts[1] if len(parts) > 1 else "")
        by_org[(sido, sg)] = r
    out: dict[str, dict] = {}
    missing: list[str] = []
    for reg in regions:
        code, sido = str(reg["sigungu_cd"]), reg.get("sido") or ""
        name = (reg.get("parent") or reg.get("name") or "").strip()
        if code.startswith("36"):
            name = ""                                   # 세종 — 시군구가 없다
        if code.startswith("50"):
            name = ""                                   # 제주 — 행정시라 도 조례
        cands = [by_org.get((sido, name)), by_org.get((sido, ""))] if name else [by_org.get((sido, ""))]
        cands = [c for c in cands if c]
        pick = next((c for c in cands if c["bcr"]), None) or (cands[-1] if cands else None)
        if pick is None:
            missing.append(f"{code} {sido} {name}".strip())
            continue
        level = "sigungu" if pick is by_org.get((sido, name)) and name else "sido"
        out[code] = {**pick, "level": level, "region": reg.get("name")}
    return out, missing


def build(ordinance_path: Path = ORDINANCE, regions_path: Path = REGIONS) -> dict:
    index = json.loads(Path(ordinance_path).read_text(encoding="utf-8"))
    regions = json.loads(Path(regions_path).read_text(encoding="utf-8"))
    rows = [_ordinance_row(r) for r in index]
    dropped: list[str] = []
    for o in rows:
        dropped += _sanity(o)
    table, missing = match(rows, regions)
    return {"generated": dt.date.today().isoformat(), "law_source": LAW_SOURCE, "law": LAW,
            "zones": list(ZONES), "sigungu": table, "missing": missing, "dropped": dropped}


def to_web(built: dict) -> dict:
    """화면용 — 조례 한 건은 한 번만(ord), 시군구는 [일련번호, 단계] 로 가리킨다.
    코드마다 조례를 되풀이하면 110KB, 이렇게 하면 30KB 대다."""
    ords: dict[str, dict] = {}
    sg: dict[str, list] = {}
    for code, o in built["sigungu"].items():
        mst = o["mst"]
        if mst not in ords:
            row = {"name": o["name"], "org": o["org"], "eff": o["effective"], "url": o["url"],
                   "bcr": o["bcr"], "far": o["far"]}
            for k, w in (("slope_deg", "slope"), ("elev_m", "elev"), ("forest_pct", "forest")):
                if o.get(k) is not None:
                    row[w] = o[k]
            ords[mst] = row
        sg[code] = [mst, o["level"]]
    return {"generated": built["generated"], "law": built["law"], "law_source": built["law_source"],
            "ord": ords, "sg": sg}


HEADER = """# 개발 한도 — 법의 범위와 시군구 조례의 값 (C1). **만든 파일이다.**
#
#   python -m redt.cli zoning-limits      ← data/ordinance/index.json + regions.json 에서
#
# 손으로 고치지 말 것. 조례 값이 틀렸으면 data/ordinance 의 조문(원문 링크)을 보고
# src/redt/collect/law.py 의 정규식을 고친 뒤 다시 만든다. 값은 정규식으로 뽑은
# **첫 값**이라 완화·강화 단서는 담지 않는다 — 원문 조문이 근거다.
#
# law:      국토계획법 시행령 §84①·§85① 상한 (단위 %). 조례는 이 안에서 정한다.
# sigungu:  시군구 코드(법정동 앞 5자리) → 적용 조례. level 이 sido 면 광역시·도
#           조례를 쓴 것 (자치구·행정시·세종). bcr=건폐율 far=용적률 (비도시 8개
#           용도지역만). slope_deg=개발행위 경사도 한도, elev_m=표고, forest_pct=입목축적.
# missing:  조례를 못 붙인 시군구. dropped: 시행령 범위 밖이라 버린 값 (읽기 오류).
#
"""


def write(built: dict, yaml_path: Path = YAML_OUT, web_path: Path = WEB_OUT) -> tuple[Path, Path]:
    import yaml
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(HEADER + yaml.safe_dump(built, allow_unicode=True, sort_keys=False, width=110),
                         encoding="utf-8")
    web_path.parent.mkdir(parents=True, exist_ok=True)
    web_path.write_text(json.dumps(to_web(built), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return yaml_path, web_path
