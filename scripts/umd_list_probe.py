"""거래가 없는 읍·면·동까지 지도에 그리려면 무엇이 필요한가 — 탐침.

사장님 지시(2026-09-09): "전국구로 확대해 주시고 제가 파일을 받는 것이
빠르면 그렇게 해주세요."

## 무엇이 없는가

시·도와 시·군·구는 전국 명부(regions.json 255곳)가 있어서, 거래가 없는
곳도 이름과 좌표를 압니다. 읍·면·동은 **거래가 있는 곳만** 있습니다 —
우리 자료가 실거래에서 나왔기 때문입니다.

거래가 없는 읍·면·동을 그리려면 두 가지가 다 있어야 합니다.

  1. 이름   전국 법정동 명부 (약 2만 곳)
  2. 좌표   그 이름을 지도 어디에 찍을 것인가

**1만 있고 2가 없으면 못 그립니다.** 이름표는 좌표 위에 놓이는 것이라,
명부만으로는 화면에 아무것도 못 올립니다.

## 그래서 무엇을 두드리는가

이 저장소는 레이어 이름을 세 번 틀렸고 공시지가 원천도 추측으로
시작했다가 헛돌았습니다. **받아 보기 전에는 모릅니다.**

  (가) 브이월드 WFS 읍면동 경계 — 이름과 도형이 한 번에 온다.
       이것이 서면 1·2 를 한 길로 끝냅니다. 도형이 오면 중심점을
       계산하면 되고, 지오코딩 할당량을 한 건도 안 씁니다.
  (나) 행정표준코드 API (data.go.kr) — 이름만. 좌표는 따로 구해야 합니다.
  (다) code.go.kr 파일 내려받기 — 이름만. 러너에서 되는지 봅니다.

셋 다 안 되면 사장님이 code.go.kr 에서 파일을 받아 주시는 것이
빠릅니다. 그 판단을 하려고 재는 것입니다.

러너는 미국이라 한국 공공 API 가 막힙니다. 서울 중계기를 거칩니다.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect.http import get_once                      # noqa: E402
from redt.config import relay                               # noqa: E402

SAMPLE_BBOX = "127.0,36.9,127.3,37.1"       # 평택 언저리. 작게 떼어 본다.


def head(text: str) -> None:
    print()
    print("=" * 68)
    print(text)
    print("=" * 68)


def show(resp, n: int = 400) -> None:
    ctype = resp.headers.get("content-type", "")
    body = resp.text[:n].replace("\n", " ")
    print(f"    http={resp.status_code} type={ctype} len={len(resp.content):,}")
    print(f"    {body}")


def probe_wfs() -> None:
    """(가) 브이월드 WFS 읍면동 경계.

    레이어 이름을 맞히지 않고 후보를 다 두드린다. 404 는 '그 이름이
    아니다' 이지 '읍면동 경계가 없다' 가 아니다.
    """
    head("(가) 브이월드 WFS — 읍면동 경계 (이름 + 도형을 한 번에)")
    for layer in ("lt_c_ademd", "LT_C_ADEMD_INFO", "lt_c_ademd_info",
                  "LT_C_ADEMD", "lt_c_adsigg"):
        print(f"  {layer}")
        try:
            resp = get_once("https://api.vworld.kr/req/wfs", {
                "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
                "TYPENAME": layer, "OUTPUT": "application/json",
                "SRSNAME": "EPSG:4326", "BBOX": SAMPLE_BBOX,
                "MAXFEATURES": "3", "key": "PROBE",
            }, timeout=40)
        except Exception as exc:                            # noqa: BLE001
            print(f"    못 불렀습니다: {exc}")
            continue
        show(resp)
        if resp.status_code == 200 and resp.text.lstrip().startswith("{"):
            try:
                got = resp.json()
            except ValueError:
                continue
            feats = got.get("features") or []
            if feats:
                print(f"    ▶ 도형 {len(feats)}개. 첫 칸의 속성:")
                print("      " + json.dumps(feats[0].get("properties", {}),
                                            ensure_ascii=False)[:300])


def probe_stan_regin() -> None:
    """(나) 행정표준코드관리시스템 API (data.go.kr). 이름만 온다."""
    head("(나) 행정표준코드 API — 이름만 (좌표는 따로 구해야 한다)")
    for path in ("1741000/StanReginCd/getStanReginCdList",
                 "1741000/StanReginCd5/getStanReginCdList"):
        print(f"  {path}")
        try:
            resp = get_once(f"https://apis.data.go.kr/{path}", {
                "type": "json", "numOfRows": "3", "pageNo": "1",
                "flag": "Y", "locatadd_nm": "평택시",
            }, timeout=40)
        except Exception as exc:                            # noqa: BLE001
            print(f"    못 불렀습니다: {exc}")
            continue
        show(resp)


def probe_code_go_kr() -> None:
    """(다) code.go.kr 파일. 러너에서 곧장 받아지는가."""
    head("(다) code.go.kr — 법정동코드 전체자료 내려받기")
    for url in ("https://www.code.go.kr/stdcode/regCodeL.do",
                "https://www.code.go.kr/etc/codeList.do"):
        print(f"  {url}")
        try:
            resp = get_once(url, {}, timeout=40)
        except Exception as exc:                            # noqa: BLE001
            print(f"    못 불렀습니다: {exc}")
            continue
        show(resp, 200)


def main() -> int:
    print("중계기:", "켜짐" if relay().enabled else "꺼짐 (직접 부릅니다)")
    probe_wfs()
    probe_stan_regin()
    probe_code_go_kr()
    head("읽는 법")
    print("""
  (가)가 서면 그것 하나로 끝납니다 — 이름과 좌표가 같이 오고
      지오코딩 할당량을 안 씁니다. 이 길로 갑니다.

  (가)가 안 서고 (나)나 (다)가 서면 이름만 얻습니다. 좌표는
      브이월드 지오코더로 따로 구해야 하는데 하루 할당량이 걸려
      며칠이 듭니다.

  셋 다 안 서면 사장님이 code.go.kr 에서 '법정동코드 전체자료' 를
      받아 주시는 편이 빠릅니다. 그래도 좌표 문제는 남습니다.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
