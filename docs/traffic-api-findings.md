# 교통량 API 조사 결과 (2026-08-31)

서울 중계기를 통해 `data.ex.co.kr` 을 직접 조사한 결과.

## 확인된 것

**엔드포인트는 존재한다.**

```
odtraffic/trafficAmountByUnit    영업소별 교통량
odtraffic/trafficAmountByRoute   노선별 교통량
locationinfo/locationinfoUnit    영업소 590행  ← 이미 수집에 사용 중
locationinfo/locationinfoIc      IC 위치
locationinfo/locationinfoRest    휴게소 203곳
```

**필수 파라미터 1개 확정.**

| 한글명 | 파라미터 | 확인 방법 |
|---|---|---|
| 집계시간단위구분코드 | **`sumTmUnitTypeCode`** | 넣으면 오류가 다음 항목으로 넘어감 |
| 기준시 | **미확정** | 후보 10개 실패 |

`기준시` 후보로 시도해 실패한 것:
`stdHour stdTime stdTm baseHour hour stdDt stdDate sumStdHour stdHh tmZon`

## 문서를 읽으려 한 시도

- `openapi/intro/introduce02` (목록) — 자바스크립트로 그려져 경로가 HTML 에 없음
- `openapi/basicinfo/openApiInfoM?apiId=NNNN` (상세) — **서버에서 그려짐** (10만 자)
  - `0001~0099` 전부 빈 템플릿
  - `0100~0260` 실제 문서. 그러나 `trafficAmountByUnit` 문자열은 **한 건도 없음**
  - 요청 변수 표는 페이지 로드 후 ajax 로 채워지는 구조로 보임

## 중요 — 이 API 로는 과거 데이터를 못 받는다

필수 파라미터가 **집계시간단위구분코드 + 기준시** 라는 것은
이 API 가 **시간 단위 실시간/최근 조회**용이라는 뜻이다.

우리 분석에 필요한 것은 **2016~2025 연도별 영업소 교통량**이다.
파라미터 이름을 맞춘다 해도 이 API 는 그것을 주지 않는다.
`docs/traffic-history.md` 에서 이미 같은 결론에 도달했었다.

## 그러므로

파라미터 추적을 더 하는 것은 **답이 나와도 쓸모가 없다.** 중단한다.

과거 교통량은 **파일**로 확보한다.

1. 대표님이 이미 갖고 계신 전국 영업소 교통량 파일 → `redt traffic --path`
2. 없거나 부족하면 도로공사 포털 / 교통량정보시스템의 연도별 통계 파일

`redt traffic` 은 이미 만들어져 있다. 인코딩 자동판별(utf-8/cp949/euc-kr),
wide→long 변환, 관측일수 300일 미만 경고까지 들어 있다.
**파일만 넣으면 바로 붙는다.**
