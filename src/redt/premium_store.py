"""프리미엄 자료 올리기 — Supabase Storage 비공개 버킷 'premium'.

격차율 표(valuation.json)와 표준지 조각(stdland-NNNNN.json)은 여기에만 둔다.
공개 저장소·Vercel·CDN 에는 싣지 않는다 (docs/membership-grades.md §4).
내려받기는 버킷 정책(premium_ok)이 막고, 올리기는 service_role 키로만 된다 —
키는 환경변수 SUPABASE_SERVICE_KEY 로만 받는다 (appraisal_db 와 같은 규칙).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import appraisal_db as _adb
from .config import PROCESSED

BUCKET = "premium"
PREMIUM_DIR = PROCESSED / "premium"          # 러너 캐시에 남는다 — 내보내기가 여기 쓴다


def configured() -> bool:
    return _adb.configured()


def upload(path: Path, name: str | None = None, tries: int = 4) -> bool:
    """파일 하나를 버킷에 (덮어쓰기). 성공이면 True.

    연결이 끊기면(reset · timeout) 2·4·8초 뒤 다시 시도한다 — run 15 에서
    한 번의 ConnectionResetError 가 sync 전체를 멈추고 valuation.json 도 안
    올라갔다. 끝까지 안 되면 False 를 돌려주고, 나머지 파일은 계속 올린다.
    """
    import time
    import requests
    name = name or path.name
    key = os.environ["SUPABASE_SERVICE_KEY"]
    body = path.read_bytes()
    for i in range(tries):
        try:
            r = requests.post(f"{_adb.base_url()}/storage/v1/object/{BUCKET}/{name}",
                              data=body,
                              headers={"apikey": key, "Authorization": f"Bearer {key}",
                                       "Content-Type": "application/json", "x-upsert": "true"},
                              timeout=120)
        except requests.RequestException as exc:
            if i + 1 < tries:
                time.sleep(2 ** (i + 1))
                continue
            print(f"  ! {name}: {type(exc).__name__} ({tries}번 시도)", file=sys.stderr)
            return False
        if r.status_code in (200, 201):
            return True
        if r.status_code >= 500 and i + 1 < tries:     # 서버 쪽 일시 오류도 다시
            time.sleep(2 ** (i + 1))
            continue
        print(f"  ! {name}: HTTP {r.status_code} {r.text[:120]}", file=sys.stderr)
        return False
    return False


def sync(src: Path | None = None, patterns: tuple[str, ...] = ("valuation.json", "stdland-*.json")) -> dict:
    """폴더의 프리미엄 파일을 전부 올린다. 키가 없으면 올리지 않고 그렇게 말한다."""
    src = src or PREMIUM_DIR
    files = [p for pat in patterns for p in sorted(src.glob(pat))]
    if not files:
        print(f"  프리미엄 파일이 없습니다 — {src}")
        return {"files": 0, "uploaded": 0, "skipped": "no-files"}
    if not configured():
        print(f"  SUPABASE_SERVICE_KEY 가 없어 프리미엄 {len(files)}개를 올리지 않았습니다 (버킷 {BUCKET})")
        return {"files": len(files), "uploaded": 0, "skipped": "no-key"}
    ok = sum(1 for p in files if upload(p))
    total = sum(p.stat().st_size for p in files)
    print(f"  프리미엄 버킷 {BUCKET}: {ok}/{len(files)}개 올림 · {total / 1e6:,.1f}MB"
          + ("" if ok == len(files) else f" — {len(files) - ok}개 실패, 다음 내보내기에서 다시 올라갑니다"))
    return {"files": len(files), "uploaded": ok, "failed": len(files) - ok, "bytes": total}
