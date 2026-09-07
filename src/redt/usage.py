"""공장과 창고를 가른다.

국토교통부 15126470 은 이름 그대로 **'공장 및 창고 등'** 부동산 매매
자료다. 즉 창고는 처음부터 같이 들어오고 있었고, 우리가 그것을 전부
`kind='factory'` 한 칸에 담아 두어 **구분이 보이지 않았을 뿐**이다.

가르는 근거는 응답의 건물주용도(building_use)다. 값이 무엇으로 오는지
문서에 없어서, 여기서는 글자에 '창고' 가 들었는지 '공장' 이 들었는지로
본다. 정확한 문자열을 박아 두면 국토부가 '창고시설' 을 '물류창고' 로
바꾸는 날 조용히 전부 '기타' 가 된다.

**값이 비어 있을 수도 있다.** 그때는 가를 근거가 없으므로 UNKNOWN 으로
두고, 화면에서는 공장 쪽에 넣는다(자료의 이름이 '공장 및 창고 등' 이고
공장이 앞이다). 억지로 한쪽에 몰아넣고 아는 척하지 않는다 —
describe() 가 몇 건이 그런지 매 실행 찍는다.
"""
from __future__ import annotations

FACTORY = "공장"
WAREHOUSE = "창고"
OTHER = "기타"
UNKNOWN = ""          # 건물주용도가 비어 있어 가를 수 없는 것


def _look(text) -> str:
    """글자 하나를 보고 공장/창고/기타/미상."""
    if not isinstance(text, str) or not text.strip():
        return UNKNOWN
    text = text.strip()
    # 창고를 먼저 본다. '공장·창고' 처럼 둘 다 든 값이 오면 창고로 센다 —
    # 창고 표본이 훨씬 적어서, 애매한 것을 공장에 넣으면 작은 쪽이 더
    # 작아지고 결국 아무것도 못 본다.
    if WAREHOUSE in text:
        return WAREHOUSE
    if FACTORY in text:
        return FACTORY
    return OTHER


def label(building_use, jimok=None) -> str:
    """화면에 그대로 쓸 용도 이름.

    **뭉개지 않는다.** 처음에는 공장/창고/기타 셋으로 줄였는데, 실제
    자료(run 33)를 보니 건물주용도가 100% 채워져 오고 값이 딱 7종이었다.

      공장 143,159 · 창고시설 30,833 · 동물 및 식물 관련시설 20,111 ·
      자동차 관련시설 10,829 · 위험물 저장 및 처리시설 7,133 ·
      자원순환 관련시설 1,804 · 운수시설 1,711

    '기타 41,588건' 은 **모르는 것이 아니라 아는 것들**이었다. 축사·온실과
    정비소와 주유소를 한 칸에 넣어 두면, 그 셋을 가려 보려던 사람에게는
    없는 것과 같다. 7종이면 필터에 그대로 늘어놓을 수 있다.

    가를 수 없을 때만 지목으로 넘어간다(지목은 이 자료에 0% 로 안 오지만,
    안 오는 날이 오면 그때 이 줄이 받는다).
    """
    if isinstance(building_use, str) and building_use.strip():
        return building_use.strip()
    if isinstance(jimok, str) and jimok.strip():
        got = _look(jimok)
        if got in (FACTORY, WAREHOUSE):
            return got
    return UNKNOWN


def classify(building_use, jimok=None) -> str:
    """공장 / 창고 / 기타 / 미상 — **색과 묶음**에만 쓴다.

    화면에 적는 이름은 label() 이 준다. 이쪽은 '창고 계열은 황토색' 처럼
    묶어서 다룰 때만 쓴다.

    근거를 **둘** 본다.

      1. 건물주용도 — 건물이 무엇으로 쓰이는가. 이것이 맞는 근거다
      2. 지목 — 땅의 법적 구분. 공장용지·창고용지가 따로 있다

    건물주용도가 비어 있어도 지목이 '창고용지' 면 창고로 볼 수 있다.
    하나만 보면 그 칸이 안 채워져 오는 날 통째로 못 가른다 — 실제로
    이 자료의 어느 칸이 채워져 오는지는 문서에 없어서, describe() 가
    매 실행 어느 쪽이 일을 했는지 찍는다.

    지목을 뒤에 두는 이유. 창고용지에 공장이 서 있을 수 있다. 건물이
    무엇인지 아는 경우에는 그것을 믿는다.
    """
    got = _look(building_use)
    if got in (FACTORY, WAREHOUSE):
        return got
    from_jimok = _look(jimok)
    if from_jimok in (FACTORY, WAREHOUSE):
        return from_jimok
    # 둘 다 가르지 못했다. 하나라도 값이 있었으면 '기타', 아니면 '미상'.
    return OTHER if OTHER in (got, from_jimok) else UNKNOWN


def describe(con) -> None:
    """건물주용도가 실제로 무엇으로 오는지 찍는다.

    이 함수가 이 파일의 핵심이다. 위 classify 는 **추측**이고, 추측이
    맞는지는 실행이 알려준다. 안 찍으면 '창고 0건' 을 보고 '창고 거래가
    없구나' 로 읽게 되는데, 사실은 '가를 칸이 비어 있다' 일 수 있다.
    """
    rows = con.execute("""
        SELECT coalesce(building_use, '') AS use,
               coalesce(jimok, '') AS jimok,
               count(*) AS n
        FROM trade WHERE kind = 'factory'
        GROUP BY 1, 2 ORDER BY n DESC
    """).fetchdf()
    total = int(rows["n"].sum()) if len(rows) else 0
    print(f"\n=== 공장·창고 구분 (kind=factory {total:,}건) ===")
    if not total:
        print("  자료가 없습니다.")
        return

    mix: dict[str, int] = {}
    for r in rows.itertuples(index=False):
        got = classify(r.use, r.jimok)
        mix[got] = mix.get(got, 0) + int(r.n)
    for label in (FACTORY, WAREHOUSE, OTHER, UNKNOWN):
        n = mix.get(label, 0)
        if n:
            name = label or "미상 (가를 칸이 비어 있음)"
            print(f"  {name:<30} {n:>9,}  ({n / total:.1%})")

    # 어느 칸이 실제로 일을 했는가. 이것을 모르면 다음에 못 가르게
    # 됐을 때 어디를 봐야 하는지 알 수 없다.
    filled_use = int(rows.loc[rows["use"] != "", "n"].sum())
    filled_jimok = int(rows.loc[rows["jimok"] != "", "n"].sum())
    print(f"\n  건물주용도가 채워진 것 {filled_use:,} ({filled_use / total:.1%})"
          f" · 지목이 채워진 것 {filled_jimok:,} ({filled_jimok / total:.1%})")

    print("\n  원값 (많은 것부터) — 건물주용도 | 지목 → 판정")
    for r in rows.head(14).itertuples(index=False):
        use = r.use or "(빈 값)"
        jm = r.jimok or "(빈 값)"
        print(f"    {use:<22} | {jm:<12} {int(r.n):>8,}"
              f"  → {classify(r.use, r.jimok) or '미상'}")
    if len(rows) > 14:
        print(f"    … 외 {len(rows) - 14}가지 조합")

    if mix.get(WAREHOUSE, 0) == 0:
        print("\n  ⚠ 창고로 갈린 것이 **한 건도 없습니다.** 화면의 '창고' 칸은")
        print("    0건이 되는데, 그것은 '창고 거래가 없다' 가 아니라")
        print("    '가를 칸이 비어 있다' 일 수 있습니다. 위 원값을 보세요.")


# ────────────────────────────────────────────────────────────────
# 토지 — 개발이 끝났는가
# ────────────────────────────────────────────────────────────────
#
# 사장님 지시(2026-09-07): "토지의 경우 개발 가능 지, 모양, 도로 접등의
# 사유로 가격 변동이 많으니 개발 완료된 물건에 대해서 더 비중을 둡시다."
#
# 자료가 그 말을 그대로 뒷받침한다. 토지 표본의 지목 분포를 보면
#
#   답 736 · 전 625 · 임야 546   → 1,907건(78%) 이 **원지**
#   대 270 · 잡종지 32 · 공장용지 20 · 창고용지 3 → 325건(13%)
#
# 전·답·임야는 같은 동네 같은 해라도 값이 몇 배씩 벌어진다. 개발이
# 될 땅인지, 도로에 붙었는지, 모양이 쓸 만한지가 값을 정하는데 그 셋을
# 우리는 하나도 모른다. 그 잡음이 헤도닉 잔차로 남아 교통량 계수를
# 통째로 덮는다.
#
# 대(垈)·공장용지·창고용지는 이미 개발이 끝났다. 건축이 가능하고
# 도로가 붙어 있는 것이 지목의 전제라, 위 세 가지 불확실성이 훨씬 작다.
#
# **원지를 버리지는 않는다.** 원지 가격도 사장님이 보시려는 것이고,
# 표본의 78% 다. 가르고 무게를 달리한다.

# 개발이 끝난 지목. 건축물이 서 있거나 설 수 있는 상태다.
DEVELOPED_JIMOK = frozenset({
    "대", "공장용지", "창고용지", "학교용지", "주차장", "주유소용지",
    "체육용지", "종교용지", "잡종지",
})

# 원지. 개발 여부·도로접·모양에 따라 값이 몇 배로 벌어진다.
RAW_JIMOK = frozenset({"전", "답", "과수원", "목장용지", "임야", "염전"})

# 그 밖(도로·구거·하천·묘지·철도용지…)은 둘 중 어느 쪽도 아니다.
# 거래가 되기는 하지만 성격이 달라 따로 둔다.

DEVELOPED = "개발완료"
RAW = "원지"
OTHER_LAND = "그 밖"


def land_stage(jimok) -> str:
    """지목 → 개발완료 / 원지 / 그 밖 / 미상.

    지목으로 가르는 이유는 그것이 **실거래 자료에 실제로 있는 유일한
    단서**이기 때문이다. 도로접면과 형상은 실거래 API 가 주지 않는다
    (scripts/land_shape_probe.py 가 확인한다).
    """
    if not isinstance(jimok, str) or not jimok.strip():
        return UNKNOWN
    text = jimok.strip()
    if text in DEVELOPED_JIMOK:
        return DEVELOPED
    if text in RAW_JIMOK:
        return RAW
    return OTHER_LAND


# ────────────────────────────────────────────────────────────────
# 도로 접함 — 토지 값을 정하는 첫 번째 조건
# ────────────────────────────────────────────────────────────────
#
# 사장님 지시(2026-09-07): "부정형이 무조건 좋지 않은 건 아닙니다.
# 도로를 접하는 가가 제일 중요합니다."
#
# 맞는 지적이고, 두 변수를 **다르게 다뤄야 한다**는 뜻이기도 하다.
#
#   형상    부정형·사다리형·세로장방… 은 **순서가 없다.** 부정형이라도
#           넓고 도로에 붙었으면 쓸 수 있고, 반듯해도 맹지면 못 쓴다.
#           그래서 그냥 종류로 두고 더미로 넣는다.
#   도로접  **순서가 있다.** 광대로 > 중로 > 소로 > 세로(가) >
#           세로(불) > 맹지. 도로 폭이 곧 무엇을 지을 수 있는가다.
#
# 순서가 있는 것을 종류로만 넣으면 '맹지가 소로보다 비쌀 수도 있다' 는
# 가능성을 열어 두는 셈이라 계수가 흔들린다. 등급으로 넣는다.
#
# 값은 개별공시지가 토지특성의 도로접면 코드다 (실측으로 확인한 값:
# 세로한면(가) · 맹지 · 소로한면 · 세로한면(불) · 지정되지않음).

# 도로 폭 등급. 클수록 넓은 길에 접한다.
ROAD_GRADE = {
    "광대": 5,     # 광대로한면·광대소각·광대세각 (폭 25m 이상)
    "중로": 4,     # 중로한면·중로각지 (12~25m)
    "소로": 3,     # 소로한면·소로각지 (8~12m)
}
ROAD_NARROW_OK = 2      # 세로(가) — 8m 미만, 자동차 통행 가능
ROAD_NARROW_NO = 1      # 세로(불) — 자동차 통행 불가
ROAD_NONE = 0           # 맹지


def road_grade(road_side) -> int | None:
    """도로접면 → 0(맹지)~5(광대로). 모르면 None.

    '지정되지않음' 은 **0 이 아니다.** 맹지와 같이 두면 도로가 없는 땅과
    조사가 안 된 땅이 한 칸에 섞인다. 모르는 것은 모른다고 둔다.
    """
    if not isinstance(road_side, str) or not road_side.strip():
        return None
    text = road_side.strip()
    if "지정되지" in text or "미상" in text:
        return None
    if "맹지" in text:
        return ROAD_NONE
    for key, grade in ROAD_GRADE.items():
        if key in text:
            return grade
    if "세로" in text or "세각" in text:
        # (가)=자동차 통행 가능, (불)=불가. 이 한 글자가 땅의 쓸모를 가른다 —
        # 차가 못 들어가면 공장도 창고도 못 짓는다.
        if "불" in text:
            return ROAD_NARROW_NO
        return ROAD_NARROW_OK
    return None


def road_car_ok(road_side) -> int | None:
    """자동차가 들어갈 수 있는가. 1/0, 모르면 None.

    등급과 따로 두는 이유. 값이 등급을 따라 고르게 오르지 않고 **여기서
    한 번 크게 꺾인다.** 차가 들어가느냐 마느냐가 건축 가능 여부를
    가르기 때문이다. 등급만 넣으면 그 꺾임이 직선에 묻힌다.
    """
    grade = road_grade(road_side)
    if grade is None:
        return None
    return int(grade >= ROAD_NARROW_OK)


def is_corner(road_side) -> int | None:
    """각지(두 면 이상이 도로에 접함)인가.

    같은 폭이라도 각지는 진출입이 자유롭고 건축 배치가 유리해 값이 다르다.
    """
    if not isinstance(road_side, str) or not road_side.strip():
        return None
    text = road_side.strip()
    if "지정되지" in text:
        return None
    return int("각지" in text or "각" in text and "한면" not in text)
