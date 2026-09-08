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
import threading
import time

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
gc._PACE = gc._Pace(0)          # 검사에서는 속도 상한을 끈다

# 1~7 은 '몇 번째 호출에서 멈추는가' 를 세는 검사라 순서가 정해져야 한다.
# 병렬 자체는 8·9 에서 따로 본다.
_SEQ = {"workers": 1, "calls_per_sec": 0}
gc._geo_cfg = lambda: _SEQ


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
print("6-B. 중계기가 그 주소에 없으면 '404' 셋 대신 그 한 줄을 말한다")

# run 58~60 이 빨갛게 났습니다. 세 줄이 똑같이 404 였습니다 —
#
#   FAIL 실거래가 API 호출 실패  → 404 ... /api/relay?target=apis.data.go.kr...
#   FAIL VWorld 호출 실패        → 404 ... /api/relay?target=api.vworld.kr...
#   FAIL 도로공사 API 호출 실패  → 404 ... /api/relay?target=data.ex.co.kr...
#
# 세 API 가 동시에 죽은 것이 아닙니다. **중계기가 그 주소에 없던 것**입니다.
# 사장님이 Vercel 주소를 바꾸셨는데 REDT_RELAY_URL 은 옛 주소를 가리키고
# 있었습니다. 원인이 하나인데 실패가 셋으로 보이면 무엇을 고쳐야 할지
# 고를 수가 없습니다. 중계기부터 두드리고, 죽었으면 나머지는 건너뜁니다.
import types as _types                                          # noqa: E402

class _Relay:
    url = "https://old-address.example"
    token = "t"
    enabled = True

def _relay_probe(status):
    """requests.get 을 갈아 끼워 중계기 응답만 흉내낸다."""
    import requests as _rq
    real = _rq.get
    _rq.get = lambda *a, **k: _types.SimpleNamespace(status_code=status)
    return real

dr.relay = lambda: _Relay()
dr.keys = lambda: _types.SimpleNamespace(data_go_kr="K", vworld="K", ex="K")

import requests as _rq                                          # noqa: E402
_real_get = _rq.get
try:
    for status, want_fail, word in [
        (404, True, "REDT_RELAY_URL"),
        (401, True, "REDT_RELAY_TOKEN"),
        (400, False, ""),
    ]:
        dr._fail.clear(); dr._warn.clear(); dr._relay_dead = False
        _relay_probe(status)
        dr._check_keys()
        if want_fail:
            check(len(dr._fail) == 1,
                  f"{status} 는 막힌 항목이다 (막힘 {dr._fail})")
            check(dr._relay_dead, f"{status} 뒤에는 중계기를 죽은 것으로 본다")
        else:
            check(not dr._fail, f"400 은 살아 있다는 뜻이다 (막힘 {dr._fail})")
            check(not dr._relay_dead, "400 뒤에는 실호출을 계속한다")

    # 죽었으면 뒤 세 절은 부르지도 않는다 — 404 를 세 번 더 보여줘 봐야
    # 알려주는 것이 없다.
    dr._fail.clear(); dr._warn.clear(); dr._relay_dead = True
    _rq.get = _real_get
    dr._check_rtms(); dr._check_vworld(); dr._check_ex()
    check(not dr._fail, f"중계기가 죽었으면 실호출은 건너뛴다 (막힘 {dr._fail})")
    check(len(dr._warn) == 3, f"대신 셋 다 '건너뜀' 으로 남는다 (경고 {len(dr._warn)}건)")
finally:
    _rq.get = _real_get
    dr._relay_dead = False
    dr._fail.clear(); dr._warn.clear()

print()
print("7. 영업소 좌표 찾기도 같은 한도를 쓴다 — 캐시를 오염시키면 안 된다")

# 사장님 지적: "지금 ic 좌표 붙이고 있는 API가 지오코딩 API입니다."
# 맞습니다. fill-tollgates 의 장소검색과 지오코딩은 **같은 브이월드 키,
# 같은 하루 한도**를 씁니다. 지오코딩이 한도를 다 쓰면 영업소 보충도
# 같이 막힙니다.
#
# 그런데 이쪽에는 한도 감지가 없었습니다. 브이월드는 한도를 넘겨도
# HTTP 200 에 정상 모양의 JSON 을 주고 result.items 만 없습니다. 옛
# 코드는 그것을 '검색 결과 없음' 과 구별하지 못하고 lat=None 으로
# 캐시에 박았습니다. 캐시는 다음 실행이 물려받고 한 번 박히면 다시 안
# 묻습니다 — **한도가 풀린 뒤에 돌려도 마도를 영원히 못 찾습니다.**
#
# 지오코딩에서 한 번 낸 사고인데 여기는 놓쳤습니다.
import json as _json                                            # noqa: E402
import tempfile as _tf                                          # noqa: E402
from pathlib import Path as _P                                  # noqa: E402
from redt.collect import tollgate_fill as tf                    # noqa: E402

SEARCH_OK = {"response": {"status": "OK", "result": {"items": [
    {"title": "마도영업소", "point": {"x": "126.75", "y": "37.15"}}]}}}
SEARCH_NONE = {"response": {"status": "NOT_FOUND", "result": {"items": []}}}
SEARCH_OVER = {"response": {"status": "ERROR",
                            "error": {"code": "OVER_REQUEST_LIMIT",
                                      "text": "일일 제한량 초과"}}}

def _serve(*bodies):
    seq, calls = list(bodies), []
    def _once(url, params=None, **kw):
        calls.append(params or {})
        body = seq[min(len(calls) - 1, len(seq) - 1)]
        return type("R", (), {"json": staticmethod(lambda b=body: b),
                              "status_code": 200})()
    tf.get_once = _once
    return calls

def _cache():
    return tf._Cache(_P(_tf.mkdtemp()) / "poi.jsonl")

_real_keys = tf.keys
tf.keys = lambda: type("K", (), {"require": staticmethod(lambda n: "T")})()
try:
    # 한도에 걸린 응답을 '없더라' 로 캐시하면 안 된다
    c = _cache()
    _serve(SEARCH_OVER)
    try:
        tf.search_place("마도영업소", c)
        check(False, "한도 초과를 예외로 알린다")
    except tf.QuotaExhausted as exc:
        check("OVER_REQUEST_LIMIT" in str(exc),
              f"한도 초과를 예외로 알린다 ({str(exc)[:60]})")
    check(len(c.data) == 0, f"한도 초과는 캐시에 안 적는다 (적힌 것 {len(c.data)}건)")

    # 진짜 '없더라' 는 적어 둔다 — 매번 다시 물으면 한도를 낭비한다
    c2 = _cache()
    _serve(SEARCH_NONE)
    check(tf.search_place("없는영업소", c2) is None, "없는 이름은 None 을 준다")
    check(len(c2.data) == 1 and c2.data["없는영업소"]["status"] == "NOT_FOUND",
          "진짜 없더라는 근거(status)와 함께 적어 둔다")

    # 옛 코드가 적은 행(status 없음)은 출처를 알 수 없으므로 지우고 다시 묻는다
    c3 = _cache()
    c3.put("마도영업소", {"lat": None, "lon": None, "title": None})   # 옛 모양
    c3.put("확인된없음", {"lat": None, "lon": None, "status": "NOT_FOUND"})
    c3.put("찾은곳", {"lat": 37.1, "lon": 126.7})
    dropped = tf.purge_failures(c3)
    check(dropped == 1, f"출처 불명 1건만 지운다 (지운 것 {dropped}건)")
    check("마도영업소" not in c3.data, "오염된 행은 사라진다")
    check("확인된없음" in c3.data, "근거 있는 '없음' 은 남는다 (한도를 아낀다)")
    check("찾은곳" in c3.data, "찾은 것은 당연히 남는다")

    # 한도에 걸리면 남은 영업소를 건드리지 않고 멈춘다
    class _Con:
        def execute(self, sql, *a):
            low = sql.lower()
            if "from tollgate where lat is not null" in low:
                rows = []
            elif "select lat, lon from tollgate" in low:
                rows = []
            elif "from traffic" in low:
                rows = [("805",), ("806",), ("808",)]
            else:
                rows = [("805", "마도"), ("806", "마도서"), ("808", "마도서2")]
            return type("C", (), {"fetchall": staticmethod(lambda r=rows: r)})()
    tf.names_from_traffic = lambda: {}
    _serve(SEARCH_OVER)
    got = tf.fill_missing(_Con())
    check(len(got) == 0, f"한도면 한 곳도 안 채운다 (채운 것 {len(got)}건)")
finally:
    tf.keys = _real_keys

print()
print("8. 병렬 — 워커를 여럿 두어도 캐시가 오염되지 않는가")

# 한 건씩 부르면 3만 건에 2시간 58분이었다(run 21). 병렬로 바꾸면서
# **멈추는 규칙이 살아 있는지**가 이 검사의 요점이다. 순차 코드에서는
# break 하나면 됐지만, 워커가 여럿이면 깃발을 들어야 한다.
_PAR = {"workers": 8, "calls_per_sec": 0}
gc._geo_cfg = lambda: _PAR

_OK_UNTIL = 40
_lk = threading.Lock()
_st = {"now": 0, "max": 0, "n": 0}


def _get_par(url, params):
    with _lk:
        _st["now"] += 1
        _st["max"] = max(_st["max"], _st["now"])
        _st["n"] += 1
        n = _st["n"]
    try:
        time.sleep(0.02)                    # 응답 기다리는 시간을 흉내낸다
        return FakeResp(OK_BODY if n <= _OK_UNTIL else OVER_LIMIT)
    finally:
        with _lk:
            _st["now"] -= 1


gc.get = _get_par
cache5 = fresh_cache()
rows_many = [("41111", "가", f"{i}-1") for i in range(200)]
_t0 = time.monotonic()
got5 = gc.geocode_many(rows_many, cache=cache5)
_elapsed = time.monotonic() - _t0

check(_st["max"] >= 4, f"실제로 동시에 부른다 (최대 동시 {_st['max']}건)")

# 순차라면 호출 한 건에 0.02초 × {_st['n']}회가 그대로 벽시계 시간이 된다.
_seq_est = _st["n"] * 0.02
check(_elapsed < _seq_est / 2,
      f"순차보다 빠르다 ({_elapsed:.2f}초 < 순차 추정 {_seq_est:.2f}초의 절반)")

# OK 를 준 것이 정확히 40건이므로, 캐시도 정확히 40건이어야 한다.
# 41번째 이후는 전부 한도 오류라 아무것도 안 쓴다 — 워커가 몇 개든.
check(len(cache5) == _OK_UNTIL,
      f"한도 뒤로는 캐시에 한 줄도 안 쓴다 (캐시 {len(cache5)}건 / OK {_OK_UNTIL}건)")
check(len(got5) == _OK_UNTIL, f"돌려준 값도 {_OK_UNTIL}건 (받은 값 {len(got5)})")
check(all(v["lat"] is not None for v in cache5._data.values()),
      "좌표 없는 항목이 캐시에 하나도 없다")

# 깃발을 안 들면 200건을 전부 부른다. 실제로는 한도 직후 떠 있던 것만 더 간다.
check(_st["n"] <= _OK_UNTIL + _PAR["workers"],
      f"한도 직후 떠 있던 것만 더 간다 (호출 {_st['n']}회 ≤ "
      f"{_OK_UNTIL + _PAR['workers']}회, 대기 {len(rows_many)}건)")

# 동시에 적은 파일이 다음 실행에서 읽히는가 — 잠그지 않으면 여기서 깨진다.
_reloaded = gc.GeocodeCache(cache5.path)
check(len(_reloaded) == len(cache5),
      f"동시에 적어도 파일이 안 깨진다 (다시 읽어 {len(_reloaded)}건)")

print()
print("9. 전체 속도 상한 — 워커가 몇 개든 합쳐서 초당 N건")

# 워커 수로만 속도를 정하면, 응답이 빨라지는 날 우리가 통제 못 하는
# 속도가 나온다. 상한은 워커와 별개로 지켜져야 한다.
_pace = gc._Pace(50)                        # 초당 50건 = 20ms 간격
_t0 = time.monotonic()
for _ in range(10):
    _pace.wait()
_el = time.monotonic() - _t0
check(_el >= 0.17, f"순차로 10건에 최소 0.18초 (걸린 시간 {_el:.3f}초)")

_pace2 = gc._Pace(50)
_t0 = time.monotonic()
_ths = [threading.Thread(target=_pace2.wait) for _ in range(20)]
for _t in _ths:
    _t.start()
for _t in _ths:
    _t.join()
_el2 = time.monotonic() - _t0
check(_el2 >= 0.35,
      f"스레드 20개가 동시에 와도 상한을 지킨다 (걸린 시간 {_el2:.3f}초)")

_t0 = time.monotonic()
for _ in range(100):
    gc._Pace(0).wait()
check(time.monotonic() - _t0 < 0.05, "상한을 0 으로 두면 안 쉰다")

print()
if fail:
    print(f"실패 {len(fail)}건")
    sys.exit(1)
print("모두 통과")
