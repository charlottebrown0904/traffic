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
OWNER = {"user": "사람", "claude": "Claude", "both": "함께"}
KST = timezone(timedelta(hours=9))


def bar(done: int, total: int, width: int = 20) -> str:
    if not total:
        return "―"
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)



def _keys_section(data: dict) -> list[str]:
    """발급이 필요한 키와, 그 키로 열어야 하는 데이터셋을 한 표로."""
    keys = data.get("keys") or []
    if not keys:
        return []
    total = len(keys) + sum(len(k.get("datasets", [])) for k in keys)
    got = sum(k["status"] == "done" for k in keys) + sum(
        ds["status"] == "done" for k in keys for ds in k.get("datasets", [])
    )
    L = [
        "",
        "---",
        "",
        "## 데이터 소스 ↔ 어느 키를 쓰는가",
        "",
        "> data.go.kr 에 **목록만** 있고 실제 발급·호출은 제공기관 포털 키를 쓰는 것이 있습니다.",
        "> 개별공시지가와 영업소 위치정보가 그렇습니다. 아래 표의 `키` 열이 기준입니다.",
        "",
        "| 데이터 | 제공기관 | 신청 포털 | 쓰는 키 | 비고 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in data.get("source_map", []):
        L.append(
            f"| {m['source']} | {m['provider']} | `{m['portal']}` "
            f"| **{m['key']}** | {m['note']} |"
        )
    L += [
        "",
        f"## 발급이 필요한 API 키  `{got}/{total}`",
        "",
        f"`{bar(got, total)}`",
        "",
        "> 키 값 자체는 채팅에 붙이지 마세요. `config/.env` 에 넣고 `make doctor` 출력만 보내주시면 됩니다.",
        "> (`.env` 는 gitignore 되어 커밋되지 않고, doctor 출력의 키는 `***` 로 가려집니다.)",
        "",
    ]
    for k in keys:
        mark = "x" if k["status"] == "done" else " "
        L += [
            f"### [{mark}] {k['id']} · `{k['env']}` — {k['name']}",
            "",
            f"- **필요도** {k['need']}  ·  **소요** {k['lead']}  ·  **포털** {k['portal']}",
            f"- **왜** {k['why']}",
            f"- **주의** {k['note']}",
        ]
        if k.get("datasets"):
            L += [
                "",
                "| | 데이터셋 | 번호 | 이 프로젝트에서 | 필요도 |",
                "| --- | --- | --- | --- | --- |",
            ]
            for ds in k["datasets"]:
                m = "x" if ds["status"] == "done" else " "
                L.append(
                    f"| [{m}] | [{ds['name']}]({ds['url']}) | `{ds['id']}` "
                    f"| {ds['use']} | {ds['prio']} |"
                )
        L.append("")

    nokey = data.get("nokey") or []
    if nokey:
        L += ["### 키가 필요 없는 것 (신청하지 마세요)", "",
              "| 자료 | 이 프로젝트에서 | 받는 법 |", "| --- | --- | --- |"]
        for n in nokey:
            name = f"[{n['name']}]({n['url']})" if n["url"] else n["name"]
            L.append(f"| {name} | {n['use']} | {n['how']} |")
        L.append("")
    return L


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
    L += ["", "### 사람이 해야 할 대기 항목", ""]
    for t in mine[:8]:
        L.append(f"- `{t['id']}` {t['title']} — {t.get('note', '')}")
    if len(mine) > 8:
        L.append(f"- … 외 {len(mine) - 8}건")

    L += _keys_section(data)

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
