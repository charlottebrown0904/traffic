"""한도 초과가 '주소 없음' 으로 둔갑하지 않는지 검사한다.

브이월드는 실패를 status 로 구분해서 준다.

  OK          찾았다
  NOT_FOUND   그런 주소가 없다          ← 캐시에 남겨도 된다
  ERROR       한도 초과·인증 오류·장애   ← 우리 문제다

예전 코드는 셋을 다 (None, None) 으로 만들고, 그 실패를 캐시에 NULL 로
적었다. 하루 한도에 걸리는 순간 남은 주소가 전부 '좌표 없는 주소' 로
**영구 기록**되고, 한도가 풀려도 다시 물어보지 않는다. 로그에는
'실패 N건' 이라고만 남아 '시골 지번은 원래 안 붙는구나' 로 읽힌다.

지오코딩은 이 프로젝트에서 가장 비싼 자원이라, 이 오염은 되돌리기도
어렵다. 캐시를 지우면 멀쩡한 것까지 다시 사야 한다.
"""
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt.collect import geocode as gc      # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


class FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def json(self):
        if self._p is None:
            raise ValueError("not json")
        return self._p


def serve(*payloads):
    """호출마다 정해진 응답을 돌려주는 가짜 브이월드."""
    seq = list(payloads)
    calls = []

    def _get(url, params):
        calls.append(params.get("address"))
        return FakeResp(seq[min(len(calls) - 1, len(seq) - 1)])
    return _get, calls


OK_BODY = {"response": {"status": "OK",
                        "result": {"point": {"x": "127.1", "y": "37.1"}}}}
NOT_FOUND = {"response": {"status": "NOT_FOUND"}}
OVER_LIMIT = {"response": {"status": "ERROR",
                           "error": {"code": "OVER_LIMIT",
                                     "text": "일일 요청 건수 초과"}}}

gc.keys = lambda: type("K", (), {"require": staticmethod(lambda n: "k")})()
gc.polite_sleep = lambda *a, **k: None


print("1. 세 가지 응답을 구분한다")
gc.get, _ = serve(OK_BODY)
check(gc.geocode_one("주소") == (37.1, 127.1), "OK 는 좌표를 준다")

gc.get, _ = serve(NOT_FOUND)
check(gc.geocode_one("주소") == (None, None), "NOT_FOUND 는 (None, None)")

gc.get, _ = serve(OVER_LIMIT)
try:
    gc.geocode_one("주소")
    check(False, "한도 초과는 예외를 던진다")
except gc.QuotaExhausted as exc:
    check("OVER_LIMIT" in str(exc) and "초과" in str(exc),
          f"한도 초과는 예외를 던지고 사유를 담는다 ({exc})")

gc.get, _ = serve(None)          # JSON 이 아닌 응답
try:
    gc.geocode_one("주소")
    check(False, "JSON 이 아니면 예외를 던진다")
except gc.QuotaExhausted:
    check(True, "JSON 이 아닌 응답도 시스템 오류로 다룬다")


def fresh_cache():
    return gc.GeocodeCache(pathlib.Path(tempfile.mkdtemp()) / "c.jsonl")


print()
print("2. 한도에 걸리면 멈춘다 — 남은 주소를 오염시키지 않는다")
rows = [("41111", "가", f"{i}-1") for i in range(10)]
# 3건 성공한 뒤 한도 초과
gc.get, calls = serve(OK_BODY, OK_BODY, OK_BODY, OVER_LIMIT)
cache = fresh_cache()
got = gc.geocode_many(rows, cache=cache)
check(len(got) == 3, f"성공한 3건만 돌려준다 (받은 값: {len(got)})")
check(len(cache) == 3,
      f"캐시에도 3건만 있다 — 나머지는 안 건드린다 (받은 값: {len(cache)})")
check(len(calls) == 4, f"한도에 걸린 즉시 멈춘다 (호출 {len(calls)}회)")

print()
print("3. 다음 실행이 남은 것을 그대로 이어받는다")
gc.get, calls2 = serve(OK_BODY)
got2 = gc.geocode_many(rows, cache=cache)
check(len(got2) == 10, f"이번엔 10건 다 나온다 (받은 값: {len(got2)})")
check(len(calls2) == 7, f"이미 받은 3건은 다시 안 부른다 (호출 {len(calls2)}회)")

print()
print("4. NOT_FOUND 는 캐시에 남겨 다시 안 부른다")
gc.get, calls3 = serve(NOT_FOUND)
cache2 = fresh_cache()
gc.geocode_many(rows[:2], cache=cache2)
before = len(calls3)
gc.geocode_many(rows[:2], cache=cache2)
check(len(calls3) == before,
      "진짜로 없는 주소는 재시도하지 않는다 (호출이 안 늘어남)")

print()
print("5. 2단계 지오코딩도 같다")
gc.get, calls4 = serve(OK_BODY, OVER_LIMIT)
cache3 = fresh_cache()
pairs = [("41111", f"동{i}") for i in range(5)]
umd = gc.geocode_umd(pairs, cache=cache3)
check(len(umd) == 1, f"법정동 루프도 한도에서 멈춘다 (받은 값: {len(umd)})")
check(len(cache3) == 1, f"캐시 오염 없음 (받은 값: {len(cache3)})")

gc.get, _ = serve(OK_BODY, OVER_LIMIT)
cache4 = fresh_cache()
parcels = gc.geocode_parcel(rows[:5], cache=cache4)
check(len(parcels) == 1, f"지번 루프도 한도에서 멈춘다 (받은 값: {len(parcels)})")
check(len(cache4) == 1, f"캐시 오염 없음 (받은 값: {len(cache4)})")

print()
print("6. 한도 소진이 파이프라인 전체를 세우지 않는다")

# run 19 가 2분 만에 죽었습니다. doctor 가 브이월드 한도 초과를 '막힌
# 항목' 으로 세고 exit 1 을 냈고, 그 뒤 단계가 전부 skipped 됐습니다.
#
#   공장 남은 16,060셀 수집   ← 실거래 API 는 멀쩡했다
#   거래 ↔ 영업소 공간 조인   ← 지오코딩과 무관
#   분석 패널 · 탄력성 · DiD  ← 무관
#   화면용 JSON 생성          ← 무관
#
# 넷 중 어느 것도 지오코딩을 쓰지 않는데 하나도 못 했습니다. 하루 한도는
# 자정에 저절로 풀리는 것이지 고쳐야 할 고장이 아닙니다. 막힌 것과
# 기다리면 되는 것을 갈라야 합니다.
from redt import doctor as dr                                   # noqa: E402

# 검사 환경에는 키가 없어서 doctor 가 앞에서 '건너뜀' 으로 빠진다.
# 그러면 정작 보고 싶은 갈래를 한 줄도 안 탄다.
class _Keys:
    vworld = "TESTKEY"
dr.keys = lambda: _Keys()

dr._fail.clear(); dr._warn.clear()
gc.get, _ = serve(OVER_LIMIT)
dr._check_vworld()
check(not dr._fail, f"한도 초과는 '막힌 항목' 이 아니다 (막힘 {dr._fail})")
check(len(dr._warn) == 1, f"대신 경고로 남는다 (경고 {dr._warn})")

# 다른 실패까지 같이 눈감으면 안 된다 — 키가 틀린 것은 기다려도 안 풀린다.
dr._fail.clear(); dr._warn.clear()
def _boom(*a, **k):
    raise RuntimeError("키가 승인되지 않았습니다")
gc.get = _boom
dr._check_vworld()
check(len(dr._fail) == 1,
      f"한도 말고 진짜 실패는 그대로 막는다 (막힘 {dr._fail})")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
