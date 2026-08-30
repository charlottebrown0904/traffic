"""internal/tasks.json → internal/PROGRESS.md

plan.html 은 GitHub 웹에서 소스로만 보인다. 같은 데이터를 GitHub 가 렌더링해 주는
마크다운으로 뽑아, 저장소만 열어도 진행률과 다음 할 일이 바로 보이게 한다.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "internal" / "tasks.json"
OUT = ROOT / "internal" / "PROGRESS.md"

MARK = {"done": "x", "doing": " ", "todo": " ", "blocked": " "}
BADGE = {"done": "완료", "doing": "**진행중**", "todo": "대기", "blocked": "**막힘**"}
OWNER = {"user": "사장님", "claude": "Claude", "both": "함께"}
KST = timezone(timedelta(hours=9))


def bar(done: int, total: int, width: int = 20) -> str:
    if not total:
        return "―"
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    phases = data["phases"]
    tasks = [t for p in phases for t in p["tasks"]]
    done = sum(t["status"] == "done" for t in tasks)

    L = [
        "# 진행 현황",
        "",
        "> `internal/tasks.json` 에서 자동 생성됩니다. 이 파일을 직접 고치지 마세요.",
        "> 수정은 `tasks.json` 을 고친 뒤 `make progress` 를 실행합니다.",
        "",
        f"생성 시각 · {datetime.now(KST):%Y-%m-%d %H:%M} KST",
        "",
        f"## 전체 {done} / {len(tasks)} ({done / len(tasks) * 100:.0f}%)",
        "",
        f"`{bar(done, len(tasks))}`",
        "",
        "| 단계 | 목표 | 진행 |",
        "| --- | --- | --- |",
    ]
    for p in phases:
        d = sum(t["status"] == "done" for t in p["tasks"])
        n = len(p["tasks"])
        L.append(f"| **{p['id']}** {p['name']} | {p['goal']} | `{bar(d, n, 10)}` {d}/{n} |")

    now = [t for t in tasks if t["status"] in ("doing", "blocked")]
    mine = [t for t in tasks if t["status"] == "todo" and t["owner"] in ("user", "both")]
    L += ["", "## 지금 움직이는 것", ""]
    if now:
        for t in now:
            L.append(f"- {BADGE[t['status']]} `{t['id']}` {t['title']} — {t.get('note', '')}")
    else:
        L.append("- 없음")
    L += ["", "### 사장님이 하셔야 할 대기 항목", ""]
    for t in mine[:8]:
        L.append(f"- `{t['id']}` {t['title']} — {t.get('note', '')}")
    if len(mine) > 8:
        L.append(f"- … 외 {len(mine) - 8}건")

    L += ["", "---", "", "## 단계별 상세", ""]
    for p in phases:
        d = sum(t["status"] == "done" for t in p["tasks"])
        n = len(p["tasks"])
        L += [f"### {p['id']} · {p['name']}  `{d}/{n}`", "", f"목표 — {p['goal']}", ""]
        for t in p["tasks"]:
            note = f" — {t['note']}" if t.get("note") else ""
            L.append(
                f"- [{MARK[t['status']]}] `{t['id']}` {t['title']} "
                f"·{OWNER[t['owner']]}· {BADGE[t['status']]}{note}"
            )
        L.append("")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}  ({done}/{len(tasks)}, {done / len(tasks) * 100:.0f}%)")


if __name__ == "__main__":
    main()
