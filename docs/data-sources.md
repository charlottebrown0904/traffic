# 데이터 소스 목록 (신청 · 엔드포인트 · 주의사항)

> ⚠️ 공공 API는 엔드포인트/파라미터가 종종 바뀝니다. 아래는 작성 시점 기준이며,
> 실제 연동 전 각 포털의 활용신청 페이지에서 한 번 확인하세요.

---

## 1. 교통량 — 한국도로공사 (이미 확보 ✅)

**포털**: https://data.ex.co.kr (도로공사 자체 오픈 API, 별도 회원가입)

인증키 발급: https://data.ex.co.kr/openapi/apikey/requestKey
API 목록: https://data.ex.co.kr/openapi/intro/introduce02

| 용도 | 경로 |
|---|---|
| 영업소 마스터 + 좌표 | `/openapi/business/curBusinessInfo` |
| TCS 영업소별 차종 교통량 | `/openapi/trafficapi/trafficIC` |
| 노선별 교통량 | `/openapi/trafficapi/trafficAmountByRoute` |

**공공데이터포털에도 동일 계열 데이터가 있습니다** (기존 `DATA_GO_KR_KEY` 재사용 가능):
- [한국도로공사_영업소 위치정보 (15076728)](https://www.data.go.kr/data/15076728/openapi.do) ← **영업소 좌표**
- [한국도로공사_실시간 영업소별 교통량 (15076872)](https://www.data.go.kr/data/15076872/openapi.do)

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

신청 절차는 [docs/api-keys.md](api-keys.md) 참고.

| 물건 종류 | 서비스 / 오퍼레이션 | 데이터셋 | 우선순위 |
|---|---|---|---|
| **토지** 매매 | `RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade` | 15126466 | ★★★ |
| **공장·창고 등** 매매 | `RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade` | 15126470 | ★★★ |
| **단독/다가구** 매매 | `RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade` | 15126465 | ★★ |
| 상업업무용 매매 | `RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade` | 15126463 | ★ |

### 응답 필드 (영문 camelCase — 한글 태그가 아닙니다)

| 필드 | 의미 | 쓰임 |
|---|---|---|
| `umdNm`, `jibun` | 법정동, 지번 | 지오코딩 입력 |
| `dealAmount` | 거래금액 (**만원** 단위, 쉼표 포함) | ×10,000 하여 원 단위로 |
| `dealArea` | 거래면적 (토지) | 단가 분모 |
| `plottageAr` / `buildingAr` | 대지면적 / 건물면적 (공장·상업) | 분모 / 헤도닉 통제 |
| `jimok` | 지목 (전·답·대·임야·공장용지) | **헤도닉 핵심 통제변수** |
| `landUse` | 용도지역 (계획관리·생산녹지·공업) | **헤도닉 핵심 통제변수** |
| `shareDealingType` | 지분구분 | 지분거래 → ㎡단가 왜곡, 제외 |
| `cdealType` / `cdealDay` | 해제여부 / 해제일 | **`O` 면 계약 해제 → 반드시 제외** |
| `dealingGbn` | 중개거래 / 직거래 | 직거래는 특수관계 가능성 |
| `slerGbn`, `buyerGbn` | 매도·매수자 구분 (개인/법인/공공) | 법인 매집 신호로 활용 여지 |

공통 파라미터: `serviceKey`, `LAWD_CD`(시군구 5자리), `DEAL_YMD`(YYYYMM), `pageNo`, `numOfRows`

**치명적 제약 ⚠️**
- 조회 단위가 **시군구 × 계약년월**입니다. 전국 250개 시군구 × 12개월 × 11년
  = 약 33,000 요청 / 물건종류. 일일 트래픽(기본 10,000)을 고려해 나눠 받아야 합니다.
  → `collect_log` 테이블로 중단/재개를 지원합니다.
- 응답에 **좌표가 없습니다.** `시군구 + 법정동 + 지번`만 옵니다 → 지오코딩 필수 (§3).
- **토지·일반건축물의 지번은 개인정보 보호를 이유로 일부만 공개됩니다.**
  → 상당수 거래가 법정동 중심점(오차 ±1~2km)으로만 지오코딩됩니다.
  → `geocode_level` 로 정밀도를 기록하고, 근거리 밴드는 지번단위 좌표만 사용합니다.
  자세한 대응은 [api-keys.md](api-keys.md) 마지막 절 참고.
- **해제된 계약**(`cdealType='O'`)이 섞여 있습니다. 실제 거래가 아니므로 제외합니다.
- 지분 거래(`shareDealingType`)는 ㎡당 단가를 왜곡하므로 제외합니다.
- 잘못된 `LAWD_CD` 에 **오류가 아니라 0건**을 반환합니다 → `regions --verify` 로 선검증.

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
