"""자치법규 API 응답을 미리 모른 채로 조문을 찾아내는가.

API 는 여기서 못 부른다 (egress 차단). 그래서 본다:
  1. 키 이름에 '조문' 이 든 사전을 어디에 있든 찾는다.
  2. 관심 낱말(건폐율·경사도…)이 든 조문만 남긴다.
  3. 목록 행에서 MST·이름·기관을 여러 후보 키로 짚는다.
  4. 중계기 허용목록과 클라이언트 목록에 www.law.go.kr 이 짝으로 있다.

  실행: python scripts/test_law.py   (make test 에 포함)
"""
import os
import pathlib
import sys

os.environ.setdefault("VWORLD_KEY", "test-key")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from redt.collect import law as L                  # noqa: E402

fail = []


def check(ok, label):
    print(f"  {'✓' if ok else '✗'} {label}")
    if not ok:
        fail.append(label)


print("1. 조문 사전을 재귀로 찾는다")
payload = {"LawService": {"자치법규명": "안성시 도시계획 조례", "조문": {"조문단위": [
    {"조문번호": "1", "조문제목": "목적", "조문내용": "제1조(목적) 이 조례는 …"},
    {"조문번호": "58", "조문제목": "용도지역 안에서의 건폐율", "조문내용": "제58조 … 계획관리지역: 40퍼센트 이하"},
    {"조문번호": "20", "조문제목": "개발행위허가의 기준", "조문내용": "… 경사도 20도 미만 … 임목축적 150퍼센트 …",
     "항": [{"항번호": "1", "항내용": "…"}]},
]}}}
arts = L.articles(payload)
check(len(arts) == 3, f"조문 3개 — {len(arts)}")
rel = L.relevant(payload)
check([a["no"] for a in rel] == ["58", "20"], f"관심 조문만 남긴다 — {[a['no'] for a in rel]}")
check(rel[0]["title"] == "용도지역 안에서의 건폐율" and "40퍼센트" in rel[0]["text"], "제목·본문을 옮긴다")

print()
print("2. 목록 행의 열쇠")
row = {"자치법규일련번호": "1611223", "자치법규명": "안성시 도시계획 조례", "지자체기관명": "경기도 안성시"}
check(L._pick(row, "MST", "자치법규일련번호") == "1611223", "MST 가 없으면 일련번호")
check(L._find_rows({"OrdinSearch": {"ordin": [row]}}) == [row], "중첩된 목록을 찾는다")
check(L._find_rows({"OrdinSearch": {"totalCnt": "1", "law": row}}) == [row], "한 건짜리 목록(dict 하나)도 한 행이다")
check(L._find_int({"OrdinSearch": {"totalCnt": "231"}}, ("totalCnt",)) == 231, "전체 건수")

print()
print("2-1. 포털 길의 XML 을 조문 걷기가 읽는다")
import xml.etree.ElementTree as ET                 # noqa: E402
xml = ET.fromstring("<response><body><items><item><조문번호>58</조문번호><조문제목>건폐율</조문제목>"
                    "<조문내용>계획관리지역 40퍼센트</조문내용></item><item><조문번호>1</조문번호>"
                    "<조문제목>목적</조문제목><조문내용>…</조문내용></item></items></body></response>")
obj = L._xml_obj(xml)
check(len(L.articles(obj)) == 2 and L.relevant(obj)[0]["no"] == "58", "XML → dict → 조문 2개 · 관심 1개")

print()
print("2-2. 틀 페이지에서 본문 하위 주소를 찾는다")
frame = ('<script>$("#c").load("/LSW/ordinInfoR.do?ordinSeq=2121099&chrClsCd=010202");'
         ' url: "ordinJoCntntsP.do?ordinSeq=" + seq, a="/LSW/ordinSearchList.do?q=1"; b="/LSW/lsLoginP.do"</script>'
         '<iframe src="https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2121099"></iframe>')
cands = L.web_candidates("2121099", frame)
check(cands[0] == "https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq=2121099&chrClsCd=010202",
      "페이지에 있던 주소가 먼저 · ordinSeq 를 채운다")
check(any("ordinJoCntntsP.do?ordinSeq=2121099" in c for c in cands), "상대 주소는 /LSW/ 아래로 · JS 이어붙임은 버린다")
check(not any("Search" in c or "Login" in c for c in cands), "검색·로그인 주소는 뺀다")
check(len(cands) == len(set(cands)) and all(f in "".join(cands) for f in L.WEB_FIXED), "중복 없음 · 고정 후보 포함")

print()
print("2-3. 항·호까지 펼치고 · 조문번호 표기 · 웹 HTML 예비 · 요약 숫자")
art = {"조문번호": "005800", "조문여부": "Y", "조문제목": "용도지역 안에서의 건폐율",
       "조문내용": "제58조(용도지역 안에서의 건폐율) 건폐율은 다음 각 호와 같다.",
       "항": [{"항번호": "1", "항내용": "1. 보전관리지역: 20퍼센트 이하", "호": [{"호내용": "15. 계획관리지역: 40퍼센트 이하"}]}]}
ft = L.flat_text(art)
check("계획관리지역: 40퍼센트" in ft and "005800" not in ft, "항·호 문장이 들어가고 번호는 빠진다")
check(L.art_no("005802") == "제58조의2" and L.art_no("000100") == "제1조" and L.art_no("58") == "제58조", "조문번호 표기")
rel2 = L.relevant({"조문": {"조문단위": [art]}})
check(rel2 and rel2[0]["label"] == "제58조" and "40퍼센트" in rel2[0]["text"], "relevant 가 항·호 본문으로 고른다")
html = ("<html><script>var a=1;</script><div>안성시 도시계획 조례 제1장 총칙 <p>제1조(목적) 이 조례는 …</p>"
        "<p>제20조(개발행위허가의 기준) ① 경사도 20도 미만 … 표고 200미터 … 입목축적 150퍼센트</p>"
        "<p>제58조의2(건폐율 특례) 계획관리지역: 40퍼센트 이하</p></div></html>")
ha = L.html_articles(html)
check([a["조문번호"] for a in ha] == ["000100", "002000", "005802"], f"HTML → 조문 3개 {[a['조문번호'] for a in ha]}")
check(ha[1]["조문제목"] == "개발행위허가의 기준" and "script" not in ha[0]["조문내용"], "제목·script 제거")
summ = L.summarize(L.relevant({"조문": ha}))
check(summ["건폐율_계획관리"] == "40" and summ["경사도_도"] == "20" and summ["표고_m"] == "200"
      and summ["입목축적_pct"] == "150" and summ["용적률_계획관리"] == "", f"요약 숫자 {summ}")

print()
print("2-4. 목록 고르기 — 도시계획조례만 · 기관별 최신 하나")
rows = [{"자치법규명": "안성시 도시계획 조례", "지자체기관명": "경기도 안성시", "자치법규일련번호": "1", "시행일자": "20240101"},
        {"자치법규명": "안성시 도시계획 조례", "지자체기관명": "경기도 안성시", "자치법규일련번호": "2", "시행일자": "20260410"},
        {"자치법규명": "안성시 도시계획 조례 시행규칙", "지자체기관명": "경기도 안성시", "자치법규일련번호": "3", "시행일자": "20260410"},
        {"자치법규명": "양평군 군계획 조례", "지자체기관명": "경기도 양평군", "자치법규일련번호": "4", "시행일자": "20250101"},
        {"자치법규명": "고양시 도시계획위원회 조례", "지자체기관명": "경기도 고양시", "자치법규일련번호": "5", "시행일자": "20250101"},
        {"자치법규명": "세종특별자치시 도시·군계획 조례", "지자체기관명": "세종특별자치시", "자치법규일련번호": "6", "시행일자": "20250101"}]
w = L.wanted(rows)
check([r["_mst"] for r in w] == ["2", "4", "6"], f"안성 최신(2) · 양평 군계획 · 세종 도시·군계획 — {[r['_mst'] for r in w]}")
check(L.slug_of(w[0]) == "경기도_안성시_안성시_도시계획_조례", f"파일 이름 {L.slug_of(w[0])}")

print()
print("3. 중계기와 클라이언트가 짝이다")
relay = (ROOT / "api" / "relay.js").read_text(encoding="utf-8")
http = (ROOT / "src" / "redt" / "collect" / "http.py").read_text(encoding="utf-8")
check('"www.law.go.kr":   { param: "OC",         env: "LAW_OC", keepClient: true,' in relay, "중계기가 OC 를 끼워 넣는다")
check('rule.keepClient && given && given !== "__via_relay__"' in relay, "호출 측이 준 OC(견본 계정 test)는 살린다")
check('"OC": "test"' in (ROOT / "src" / "redt" / "collect" / "law.py").read_text(encoding="utf-8"), "본문은 OC=test 로 부른다")
check('"OC"' not in relay.split("const STRIP")[1].split("\n")[0], "들어온 OC 는 지우지 않는다 (포털이 법제처로 넘긴다)")
check('"www.law.go.kr"' in http.split("RELAYED_HOSTS = {")[1].split("}")[0], "클라이언트가 중계기로 보낸다")
check('"OC"' not in http.split("_KEY_PARAMS = ")[1].split("\n")[0], "OC 는 중계기로 실어 보낸다")

print()
if fail:
    print(f"실패 {len(fail)}건:")
    for f in fail:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
