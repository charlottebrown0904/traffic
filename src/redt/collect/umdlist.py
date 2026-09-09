"""전국 법정동 명부 — 거래가 없는 읍·면·동도 지도에 그리려고.

사장님 지시(2026-09-09): "전국구로 확대해 주시고"

## 왜 필요한가

우리 자료는 실거래에서 나왔습니다. 그래서 **거래가 있었던 읍·면·동만**
압니다(17,430곳). 거래가 한 건도 없던 곳은 이름조차 모르고, 모르는 곳은
지도에 못 그립니다 — 시·군·구에서 대전 세 구가 사라졌던 것과 같은 일이
한 단계 아래에서 벌어지고 있습니다.

## 어디서 받는가 — 탐침이 정한 그대로

  행정안전부_행정표준코드 (data.go.kr, 1741000/StanReginCd)

브이월드 데이터 API·WFS 는 우리 중계기를 거치면 502 로 끊깁니다. 가볍게
(도형 없이 다섯 줄만) 물어도 같아서 크기 문제가 아닙니다. code.go.kr 은
파일을 사람이 눌러 받는 화면이라 자동화에 맞지 않습니다.

## 급소 셋

**(1) 이 표에는 좌표가 없습니다.** 이름과 코드뿐입니다. 좌표는 뒤이어
브이월드 지오코더로 구합니다 — 우리가 이미 쓰는 길이고, 빈 곳이 3천
안팎이라 하루 한도(3~4만) 안에서 끝납니다.

**(2) 우리 umd 는 '면 + 리' 두 마디입니다.** '금남면 국곡리' 처럼.
표준코드는 마디를 따로 주므로 우리 꼴로 이어 붙입니다.

**(3) 시군구 코드가 우리 것과 다를 수 있습니다.** 전남광주통합특별시가
접두사 12 를 새로 받았는데 바깥 자료는 아직 29·46 으로 줍니다. 인구 표에서
이미 겪은 일이라(webexport._umd_pop_alias) **이름으로 잇습니다.**
"""
from __future__ import annotations

import json

from .http import get

URL = "https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList"
PAGE = 1000                      # 한 쪽에 몇 줄. 표 전체가 2만 줄쯤이다.
MAX_PAGES = 60                   # 6만 줄. 그보다 많으면 무언가 잘못됐다.


class ShapeError(RuntimeError):
    """응답이 우리가 아는 꼴이 아니다. **조용히 빈 손으로 끝내지 않는다.**"""


def _rows(payload: dict) -> tuple[list[dict], int | None, str]:
    """(줄들, 전체건수, 서비스가 한 말).

    표준코드 응답은 리스트 안에 head 와 row 가 나뉘어 옵니다. 꼴을
    맞히지 않고 **찾아서** 읽습니다 — 이 저장소는 응답 모양을 세 번
    틀렸습니다.
    """
    blocks = payload.get("StanReginCd")
    if not isinstance(blocks, list):
        # 오류는 전혀 다른 봉투로 옵니다 (OpenAPI_ServiceResponse).
        msg = json.dumps(payload, ensure_ascii=False)[:300]
        raise ShapeError(f"StanReginCd 가 없습니다: {msg}")
    rows: list[dict] = []
    total: int | None = None
    said = ""
    for b in blocks:
        if not isinstance(b, dict):
            continue
        for h in b.get("head") or []:
            if not isinstance(h, dict):
                continue
            if "totalCount" in h:
                total = int(h["totalCount"])
            res = h.get("RESULT")
            if isinstance(res, dict):
                said = f"{res.get('resultCode')} {res.get('resultMsg')}"
        rows.extend(r for r in (b.get("row") or []) if isinstance(r, dict))
    return rows, total, said


def fetch_all(quiet: bool = False) -> list[dict]:
    """표를 통째로. 쪽마다 이어 받습니다."""
    out: list[dict] = []
    total: int | None = None
    for page in range(1, MAX_PAGES + 1):
        resp = get(URL, {"type": "json", "numOfRows": str(PAGE),
                         "pageNo": str(page), "flag": "Y"}, timeout=60)
        try:
            payload = resp.json()
        except ValueError:
            raise ShapeError(
                f"JSON 이 아닙니다 (http={resp.status_code}): "
                f"{' '.join(resp.text[:300].split())}") from None
        rows, got_total, said = _rows(payload)
        if page == 1:
            total = got_total
            if not quiet:
                print(f"  전체 {total:,}줄 · 서비스: {said}")
                if rows:
                    # **첫 줄을 통째로 찍습니다.** 칸 이름을 기억으로 적으면
                    # 틀린 칸을 읽고도 맞는 줄 압니다.
                    print("  첫 줄: "
                          + json.dumps(rows[0], ensure_ascii=False)[:400])
        if not rows:
            break
        out.extend(rows)
        if not quiet and page % 5 == 0:
            print(f"    {len(out):,}줄", flush=True)
        if total is not None and len(out) >= total:
            break
    if total is not None and len(out) < total:
        print(f"  ⚠ {total:,}줄 중 {len(out):,}줄만 받았습니다 "
              f"(쪽 한도 {MAX_PAGES})")
    return out


def _text(row: dict, *names: str) -> str:
    for n in names:
        v = row.get(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def to_places(rows: list[dict]) -> list[dict]:
    """표준코드 줄 → 우리가 쓰는 꼴.

    돌려주는 칸:
      sigungu_cd  5자리 (표준코드 기준. 우리 코드로 잇는 것은 적재 쪽 일)
      umd         '금남면 국곡리' / '고운동' — 우리 trade.umd 와 같은 꼴
      level       'umd' (읍·면·동) 또는 'ri' (리)
      sigungu     시군구 이름 (세종처럼 없는 곳은 빈 값)
      full_nm     전체 주소 (시도부터)

    **폐지된 구역은 뺍니다.** 표에는 없어진 동도 남아 있고, 그것까지
    그리면 지도에 있지도 않은 이름이 뜹니다.
    """
    out = []
    seen = set()
    for r in rows:
        code = _text(r, "region_cd")
        if len(code) != 10 or not code.isdigit():
            continue
        # 말소일자가 있으면 없어진 구역입니다.
        if _text(r, "del_de", "delDe"):
            continue
        full = _text(r, "locatadd_nm")
        if not full:
            continue
        parts = full.split()
        # 시도 · 시군구(한두 마디) · 읍면동 · 리 순으로 옵니다. 우리가 쓰는
        # 것은 **끝의 한두 마디**뿐이라 앞은 안 셉니다.
        umd_cd, ri_cd = code[5:8], code[8:10]
        if umd_cd == "000":
            continue                       # 시·군·구 줄. 우리에겐 이미 있다.
        if ri_cd == "00":
            name, level = parts[-1], "umd"
        else:
            if len(parts) < 2:
                continue
            name, level = " ".join(parts[-2:]), "ri"
        key = (code[:5], name)
        if key in seen:
            continue
        seen.add(key)
        # 시군구 이름은 **앞뒤를 떼고 남는 것**이다. 첫 마디가 시·도,
        # 끝의 한두 마디가 읍면동·리다. 세종처럼 시군구가 없는 곳은
        # 자연히 빈 값이 되는데, 그것이 맞다 — 우리 실거래 자료도
        # 세종의 시군구 칸이 비어 있다.
        tail = 2 if level == "ri" else 1
        sigungu = " ".join(parts[1:len(parts) - tail])
        out.append({"region_cd": code, "sigungu_cd": code[:5],
                    "sigungu": sigungu, "umd": name,
                    "level": level, "full_nm": full})
    return out
