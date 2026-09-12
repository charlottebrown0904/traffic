#!/usr/bin/env python3
"""토지가격비준표(.xls) → 긴 형식 TSV, 그리고 우리 지수표와의 대조.

    PYTHONPATH=src python3 scripts/parse_bijunpyo.py <파일.xls> \
        --sgg 41550 --sgg-name 안성시 --year 2026 --out data/interim/bijunpyo.tsv
    PYTHONPATH=src python3 scripts/parse_bijunpyo.py <파일.xls> --compare

■ 배율의 **방향** — 이것을 틀리면 모든 값이 뒤집힌다

파일에는 방향이 적혀 있지 않다. 표 하나로 확정할 수 있다.

    도로접면 시트에서  행'맹지' × 열'광대한면' = 1.37
                       행'광대한면' × 열'맹지'   = 0.73   (≒ 1/1.37)

맹지가 광대한면보다 비쌀 수는 없다. 그러므로

    **행 = 비교표준지, 열 = 산정 대상 토지, 값 = 곱하는 배율**
    대상 단가 = 표준지 단가 × 표(표준지 항목, 대상 항목)

행이 대상이라고 읽으면 맹지가 광대한면의 1.37배가 되어 버린다. 우리
`valuation.py` 의 지수표는 세로(가)=1.00 기준의 '지수'라 모양이 다르다.
같은 줄로 만들려면 표의 **세로(가) 행**을 꺼내면 된다 (--compare).

■ 파일에 없는 것

시트 이름은 용도지역뿐이고(예: '주거지역'), **시군구와 기준연도가 어디에도
없다.** 파일명도 내부 일련번호(1789231346981)다. 그래서 --sgg·--year 를
필수로 받는다 — 받아 적지 않으면 어느 시군구 표인지 영원히 알 수 없다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sheet_rows(path: Path) -> list[tuple[str, list[list[str]]]]:
    """(시트이름, 행들). .xls 는 xlrd, .xlsx 는 openpyxl 로 읽는다."""
    def clean(v):
        if v is None:
            return ""
        if isinstance(v, float) and v == int(v) and abs(v) >= 1000:
            return str(int(v))
        if isinstance(v, float):
            return f"{v:g}"
        return str(v).strip()

    # **확장자를 믿지 않는다.** 같은 사이트가 .xls 라는 이름으로 세 가지를
    # 내려준다 — 진짜 BIFF8(D0CF11E0), 실은 xlsx(PK), 실은 HTML 표.
    # 확장자로 갈라서 열면 첫 줄에서 죽는다.
    head = path.open("rb").read(8)
    out = []
    if head[:2] == b"PK":
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        for ws in wb.worksheets:
            out.append((ws.title, [[clean(v) for v in r]
                                   for r in ws.iter_rows(values_only=True)]))
        return out
    if head[:4] != b"\xd0\xcf\x11\xe0":
        raise SystemExit(f"{path.name} 은 엑셀이 아닙니다 (앞 8바이트 {head!r}). "
                         "HTML 표로 왔을 수 있습니다 — 브라우저로 먼저 열어 보세요.")
    import xlrd
    wb = xlrd.open_workbook(path)
    for sh in wb.sheets():
        out.append((sh.name, [[clean(v) for v in sh.row_values(r)]
                              for r in range(sh.nrows)]))
    return out


def _num(cell: str):
    if cell in ("", "-", "·"):
        return None
    try:
        return float(cell)
    except ValueError:
        return None


def _trim(row: list[str]) -> list[str]:
    row = list(row)
    while row and row[-1] == "":
        row.pop()
    return row


def blocks(rows: list[list[str]]) -> list[tuple[str, list[str], list[tuple[str, list]]]]:
    """(항목명, 열 라벨, [(행 라벨, 값들)]) 로 자른다.

    파일의 구조는 단순하다 — **빈 줄로 나뉜 덩어리, 각 덩어리의 첫 줄이
    머리 행**이다. 그 규칙 대신 '뒤 칸이 글자면 머리 행' 으로 판별하면 두
    군데서 틀린다.

      · 토지면적 은 열 라벨이 숫자다 (3300 16500 33000 …) → 머리 행을
        놓치고 항목 하나가 통째로 사라진다.
      · 지목표의 광·염·학·도·철 … 처럼 주거지역에 있을 수 없는 지목은
        한 줄이 전부 '-' 다 → 덩어리가 다섯 조각으로 쪼개진다.

    둘 다 실제로 겪었다. 그래서 빈 줄만 본다.
    """
    out, group = [], []
    for raw in list(rows) + [[]]:
        row = _trim(raw)
        if row and row[0]:
            group.append(row)
            continue
        if len(group) >= 2:
            name, cols = group[0][0], group[0][1:]
            body = [(r[0], [_num(c) for c in r[1:len(cols) + 1]]) for r in group[1:]]
            out.append((name, cols, body))
        group = []
    return out


# 우리 지수표와 이름이 맞는 칸 (비준표 글 → valuation.py 표의 열쇠)
ROAD_MAP = {
    "광대한면": "광대", "중로한면": "중로", "소로한면": "소로",
    "세로(가)": "(가)", "세로(불)": "(불)", "맹지": "맹지",
}
SHAPE_MAP = {"정방형": "정방", "가장형": "가장", "세장형": "세장",
             "사다리": "사다리", "부정형": "부정", "자루형": "자루"}
SLOPE_MAP = {"평지": "평지", "완경사": "완경사", "급경사": "급경사",
             "고지": "고지", "저지": "저지"}


def compare(bl, zone: str) -> None:
    """비준표의 기준 행을 우리 지수표와 나란히 찍는다."""
    from redt.valuation import ROAD_INDEX, SHAPE_INDEX, SLOPE_INDEX

    def ours(table, key):
        for k, v in table:
            if k == key:
                return v
        return None

    def line(block_name, base_row, mapping, table, label):
        found = next((b for b in bl if b[0] == block_name), None)
        if not found:
            return
        name, cols, body = found
        row = next((r for r in body if r[0] == base_row), None)
        if row is None:
            return
        print(f"\n[{label}]  비준표 기준행 = {base_row}  ({zone})")
        print(f"{'항목':<10} {'비준표':>7} {'우리':>7} {'차이':>7}")
        for col, val in zip(cols, row[1]):
            key = mapping.get(col)
            if key is None or val is None:
                continue
            mine = ours(table, key)
            gap = "" if mine is None else f"{(val - mine) * 100:+.0f}pp"
            print(f"{col:<10} {val:>7.2f} {'' if mine is None else f'{mine:>7.2f}'} {gap:>7}")

    line("도로접면", "세로(가)", ROAD_MAP, ROAD_INDEX, "도로접면")
    shape_block = "형상(주거.공업)" if "주거" in zone or "공업" in zone else "형상(전,답)"
    line(shape_block, "정방형", SHAPE_MAP, SHAPE_INDEX, "형상")
    line("고저", "평지", SLOPE_MAP, SLOPE_INDEX["*"], "고저·지세")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--sgg", help="시군구 법정동코드 5자리")
    ap.add_argument("--sgg-name", default="")
    ap.add_argument("--year", help="기준연도 (개별공시지가 기준일의 연도)")
    ap.add_argument("--out", type=Path, help="긴 형식 TSV 저장 위치")
    ap.add_argument("--compare", action="store_true",
                    help="우리 지수표와 나란히 찍는다 (저장하지 않음)")
    a = ap.parse_args()

    sheets = sheet_rows(a.path)
    print(f"{a.path.name} — 시트 {len(sheets)}개: {', '.join(n for n, _ in sheets)}")

    all_blocks = []
    for zone, rows in sheets:
        bl = blocks(rows)
        print(f"\n■ {zone} — 항목 {len(bl)}개")
        for name, cols, body in bl:
            print(f"   {name:<16} {len(body):>3}행 × {len(cols):>2}열")
        if a.compare:
            compare(bl, zone)
        all_blocks.append((zone, bl))

    if not a.out:
        return 0
    if not (a.sgg and a.year):
        print("\n--out 을 쓰려면 --sgg 와 --year 가 필요합니다. "
              "파일 안에 시군구·연도가 없어서, 받아 적지 않으면 어느 표인지 알 수 없습니다.",
              file=sys.stderr)
        return 2
    if not re.fullmatch(r"\d{5}", a.sgg):
        print("--sgg 는 시군구 법정동코드 5자리입니다.", file=sys.stderr)
        return 2

    a.out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("sgg_cd\tsgg_nm\tyear\tland_use\titem\tstd\ttarget\tratio\n")
        for zone, bl in all_blocks:
            for name, cols, body in bl:
                for std, vals in body:
                    for col, val in zip(cols, vals):
                        if val is None:
                            continue
                        fh.write(f"{a.sgg}\t{a.sgg_name}\t{a.year}\t{zone}\t"
                                 f"{name}\t{std}\t{col}\t{val:g}\n")
                        n += 1
    print(f"\n{a.out} — {n}행 (행=표준지, 열=대상, 값=곱하는 배율)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
