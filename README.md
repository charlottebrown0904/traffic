# 고속도로 교통량 × 토지·공장 실거래가 상관분석

고속도로 IC/영업소의 **차종별 교통량 변화**와 인근 **토지·공장·단독건물 실거래가 변화**의
관계를 정량화하고, 지도 기반 투자 스크리닝 도구로 만드는 프로젝트.

- 전체 계획: [ROADMAP.md](ROADMAP.md)
- 분석 설계와 가설: [docs/hypothesis.md](docs/hypothesis.md) ← **먼저 읽어주세요**
- **API 키 신청**: [docs/api-keys.md](docs/api-keys.md)
- **교통량 과거 시계열 확보**: [docs/traffic-history.md](docs/traffic-history.md) ← 현재 병목
- 데이터 소스·API: [docs/data-sources.md](docs/data-sources.md)
- 스키마: [docs/data-model.md](docs/data-model.md)
- 법적 체크리스트: [docs/legal-notes.md](docs/legal-notes.md)

## 현재 단계: Step 1 — 데이터 레이어

```
수집 → 정규화 → 지오코딩 → 공간조인 → 패널 → 분석
```

## 빠른 확인 (API 키 불필요)

합성 데이터에 **진짜 β를 심어놓고** 추정기가 그것을 되찾는지 검증합니다.

```bash
make install
make demo
```

기대 출력 — 심어둔 값 `{0-3km: 0.50, 3-5km: 0.30, 5-10km: 0.10, 10-20km: 0.00}`

```
 band    kind   n   beta     se       p
  0-3    land 420   0.542  0.103   0.000     ← 회수
  3-5    land 420   0.255  0.103   0.014     ← 회수
 5-10    land 420   0.179  0.109   0.101
10-20    land 420  -0.078  0.084   0.354     ← 위약 밴드, 0에 가까움 ✅
```

동시에 `L1 수준 상관`을 보면 **위약 밴드(10–20km)에서도 r=0.26** 이 나옵니다.
단순 상관이 왜 위험한지 그 자체로 보여주는 대목입니다.

## 실제 데이터 파이프라인

```bash
cp config/.env.example config/.env   # API 키 입력 → docs/api-keys.md 참고

python -m redt.cli regions                        # 파일럿 권역 확인
python -m redt.cli regions --verify                # 시군구 코드 시험 조회 ← 수집 전 필수

python -m redt.cli tollgates                      # 영업소 마스터 + 좌표
python -m redt.cli probe-ex                            # 도로공사 API 과거조회 가능여부 탐침
python -m redt.cli traffic --path <내파일> --inspect   # 컬럼 먼저 확인
python -m redt.cli traffic --path <내파일> --source tcs # 정규화 적재
python -m redt.cli coverage                            # 시계열 확보 현황 판정

# 파일럿 권역만 수집 (중단해도 이어서 재개됨)
python -m redt.cli trades --region gyeonggi_south --kind land,factory \
                          --start 2015-01 --end 2025-12
python -m redt.cli geocode --limit 5000           # 지번 → 좌표 (캐시됨)
python -m redt.cli link                           # 공간 조인
python -m redt.cli panel                          # 헤도닉 + 패널
python -m redt.cli analyze --volume freight       # 화물차 기준 분석
python -m redt.cli status                         # 적재 현황
```

## 구조

```
src/redt/
  config.py          설정 (settings.yaml + .env)
  db.py              DuckDB 스키마 / upsert
  collect/
    http.py          재시도·레이트리밋
    tollgate.py      도로공사 영업소 마스터
    traffic.py       확보한 교통량 파일 정규화
    rtms.py          국토부 실거래가
    geocode.py       VWorld 지오코딩 (+ 영구 캐시)
  transform/
    spatial.py       haversine 거리 밴드 조인
    panel.py         헤도닉 보정 + 패널 구축
  analyze/
    correlation.py   L1 상관 / L2 탄력성 / L3 위약 검정
```

## 파일럿 권역

전국을 한 번에 긁지 않고 **경기 남부 물류·공장 벨트**(평택·화성·안성·이천·오산·용인처인·
여주·광주) 먼저 검증합니다. 경부/서해안/평택제천/영동이 교차하고 평택항·삼성 평택캠퍼스로
화물 물동량이 급증한 구간이라 β가 잡히면 가장 잘 잡히는 곳입니다.
여기서 안 나오면 전국에서도 안 나옵니다.

권역 정의는 `config/pilot_regions.yaml` 에서 수정합니다.

> ⚠️ RTMS API는 **잘못된 시군구 코드에 오류 대신 0건을 반환**합니다.
> 수집 전 반드시 `regions --verify` 로 코드를 확인하세요.

## 주의

이 저장소의 산출물은 **과거 실거래 데이터 기반 통계**이며 미래 가격을 보장하지 않습니다.
상관관계는 인과가 아닙니다. 제품화 시 문구는 [docs/legal-notes.md](docs/legal-notes.md) 참고.
