# 데이터 소스 목록 (신청 · 엔드포인트 · 주의사항)

> ⚠️ 공공 API는 엔드포인트/파라미터가 종종 바뀝니다. 아래는 작성 시점 기준이며,
> 실제 연동 전 각 포털의 활용신청 페이지에서 한 번 확인하세요.

---

## 1. 교통량 — 한국도로공사 (이미 확보 ✅)

**포털**: https://data.ex.co.kr (도로공사 자체 오픈 API, 별도 회원가입)

| 용도 | 경로 |
|---|---|
| 영업소 마스터 + 좌표 | `/openapi/business/curBusinessInfo` |
| TCS 영업소별 차종 교통량 | `/openapi/trafficapi/trafficIC` |
| 노선별 교통량 | `/openapi/trafficapi/trafficAmountByRoute` |

공통 파라미터: `key`, `type=json`, `numOfRows`, `pageNo`

**차종 코드 (도로공사 TCS 기준)**
| 코드 | 차종 |
|---|---|
| 1 | 승용차 / 소형승합 |
| 2 | 중형승합 / 소형화물 |
| 3 | 대형승합 / 2축 화물 |
| 4 | 3축 화물 |
| 5 | 4축 이상 특수/트레일러 |
| 6 | 경차 |

> **핵심**: 3·4·5종 합계가 "화물 교통량"이며, 공장·창고·물류토지 가격의 선행지표
> 후보입니다 (docs/hypothesis.md H4).

**주의**: 영업소는 IC와 1:1이 아닙니다. 하이패스 전용 IC, 요금소 없는 분기점(JC)이
있고, 개방식/폐쇄식 요금소 구조에 따라 "입구/출구" 집계 방식이 다릅니다.
→ `docs/data-model.md`의 `tollgate` 테이블에 `is_open_type`, `has_hipass_only` 플래그를 둡니다.

---

## 2. 실거래가 — 국토교통부 RTMS OpenAPI

**포털**: https://www.data.go.kr (활용신청 → 일반 인증키 발급, 승인 즉시)
**Base**: `https://apis.data.go.kr/1613000/`

| 물건 종류 | 서비스 / 오퍼레이션 | 우선순위 |
|---|---|---|
| **토지** 매매 | `RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade` | ★★★ |
| **공장·창고 등** 매매 | `RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade` | ★★★ |
| **단독/다가구** 매매 | `RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade` | ★★ |
| 상업업무용 매매 | `RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade` | ★ |

공통 파라미터: `serviceKey`, `LAWD_CD`(시군구 5자리), `DEAL_YMD`(YYYYMM), `pageNo`, `numOfRows`

**치명적 제약 ⚠️**
- 조회 단위가 **시군구 × 계약년월**입니다. 전국 250개 시군구 × 12개월 × 10년
  = **약 30,000 요청 / 물건종류**. 일일 트래픽 한도(기본 10,000)를 고려해 나눠 받아야 합니다.
- 응답에 **좌표가 없습니다.** `시군구 + 법정동 + 지번`만 옵니다 → 지오코딩 필수 (§3).
- 토지 거래는 **지분 거래**가 섞입니다 (`거래면적` vs `지분`). 지분 거래는 ㎡당 단가가
  왜곡되므로 별도 플래그 처리합니다.

---

## 3. 지오코딩 — VWorld

**포털**: https://www.vworld.kr (오픈API 인증키, 도메인 등록 필요)
```
https://api.vworld.kr/req/address
  ?service=address&request=getcoord&version=2.0
  &crs=epsg:4326&type=PARCEL&address=경기도 화성시 ...&key=...
```
- `type=PARCEL` : 지번 주소 (실거래가 데이터에 맞음)
- 일일 호출 제한이 있으므로 **주소→좌표 캐시 필수** (`data/interim/geocode_cache.jsonl`)
- 대안: 행안부 도로명주소 API (juso.go.kr), 카카오 로컬 API

> 거래 건수가 수십만 건이라도 **고유 지번 수**는 훨씬 적고, 한 번 지오코딩하면
> 영구 재사용 가능하므로 캐시가 비용을 결정합니다.

---

## 4. 법정동코드 (시군구 5자리 목록)

- 행안부 「법정동코드 전체자료」: https://www.code.go.kr
- 또는 data.go.kr 「행정안전부_법정동코드」
- 폐지 여부(`폐지여부=존재`) 필터, 5자리 시군구 단위로 distinct

---

## 5. 산업단지 / 택지지구  (Step 1b)

| 데이터 | 소스 |
|---|---|
| 전국 산업단지 현황 (위치·면적·분양률) | 한국산업단지공단(KICOX), data.go.kr |
| 산업입지 정보 | 산업입지정보시스템 industryland.or.kr |
| 공공택지·공공주택지구 | LH 청약센터 / LH 공공데이터 |
| 도시개발구역 현황 | 국토교통부, data.go.kr |
| 지구지정 고시 이력 | 국토부 고시 / 관보 (수기 정리 필요할 수 있음) |

**필요한 것은 "현황"이 아니라 "지정 고시일"입니다** — 이벤트 스터디(H5)의 t=0.
현황 데이터에 고시일이 없으면 관보/고시문에서 별도 수집해야 합니다.

---

## 6. 통제변수 (Step 3에서 필요)

| 변수 | 소스 |
|---|---|
| 용도지역 (계획관리/생산녹지/공업 등) | 국토부 토지이용계획정보 (LURIS) API |
| 개별공시지가 | 국토부 / data.go.kr — 시계열 baseline으로 유용 |
| 인구·사업체 수 | KOSIS |

용도지역은 토지 가격의 **가장 큰 단일 설명변수**입니다. 이것을 통제하지 않으면
교통량 계수가 오염됩니다.

---

## 필요한 API 키 정리 (`config/.env`)
```
DATA_GO_KR_KEY=      # 국토부 실거래가 (data.go.kr 일반 인증키, Decoding 값)
EX_API_KEY=          # 한국도로공사 data.ex.co.kr
VWORLD_KEY=          # VWorld 지오코더
```
