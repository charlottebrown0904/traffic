"""산업단지·공장등록 통계 — 사장님이 직접 받아 주신 파일을 읽는다 (2026-09-15).

포털 길이 막혀 있었다 (run 125: 후보 여섯 곳 어디에도 지정일이 없음).
사장님이 한국산업단지공단·팩토리온에서 직접 받아 주셨다.

## 무엇이 들었나 — 갈래마다 주는 것이 다르다

    kicox_park_national_*.csv   국가산단 현황 (시군구·면적·입주·가동)   지정일 ✗
    kicox_park_general_*.csv    일반산단 현황 (같은 모양, 788개)        지정일 ✗
    kicox_parks_full_*.xlsx     전국산단 현황통계 — **부록1 에 지정일** ○
    factoryon_registry_*.xlsx   공장등록현황 — **시군구별 등록공장 수** ○
    kicox_park_industry_*.csv   산단별 업종별 입주업체 수             지정일 ✗

지정일은 **분기 신규분에만** 있다. 한 분기 파일에서 얻는 것은 그 분기에
새로 지정된 몇 건뿐이다 — 분기 파일을 여러 개 모아야 이력이 된다.

## 여기서 제일 조심할 것 — 묶음 행

현황표에는 상위 묶음과 하위 지구가 **같이** 들어 있다.

    한국수출산업 (①)        1,922 천㎡     ← 묶음
    　　 서울디지털 ①        1,922 천㎡     ← 그 안의 지구

그냥 더하면 두 배가 된다. 게다가 묶음은 **여러 시군구에 걸친다** —
반월특수지역(①+②+③+④) 은 안산시로 적혀 있지만 그 안은 시흥·안산·화성이다.
그래서 **묶음을 버리고 잎(leaf)만 센다.** 묶음을 남기면 시군구가 틀린다.

묶음은 이름 끝의 `(①)` · `(① + ②)` 로 가린다. **`(①` 만 보면 안 된다** —
`구미국가(4단지) (② + ③)` 처럼 ② 로 시작하는 묶음이 있고, 그것 하나를
놓쳐 국가산단 합이 6,766 천㎡ 어긋났다.

이 규칙이 맞는지는 **공표 요약표와 맞춰 본다** (국가 802,695 천㎡ ·
입주 67,974 · 가동 62,743 → 셋 다 딱 맞았다). 안 맞으면 그 차이를 적는다.
"""
from __future__ import annotations

import re

import pandas as pd

# 묶음 행 — `(①)` · `(① + ②)` · `(② + ③)`.
BUNDLE = re.compile(r"\([①②③④⑤⑥⑦⑧⑨](?:\s*\+\s*[①②③④⑤⑥⑦⑧⑨])*\)")

PARK_KINDS = {"국가": "국가산단", "일반": "일반산단",
              "도시첨단": "도시첨단산단", "농공": "농공단지"}


def _num(s) -> pd.Series:
    return pd.to_numeric(pd.Series(s).astype(str).str.replace(",", "").str.strip(),
                         errors="coerce")


def read_parks(path) -> pd.DataFrame:
    """산단 현황 CSV → **잎 행만**. 묶음은 버린다 (시군구가 틀리므로)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    need = {"유형", "시도", "시군", "단지명", "조성상태"}
    if not need.issubset(df.columns):
        raise RuntimeError(f"{path}: 기대한 칸이 없습니다 — {list(df.columns)[:8]}")
    name = df["단지명"].astype(str)
    df = df[~name.str.contains(BUNDLE, regex=True)].copy()
    df["단지명"] = (df["단지명"].astype(str)
                   .str.replace(" ", " ").str.replace("▷", " ").str.strip())
    for c in ("유형", "시도", "시군", "조성상태"):
        df[c] = df[c].astype(str).str.strip()
    ren = {"지정면적(천제곱미터)": "지정면적", "관리면적(천제곱미터)": "관리면적",
           "입주업체(개)": "입주업체", "가동업체(개)": "가동업체"}
    for a, b in ren.items():
        if a in df.columns:
            df[b] = _num(df[a])
    return df.reset_index(drop=True)


def check_parks(df: pd.DataFrame, want: dict) -> dict:
    """잎 합이 공표 요약표와 맞는가. **안 맞으면 숨기지 않고 차이를 돌려준다.**"""
    got = {"단지수": int(len(df))}
    for k in ("지정면적", "입주업체", "가동업체"):
        if k in df.columns:
            got[k] = float(df[k].sum())
    out = {}
    for k, w in (want or {}).items():
        g = got.get(k)
        out[k] = {"우리": g, "공표": w,
                  "차이": None if g is None else round(g - w, 2),
                  "맞나": g is not None and abs(g - w) < max(1.0, abs(w) * 0.001)}
    return {"합계": got, "대조": out}


def parks_by_sigungu(df: pd.DataFrame, code_map: dict) -> list[tuple]:
    """시군구마다 단지수·면적·입주·가동. region_year 모양으로 돌려준다.

    `code_map` 은 ('시도','시군') → 시군구코드. 못 이은 것은 **버리지 않고**
    부르는 쪽에 세게 한다 — 조용히 빠지면 그 지역이 0 인 줄 알게 된다.
    """
    rows, unmatched = [], {}
    year = None
    for (sido, sigun), blk in df.groupby(["시도", "시군"]):
        code = code_map.get((sido, sigun)) or code_map.get(sigun)
        if not code:
            unmatched[f"{sido} {sigun}"] = int(len(blk))
            continue
        rows.append((code, "park_count", float(len(blk))))
        for src, metric, scale in (("지정면적", "park_area_km2", 0.001),
                                   ("입주업체", "park_tenant", 1.0),
                                   ("가동업체", "park_active", 1.0)):
            if src in blk.columns:
                rows.append((code, metric, float(blk[src].sum()) * scale))
    return rows, unmatched


def read_factory_sigungu(path, sheet: str = "시군구별 공장등록현황") -> pd.DataFrame:
    """공장등록현황 xlsx → 시군구별 등록공장 수.

    머리글이 셋째 줄에 있다 (제목 한 줄 + 빈 줄). 첫 줄을 머리글로 읽으면
    표 전체가 한 칸으로 뭉개진다.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    head = None
    for i in range(min(8, len(raw))):
        vals = [str(v).strip() for v in raw.iloc[i].tolist()]
        if "시도명" in vals and "시군구명" in vals:
            head = i
            break
    if head is None:
        raise RuntimeError(f"{path}[{sheet}]: '시도명·시군구명' 머리글을 못 찾았습니다")
    df = pd.read_excel(path, sheet_name=sheet, header=head)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["시군구명"].notna()].copy()
    for c in ("시도명", "시군구명"):
        df[c] = df[c].astype(str).str.strip()
    for c in ("등록완료", "부분등록", "휴업", "영업정지", "합계"):
        if c in df.columns:
            df[c] = _num(df[c])
    return df.reset_index(drop=True)


def factory_by_sigungu(df: pd.DataFrame, code_map: dict) -> tuple[list, dict]:
    """공장등록 → region_series 모양. **휴업·영업정지는 따로 둔다.**

    '공장이 몇 개인가' 와 '몇 개가 도는가' 는 다른 물음이다. 합계 하나로
    접으면 문 닫은 공장이 가동 중인 공장과 같은 무게가 된다.
    """
    rows, unmatched = [], {}
    for _i, r in df.iterrows():
        sido, sgg = r["시도명"], r["시군구명"]
        code = code_map.get((sido, sgg)) or code_map.get(sgg)
        if not code:
            unmatched[f"{sido} {sgg}"] = unmatched.get(f"{sido} {sgg}", 0) + 1
            continue
        for src, metric in (("등록완료", "factory_done"), ("부분등록", "factory_part"),
                            ("휴업", "factory_rest"), ("영업정지", "factory_stop"),
                            ("합계", "factory_all")):
            v = r.get(src)
            if pd.notna(v):
                rows.append((code, metric, float(v)))
    return rows, unmatched


def read_new_parks(path, sheet: str = "부록1)신규지정 및 해제현황") -> pd.DataFrame:
    """부록1 → **지정일자가 있는 유일한 표.** 신규지정과 해제를 갈라 담는다.

    한 장에 두 표가 세로로 붙어 있다 (신규지정 위, 지정해제 아래). 머리글이
    두 번 나오므로 그 자리에서 갈라야 한다 — 한 표로 읽으면 해제분이
    신규지정으로 둔갑한다.
    """
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    heads = []
    for i in range(len(raw)):
        vals = [str(v).strip() for v in raw.iloc[i].tolist()]
        if "단지명" in vals and "지정일자" in vals:
            heads.append((i, "해제" if any("해제일자" == v for v in vals) else "신규"))
    out = []
    for n, (i, kind) in enumerate(heads):
        end = heads[n + 1][0] if n + 1 < len(heads) else len(raw)
        cols = [str(v).strip() for v in raw.iloc[i].tolist()]
        blk = raw.iloc[i + 1:end].copy()
        blk.columns = cols
        blk = blk[blk.get("단지명").notna()] if "단지명" in blk else blk.iloc[0:0]
        # '일반산업단지 합계 : 9개' 같은 소계 줄은 시도 칸이 숫자다 — 버린다.
        if "시도" in blk.columns:
            blk = blk[blk["시도"].astype(str).str.strip().str.len().between(1, 8)]
            blk = blk[~blk["시도"].astype(str).str.match(r"^\d")]
        blk["사건"] = kind
        out.append(blk)
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    for c in ("유형", "시도", "시군구", "단지명", "사건"):
        if c in df.columns:
            df[c] = df[c].astype(str).str.replace("\n", " ").str.strip()
    for c in ("지정일자", "해제일자"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df
