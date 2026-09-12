"""감정평가 인자 DB — 비공개 Supabase 에서 읽는다.

## 왜 저장소 밖인가

평가서 52건에서 뽑은 격차율(어느 조건에서 표준지 대비 몇 배를 줬나)은
쌓일수록 값이 오르는 우리 노하우다. 2026-09-11 지시: "이 데이터 베이스는
외부에서 볼 수 없게 해야함". 저장소는 공개라 파일로 두면 누구나 본다.

그래서 표는 Supabase 의 두 표에 있다. RLS 가 켜져 있고 익명·인증 정책이
없어 **service key 로만 읽힌다.** 화면(브라우저)은 이 표를 직접 못 보고,
러너가 내보낸 **집계값**(용도지역군 × 지목군별 중앙값·사분위·건수)만
valuation.json 으로 받는다 — 개별 평가서 한 건의 숫자는 밖으로 안 나간다.

  appraisal_case    평가서 한 건 = 한 행. 열은 예전 원장(ledger.tsv)과 같다.
                    사람 이름 열은 없다 (소유자·채무자는 애초에 안 옮겼다).
  appraisal_factor  평가서 × 조건. 가로·접근·환경·자연·획지·행정적·기타.
                    ratio 가 표준지 대비 배율, why 가 평가사가 적은 사유.

## 읽는 순서

  1. SUPABASE_URL + SUPABASE_SERVICE_KEY 가 있으면 REST 로 (러너·서버)
  2. 없으면 data/private/ledger.tsv — gitignored 손 사본 (개발자 컨테이너)
  3. 둘 다 없으면 빈 목록. 호출자는 '자료 없음' 으로 다룬다 — 1.00 으로
     메우지 않는다 (valuation.decide_other).

키는 환경변수로만 받는다. 코드·설정 파일·로그에 적지 않는다.
"""
from __future__ import annotations

import csv
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_LEDGER = ROOT / "data" / "private" / "ledger.tsv"
PAGE = 1000
# 프로젝트 주소는 비밀이 아니다 (브라우저에도 실린다). 시크릿 SUPABASE_URL 에
# 키를 넣는 실수가 있어(run 15: 주소 자리에 sb_publishable_… 가 들어왔다)
# 주소가 주소꼴이 아니면 이것을 쓴다.
DEFAULT_URL = "https://caykbxvnebpifcduqjre.supabase.co"


def base_url() -> str:
    raw = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    if not raw or raw.startswith(("sb_", "eyJ")) or "." not in raw:
        return DEFAULT_URL
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw


def key_kind() -> str:
    k = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if k.startswith("sb_publishable_") or k.startswith("sb_p"):
        return "publishable"
    if k.startswith("sb_secret_"):
        return "secret"
    if k.startswith("eyJ"):
        return "legacy-jwt"
    return "unknown"

_cache: dict[str, list[dict]] = {}


def configured() -> bool:
    return bool(os.environ.get("SUPABASE_SERVICE_KEY"))


def source() -> str:
    """무엇을 읽었는지 한 줄 — 로그와 valuation.json 에 적는다."""
    if configured():
        return "supabase"
    if PRIVATE_LEDGER.exists():
        return "private-file"
    return "none"


def _headers() -> dict:
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}


def _rest(table: str, select: str = "*") -> list[dict]:
    """PostgREST 로 표 하나를 끝까지 읽는다 (Range 로 쪽을 넘긴다)."""
    import requests
    base = base_url()
    if key_kind() == "publishable":
        raise RuntimeError("SUPABASE_SERVICE_KEY 에 publishable 키가 들어 있습니다 — RLS 때문에 아무것도 못 읽습니다. "
                           "service_role(eyJ…) 또는 sb_secret_… 키여야 합니다")
    out: list[dict] = []
    start = 0
    while True:
        h = dict(_headers())
        h["Range-Unit"] = "items"
        h["Range"] = f"{start}-{start + PAGE - 1}"
        r = requests.get(f"{base}/rest/v1/{table}", params={"select": select},
                         headers=h, timeout=30)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"supabase {table}: HTTP {r.status_code} {r.text[:200]} (키 종류: {key_kind()})")
        rows = r.json()
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def normalize(rows: list[dict]) -> list[dict]:
    """REST 는 None 을, 파일은 '' 을 준다. 호출자는 문자열 메서드를 바로
    쓰므로 None 을 '' 로 맞춘다. 숫자는 그대로 둔다 (valuation._num 이 푼다)."""
    return [{k: ("" if v is None else v) for k, v in r.items()} for r in rows]


def load_cases() -> list[dict]:
    """평가서 행 — 예전 load_ledger() 와 같은 꼴."""
    if "cases" in _cache:
        return _cache["cases"]
    rows: list[dict] = []
    if configured():
        try:
            rows = normalize(_rest("appraisal_case"))
        except Exception as e:                      # noqa: BLE001 — 원장 없이도 산출은 돈다
            print(f"  ! 비공개 원장을 못 읽었습니다 ({type(e).__name__}: {str(e)[:120]}) — 평가선례 갈래 없이 갑니다",
                  file=sys.stderr)
            rows = []
    elif PRIVATE_LEDGER.exists():
        with open(PRIVATE_LEDGER, encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
    _cache["cases"] = rows
    return rows


def load_factors() -> list[dict]:
    """조건별 격차율 행. 파일 사본에는 없다 (Supabase 에서만)."""
    if "factors" in _cache:
        return _cache["factors"]
    rows = []
    if configured():
        try:
            rows = normalize(_rest("appraisal_factor"))
        except Exception as e:                      # noqa: BLE001
            print(f"  ! appraisal_factor 를 못 읽었습니다 ({type(e).__name__})", file=sys.stderr)
    _cache["factors"] = rows
    return rows


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def factor_summary(rows: list[dict] | None = None) -> dict:
    """조건(group_nm)별 격차율 분포 — 화면·문서용 집계. 개별 건은 안 나간다.

    1차 원장(52건)은 1.00('차이 없음') 을 적지 않았고, 2차(164파일)부터는
    조건마다 1.00 도 적는다. 그래서 eq_1 을 따로 세어 준다 — 1.00 을 뺀
    분포를 보려면 below_1·above_1 만 보면 된다."""
    rows = load_factors() if rows is None else rows
    by: dict[str, list[float]] = {}
    why: dict[str, list[str]] = {}
    for r in rows:
        v = _num(r.get("ratio"))
        g = r.get("group_nm") or ""
        if not v or not g:
            continue
        by.setdefault(g, []).append(v)
        if r.get("why"):
            why.setdefault(g, []).append(str(r["why"]))
    out = {}
    for g, vals in by.items():
        vals.sort()
        n = len(vals)
        out[g] = {"n": n, "median": round(statistics.median(vals), 3),
                  "min": vals[0], "max": vals[-1],
                  "q1": round(vals[n // 4], 3), "q3": round(vals[(3 * n) // 4], 3),
                  "below_1": sum(1 for v in vals if v < 1), "above_1": sum(1 for v in vals if v > 1),
                  "eq_1": sum(1 for v in vals if v == 1),
                  "why": sorted(set(why.get(g, [])))[:12]}
    return out


def clear_cache() -> None:
    _cache.clear()
