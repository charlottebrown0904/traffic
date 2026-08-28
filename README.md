# 고속도로 교통량 × 토지·공장 실거래가 상관분석

고속도로 IC/영업소의 **차종별 교통량 변화**와 인근 **토지·공장·단독건물 실거래가 변화**의
관계를 정량화하고, 지도 기반 투자 스크리닝 도구로 만드는 프로젝트.

> **▶ [역할 분담 — 내가 할 일 / Claude 가 할 일](docs/who-does-what.md)** ← 지금 볼 것
> **▶ [단계별 실행 가이드](docs/START-HERE.md)** ← 파이프라인 실행 순서

| 문서 | 내용 |
|---|---|
| [who-does-what.md](docs/who-does-what.md) | **역할 분담** — Supabase · Actions · giscus · 결제까지 전 트랙 |
| [START-HERE.md](docs/START-HERE.md) | 단계별 실행 순서와 통과 기준 |
| [hypothesis.md](docs/hypothesis.md) | **분석 설계와 가설** — 먼저 읽어주세요 |
| [api-keys.md](docs/api-keys.md) | API 키 신청 (어느 데이터셋을 신청하나) |
| [traffic-history.md](docs/traffic-history.md) | 교통량 과거 시계열 확보 ← **현재 병목** |
| [product-format.md](docs/product-format.md) | 제품 화면 형식 |
| [listings-api.md](docs/listings-api.md) | 매물 API (인증·권한·결제 자리) |
| [data-sources.md](docs/data-sources.md) | 데이터 소스와 응답 필드 |
| [data-model.md](docs/data-model.md) | 스키마 |
| [legal-notes.md](docs/legal-notes.md) | 법적 체크리스트 |
| [ROADMAP.md](ROADMAP.md) | 전체 계획 |

## 누가 무엇을 하나

**사용자만 할 수 있는 일**은 신원·자격이 필요하거나(계정 가입, 사업자등록, PG 계약),
돈이 걸렸거나(결제 수단, 도메인), 법적 책임이 따르거나(약관 확정, 변호사 검토),
사업 판단(가격 정책, 대상 지역)인 것들입니다.
나머지 — 코드·스키마·테스트·문서·마이그레이션·정책 초안 — 는 제가 합니다.

| 트랙 | 🧑 사용자 | 🤖 Claude |
|---|---|---|
| **A. 데이터** | API 키 신청, `probe-history` 실행 | 수집기·지오코딩·분석 |
| **B. Supabase** | 프로젝트 생성, PostGIS 켜기, 키 등록 | 마이그레이션·RLS 정책·프런트 전환 |
| **C. Actions** | Secrets 등록 | CI·일별 수집·월별 갱신·배포 워크플로 |
| **D. 배포** | 도메인, 호스팅 계정, DNS | 빌드 설정, 환경변수 연결 |
| **E. 결제** | 사업자등록, 통신판매업 신고, PG 계약 | 위젯 연동, 웹훅 검증, 만료 배치 |
| **F. 자격검증** | 확인 방식 결정 | 등록증 업로드·승인 화면 |
| **G. 콘텐츠** | Discussions 켜기, giscus 설치 | 리포트 템플릿·자동 생성 |
| **H. 법무** | **변호사 검토**, 약관 게시 | 초안 작성 |

전 항목과 순서·의존관계는 **[who-does-what.md](docs/who-does-what.md)** 에 있습니다.

> 🔑 `anon key` 처럼 공개용 값은 알려주셔도 됩니다.
> `service_role key`·PG 시크릿·DB 비밀번호는 **채팅에 붙여넣지 마세요.**
> 저는 참조하는 코드만 쓰고, 값은 사용자가 GitHub Secrets 에 직접 넣습니다.

## 현재 단계

```
수집 → 정규화 → 지오코딩 → 공간조인 → 패널 → 분석 → 스코어 → 화면
└────────── 실데이터 대기 ──────────┘   └── 형식 완성 ──┘
```

데이터 수집은 API 키를 기다리는 중이고, **그 뒤 파이프라인과 화면 형식은 완성**되어
합성 데이터로 끝까지 돌아갑니다. 실데이터가 들어오면 같은 명령이 그대로 실행됩니다.

```bash
make web    # 스코어 계산 + JSON 생성 + 서버 (http://127.0.0.1:8000)
make serve  # 화면 + 매물 API 만 (JSON 이 이미 있을 때)
```

## 빠른 확인 (API 키 불필요)

합성 데이터에 **진짜 β를 심어놓고** 추정기가 그것을 되찾는지 검증합니다.

```bash
make install
make demo   # 합성 데이터로 β 회수 검증
make test   # 백필 파서·롤업 로직 검증
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
python -m redt.cli probe-history                       # 과거 날짜 조회 가능 범위 판정
python -m redt.cli backfill --endpoint <경로> --date-param <파라미터> \
       --start 2015-01-01 --end 2025-12-31             # 일별 백필 (중단 시 재개)
python -m redt.cli rollup                              # 일별 → 연 집계
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
    scoring.py       영업소별 2×2 분면 스코어
  webexport.py       DuckDB → web/data/*.json

  server/            매물 API (FastAPI + SQLite)
    app.py           라우트 · 인증 · 소유권 검사
    store.py         스키마 (중개사 / 세션 / 매물)
    security.py      scrypt 해싱 · 토큰
    models.py        요청·응답 스키마

web/                 화면 (분석은 JSON, 매물은 API)
  index.html         탐색 / 스코어보드 / 매물 3개 탭
  app.js  style.css
```

## 파일럿 권역

전국을 한 번에 긁지 않고 **경기 남부 물류·공장 벨트**(평택·화성·안성·이천·오산·용인처인·
여주·광주) 먼저 검증합니다. 경부/서해안/평택제천/영동이 교차하고 평택항·삼성 평택캠퍼스로
화물 물동량이 급증한 구간이라 β가 잡히면 가장 잘 잡히는 곳입니다.
여기서 안 나오면 전국에서도 안 나옵니다.

권역 정의는 `config/pilot_regions.yaml` 에서 수정합니다.

> ⚠️ RTMS API는 **잘못된 시군구 코드에 오류 대신 0건을 반환**합니다.
> 수집 전 반드시 `regions --verify` 로 코드를 확인하세요.

## 이번 주에 하실 것

1. **공공데이터포털·브이월드 키 신청** — 승인 대기가 있으니 가장 먼저
2. **Supabase 프로젝트 생성 + PostGIS 활성화** — 10분
3. **`python -m redt.cli probe-history`** — 한 줄. 결과가 방향을 가름
4. **사업자등록 알아보기** — 결제까지 가려면 제일 오래 걸림

## 주의

이 저장소의 산출물은 **과거 실거래 데이터 기반 통계**이며 미래 가격을 보장하지 않습니다.
상관관계는 인과가 아닙니다. 제품화 시 문구는 [docs/legal-notes.md](docs/legal-notes.md) 참고.
