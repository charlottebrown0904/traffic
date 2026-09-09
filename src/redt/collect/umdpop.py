"""읍·면·동 인구 — KOSIS 행정동 표를 받아 우리 법정동 이름에 붙인다.

사장님 지시(2026-09-09): 땅값 글자 옆의 (XX만)을 읍·면·동에도.

## 무엇을 받는가 — 탐침이 알려준 그대로

  표      101 / DT_1B04005N  행정구역(읍면동)별/5세별 주민등록인구(2011년~)
  축      objL1 = 지역 (4,818개) · objL2 = 연령 (22단, '계' 는 0)
  항목    itmId = T2 (총인구수)

한 해에 4,818 × 1 × 1 = 4,818셀. KOSIS 의 4만 셀 한도 아래다. 축을
안 채우면 err 20, 셋을 채우면 err 21, 연령을 ALL 로 두면 err 31 이
온다 — 세 가지를 다 받아 보고 정한 조합이다(run 68~70).

## 급소: **행정동이지 법정동이 아니다**

받은 코드는 10자리 행정동 코드다.

    1111051500  청운효자동   ← 행정동
                청운동·신교동·궁정동·효자동·창성동·통인동…  ← 그 안의 법정동

우리 실거래에는 **법정동 이름**만 있다(umd). 그러니 1:1 이 아니다.

  읍·면    거의 그대로 맞는다. 공도읍·미양면은 행정동 이름도 같다.
  동       도시에서 자주 어긋난다. 청운효자동은 우리 자료에 없는 이름이다.

**못 맞춘 것을 억지로 채우지 않는다.** 채우면 그 거짓이 화면에
'이 리의 인구' 로 뜬다 — 없는 것보다 나쁘다. 맞춘 비율을 세어
로그에 남기고, 못 맞춘 곳은 비운다.

그리고 이 제품이 보는 땅(계획관리·생산관리)은 **읍·면에 있다.**
어긋나는 쪽은 도시의 동인데, 거기는 애초에 우리 관심 밖이다.
"""
from __future__ import annotations

import pandas as pd

from . import kosis

ORG_ID = "101"
TBL_ID = "DT_1B04005N"
ITM_TOTAL = "T2"          # 총인구수
AGE_TOTAL = "0"           # 연령 '계'

# 표가 2011년부터다. 그 앞 해는 이 표에 없다 — 시군구 인구로 남긴다.
FIRST_YEAR = 2011


def fetch_year(year: int) -> pd.DataFrame:
    """한 해치. 행정동 코드·이름·인구."""
    rows = kosis.fetch_table(
        ORG_ID, TBL_ID, str(year), str(year),
        obj_l1="ALL", itm_id=ITM_TOTAL,
        obj={"objL2": AGE_TOTAL}, quiet=True)
    out = []
    for r in rows:
        code = str(r.get("C1") or "").strip()
        name = str(r.get("C1_NM") or "").strip()
        val = r.get("DT")
        # **10자리만 읍·면·동이다.** 같은 응답에 전국(00)·시도(2)·
        # 시군구(5)가 섞여 있고, 시군구 코드는 그 안의 동 인구를 이미
        # 포함한다. 골라 쓰지 않으면 같은 사람을 두 번 센다
        # (시군구 인구에서 겪은 것과 같은 함정).
        if len(code) != 10 or not name:
            continue
        try:
            pop = int(float(val))
        except (TypeError, ValueError):
            continue
        if pop <= 0:
            continue
        out.append({"adm_cd": code, "sigungu_cd": code[:5],
                    "umd": name, "year": int(year), "pop": pop})
    return pd.DataFrame(out)


def collect(start: int, end: int) -> pd.DataFrame:
    """여러 해. 한 해가 한 번의 호출이라 값싸다."""
    frames = []
    for y in range(max(start, FIRST_YEAR), end + 1):
        try:
            df = fetch_year(y)
        except Exception as exc:                            # noqa: BLE001
            # 한 해가 막혔다고 나머지를 버리지 않는다.
            print(f"  {y}년 실패 — {type(exc).__name__}: {str(exc)[:120]}")
            continue
        print(f"  {y}년 {len(df):,}개 읍면동")
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["adm_cd", "sigungu_cd", "umd",
                                     "year", "pop"])
    return pd.concat(frames, ignore_index=True)


def match_report(pop: pd.DataFrame, ours: pd.DataFrame) -> dict:
    """우리 법정동 이름 중 몇 %가 행정동 이름과 맞는가.

    **읍·면과 동을 갈라서 센다.** 합쳐 세면 '70% 맞음' 같은 숫자가
    나오는데, 그 안에서 우리가 쓰는 읍·면은 95%이고 안 쓰는 동이
    30%일 수 있다. 갈라 놓지 않으면 쓸 만한지 아닌지를 못 읽는다.
    """
    if pop.empty or ours.empty:
        return {"total": 0, "hit": 0}
    have = set(zip(pop["sigungu_cd"], pop["umd"]))
    ours = ours.copy()
    ours["hit"] = [(s, u) in have for s, u in
                   zip(ours["sigungu_cd"], ours["umd"])]

    def kind(name: str) -> str:
        n = str(name)
        if n.endswith("읍") or n.endswith("면"):
            return "읍·면"
        return "동·기타"

    ours["kind"] = [kind(u) for u in ours["umd"]]
    by = ours.groupby("kind")["hit"].agg(["sum", "count"])
    return {
        "total": int(len(ours)),
        "hit": int(ours["hit"].sum()),
        "by_kind": {k: (int(r["sum"]), int(r["count"]))
                    for k, r in by.iterrows()},
    }
