"""연속지적도를 대량으로 받아 지오코딩을 끝낼 수 있는가 — 탐침.

요구사항(2026-09-08): "B를 위한 사전 준비내용 알려주고, 탐침해봅시다"

## 무엇을 확인하는가

브이월드 지오코더는 하루 3만~4만 건입니다. 좌표 없는 거래가 329만 건이니
그대로면 100번 가까이 실행해야 합니다. **부르지 않고 계산하는 길**이
있는지를 봅니다.

  실거래 자료  →  법정동코드 + 지번  →  PNU  →  연속지적도 필지  →  중심 좌표

PNU 는 계산으로 나옵니다 (19자리).

    4155025300  1        0123     0004
    법정동코드   산여부   본번     부번
    (10)        (1)      (4)      (4)

  산여부: 일반 1 · 산 2

이 길이 서면 API 호출이 0 이 되고, 덤으로 필지 도형(면적·모양)까지
따라옵니다 — 레이더의 '모양·지세' 축 입력입니다.

## 왜 탐침부터인가

이 저장소는 레이어 이름을 세 번 틀렸고 공시지가 원천도 추측으로
시작했다가 헛돌았습니다. **받아 보기 전에는 모릅니다.**

특히 두 가지가 미지수입니다.

  1. 우리 실거래에는 법정동 **이름**만 있고 코드가 없습니다.
     이름 → 코드 대조표를 어디서 받는가.
  2. 연속지적도를 키 없이·로그인 없이 통째로 받을 수 있는가.
     받을 수 없으면 이 길은 서지 않습니다.

  python scripts/cadastral_probe.py            # 안성시(41550)
  python scripts/cadastral_probe.py 41220      # 평택시
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import duckdb                                               # noqa: E402

from redt.collect.http import get_once                      # noqa: E402
from redt.config import DB_PATH, relay                      # noqa: E402

DEFAULT_SIGUNGU = "41550"        # 안성시 — 필지 특성 실측을 한 곳
SAMPLE = 12

# 연속지적도 원천 후보. **이름을 맞히지 않고 두드려 본다.**
#
# 브이월드 WFS 레이어 이름은 공개 문서에 두 가지로 적혀 있다
# (lp_pa_cbnd_bubun / lp_pa_cbnd_bonbun). 둘 다 넣는다 — 하나가 404 면
# 그것이 답이지 '연속지적도가 없다' 는 뜻이 아니다.
WFS = "https://api.vworld.kr/req/wfs"
DATA_API = "https://api.vworld.kr/req/data"

WFS_LAYERS = ["lp_pa_cbnd_bubun", "lp_pa_cbnd_bonbun", "dt_d194"]

# 시험용 네모 — 안성 시가지. 위경도 0.02도.
#
# 이 크기를 정해 놓아야 '한 번에 몇 필지' 를 면적으로 환산할 수 있다.
# 위도 37도에서 경도 1도는 약 89km, 위도 1도는 약 111km.
BBOX = "127.26,36.99,127.28,37.01"
BOX_KM2 = (0.02 * 89) * (0.02 * 111)     # 약 3.95 km²
LAND_KM2 = 100_400                        # 대한민국 육지 면적
MAXF = 1000

# 통째로 내려받는 길. 중계기 허용목록(api/relay.js 의 ALLOW)에 없는
# 호스트는 미국 러너에서 직접 나가므로 지오블록에 막힐 수 있다.
# **막히는 것도 결과다** — 어디를 중계기에 추가해야 하는지 알려준다.
BULK = [
    ("공공데이터포털 파일데이터 검색",
     "https://www.data.go.kr/tcs/dss/selectDataSetList.do",
     {"keyword": "연속지적도"}),
    ("국가공간정보포털 오픈마켓",
     "https://www.nsdi.go.kr/lxportal/?menuno=2679", {}),
]

# 법정동코드 대조표 후보. 이름→코드가 없으면 PNU 를 못 만든다.
BJD = [
    ("행정표준코드관리시스템 법정동코드 전체자료",
     "https://www.code.go.kr/stdcode/regCodeL.do", {}),
    ("브이월드 행정구역 WFS (읍면동)",
     WFS, {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
           "TYPENAME": "lt_c_ademd", "MAXFEATURES": "3",
           "OUTPUT": "application/json",
           # **도형을 빼고 묻는다.** 지난 탐침은 읍면동 3건에 9.5MB 를
           # 받았다 — 우리가 원한 것은 코드와 이름 두 칸뿐인데 경계
           # 폴리곤이 통째로 딸려왔다. 전국 5천 읍면동이면 GB 단위다.
           "PROPERTYNAME": "emd_cd,emd_kor_nm,sgg_oid,col_adm_se"}),
]


def head(n: str) -> None:
    print()
    print(n)
    print("-" * len(n))


def shape(resp) -> str:
    """무엇이 왔는지 한 줄로. 본문을 통째로 찍으면 키가 섞여 나온다."""
    ct = (resp.headers.get("content-type") or "?").split(";")[0]
    body = resp.text or ""
    peek = re.sub(r"\s+", " ", body[:120])
    return f"{resp.status_code} · {ct} · {len(body):,}B · {peek}"


def feats(resp) -> tuple[int, list[dict]]:
    """FeatureCollection 이면 몇 개가 왔는지. 아니면 (0, [])."""
    try:
        d = resp.json()
    except Exception:
        return 0, []
    fs = d.get("features") or []
    return len(fs), [f.get("properties") or {} for f in fs[:3]]


def pnu(bjd10: str, jibun: str) -> str | None:
    """법정동코드 10 + 산여부 1 + 본번 4 + 부번 4.

    지번은 '123-4' · '산 45' · '123' 세 모양이 온다. 그 밖의 것은
    **만들지 않는다** — 틀린 PNU 는 엉뚱한 필지를 가리키고, 그것은
    좌표가 없는 것보다 나쁘다.
    """
    if not (bjd10 and len(bjd10) == 10 and jibun):
        return None
    s = jibun.strip()
    mount = "2" if s.startswith("산") else "1"
    s = s.lstrip("산").strip()
    m = re.fullmatch(r"(\d{1,4})(?:-(\d{1,4}))?", s)
    if not m:
        return None
    bon, bu = m.group(1), m.group(2) or "0"
    return f"{bjd10}{mount}{int(bon):04d}{int(bu):04d}"


def main() -> int:
    sigungu = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SIGUNGU
    print("=" * 68)
    print(f" 연속지적도 탐침 — 시군구 {sigungu}")
    print("=" * 68)
    print(f"  중계기 {'경유' if relay().enabled else '없음 (직접 호출)'}")

    # ── 1. 우리가 이미 가진 것 ──────────────────────────────────────
    #
    # PNU 를 만들려면 지번이 파싱돼야 한다. 실제 값을 보지 않고
    # 정규식을 짜면 '산 45-1' 같은 것에서 조용히 깨진다.
    head("1. 우리 실거래의 지번은 어떻게 생겼는가")
    rows, total, ok = [], 0, 0
    if DB_PATH.exists():
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            rows = con.execute(
                "SELECT umd, jibun FROM trade WHERE sigungu_cd = ? "
                "AND jibun IS NOT NULL LIMIT ?", [sigungu, SAMPLE]).fetchall()
            total, ok = con.execute(
                "SELECT count(*), count(*) FILTER (WHERE "
                "  regexp_matches(trim(replace(jibun,'산','')), "
                "                 '^[0-9]{1,4}(-[0-9]{1,4})?$')) "
                "FROM trade WHERE jibun IS NOT NULL").fetchone()
        except Exception as exc:
            print(f"  DB 를 못 읽었습니다: {type(exc).__name__}: {exc}")
        finally:
            con.close()
    else:
        print(f"  {DB_PATH} 가 없습니다 (러너에서 캐시 복원 뒤 도십시오)")

    # 좌표를 어느 단위로 붙였는지. 이 숫자가 곧 한도 상향 신청서의
    # 근거가 된다 — "필지 단위로 올려야 할 양" 이 몇 건인지.
    if DB_PATH.exists():
        con = duckdb.connect(str(DB_PATH), read_only=True)
        try:
            print("  좌표 단위별 거래 수 (전국)")
            for lvl, n in con.execute(
                    "SELECT coalesce(geocode_level,'(좌표 없음)'), count(*) "
                    "FROM trade GROUP BY 1 ORDER BY 2 DESC").fetchall():
                print(f"    {lvl:<12} {n:>12,}")
        except Exception as exc:
            print(f"  좌표 단위를 못 셌습니다: {type(exc).__name__}: {exc}")
        finally:
            con.close()
        print()

    for umd, jibun in rows:
        made = pnu("0" * 10, jibun)
        tail = made[10:] if made else "— 못 만듦"
        print(f"  {umd:<10} {jibun:<12} → 산·본·부 {tail}")
    if total:
        print(f"\n  전국 지번 {total:,}건 중 파싱되는 것 {ok:,}건 "
              f"({ok / total:.1%})")
        print("  → 나머지는 PNU 를 못 만듭니다. 그만큼은 지오코더가 필요합니다.")

    # ── 2. 법정동 이름 → 코드 ───────────────────────────────────────
    head("2. 법정동코드 대조표를 어디서 받는가")
    print("  우리 거래에는 법정동 **이름**만 있습니다. PNU 앞 10자리를")
    print("  만들려면 시군구코드(5) + 읍면동(3) + 리(2) 코드가 필요합니다.")
    for name, url, params in BJD:
        try:
            resp = get_once(url, params)
            n, sample = feats(resp)
            print(f"  · {name}\n      {shape(resp)}")
            if n:
                print(f"      기록 {n}건. 첫 건의 칸 이름: "
                      f"{', '.join(list(sample[0])[:8])}")
        except Exception as exc:
            print(f"  · {name}\n      막힘 — {type(exc).__name__}: {str(exc)[:120]}")

    # ── 3. 연속지적도 자체 ──────────────────────────────────────────
    head("3. 연속지적도 — API 한 번에 몇 필지가 오는가")
    print("  '한 필지씩' 이 아니라 **네모 하나에 든 필지 전부**가 옵니다.")
    print("  그래서 이 숫자가 곧 필요한 호출 수를 정합니다.\n")
    key = os.environ.get("VWORLD_KEY", "")
    for layer in WFS_LAYERS:
        params = {"SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
                  "TYPENAME": layer, "MAXFEATURES": str(MAXF),
                  "OUTPUT": "application/json", "SRSNAME": "EPSG:4326",
                  "BBOX": BBOX}
        if key:
            params["key"] = key
        try:
            resp = get_once(WFS, params, timeout=60)
            n, sample = feats(resp)
            print(f"  · {layer}\n      {shape(resp)}")
            if n:
                per_km2 = n / BOX_KM2
                print(f"      필지 {n:,}건 / {BOX_KM2:.1f}km² "
                      f"= {per_km2:,.0f}필지/km²")
                if n >= MAXF:
                    print(f"      ⚠ MAXFEATURES({MAXF})에 걸렸습니다 — "
                          f"실제로는 더 있습니다. 네모를 잘게 쪼개야 합니다.")
                print(f"      전국 육지 {LAND_KM2:,}km² 를 이 크기로 덮으면 "
                      f"약 {int(LAND_KM2 / BOX_KM2):,}번")
                print(f"      첫 건의 칸 이름: "
                      f"{', '.join(list(sample[0])[:10])}")
        except Exception as exc:
            print(f"  · {layer}\n      막힘 — {type(exc).__name__}: {str(exc)[:120]}")

    head("4. 연속지적도 — 통째로 내려받기")
    print("  이쪽이 서야 호출 0 이 됩니다. API 로 한 필지씩이면 결국")
    print("  같은 한도에 다시 묶입니다.")
    for name, url, params in BULK:
        try:
            print(f"  · {name}\n      {shape(get_once(url, params))}")
        except Exception as exc:
            print(f"  · {name}\n      막힘 — {type(exc).__name__}: {str(exc)[:120]}")

    print()
    print("=" * 68)
    print(" 읽는 법")
    print("=" * 68)
    print("  1절 파싱률이 낮으면  → 지번 정규식을 고쳐야 합니다.")
    print("  2절이 다 막히면      → PNU 를 못 만듭니다. B 는 여기서 끝납니다.")
    print("  3절만 되고 4절이 막히면 → 호출 0 은 못 하고, 한도 안에서")
    print("                            필지 도형만 얻는 절충이 남습니다.")
    print("  4절이 되면           → 지오코딩 병목이 사라집니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
