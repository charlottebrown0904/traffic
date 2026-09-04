"""결과물이 **이번 실행에서** 만들어졌는지 본다.

왜 필요한가
-----------
분석 단계는 대부분 continue-on-error 다. 한 단계가 죽어도 수집 결과는
지키려는 것인데, 그 대가로 **실패가 초록으로 덮인다.**

run 27 이 그랬다. 세 가설 판정이 KeyError 로 죽었는데 실행은 성공으로
끝났고, 판정 파일은 전 실행 것 그대로 커밋됐다. 사장님이 화면에서 보시는
숫자는 새것처럼 보이지만 몇 시간 전 것이었다.

**낡은 숫자가 새 숫자인 척하는 것이, 아무 숫자도 없는 것보다 나쁘다.**
아무것도 없으면 사람이 알아채지만, 낡은 것은 알아챌 방법이 없다.

그래서 파일 안의 generated_at 을 보고 이번 실행 것인지 확인한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n\n")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--field", default="generated_at")
    ap.add_argument("--max-age-min", type=float, default=180)
    args = ap.parse_args()

    if not os.path.exists(args.path):
        # 한 번도 안 돈 것과 이번에 못 돈 것은 다르다. 없으면 알리되 막지 않는다.
        print(f"::warning::{args.path} 이 없습니다 — 한 번도 안 만들어졌습니다.")
        return 0

    try:
        got = json.load(open(args.path, encoding="utf-8")).get(args.field, "")
        made = datetime.fromisoformat(str(got))
    except (ValueError, json.JSONDecodeError, AttributeError) as exc:
        print(f"::warning::{args.path} 의 {args.field} 를 못 읽었습니다: {exc}")
        return 0

    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - made).total_seconds() / 60
    if age > args.max_age_min:
        print(f"::error::{args.path} 이 이번 실행에서 안 만들어졌습니다 "
              f"({got}, {age:.0f}분 전).")
        summary(f"### ⛔ {args.path} 가 갱신되지 않았습니다\n"
                f"생성 시각이 `{got}` ({age:.0f}분 전)입니다. "
                "앞 단계가 조용히 실패했다는 뜻이고, 커밋되는 것은 "
                "**이전 실행 결과**입니다.")
        return 1

    print(f"{args.path} 갱신 확인 ({got}, {age:.0f}분 전)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
