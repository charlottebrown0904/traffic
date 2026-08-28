# 데이터 모델

저장소: **DuckDB** 단일 파일 (`data/processed/redt.duckdb`).
서버 불필요하고 수백만 행까지 문제없습니다. Step 5(웹 서비스)에서 PostgreSQL + PostGIS로 이관.

---

## 원천 레이어 (raw)

### `tollgate` — 영업소/IC 마스터
| 컬럼 | 타입 | 설명 |
|---|---|---|
| tollgate_id | VARCHAR PK | 도로공사 unitCode |
| name | VARCHAR | 영업소명 |
| route_no | VARCHAR | 노선번호 |
| lat, lon | DOUBLE | WGS84 |
| sido, sigungu | VARCHAR | 행정구역 |
| sigungu_cd | VARCHAR | 법정동 5자리 |
| is_open_type | BOOLEAN | 개방식 요금소 여부 |

### `traffic` — 영업소 × 연도 × 차종 교통량
| 컬럼 | 타입 |
|---|---|
| tollgate_id | VARCHAR |
| year | INTEGER |
| vehicle_type | INTEGER (1~6) |
| direction | VARCHAR ('in'/'out'/'all') |
| volume | BIGINT |

PK: (tollgate_id, year, vehicle_type, direction)

파생: `volume_freight` = 3+4+5종, `volume_passenger` = 1+6종

### `trade` — 실거래
| 컬럼 | 타입 | 설명 |
|---|---|---|
| trade_id | VARCHAR PK | 해시 |
| kind | VARCHAR | land / factory / house / commercial |
| sigungu_cd | VARCHAR | 5자리 |
| umd | VARCHAR | 법정동 |
| jibun | VARCHAR | 지번 |
| deal_year, deal_month | INTEGER | |
| area_m2 | DOUBLE | 거래면적 |
| price_krw | BIGINT | 거래금액 (원) |
| price_per_m2 | DOUBLE | 파생 |
| land_use | VARCHAR | 지목/용도지역 |
| is_share_deal | BOOLEAN | 지분거래 플래그 |
| lat, lon | DOUBLE | 지오코딩 결과 (NULL 가능) |

### `geocode_cache` — 주소 → 좌표
| addr_key(PK) | lat | lon | source | fetched_at |

### `zone_event` — 산업단지/택지지구 지정 이벤트
| zone_id | name | type (industrial/housing) | lat | lon | area_m2 | designated_date |

---

## 분석 레이어 (processed)

### `trade_tollgate_link` — 공간 조인 결과
| trade_id | tollgate_id | distance_km | band |

`band` ∈ {`0-3`, `3-5`, `5-10`, `10-20`}
- 한 거래는 **여러 영업소**에 매칭될 수 있음 (가장 가까운 것 = `is_nearest`)
- 기본 분석은 `is_nearest = TRUE`만 사용, 강건성 검정에서 전체 사용

### `panel` — 최종 분석 패널
| 컬럼 | 설명 |
|---|---|
| tollgate_id, year, band, kind | 셀 키 |
| n_trades | 거래건수 (5 미만이면 NULL 처리) |
| price_index | 헤도닉 보정 ㎡당 가격지수 (log) |
| d_ln_price | 전년 대비 로그차분 |
| volume_total / freight / passenger | 교통량 |
| d_ln_traffic_lag1 | 교통량 로그차분 (1년 시차) |
| sigungu_cd | 고정효과용 |
| has_zone_event_within_5y | 인근 지구지정 여부 |

이 `panel` 한 장이 Step 3 회귀와 Step 4 스코어링의 유일한 입력입니다.

---

## 파이프라인 순서
```
1. collect tollgates   → tollgate
2. normalize traffic   → traffic         (기존 확보 파일 입력)
3. collect trades      → trade           (시군구 × 월 루프, 오래 걸림)
4. geocode             → trade.lat/lon   (캐시 활용)
5. spatial join        → trade_tollgate_link
6. build panel         → panel
7. analyze             → 결과 테이블 + 차트
```
