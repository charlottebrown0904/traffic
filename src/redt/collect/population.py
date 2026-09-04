"""KOSIS 시군구 인구를 **우리 행정구역 코드에 맞춰** 정리한다.

받은 그대로는 못 쓴다. 세 가지가 어긋나 있다.

1. 계층이 섞여 있다
   응답에는 전국(00)·시도(2자리)·시군구(5자리)가 다 들어 있고, 시 코드는
   그 안의 구 인구를 **이미 포함**한다. 수원시 41110 = 4개 구의 합이다.
   5자리를 전부 더하면 6,092만으로 전국 5,112만보다 크다. 골라 쓰지 않으면
   같은 사람을 두 번 센다.

2. 코드가 바뀌었다
   2003~2025 사이에 창원이 통합되고, 세종이 생기고, 청주와 청원이 합쳐지고,
   광주·전남이 통합되며 접두사 12 를 새로 받았다. 코드를 그대로 맞추면
   창원시는 2010년부터만 인구가 있고 그 앞은 빈다.

3. 항목이 셋이다
   총인구수·남자인구수·여자인구수가 한 파일에 있다. 고르지 않으면 같은
   시군구·연도가 세 번 나온다.

무엇을 하는가
   우리가 실제로 쓰는 시군구 코드(config/sigungu_codes.yaml)마다, 해마다
   총인구를 하나씩 채운다. 채우지 못한 자리는 **비워 두고 몇 개인지
   보고한다** — 억지로 메우면 그 거짓이 회귀에서는 계수 크기로만 나타나
   눈에 안 띈다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from ..config import ROOT

HISTORY = ROOT / "config" / "region_history.yaml"

# KOSIS 응답의 칸 이름. 바뀌면 여기만 고친다.
COL_CODE = "C1"
COL_NAME = "C1_NM"
COL_YEAR = "PRD_DE"
COL_VALUE = "DT"
COL_ITEM = "ITM_NM"
ITEM_TOTAL = "총인구수"


def _history() -> dict:
    if not HISTORY.exists():
        return {"predecessors": {}, "sido_moves": []}
    data = yaml.safe_load(HISTORY.read_text(encoding="utf-8")) or {}
    data.setdefault("predecessors", {})
    data.setdefault("sido_moves", [])
    return data


def read_kosis(path: Path) -> pd.DataFrame:
    """KOSIS 원본에서 **5자리 시군구의 총인구**만 뽑는다."""
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in (COL_CODE, COL_YEAR, COL_VALUE, COL_ITEM)
               if c not in df.columns]
    if missing:
        raise ValueError(f"KOSIS 원본에 없는 칸: {missing} (있는 칸: {list(df.columns)})")
    out = df[df[COL_ITEM] == ITEM_TOTAL].copy()
    out = out[out[COL_CODE].str.fullmatch(r"\d{5}", na=False)]
    out["year"] = pd.to_numeric(out[COL_YEAR], errors="coerce")
    out["value"] = pd.to_numeric(out[COL_VALUE], errors="coerce")
    out = out.dropna(subset=["year", "value"])
    out["year"] = out["year"].astype(int)
    return out.rename(columns={COL_CODE: "code", COL_NAME: "name"})[
        ["code", "name", "year", "value"]]


def normalize(kosis: pd.DataFrame, our_codes: dict[str, str]) -> tuple[pd.DataFrame, dict]:
    """우리 코드 × 연도 → 총인구.

    our_codes 는 {시군구코드: 이름}. 이름은 시도가 통째로 바뀐 경우에만
    쓴다 — 코드로는 이을 수 없기 때문이다.

    돌려주는 것은 (표, 보고). 보고에는 못 채운 자리가 왜 비었는지가 든다.
    """
    hist = _history()
    pred: dict[str, list[str]] = hist["predecessors"]
    years = sorted(kosis["year"].unique())
    by_key = {(r.code, r.year): r.value for r in kosis.itertuples(index=False)}

    # 시도 통째 이동 — 옛 접두사 안에서 이름으로 잇는다.
    old_by_name: dict[str, dict[str, str]] = {}
    for move in hist["sido_moves"]:
        table: dict[str, str] = {}
        for r in kosis.drop_duplicates("code").itertuples(index=False):
            if r.code[:2] in move["from_prefixes"]:
                # 이름이 겹치면 이을 수 없다. 겹치는지 여기서 본다.
                if r.name in table and table[r.name] != r.code:
                    table[r.name] = ""          # 겹침 표시 — 아래에서 거른다
                else:
                    table.setdefault(r.name, r.code)
        old_by_name[move["to_prefix"]] = table

    rows: list[dict] = []
    gaps: dict[str, list[int]] = {}
    used_alias: dict[str, str] = {}
    for code, name in sorted(our_codes.items()):
        moved = old_by_name.get(code[:2], {}).get(name or "")
        if moved:
            used_alias[code] = moved
        for year in years:
            value = by_key.get((code, year))
            source = "직접"
            if value is None and moved:
                value = by_key.get((moved, year))
                source = f"옛코드 {moved}"
            if value is None and code in pred:
                parts = [by_key.get((p, year)) for p in pred[code]]
                if parts and all(p is not None for p in parts):
                    value = sum(parts)
                    source = "합산 " + "+".join(pred[code])
            if value is None:
                gaps.setdefault(code, []).append(year)
                continue
            rows.append({"sigungu_cd": code, "year": year,
                         "population": int(round(value)), "source": source})

    table = pd.DataFrame(rows, columns=["sigungu_cd", "year", "population", "source"])
    report = {
        "years": years,
        "our_codes": len(our_codes),
        "filled_codes": table["sigungu_cd"].nunique() if len(table) else 0,
        "cells": len(table),
        "cells_max": len(our_codes) * len(years),
        "gaps": gaps,
        "aliases": used_alias,
    }
    return table, report


def describe(report: dict, our_codes: dict[str, str]) -> None:
    """보고를 사람이 읽게 찍는다. 빈 자리를 숨기지 않는다."""
    cells, cap = report["cells"], report["cells_max"]
    pct = 100 * cells / cap if cap else 0
    print(f"\n  채운 자리 {cells:,} / {cap:,} ({pct:.1f}%)")
    print(f"  코드 {report['filled_codes']}/{report['our_codes']}"
          f" · 연도 {report['years'][0]}~{report['years'][-1]}")
    if report["aliases"]:
        print(f"  옛 코드로 이은 것 {len(report['aliases'])}개 (시도 통합):")
        for cd, old in list(report["aliases"].items())[:5]:
            print(f"    {cd} {our_codes.get(cd, '')} ← {old}")
        if len(report["aliases"]) > 5:
            print(f"    … 외 {len(report['aliases']) - 5}개")

    gaps = report["gaps"]
    if not gaps:
        print("  빈 자리 없음")
        return
    full = {c: y for c, y in gaps.items() if len(y) == len(report["years"])}
    part = {c: y for c, y in gaps.items() if c not in full}
    print(f"\n  ⚠ 빈 자리가 있는 코드 {len(gaps)}개"
          f" (통째로 빈 것 {len(full)} · 일부만 빈 것 {len(part)})")
    print("    구가 새로 갈라진 경우다. 하나를 여럿으로 나눌 근거가 없어")
    print("    잇지 않았다 — 비율로 쪼개면 변화율이 거짓이 된다.")
    for code, ys in sorted(part.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"      {code} {our_codes.get(code, ''):<14} {len(ys)}년"
              f" ({ys[0]}~{ys[-1]})")
    for code, ys in list(full.items())[:12]:
        print(f"      {code} {our_codes.get(code, ''):<14} 전 기간 없음")
