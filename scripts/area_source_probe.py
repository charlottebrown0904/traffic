"""토지대장 면적을 브이월드 말고 어디서 받을 수 있나 — 원천 탐침.

지시(2026-09-19): "브이월드를 통해 지번을 특정할 수 밖에 없나요?
4천건/일 이면 너무 오래 걸립니다."

## 왜 급한가

지번 추론 엔진이 쓰는 결정타는 **토지대장 면적**이다. 신고 면적은
대장 면적과 같아야 하는 값이라, 같은 리(里) 안에서 면적이 맞는 필지는
드물다. 지금 그 면적을 브이월드 토지특성 WFS(dt_d194)에서 받는다.

  안성시 한 곳         1,232칸
  전국 250 시군구      약 308,000칸
  하루 4,000건이면     **77일**

키를 여러 개 쓰는 우회는 약관 위반이라 안 한다. 그러면 남는 길은
**같은 값을 다른 데서 한 번에 받는 것**이다.

## 무엇을 확인하는가

면적은 브이월드만 갖고 있는 값이 아니다. 개별공시지가는 필지마다
매년 공시되고, 그 자료에 고유번호(PNU)·지목·**면적**이 함께 붙는다.
그것이 파일로 내려받아지면 308,000번이 한 번이 된다.

  1절  포털 상세 화면을 읽어 **주소와 파일**을 찍는다 (추측하지 않는다)
  2절  표준데이터를 **실제로 불러** 칸 이름을 본다 — 면적이 있나
  3절  파일이 있으면 앞부분만 받아 머리글과 크기를 본다
  4절  브이월드 한도를 응답으로 확인한다

2절이 핵심이다. 화면 설명에 '면적' 이 적혀 있어도 API 가 그 칸을 주는지는
불러 봐야 안다. 앞에서 같은 형태로 세 번 틀렸다 — 한쪽에서 본 사실을
다른 쪽에 그대로 적용했다.

  python scripts/area_source_probe.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from redt.collect import http                                # noqa: E402
from redt.collect import indicators as ind                   # noqa: E402
from redt.config import VIA_RELAY                            # noqa: E402

# 면적을 갖고 있을 법한 데이터셋. 번호는 포털 검색으로 확인한 것이고,
# 주소와 칸 이름은 **화면을 읽어서** 뽑는다.
SETS = [
    ("15029071", "standard", "전국개별공시지가정보 표준데이터"),
    ("15052266", "fileData", "국토교통부_개별공시지가정보 (파일)"),
    ("15124014", "openapi", "개별공시지가정보 WMS/WFS/속성정보"),
    ("15004246", "fileData", "표준지공시지가 (파일 · 이미 쓰는 것)"),
]

# 면적으로 볼 만한 칸 이름. 자료마다 다르게 적는다.
AREA_KEYS = ("면적", "lndpclAr", "lndpcl_ar", "ar", "area", "lndAr", "ldAr")
PNU_KEYS = ("고유번호", "pnu", "PNU", "ldCode", "lndpclPnu")


def head(t):
    print(f"\n{t}\n" + "-" * (len(t) + 12))


def main() -> int:
    print("=" * 70)
    print(" 토지대장 면적 — 브이월드 말고 어디서 받을 수 있나")
    print("=" * 70)

    # ── 1. 포털 상세 화면 ──────────────────────────────────────────
    head("1. 포털 상세 화면 — 주소와 파일을 찍는다")
    found = {}
    for ds, kind, label in SETS:
        print(f"\n  [{ds}] {label}")
        try:
            d = ind.detail(ds, kind, timeout=40)
        except Exception as exc:                             # noqa: BLE001
            print(f"    못 읽었습니다 — {type(exc).__name__}: {exc}")
            continue
        if d.get("error"):
            print(f"    못 읽었습니다 — {d['error']}")
            continue
        found[ds] = d
        print(f"    제목 {d.get('title', '')[:70]}")
        for k in ("endpoints", "uddis", "downloads", "files", "sizes"):
            v = d.get(k) or []
            if v:
                print(f"    {k:<10} {' · '.join(str(x)[:90] for x in v[:4])}")

    # ── 2. 표준데이터를 실제로 불러 본다 ──────────────────────────
    head("2. 표준데이터를 불러 칸 이름을 본다 — 면적이 있나")
    print("  화면 설명에 '면적' 이 적혀 있어도 API 가 그 칸을 주는지는")
    print("  불러 봐야 압니다. 한 쪽에서 본 것을 다른 쪽에 그대로 적용해")
    print("  앞에서 세 번 틀렸습니다.")
    uddis = (found.get("15029071", {}).get("uddis") or [])
    eps = [e for e in (found.get("15029071", {}).get("endpoints") or [])
           if "odcloud" in e or "data.go.kr" in e]
    print(f"\n  찾은 uddi {len(uddis)}개 · 주소 {len(eps)}개")
    tried = []
    for u in uddis[:3]:
        url = f"https://api.odcloud.kr/api/15029071/v1/{u}"
        tried.append(url)
    for e in eps[:3]:
        url = e if e.startswith("http") else "https://" + e
        if url not in tried:
            tried.append(url)
    if not tried:
        print("  부를 주소를 못 찾았습니다 — 1절 발췌를 보고 손으로 채웁니다.")
    for url in tried:
        print(f"\n  → {url}")
        try:
            body = http.get_json(url, {"serviceKey": VIA_RELAY,
                                       "page": 1, "perPage": 3}, timeout=60)
        except Exception as exc:                             # noqa: BLE001
            print(f"    실패 — {type(exc).__name__}: {str(exc)[:160]}")
            continue
        rows = (body or {}).get("data") or []
        if not rows:
            print(f"    행이 없습니다 — {json.dumps(body, ensure_ascii=False)[:220]}")
            continue
        keys = list(rows[0].keys())
        print(f"    총 {body.get('totalCount', '?')}행 · 칸 {len(keys)}개")
        print(f"    {' · '.join(keys)}")
        area = [k for k in keys if any(a in k for a in AREA_KEYS)]
        pnu = [k for k in keys if any(a in k for a in PNU_KEYS)]
        print(f"    면적으로 보이는 칸  {area or '없음'}")
        print(f"    PNU 로 보이는 칸    {pnu or '없음'}")
        if area and pnu:
            print("    ★ 이 원천이면 브이월드 없이 면적을 채울 수 있습니다.")
        print(f"    첫 행 {json.dumps(rows[0], ensure_ascii=False)[:300]}")

    # ── 3. 파일이 있으면 앞부분만 ─────────────────────────────────
    head("3. 파일 — 머리글과 크기")
    for ds in ("15052266", "15004246"):
        d = found.get(ds) or {}
        links = d.get("downloads") or []
        print(f"\n  [{ds}] 내려받기 링크 {len(links)}개 · 파일 "
              f"{' · '.join((d.get('files') or [])[:3]) or '—'}")
        for ln in links[:2]:
            url = "https://www.data.go.kr/" + ln.lstrip("/")
            print(f"    → {url[:140]}")
            try:
                r = http.get_once(url, {}, timeout=60)
            except Exception as exc:                         # noqa: BLE001
                print(f"      실패 — {type(exc).__name__}: {str(exc)[:140]}")
                continue
            ct = r.headers.get("content-type", "")
            cl = r.headers.get("content-length", "?")
            print(f"      {r.status_code} · {ct[:60]} · {cl} bytes")
            blob = r.content[:400]
            try:
                print(f"      머리 {blob.decode('utf-8', 'replace')[:220]!r}")
            except Exception:                                # noqa: BLE001
                print(f"      머리(바이트) {blob[:60]!r}")

    # ── 4. 브이월드 한도 ──────────────────────────────────────────
    head("4. 브이월드 — 한도가 실제로 무엇이라고 답하나")
    print("  숫자를 문서에서 옮겨 적지 않고 응답에서 읽습니다.")
    try:
        from redt.collect import landchar as lc
        pace = lc._Pace(lc._cfg()["calls_per_sec"])
        feats, split = lc.fetch_tile((127.20, 37.00, 127.21, 37.01), pace)
        print(f"  한 칸 불러 필지 {len(feats)}개 (쪼갬 {split})")
        print("  거절 메시지가 없으면 지금은 한도 안입니다.")
    except Exception as exc:                                 # noqa: BLE001
        print(f"  실패 — {type(exc).__name__}: {str(exc)[:200]}")

    head("정리")
    print("""  면적을 파일이나 표준데이터로 한 번에 받을 수 있으면 브이월드
  308,000칸이 통째로 없어집니다. 2절에 ★ 가 찍혔으면 그 길로 갑니다.
  아무것도 안 나오면 브이월드로 가되 **순서**를 정해 돕니다.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
