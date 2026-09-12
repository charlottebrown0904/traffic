"""배포 전 public/ 정합성 검사.

두 번 크게 물린 곳을 고정한다.
  1. trailingSlash:false 라 /guide, /app 은 뒤 슬래시 없이 열린다. 상대경로를 쓰면
     브라우저가 한 단계 위에서 찾아 CSS·스크립트·링크가 전부 404 가 된다.
  2. .vercelignore 는 gitignore 문법이라 앞에 / 가 없으면 깊이를 가리지 않는다.
     'data/' 한 줄이 public/app/data/ 까지 배포에서 제외시켰다.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
REF = re.compile(r'(?:href|src)="([^"]+)"')
REQUIRED_DATA = ["meta.json", "series.json", "tollgates.json", "trades.json",
                 "traffic.json"]

fail = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        fail.append(msg)


def resolves(url: str) -> bool:
    rel = url.lstrip("/").split("#")[0].split("?")[0]
    if not rel:
        return (PUBLIC / "index.html").is_file()
    return any(
        p.is_file()
        for p in (PUBLIC / rel, PUBLIC / (rel + ".html"), PUBLIC / rel / "index.html")
    )


print("1. 상대경로 없음 (뒤 슬래시 없이 열려도 깨지지 않아야 한다)")
for html in sorted(PUBLIC.rglob("*.html")):
    rels = [
        u
        for u in REF.findall(html.read_text(encoding="utf-8"))
        if not u.startswith(("/", "http://", "https://", "//", "#", "data:", "mailto:"))
    ]
    check(not rels, f"{html.relative_to(ROOT)} 상대경로 {len(rels)}개 {rels[:3]}")

print("2. 절대경로 링크가 실제 파일로 연결된다")
for html in sorted(PUBLIC.rglob("*.html")):
    dead = [
        u
        for u in REF.findall(html.read_text(encoding="utf-8"))
        if u.startswith("/") and not u.startswith("//") and not resolves(u)
    ]
    check(not dead, f"{html.relative_to(ROOT)} 깨진 링크 {dead}")

print("3. .vercelignore 가 public/ 을 제외하지 않는다")
for i, raw in enumerate((ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines(), 1):
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    check(
        line.startswith("/") or line.startswith("*"),
        f".vercelignore:{i} '{line}' — 앞에 / 를 붙여 최상위로 한정할 것",
    )

print("4. 모든 페이지에 아이콘·manifest 가 걸려 있다")
BRAND = [
    '<link rel="icon" href="/favicon.ico"',
    '<link rel="icon" href="/favicon.svg"',
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
    '<link rel="manifest" href="/site.webmanifest">',
    '<meta name="theme-color"',
]
for html in sorted(PUBLIC.rglob("*.html")):
    text = html.read_text(encoding="utf-8")
    missing = [tag for tag in BRAND if tag not in text]
    check(not missing, f"{html.relative_to(ROOT)} 빠진 태그 {missing}")
for name in ("favicon.ico", "favicon.svg", "icon.svg", "apple-touch-icon.png",
             "site.webmanifest", "brand/icon-192.png", "brand/icon-512.png",
             "brand/icon-maskable-512.png"):
    check((PUBLIC / name).is_file(), f"public/{name}")

print("5. 앱 데이터 파일이 존재한다")
for name in REQUIRED_DATA:
    check((PUBLIC / "app" / "data" / name).is_file(), f"public/app/data/{name}")

print()
print("화면 데이터가 **브라우저 기준으로** 올바른 JSON인가")

# 파이썬 json 은 기본으로 NaN·Infinity 를 읽고 씁니다. 브라우저의
# JSON.parse 는 거부합니다. 그래서 파일은 멀쩡해 보이고 파이썬 검사도
# 통과하는데 화면만 죽습니다.
#
# run 21 이 정확히 그랬습니다. 명부에서 영업소 119곳을 새로 등재했는데
# 그중 41곳이 시도·시군구를 아직 모릅니다(좌표를 못 받아 지역을 못
# 되짚었습니다). 그 NaN 이 traffic.json 에 실려 파일이 JSON 이 아니게
# 됐고, 배포된 화면의 순위 탭이 통째로 꺼졌습니다.
#
# 그래서 이 검사는 **엄격 모드**로 읽습니다 — 브라우저와 같은 기준입니다.
import json as _json                                            # noqa: E402
from pathlib import Path as _Path                               # noqa: E402


def _strict(text):
    """NaN·Infinity 를 만나면 터진다 (브라우저와 같은 동작)."""
    def boom(c):
        raise ValueError(f"JSON 이 아닌 값: {c}")
    return _json.loads(text, parse_constant=boom)


_web = _Path(__file__).resolve().parents[1] / "public" / "app" / "data"
_files = sorted(_web.glob("*.json"))
check(len(_files) >= 5, f"화면 데이터가 있다 ({len(_files)}개)")
for _f in _files:
    try:
        _strict(_f.read_text(encoding="utf-8"))
        check(True, f"{_f.name} 이 브라우저가 읽을 수 있는 JSON 이다")
    except ValueError as exc:
        check(False, f"{_f.name} 이 브라우저가 읽을 수 있는 JSON 이다 — {exc}")

# 내보내기가 NaN 을 만나면 조용히 흘려보내지 않는지. 벽이 실제로 서 있는지
# 확인하는 것이라, 되짚어 실패하는 것까지 봐야 의미가 있습니다.
import math as _math                                            # noqa: E402
from redt import webexport as _wx                               # noqa: E402

_clean = _wx._finite({"a": _math.nan, "b": [1.0, _math.inf], "c": {"d": -_math.inf}})
check(_clean == {"a": None, "b": [1.0, None], "c": {"d": None}},
      f"NaN·Infinity 를 None 으로 바꾼다 ({_clean})")
check(_wx._text(_math.nan) == "" and _wx._text("경기도") == "경기도",
      "NaN 은 참이라 `or` 를 통과한다 — 문자열인지 직접 본다")

# ── 화면이 '이 값의 기준' 을 말할 수 있어야 한다 ────────────────────
#
# 요구사항(2026-09-09): "IC 선택 시 나오는 반경 내 토지 가격은 현재
# 지도에서 보이는 필터 내용이 아니라 3종 토지 가격임을 명기".
#
# 지도의 땅값 글자는 켜 놓은 용도지역을 따르고, IC 반경 추이는
# settings.yaml 의 land_use_filter 로 고정돼 있다. 같은 화면에 기준이
# 다른 두 값이 있으니 화면이 그것을 말해야 하는데, 말하려면 그 목록이
# 내보내기에 실려 있어야 한다. **화면에 손으로 적어 두면 설정을 고친
# 날 조용히 거짓말이 된다.**
from redt.config import settings as _settings               # noqa: E402
import inspect as _inspect                                  # noqa: E402

_src = _inspect.getsource(_wx.export)
check('"land_use_filter"' in _src,
      "내보내기가 meta 에 land_use_filter 를 싣는다")
check(bool(_settings().get("land_use_filter")),
      f"설정에 분석 용도지역이 있다 — {_settings().get('land_use_filter')}")

# ── 거래가 없는 지자체도 지도에 남는가 ────────────────────────────
#
# 보고된 문제(2026-09-09): 대전에서 유성구·대덕구만 보이고 동구·중구·
# 서구가 통째로 사라졌다. 화면 쪽은 이제 값이 없어도 태그를 그리는데,
# 그러려면 내보내기가 **'거래 0건' 과 '다섯 건이 안 됨' 을 갈라** 줘야
# 한다. 둘에 똑같이 0 을 적으면 세 건 있던 곳을 없던 곳이라 말하게 된다.
class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


_few = _wx._landprice_cell(
    _Row(n_y3=3, p50_y3=100.0, avg_y3=100.0, from_y3=2023), with_few=True)
check(_few.get("few", {}).get("y3") == 3,
      f"다섯 건이 안 되는 창의 건수를 싣는다 — {_few}")
check("y3" not in _few,
      "그래도 값(중앙값)은 안 싣는다 — 다섯 건으로는 못 쓴다")

_none = _wx._landprice_cell(
    _Row(n_y3=0, p50_y3=None, avg_y3=None, from_y3=None), with_few=True)
check("few" not in _none and not _none,
      f"거래가 0건이면 few 도 없다 (없는 것은 없는 것이다) — {_none}")

_plain = _wx._landprice_cell(
    _Row(n_y3=3, p50_y3=100.0, avg_y3=100.0, from_y3=2023))
check(not _plain,
      "읍·면·동 조각은 예전 그대로다 (수만 칸에 한 칸을 더하지 않는다)")

# ── 이름이 안 오는 시군구 ─────────────────────────────────────────
#
# 세종특별자치시는 시도 아래에 시군구가 없어 실거래 응답의 시군구명이
# 빈 채로 온다. 그래서 지도에 '36110' 이 찍혔다.
_fill = _wx._region_name_fill()
check(_fill.get("36110", {}).get("name"),
      f"이름이 안 오는 코드의 대체 이름이 있다 — {_fill.get('36110')}")
check(_fill.get("36110", {}).get("sido") == "세종특별자치시",
      "시·도 축척에서 묶을 이름도 있다")
_ps = _inspect.getsource(_wx._regions)
check("got_name = _text(c.name)" in _ps and 'spare.get("name")' in _ps,
      "자료에 이름이 있으면 그것이 이긴다 (덮어쓰지 않는다)")

# ── 첫 화면 '왜 교통량인가' ────────────────────────────────────────
#
# 회의 합의점(2026-09-12): "그 검증 과정은 사용자에게 의미 없다. 왜
# 교통량을 봐야 하는지를 초보도 납득하게 첫 화면에서 설명해야 한다.
# 지역별 가격-교통량 추이 사례 몇 개 + 신뢰 수치를 간단히 노출."
#
# 그림과 숫자는 scripts/build_why.py 가 자료에서 계산해 표시(marker) 사이에
# 박아 넣는다. **손으로 고치면 자료와 화면이 갈라진다.** 그래서 이 검사는
# 화면에 적힌 숫자가 지금 why-traffic.json 과 같은지 본다 — 자료를 새로
# 뽑고 build_why.py 를 안 돌린 날 여기서 걸린다.
import json as _json

_land = (PUBLIC / "index.html").read_text(encoding="utf-8")
_why = _json.loads((PUBLIC / "app" / "data" / "why-traffic.json")
                   .read_text(encoding="utf-8"))

check("<!-- why:start -->" in _land and "<!-- why:end -->" in _land,
      "첫 화면에 생성 구간 표시가 있다 (build_why.py 가 갈아 끼우는 자리)")

_gen = _land.split("<!-- why:start -->", 1)[1].split("<!-- why:end -->", 1)[0]

check(_gen.count("<figure class=\"why-fig\"") == len(_why["cases"]) == 3,
      f"사례 그림이 자료와 같은 수다 — {len(_why['cases'])}개")
for _c in _why["cases"]:
    check(f"{_c['sigungu']} {_c['name']}" in _gen,
          f"{_c['sigungu']} {_c['name']} 가 화면에 있다")
    check("%+.1f%%" % _c["price_cagr"] in _gen,
          f"{_c['name']} 의 가격 상승률이 자료와 같다 ({_c['price_cagr']:+.1f}%)")

_tr = _why["trust"]
check(f"{round(_tr['trades'] / 10000):,}만 건" in _gen,
      f"신뢰 수치가 자료에서 온다 — 실거래 {round(_tr['trades'] / 10000):,}만 건")
check(f"{_tr['tollgates']:,}곳" in _gen and
      f"{_tr['year_min']}~{_tr['year_max']}년" in _gen,
      "영업소 수와 수집 기간도 자료에서 온다")

# 축은 하나여야 한다 — 단위가 다른 두 계열을 한 그림에 올리는 유일한 길이
# 지수화다. 지수 기준이 100 이 아니면 두 축 그래프를 그린 것이다.
check(all(c["traffic"][0][1] == 100.0 and c["price"][0][1] == 100.0
          for c in _why["cases"]),
      "두 계열 모두 첫 해 = 100 지수다 (축 두 개짜리 그래프가 아니다)")

# 계열이 둘이면 범례는 항상 있고, 색만으로 구분하게 두지 않는다.
check('class="why-legend"' in _gen and _gen.count("why-end") >= 6,
      "범례가 있고 끝점에 계열 이름을 직접 적는다")
check('class="why-table"' in _gen,
      "표로도 읽을 수 있다 (색을 못 읽는 사람 몫)")

# 고른 사례의 분모. 상위 셋만 보여 주고 "다 이렇습니다" 로 두면 광고가 된다.
_pool = _why["pool"]
check(f"{_pool['n']}곳 중 {_pool['negative']}곳" in _gen,
      f"모든 자리가 그렇지 않다고 분모를 적는다 — {_pool['n']}곳 중 {_pool['negative']}곳")
check(_pool["negative"] > 0 and _pool["n"] > len(_why["cases"]),
      "분모가 사례 수보다 크고, 따라오지 않은 자리가 실제로 있다")

# 상관을 인과로 말하지 않는다. 이 한 줄이 빠지면 광고가 된다.
check("증명은 아닙니다" in _gen,
      "같이 움직였다는 것이 원인의 증명이 아니라고 적혀 있다")
check("2~4km" in _land and "정점" in _land,
      "가까울수록 좋다는 뜻이 아니라는 단서가 있다")
check("58.6%" in _land and "61.6%" in _land and "국토연구원" in _land,
      "IC 10km 안 공단 입지 비율의 출처가 적혀 있다")

# 계열 색은 dataviz 검산기를 통과한 값이다. 눈으로 바꾸지 못하게 못을 박는다.
for _hex in ("#2563C9", "#C2740B", "#4A8AD0", "#B07E33"):
    check(_hex in _land, f"검산 통과한 계열 색 {_hex} 가 그대로다")


print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
