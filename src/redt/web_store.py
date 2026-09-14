"""화면 데이터 올리기 — Supabase Storage **공개** 버킷 'appdata'.

## 왜 옮기는가

`public/app/data` 가 64MB 이고 그것이 Vercel 배포 하나(65MB)의 **98%** 다.
Vercel 은 배포를 지우지 않으므로 푸시마다 64MB 가 쌓이고, 그래서 저장
한도(10GB)를 넘겨 **배포가 막혔다** (docs/vercel-limits.md).

같은 파일을 버킷에 두면 배포가 **1.5MB** 가 된다 — 43분의 1이다. 그리고
세 한도가 한꺼번에 내려간다: Deployment Storage · Fast Origin Transfer
(그 파일을 지금 Vercel 이 내보내고 있다) · Edge Requests.

## 공개 버킷인 까닭

이 자료는 이미 toji.fyi 에서 누구나 받던 것이다. 옮긴다고 새로 열리는
것이 없다. **프리미엄 자료는 여기 섞지 않는다** — 격차율 표와 표준지
조각은 그대로 비공개 버킷 'premium' 에 있다 (premium_store.py).

올리기는 service_role 키로만 된다. 키는 환경변수 SUPABASE_SERVICE_KEY
로만 받는다 — 코드에도 로그에도 안 적는다.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from . import appraisal_db as _adb

BUCKET = "appdata"
# 배포에 남길 것. 이 셋은 작고, 화면이 **가장 먼저** 읽는 것이라 버킷이
# 잠깐 흔들려도 화면이 뜨는 편이 낫다.
KEEP_LOCAL = ("meta.json",)


def configured() -> bool:
    return _adb.configured()


def public_base() -> str:
    """브라우저가 받을 주소. 열쇠가 필요 없다 (공개 버킷)."""
    return f"{_adb.base_url()}/storage/v1/object/public/{BUCKET}"


def upload(path: Path, name: str | None = None, tries: int = 4) -> bool:
    """파일 하나를 버킷에 (덮어쓰기). premium_store 와 같은 규칙이다."""
    import requests
    name = name or path.name
    key = os.environ["SUPABASE_SERVICE_KEY"]
    body = path.read_bytes()
    for i in range(tries):
        try:
            r = requests.post(
                f"{_adb.base_url()}/storage/v1/object/{BUCKET}/{name}",
                data=body,
                headers={"apikey": key, "Authorization": f"Bearer {key}",
                         "Content-Type": "application/json",
                         # 한 달. 파일이 바뀌면 이름이 아니라 내용이 바뀌므로
                         # 화면은 meta.json 의 판 번호로 새것을 알아챈다.
                         "Cache-Control": "public, max-age=3600",
                         "x-upsert": "true"},
                timeout=180)
        except requests.RequestException as exc:
            if i + 1 < tries:
                time.sleep(2 ** (i + 1))
                continue
            print(f"  ! {name}: {type(exc).__name__} ({tries}번 시도)", file=sys.stderr)
            return False
        if r.status_code in (200, 201):
            return True
        if r.status_code >= 500 and i + 1 < tries:
            time.sleep(2 ** (i + 1))
            continue
        print(f"  ! {name}: HTTP {r.status_code} {r.text[:120]}", file=sys.stderr)
        return False
    return False


def sync(src: Path, log=print) -> dict:
    """폴더의 *.json 을 통째로 올린다. 무엇을 올렸는지 센다."""
    files = sorted(p for p in src.glob("*.json") if p.is_file())
    st = {"ok": 0, "fail": 0, "bytes": 0, "n": len(files)}
    if not configured():
        log("  Supabase 설정이 없습니다 — 올리지 않습니다")
        return st
    for p in files:
        if upload(p):
            st["ok"] += 1
            st["bytes"] += p.stat().st_size
        else:
            st["fail"] += 1
    log(f"  버킷 {BUCKET}: {st['ok']}/{st['n']}개 · {st['bytes'] / 1e6:,.1f}MB"
        + (f" · 실패 {st['fail']}" if st["fail"] else ""))
    return st


def verify(names: tuple[str, ...], log=print) -> bool:
    """올린 것을 **공개 주소로 다시 받아 본다.**

    올리기가 200 을 줬다는 것과 브라우저가 받을 수 있다는 것은 다른 말이다.
    버킷이 비공개로 남아 있거나 경로가 틀리면 올리기는 멀쩡한데 화면만
    빈다. 그 둘을 가르려면 **열쇠 없이** 받아 봐야 한다.
    """
    import requests
    base = public_base()
    ok = True
    for n in names:
        try:
            # 열쇠를 일부러 안 붙인다 — 브라우저와 같은 자리에서 본다.
            r = requests.get(f"{base}/{n}", timeout=60)
        except requests.RequestException as exc:
            log(f"  ✗ {n}: {type(exc).__name__}")
            ok = False
            continue
        size = len(r.content)
        if r.status_code == 200 and size > 0:
            log(f"  ✓ {n}: {size / 1000:,.0f}KB")
        else:
            log(f"  ✗ {n}: HTTP {r.status_code} · {size}B · {r.text[:80]}")
            ok = False
    return ok
