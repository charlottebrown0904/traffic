"""OSM 선형 스냅 — 그물이 제 일을 하는지 본다 (네트워크 없이).

**왜 이 검사가 생겼나.** osm_geom 에서 `snap` 이 통째로 빠진 채 올라간
적이 있다(손질하다 파일 끝을 잘라 먹었다). 문법은 멀쩡했고, 러너가
남한 전체 선형 24,449조각을 2분에 걸쳐 받은 **뒤에야** AttributeError
로 죽었다. 있어야 할 함수가 있는지는 여기서 1초에 판정한다.

나머지는 그물이다. 틀린 선형은 직선보다 나쁘므로, 연장과 안 맞는 경로는
**좌표를 안 내야** 한다.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import osm_geom as OG                                  # noqa: E402

FAIL = 0


def check(name, ok, note=""):
    global FAIL
    print(f"  {'통과' if ok else '실패'}  {name}" + (f" — {note}" if note else ""))
    if not ok:
        FAIL += 1


def main() -> None:
    print("OSM 선형 스냅\n")

    # 1. 있어야 할 것이 있나 — 잘려 나간 적이 있다.
    need = ("fetch", "build_routes", "snap", "simplify", "route_key", "km")
    missing = [n for n in need if not hasattr(OG, n)]
    check("공개 함수가 다 있다", not missing, f"없는 것 {missing or '없음'}")

    # 2. 이름 모으기 — '경부선'(도로공사)과 '경부고속도로'(OSM)가 만나야 한다
    check("'경부선' 과 '경부고속도로' 가 같은 열쇠가 된다",
          OG.route_key("경부선") == OG.route_key("경부고속도로") == "경부",
          f"{OG.route_key('경부선')} / {OG.route_key('경부고속도로')}")

    # 3. 조각을 꿰매 경로가 나오나. 0.01도 ≈ 1.11km 짜리 세 조각을 잇는다.
    ways = [
        {"key": "시험", "name": "시험고속도로", "ref": "9", "building": False,
         "pts": [(36.00, 127.00), (36.01, 127.00)]},
        {"key": "시험", "name": "시험고속도로", "ref": "9", "building": False,
         "pts": [(36.01, 127.00), (36.02, 127.00)]},
        {"key": "시험", "name": "시험고속도로", "ref": "9", "building": False,
         "pts": [(36.02, 127.00), (36.03, 127.00)]},
    ]
    routes = OG.build_routes(ways)
    full = OG.km((36.00, 127.00), (36.03, 127.00))
    path, res = OG.snap(routes, "시험선", (36.00, 127.00), (36.03, 127.00), full)
    check("조각 셋을 한 경로로 꿴다", bool(path) and len(path) >= 2,
          f"꼭짓점 {len(path) if path else 0}개 · 비 {res}")

    # 4. **그물.** 고시 연장이 경로의 절반이면 엉뚱한 길을 따라간 것이다.
    bad, why = OG.snap(routes, "시험선", (36.00, 127.00), (36.03, 127.00),
                       full / 3)
    check("연장과 안 맞으면 좌표를 안 낸다", bad is None, f"→ {why}")

    # 5. 모르는 노선은 조용히 비켜선다 (직선으로 되돌아간다)
    none, why2 = OG.snap(routes, "없는선", (36.0, 127.0), (36.03, 127.0), full)
    check("모르는 노선이면 비켜선다", none is None, f"→ {why2}")

    # 6. 긴 경로에서 스택이 안 넘친다 — 되돌이로 짜면 여기서 터진다
    try:
        n = len(OG.simplify([(i * 1e-5, 0.0) for i in range(20000)]))
        ok = n == 2
    except RecursionError:
        ok, n = False, "RecursionError"
    check("2만 점을 줄여도 스택이 안 넘친다", ok, f"→ {n}점")

    print("\n" + ("모두 통과" if not FAIL else f"실패 {FAIL}건"))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
