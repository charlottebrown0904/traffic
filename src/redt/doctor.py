"""수집 전 점검 — 무엇이 막혀 있는지 한 번에 알려준다.

키를 넣고 처음 돌릴 때, '왜 안 되는지'를 스택트레이스가 아니라 문장으로 본다.
키 값 자체는 절대 출력하지 않는다 (길이만 표시).
"""
from __future__ import annotations

import datetime as dt
import importlib
import sys

from .config import DB_PATH, PROCESSED, ROOT, keys, relay
from .scrub import scrub as _scrub

PACKAGES = [
    ("requests", "API 호출"),
    ("pandas", "표 처리"),
    ("duckdb", "분석 DB"),
    ("pyarrow", "parquet 저장"),
    ("yaml", "설정 파일"),
    ("dotenv", "키 로딩"),
    ("tenacity", "재시도"),
]

_fail: list[str] = []
_warn: list[str] = []

# 중계기가 그 주소에 없으면 3·4·5 절이 똑같은 404 를 세 번 토한다. 원인은
# 하나인데 실패가 셋이면 읽는 사람이 무엇을 고쳐야 할지 못 고른다.
# 한 번 판정해서 여기 적어 두고, 아래 실호출들은 건너뛴다.
_relay_dead = False

def _say(ok: bool | None, label: str, hint: str = "") -> None:
    mark = "  ok   " if ok else ("  --   " if ok is None else "  FAIL ")
    print(mark + label + (f"\n         → {_scrub(hint)}" if hint and not ok else ""))
    if ok is False:
        _fail.append(label)
    elif ok is None:
        _warn.append(label)


def _recent_ym(months_back: int = 2) -> str:
    """RTMS 는 신고 지연이 있어 최근 달은 비어 있다. 2개월 전을 쓴다."""
    today = dt.date.today()
    y, m = today.year, today.month - months_back
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def _check_packages() -> None:
    print("\n1. 파이썬 패키지")
    for name, why in PACKAGES:
        try:
            importlib.import_module(name)
            _say(True, f"{name} ({why})")
        except ImportError:
            _say(False, f"{name} ({why})", "pip install -r requirements.txt")


def _relay_alive() -> tuple[bool | None, str]:
    """중계기가 그 주소에 실제로 살아 있는지 한 번 두드린다.

    target 없이 부르면 살아 있는 중계기는 400('target 파라미터가 없습니다')
    을 준다. **404 는 중계기가 대답한 것이 아니라 그 주소에 아무것도 없다는
    뜻이다** — Vercel 주소를 바꾸면 이렇게 된다. run 58~60 이 그것이었다:
    실거래가·브이월드·도로공사 세 줄이 모두 404 였고, 셋 다 같은 원인이었다.
    """
    import requests

    cfg = relay()
    try:
        r = requests.get(f"{cfg.url}/api/relay",
                         headers={"x-relay-token": cfg.token}, timeout=15)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"
    if r.status_code == 404:
        return False, ("그 주소에 중계기가 없습니다 (404). Vercel 주소를 "
                       "바꾸셨다면 GitHub Secrets 의 REDT_RELAY_URL 도 "
                       "새 주소로 바꾸셔야 합니다.")
    if r.status_code == 401:
        return False, "토큰이 거절됐습니다 (401) — REDT_RELAY_TOKEN 을 확인하세요"
    if r.status_code == 400:
        return True, ""          # target 이 없다고 나무란다 = 살아 있다
    return None, f"뜻밖의 응답 {r.status_code} — 중계기 배포를 확인하세요"


def _skip_if_relay_dead() -> bool:
    if _relay_dead:
        _say(None, "건너뜀 — 중계기가 응답하지 않습니다 (2절 참고)")
        return True
    return False


def _check_keys() -> None:
    """키는 config/.env 로도, 환경변수로도 들어온다 (Codespaces Secrets 등).
    파일이 없다고 실패시키면 안 된다 — 값이 있는지만 본다."""
    env = ROOT / "config" / ".env"
    source = "config/.env" if env.exists() else "환경변수"
    cfg = relay()
    if cfg.enabled:
        print("\n2. API 키  (서울 중계기 경유 — 키는 중계기 쪽에 있습니다)")
        _say(True, f"중계기 {cfg.url}/api/relay")
        ok, why = _relay_alive()
        _say(ok, "중계기 응답", why)
        if ok is False:
            global _relay_dead
            _relay_dead = True
        return
    print(f"\n2. API 키  (읽은 곳: {source})")
    if not env.exists():
        _say(None, "config/.env 파일 없음",
             "환경변수로 넣으셨다면 정상입니다. 아니면 "
             "cp config/.env.example config/.env 로 만드세요")

    k = keys()
    for attr, label, need in [
        ("data_go_kr", "DATA_GO_KR_KEY  실거래가", True),
        ("vworld", "VWORLD_KEY      지오코딩·개별공시지가", True),
        ("ex", "EX_API_KEY      교통량", False),
    ]:
        value = getattr(k, attr)
        if value:
            _say(True, f"{label}  ({len(value)}자)")
        elif need:
            _say(False, f"{label}  (비어 있음)",
                 "config/.env 에 넣거나 환경변수로 지정하세요")
        else:
            _say(None, f"{label}  (비어 있음)", "선택 항목 — 없어도 수집은 진행됩니다")


def _check_rtms() -> None:
    print("\n3. 실거래가 API 실호출 (평택시 · 토지 · 최근 확정월)")
    if not keys().data_go_kr and not relay().enabled:
        _say(None, "건너뜀 — 키 없음")
        return
    if _skip_if_relay_dead():
        return
    try:
        from .collect.rtms import fetch_page
        ym = _recent_ym()
        rows, total = fetch_page("land", "41220", ym, page=1, rows=5)
        if total == 0:
            _say(None, f"{ym} 응답 0건",
                 "키는 유효하나 해당 월 데이터가 없습니다. 시군구 코드를 "
                 "`redt regions --verify` 로 확인하세요")
        else:
            _say(True, f"{ym} 총 {total}건 · 표본 {len(rows)}건 파싱")
    except Exception as exc:
        _say(False, "실거래가 API 호출 실패", f"{type(exc).__name__}: {str(exc)[:200]}")


def _check_vworld() -> None:
    print("\n4. VWorld 지오코딩 실호출")
    if not keys().vworld and not relay().enabled:
        _say(None, "건너뜀 — 키 없음")
        return
    if _skip_if_relay_dead():
        return
    try:
        from .collect.geocode import geocode_one, QuotaExhausted
        lat, lon = geocode_one("경기도 성남시 분당구 판교역로 235", kind="ROAD")
        if lat and lon:
            _say(True, f"좌표 회신 ({lat:.5f}, {lon:.5f})")
        else:
            _say(False, "좌표 없음",
                 "키 승인 상태와 등록 도메인을 VWorld 마이페이지에서 확인하세요")
    except QuotaExhausted as exc:
        # **하루 한도를 다 쓴 것은 고장이 아니다.**
        #
        # run 19 가 여기서 통째로 멈췄다. 2분 만에 죽고 공장 16,060셀도,
        # 조인도, 패널도, 화면 갱신도 하나도 못 했다. 그 넷 중 어느 것도
        # 지오코딩을 쓰지 않는다.
        #
        # 하루 한도는 자정에 저절로 풀린다. 그 사이에 못 할 일과 할 수
        # 있는 일을 갈라야지, 하나가 막혔다고 전부 세우면 안 된다.
        # 지오코딩 단계는 자기가 알아서 멈추고(QuotaExhausted 를 잡는다)
        # 남은 것을 다음 실행에 넘긴다.
        _say(None, "지오코딩 한도 소진 — 오늘은 좌표를 못 붙입니다",
             f"{str(exc)[:160]}\n"
             "         나머지 단계(수집·조인·분석·화면)는 그대로 진행합니다. "
             "한도는 자정에 풀립니다.")
    except Exception as exc:
        _say(False, "VWorld 호출 실패", f"{type(exc).__name__}: {str(exc)[:200]}")


def _check_ex() -> None:
    print("\n5. 도로공사 API 실호출 (영업소 마스터)")
    if not keys().ex and not relay().enabled:
        _say(None, "건너뜀 — 키 없음")
        return
    if _skip_if_relay_dead():
        return
    try:
        from .collect.tollgate import fetch_tollgates
        df = fetch_tollgates(rows_per_page=10, max_pages=1)
        _say(len(df) > 0, f"영업소 {len(df)}건 회신",
             "키는 통과했으나 행이 비었습니다. `redt probe-ex` 로 엔드포인트를 확인하세요")
    except Exception as exc:
        _say(False, "도로공사 API 호출 실패", f"{type(exc).__name__}: {str(exc)[:200]}")


def _check_storage() -> None:
    print("\n6. 저장 경로")
    try:
        PROCESSED.mkdir(parents=True, exist_ok=True)
        probe = PROCESSED / ".doctor"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _say(True, f"쓰기 가능 — {PROCESSED.relative_to(ROOT)}/")
    except Exception as exc:
        _say(False, "쓰기 불가", str(exc)[:200])
        return
    try:
        import duckdb
        duckdb.connect(str(DB_PATH)).close()
        _say(True, f"DuckDB 열기 — {DB_PATH.relative_to(ROOT)}")
    except Exception as exc:
        _say(False, "DuckDB 열기 실패", str(exc)[:200])


def run() -> int:
    print("=" * 60)
    print(" redt doctor — 수집 전 점검")
    print("=" * 60)
    print(f"  python {sys.version.split()[0]}  ·  {ROOT}")
    _check_packages()
    _check_keys()
    _check_rtms()
    _check_vworld()
    _check_ex()
    _check_storage()

    print("\n" + "=" * 60)
    if _fail:
        print(f" 막힌 항목 {len(_fail)}건 — 위 → 표시를 순서대로 해결하세요")
        for item in _fail:
            print(f"   · {item}")
        return 1
    if _warn:
        print(f" 진행 가능 (선택 항목 {len(_warn)}건 미설정)")
        for item in _warn:
            print(f"   · {item}")
        print("\n 다음: make collect")
        return 0
    print(" 전부 통과 — 다음: make collect")
    return 0
