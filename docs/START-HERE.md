> **PC에 아무것도 설치하지 않고 브라우저에서 실행하려면** → [docs/run-in-browser.md](run-in-browser.md)

# 단계별 실행 가이드 — 무엇이 필요한가

각 단계는 **통과 기준(Gate)** 을 갖습니다.
기준을 못 넘으면 다음 단계로 가도 결과가 무의미하니, 거기서 멈추고 분기합니다.

| 단계 | 내용 | 담당 | 소요 |
|---|---|---|---|
| 0 | 환경 준비 | 사용자 | 30분 |
| 1 | API 키 3개 | 사용자 | 2시간 + 대기 |
| 2 | 교통량 과거 시계열 ✅ **2003~2025 확보 완료** | 사용자 + 코드 | — |
| 3 | 영업소 좌표 + 코드 정합성 | 코드 | 30분 |
| 4 | 실거래가 수집 | 코드 | 1일 |
| 5 | **지오코딩** ← 현재 병목 | 코드 | 1~3일 |
| 6 | 분석 실행 및 판정 | 코드 | 1시간 |
| 7 | 결과에 따른 분기 | 함께 결정 | — |

전체 **약 1~2주**. 대부분은 API 대기와 자동 수집 시간입니다.

---

## 단계 0 — 환경 준비

**필요한 것**: Python 3.10 이상

```bash
git clone <저장소> && cd traffic
make install
make demo    # 합성 데이터로 파이프라인 검증
make test    # 백필 파서·롤업 로직 검증
```

**✅ Gate 0**: `make demo` 마지막에 두 종류 모두 아래 모양이면 통과.
```
[factory] 정점 1-3km β=+0.32(p=0.004) / 위약 5-10km β=-0.07(p=0.559) → ✅ 거리 감쇠 확인
[land]    정점 3-5km β=+0.39(p=0.003) / 위약 5-10km β=+0.10(p=0.332) → ✅ 거리 감쇠 확인
```
숫자는 난수라 조금씩 다릅니다. 봐야 할 것은 **모양**입니다 —
영향범위(0-5km)에 유의한 양수가 있고, **위약 5-10km 는 0 근처이며
유의하지 않다.** 합성 자료에는 위약 밴드에 참값 0 을 심어뒀으므로,
여기서 위약이 유의하게 나오면 분석기가 고장난 것입니다.
이건 **심어둔 정답을 코드가 되찾았다**는 뜻이지, 실제 부동산에서 β가 나온다는 뜻이 아닙니다.
분석기가 고장나지 않았음을 확인하는 절차입니다.

---

## 단계 1 — API 키 3개

상세: **[docs/api-keys.md](api-keys.md)**

**사용자가 할 일**

1. **공공데이터포털** (https://www.data.go.kr) 회원가입 → 아래 4개 각각 `활용신청`
   - [토지 매매 15126466](https://www.data.go.kr/data/15126466/openapi.do) ★필수
   - [공장·창고 등 15126470](https://www.data.go.kr/data/15126470/openapi.do) ★필수
   - [단독/다가구 15126465](https://www.data.go.kr/data/15126465/openapi.do)
   - [상업업무용 15126463](https://www.data.go.kr/data/15126463/openapi.do)
   - 덤으로 [영업소 위치정보 15076728](https://www.data.go.kr/data/15076728/openapi.do) — 단계 3에서 씀
2. **브이월드** (https://www.vworld.kr) → 인증키 발급, **`Geocoder API 2.0` 포함**, 도메인 `localhost`
3. **도로공사** — 교통량 받으실 때 쓴 키 재사용. 없으면 https://data.ex.co.kr/openapi/apikey/requestKey

```bash
cp config/.env.example config/.env   # 3개 값 채우기
```

> ⚠️ 인증키는 **Decoding** 값을 복사하세요. Encoding 값을 넣으면 이중 인코딩되어
> `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` 가 납니다. 가장 흔한 삽질 포인트입니다.

**✅ Gate 1**
```bash
python -m redt.cli regions --verify
```
파일럿 시군구들이 `OK ... totalCount=NN` 으로 나오면 통과.
전부 `0건`이면 키가 아직 활성화 안 된 것(1~2시간 대기) 또는 Encoding 키를 넣은 것입니다.

---

## 단계 2 — 교통량 과거 시계열 ⚠️ 최대 병목

상세: **[docs/traffic-history.md](traffic-history.md)**

현재 2025년 한 해뿐이라 **Δ교통량을 계산할 수 없습니다.** 여기가 뚫려야 H2가 성립합니다.

### 2-1. 실시간 API로 과거가 조회되는지 판정

```bash
python -m redt.cli probe-history
```

### 2-2. 판정 결과에 따라 분기

**분기 A — 1년 이상 조회됨** ✅
```bash
python -m redt.cli backfill --endpoint <출력된경로> --date-param <출력된파라미터> \
       --start 2015-01-01 --end 2025-12-31
python -m redt.cli rollup
```
약 4,000일. 중단해도 `traffic_fetch_log` 로 이어받으니 며칠에 나눠 돌려도 됩니다.

**분기 B — 부족하거나 안 됨** → 파일데이터를 직접 내려받습니다
- [data.ex.co.kr 입출구 교통량](https://data.ex.co.kr/portal/fdwn/view?type=TCS&num=65&requestfrom=dataset)
- [영업소별 교통량 15043774](https://www.data.go.kr/data/15043774/fileData.do)
- [분기별 톨게이트 일교통량 15043784](https://www.data.go.kr/data/15043784/fileData.do)
- 장기 시계열 대안: [연평균일교통량 15062249](https://www.data.go.kr/data/15062249/fileData.do), [road.re.kr 통계연보](https://www.road.re.kr/)

```bash
python -m redt.cli traffic --path data/raw/<파일> --inspect      # 컬럼 확인
python -m redt.cli traffic --path data/raw/<파일> --source tcs   # 적재
```

### 2-3. ⚠️ 반드시 확인할 것 — 하이패스 구분

TCS 자료는 **현금과 하이패스가 구분**되어 있습니다. 하이패스 이용률은 계속 올랐으므로,
**현금분만 뽑아 연도별로 이으면 실제로는 늘어난 교통량이 급감한 것처럼 보이고
β 부호가 뒤집힙니다.** `rollup` 이 구분값 분포를 출력하니 확인하세요.

**✅ Gate 2**
```bash
python -m redt.cli coverage
```
`✅ H2 분석 가능` 이 떠야 통과. `❌` 면 단계 7의 **분기 B(H5 이벤트 스터디)** 로 갑니다.

---

## 단계 3 — 영업소 좌표와 코드 정합성

```bash
python -m redt.cli tollgates          # API 사용
# 또는
python -m redt.cli tollgates --path data/raw/tollgate.csv
```

**✅ Gate 3** — 여기서 놓치기 쉬운 함정이 있습니다.
```bash
python -m redt.cli status
```
`tollgate` 건수와 `traffic` 의 영업소 수를 **비교**하세요.
교통량 파일의 영업소 코드와 마스터의 `unitCode` 체계가 다르면
공간 조인에서 조용히 0건이 됩니다. 두 숫자가 크게 다르면 알려주세요 — 매핑을 붙이겠습니다.

---

## 단계 4 — 실거래가 수집

```bash
python -m redt.cli trades --region gyeonggi_south --kind land,factory \
       --start 2015-01 --end 2025-12
```
약 2,100 요청. 일일 한도(1만)에 걸리면 다음 날 같은 명령을 다시 돌리면 이어받습니다.

**✅ Gate 4**: `status` 의 `trade` 가 **수천 건 이상**. 수백 건이면 기간이나 코드를 의심하세요.

---

## 단계 5 — 지오코딩

```bash
python -m redt.cli geocode --limit 5000     # VWorld 한도에 맞춰 나눠 실행
```
캐시되므로 여러 번 나눠 돌려도 낭비가 없습니다.

**✅ Gate 5** — 출력되는 정밀도 분포에서 **`parcel` 비율**을 봅니다.

| parcel 비율 | 판정 |
|---|---|
| 50% 이상 | ✅ 그대로 진행 |
| 30~50% | ⚠️ 근거리 밴드 표본이 얇을 수 있음 |
| 30% 미만 | ❌ 밴드를 `0-5/5-10/10-20/20-40km` 로 넓혀야 함 |

국토부가 토지·일반건축물 지번을 일부만 공개하기 때문에 생기는 제약입니다.

---

## 단계 6 — 분석 실행

```bash
python -m redt.cli link      # 거래 ↔ 영업소 거리 밴드 조인
python -m redt.cli panel     # 헤도닉 보정 + 패널 구축
python -m redt.cli analyze --volume freight     # 화물차 기준
python -m redt.cli analyze --volume total       # 전체 기준
```

**✅ Gate 6 — 위약 밴드 검사**

마지막 `=== 해석 ===` 블록을 봅니다.

- `✅ 거리 감쇠 확인` → 근거리 β가 크고 원거리 β가 0에 가까움. **가설 성립**
- `⚠️ 원거리 밴드에서도 계수가 큼` → IC 효과가 아니라 지역 효과. 통제 보강 필요

> 경기 남부는 8개 시군구가 붙어 있어 20km 밖도 같은 개발 축입니다.
> ⚠️ 가 나와도 **가설이 틀린 게 아니라 대조군 설계가 이 권역에 안 맞는 것**일 수 있어,
> 충남·충북 권역을 추가해 지리적 대비를 만드는 쪽으로 조정합니다.

---

## 단계 7 — 결과에 따른 분기

### 분기 A — β가 나왔다 (근거리 유의 + 원거리 0)

제품화로 갑니다.
1. **스코어링 엔진** — 영업소별 교통량 모멘텀 × 가격 모멘텀 2×2 매트릭스.
   **교통량↑ / 가격정체 = 저평가 후보** 가 투자자가 보고 싶어하는 화면입니다.
2. **지도 UI** — 영업소 마커 + 거리밴드 + 실거래 점 + 스코어 패널
3. **매물 등록·과금** — 단, [docs/legal-notes.md](legal-notes.md) 선검토

### 분기 B — β가 안 나왔다 / 교통량 시계열을 못 구했다

**H5(지구지정 이벤트 스터디)로 전환합니다. 교통량 시계열이 전혀 필요 없습니다.**

추가로 필요한 것:
- 산업단지·택지지구의 **지정 고시일** (현황 데이터에는 없는 경우가 많아 관보/고시문에서 수집)
- 소스: KICOX, [산업입지정보시스템](https://www.industryland.or.kr), LH, 국토부 도시개발구역

산출물: "지구지정 후 N년차에 가격이 가장 많이 올랐다" 는 궤적.
**투자자에게는 이쪽이 더 잘 팔릴 수 있습니다** — "교통량이 늘면 오른다"보다
**"지정 후 몇 년째가 매수 적기인가"** 가 훨씬 행동으로 옮기기 쉽기 때문입니다.

2025년 교통량 한 해치도 버리지 않습니다. **현재 수준 지표**로는 유효해서
"이 IC는 화물 통행량 상위 N%" 같은 스크리닝 표시에 그대로 씁니다.
다만 참고 지표지 상관분석의 근거는 못 된다는 선은 지킵니다.

---

## 지금 당장 할 것

1. `make install && make demo` — 5분, 지금 바로 가능
2. 공공데이터포털 + 브이월드 키 신청 — 승인 대기가 있으니 **가장 먼저**
3. `python -m redt.cli probe-history` — 단계 2 분기를 결정하는 한 줄

3번 결과가 이 프로젝트의 방향을 가릅니다. 결과 알려주시면 다음을 붙이겠습니다.
