"""개별공시지가 두 API 를 실제로 불러 본다 — 면적이 있나, 묶어 주나.

지시(2026-09-19): "브이월드API 이미 있으니 확인하고 진행해 주세요."

화면에 찍힌 것 (운영자 확인):

    개별공시지가WFS조회    제공가능 트래픽 999,999,999
      https://api.vworld.kr/ned/wfs/getIndvdLandPriceWFS
    개별공시지가속성조회   제공가능 트래픽 999,999,999
      https://api.vworld.kr/ned/data/getIndvdLandPriceAttr

    ⓘ 제공가능 트래픽 : 해당 **오퍼레이션별로** 하루 동안 이용가능한 횟수

한도가 오퍼레이션별이고 사실상 무제한이면, 93일이라는 셈 자체가 없어진다.
다만 숫자를 화면에서 옮겨 적지 않는다 — 불러 보고 정한다.

## 무엇을 가르는가

세 가지다. 셋 다 불러 봐야 안다.

  ① **면적을 주는가**  개별공시지가는 공시지가를 연속지적도에 붙여 만든
     것이라, 토지대장 면적이 안 들어 있을 수 있다. 면적이 없으면 이 길은
     지번 추론에 못 쓴다 (엔진의 결정타가 면적이다).
  ② **법정동으로 묶어 주는가**  속성조회가 ldCode(법정동코드)를 받고
     쪽수로 넘겨 주면, 네모로 훑을 이유가 없다. 호출 수가 통째로 바뀐다.
  ③ **한도가 따로인가**  dt_d194 와 같은 통을 쓰면 아무 소용이 없다.

## 추측하지 않는다

파라미터 이름을 모르므로 **여러 모양을 다 넣어 본다.** 브이월드 NED 는
API 마다 이름이 조금씩 다르고, 문서를 못 보는 자리에서는 두드려 보는
것이 가장 빠르다. 응답 본문을 통째로 찍어 남긴다 — 실패의 이유가 거기
적혀 있다.

  python scripts/vworld_landprice_probe.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect import landchar as lc                      # noqa: E402
from redt.collect.http import get_once                       # noqa: E402
from redt.config import keys                                 # noqa: E402

ATTR = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"
WFS = "https://api.vworld.kr/ned/wfs/getIndvdLandPriceWFS"
DOMAIN = os.environ.get("VWORLD_DOMAIN", "toji.fyi")

# 안성시 공도읍 승두리. 거래가 많고 필지도 많아 표본으로 좋다.
BJD10 = "4155025328"
PNU = BJD10 + "1" + "0001" + "0000"
BOX = (127.20, 37.00, 127.21, 37.01)

AREA_WORDS = ("면적", "ar", "area")
PNU_WORDS = ("pnu", "고유번호", "ldcode")


def sp(t):
    return re.sub(r"\s+", " ", str(t))


def head(t):
    print(f"\n{t}\n" + "-" * (len(t) + 12))


def show_keys(keys_):
    area = [k for k in keys_ if any(w in k.lower() for w in AREA_WORDS)]
    pn = [k for k in keys_ if any(w in k.lower() for w in PNU_WORDS)]
    print(f"      칸 {len(keys_)}개 — {' · '.join(keys_)}")
    print(f"      면적으로 보이는 칸 {area or '없음'} · PNU 로 보이는 칸 {pn or '없음'}")
    return area, pn


def walk(obj, depth=0):
    """응답 어디에 행이 들어 있는지 모른다. 사전을 훑어 목록을 찾는다."""
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            got = walk(v, depth + 1)
            if got:
                return got
    return None


def main() -> int:
    print("=" * 72)
    print(" 개별공시지가 — 면적을 주는가 · 법정동으로 묶어 주는가")
    print("=" * 72)
    key = keys().require("vworld")

    # ── 1. 속성조회 ────────────────────────────────────────────────
    head("1. 속성조회 — 파라미터 이름을 두드려 찾는다")
    print("  문서를 못 보는 자리라 여러 모양을 다 넣어 봅니다.")
    shapes = [
        ("pnu 하나", {"pnu": PNU}),
        ("ldCode(법정동)", {"ldCode": BJD10, "numOfRows": 10, "pageNo": 1}),
        ("ldCodeNm 없이 stdrYear", {"ldCode": BJD10, "stdrYear": "2025",
                                    "numOfRows": 10, "pageNo": 1}),
        ("admCode", {"admCode": BJD10, "numOfRows": 10, "pageNo": 1}),
    ]
    winner = None
    for label, extra in shapes:
        params = {"key": key, "domain": DOMAIN, "format": "json", **extra}
        print(f"\n  [{label}] {extra}")
        try:
            r = get_once(ATTR, params, timeout=60)
        except Exception as exc:                             # noqa: BLE001
            print(f"    실패 — {type(exc).__name__}: {str(exc)[:160]}")
            continue
        print(f"    {r.status_code} · {sp(r.text)[:300]}")
        if r.status_code != 200:
            continue
        try:
            body = json.loads(r.text)
        except Exception:                                    # noqa: BLE001
            continue
        rows = walk(body)
        if not rows:
            continue
        area, pn = show_keys(list(rows[0].keys()))
        print(f"      첫 행 {json.dumps(rows[0], ensure_ascii=False)[:280]}")
        # 총 건수가 어디 있는지도 모른다. 숫자로 보이는 칸을 다 찍는다.
        tot = re.findall(r'"(totalCount|totalcount|numberOfRecords)"\s*:\s*"?(\d+)',
                         r.text)
        print(f"      총 건수 후보 {tot[:3]}")
        if area and pn and not winner:
            winner = (label, extra, area, pn)
            print("      ★ 면적과 PNU 가 함께 옵니다.")

    # ── 2. WFS ────────────────────────────────────────────────────
    head("2. WFS — 네모로 받으면 무엇이 오나")
    params = {"key": key, "domain": DOMAIN,
              "typename": "dt_d160", "bbox": ",".join(str(v) for v in BOX),
              "srsName": "EPSG:4326", "output": "application/json",
              "maxFeatures": "10", "resultType": "results"}
    for tn in ("dt_d160", "dt_d161", "indvdLandPrice", "dt_d194"):
        params["typename"] = tn
        print(f"\n  [typename={tn}]")
        try:
            r = get_once(WFS, params, timeout=60)
        except Exception as exc:                             # noqa: BLE001
            print(f"    실패 — {type(exc).__name__}: {str(exc)[:160]}")
            continue
        print(f"    {r.status_code} · {sp(r.text)[:260]}")
        if r.status_code != 200:
            continue
        try:
            feats = (json.loads(r.text) or {}).get("features") or []
        except Exception:                                    # noqa: BLE001
            continue
        if not feats:
            continue
        props = (feats[0] or {}).get("properties") or {}
        print(f"    피처 {len(feats)}개")
        show_keys(list(props.keys()))
        print(f"      첫 행 {json.dumps(props, ensure_ascii=False)[:280]}")

    # ── 3. 지금 쓰는 것과 견준다 ──────────────────────────────────
    head("3. 지금 쓰는 토지특성(dt_d194)은 같은 자리에서 무엇을 주나")
    try:
        pace = lc._Pace(lc._cfg()["calls_per_sec"])
        feats, _ = lc.fetch_tile(BOX, pace)
        print(f"  필지 {len(feats)}개")
        if feats:
            props = (feats[0] or {}).get("properties") or {}
            show_keys(list(props.keys()))
    except Exception as exc:                                 # noqa: BLE001
        print(f"  실패 — {type(exc).__name__}: {str(exc)[:200]}")

    head("정리")
    if winner:
        label, extra, area, pn = winner
        print(f"  속성조회가 [{label}] 모양으로 면적({area})과 PNU({pn}) 를 줍니다.")
        print("  법정동으로 묶여 오면 네모로 훑을 이유가 없습니다.")
    else:
        print("  속성조회에서 면적을 못 봤습니다. 2·3절을 견주어 정합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
