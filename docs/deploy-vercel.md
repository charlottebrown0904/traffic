# Vercel 배포 — sado-toji.vercel.app

## 구조

```
public/                  ← Vercel Output Directory
  index.html             /        프로모션 (임시, 나중에 삭제)
  app/
    index.html           /app     스크리닝 앱
    config.js                     배포 환경별 설정 ← 여기만 바꾸면 됨
    app.js  style.css
    data/*.json                   분석 결과 (커밋됨)
vercel.json              라우팅·캐시·보안 헤더
```

| 경로 | 내용 |
|---|---|
| `/` | 프로모션 페이지 → **서비스 바로가기** 버튼이 `/app` 으로 |
| `/app` | 스크리닝 앱 → 좌측 상단 **← 홈으로** 가 `/` 로 |

두 페이지가 서로를 가리키므로 왕복이 됩니다.

---

## 첫 화면 (`public/index.html`)

**2026-09-04 프로모션을 걷어냈습니다.** 그 전에는 "토지 미래가치 무료 진단 ·
추첨 20명" 페이지였고, 카카오톡 오픈채팅 신청 버튼(`KAKAO_LINK`)과 9월 7일
자동 마감(`DEADLINE`)이 붙어 있었습니다. 셋 다 지웠습니다.

지금은 **이 사이트가 무엇을 하는 곳인지** 만 적습니다.

| 섹션 | 내용 |
|---|---|
| 머리 | 한 줄 소개 + 회원 가입 |
| 무엇을 보여주나 | 교통량 · 반경 안 실거래 · 용도지역 · 시군구 인구 |
| 자료 | 국토부 실거래가 · 도로공사 TCS · 브이월드 · KOSIS · 도시개발사업 |
| 이용 | 가입은 관리자 승인제 |

한때 '한계' 섹션이 있었습니다 — 판정표가 세 가설 모두 '아직 모름' 이라
그것을 첫 화면에도 적었는데, 2026-09-04 요구사항으로 뺐습니다.

**대신 두 곳은 그대로 둡니다.**
  · 푸터의 "미래 가격을 예측하거나 보장하지 않습니다"
  · 앱 안의 `가설 판정` 탭 — 판정과 근거가 숫자 그대로 있습니다

첫 화면이 판정표보다 더 말하지 않는 한 화면 안팎이 어긋나지 않습니다.
앞으로 첫 화면에 "오릅니다" 류의 문구를 넣게 되면, 그때는 판정표를
먼저 보고 정해야 합니다.

외부 CSS·JS·이미지 참조가 없어(전부 인라인) 경로 이동으로 깨질 곳이 없습니다.
자바스크립트도 이제 없습니다.

---

## Vercel 화면에서 길찾기

Vercel 대시보드가 **좌측 사이드바 방식**으로 바뀌었습니다.
메뉴 이름은 또 바뀔 수 있으니 **주소로 직접 이동**하는 편이 확실합니다.

프로젝트 주소가 `vercel.com/<팀>/sado-toji` 라면 뒤에 붙이면 됩니다.

| 목적 | 주소 |
|---|---|
| 배포 목록 · Redeploy | `/deployments` |
| Git 저장소 연결 · Production Branch | `/settings/git` |
| 빌드 설정 (Framework · Output Directory) | `/settings/build-and-deployment` |
| 도메인 | `/settings/domains` |

사이드바에서 찾을 때:

- **Deployments** — 위에서 두 번째
- **Git 설정** — 맨 아래 `Settings` 의 `>` 를 펼치면 하위에 `Git`
- ⚠️ 사이드바의 **`Connect`** 는 Git 연결이 아닙니다 (네트워크 기능). 헷갈리기 쉽습니다

### Redeploy 를 못 찾겠다면

**커밋을 푸시하는 편이 더 쉽습니다.** Vercel 은 연결된 저장소에 푸시가 들어오면
자동으로 배포합니다. `main` 에 푸시하면 프로덕션, 다른 브랜치에 푸시하면
**Preview 배포**가 생기므로, 프로덕션을 건드리지 않고 연결 상태를 확인할 수 있습니다.

Redeploy 버튼은 "이미 있는 배포를 다시" 돌릴 때 쓰는 것이라,
**배포가 하나도 없으면 누를 대상 자체가 없습니다.**

---

## 🧑 사용자가 할 일

### 1. Production Branch 확인 ← 놓치기 쉬움

현재 작업은 `claude/real-estate-traffic-correlation-liujkh` 브랜치에 있습니다.
Vercel 은 기본적으로 **`main` 브랜치만 프로덕션 배포**합니다.

둘 중 하나를 하세요.

- **A.** 작업 브랜치를 `main` 에 머지 (권장)
- **B.** Vercel → Settings → Git → **Production Branch** 를 작업 브랜치로 변경

### 2. 프로젝트 연결

기존 `sado-toji` 프로젝트 → Settings → Git → 이 저장소로 연결
(또는 새 프로젝트를 만들어 확인 후 도메인을 옮겨도 됩니다)

### 3. 빌드 설정

| 항목 | 값 |
|---|---|
| Framework Preset | **Other** |
| Build Command | **비움** (빌드 없음) |
| Output Directory | `public` — `vercel.json` 에 이미 지정됨 |
| Install Command | 비움 |
| Root Directory | 저장소 루트 (비움) |

정적 파일만 올리므로 빌드가 필요 없습니다. 환경변수도 아직 없습니다.

### 4. 배포 확인

- `https://sado-toji.vercel.app/` → 프로모션
- `https://sado-toji.vercel.app/app` → 스크리닝 앱
- 앱 상단에 **데모 데이터** 배너가 보이면 정상 (합성 데이터라는 표시)

---

## ⚠️ Vercel 에서는 매물 기능이 동작하지 않습니다

이유가 명확합니다. 매물 API 는 **SQLite 파일**에 저장하는데,
Vercel 은 서버리스라 **파일시스템이 요청마다 초기화**됩니다.
억지로 올리면 등록한 매물이 조용히 사라집니다.

그래서 앱이 **API 가 있는지 먼저 확인**하고, 없으면 매물 탭을
"준비 중" 안내로 대체합니다. 탐색·스코어보드는 정상 동작합니다.

| 환경 | 매물 탭 |
|---|---|
| 로컬 (`make serve`) | ✅ 전체 동작 |
| Vercel (지금) | 안내 표시 |
| Vercel + Supabase (다음) | ✅ 전체 동작 |

**해결은 Supabase 이전입니다** ([who-does-what.md](who-does-what.md) 트랙 B).
Postgres 는 서버리스에서도 상태를 유지하고, RLS 로 권한도 DB 가 강제합니다.

그때 바꿀 것은 `public/app/config.js` 한 줄입니다.

```js
apiBase: 'https://<프로젝트>.supabase.co/rest/v1',
```

---

## 데이터 갱신

`public/app/data/*.json` 은 **커밋된 파일**입니다. Vercel 에 빌드가 없으므로
저장소에 있는 그대로 배포됩니다.

분석을 다시 돌린 뒤에는 갱신해서 커밋하세요.

```bash
make web          # 스코어 계산 + JSON 생성
git add public/app/data && git commit -m "데이터 갱신" && git push
```

푸시하면 Vercel 이 자동 재배포합니다.

> 나중에 GitHub Actions 로 월 1회 자동 갱신·커밋하도록 만들 수 있습니다
> ([who-does-what.md](who-does-what.md) C6).

---

## 프로모션 페이지를 없앨 때

1. `public/index.html` 삭제
2. `vercel.json` 에 rewrite 추가

```json
{
  "outputDirectory": "web",
  "cleanUrls": true,
  "rewrites": [
    { "source": "/", "destination": "/app/index.html" }
  ]
}
```

3. `public/app/config.js` 에서 `homeUrl` 을 `null` 로 — 앱의 **← 홈으로** 버튼이 사라집니다

이 셋이면 `/` 가 바로 앱이 됩니다. 앱을 옮기지 않으므로 `/app` 링크도 계속 삽니다.

---

## 저장 한도 — 배포가 조용히 멈춘 날 (2026-09-11)

증상: main 에 합쳐도 production 이 안 올라가고, 나중엔 브랜치 미리보기도 안 생겼다.
Usage 화면: **Deployment Storage 20.88 GB / 10 GB**. 배포 하나가 194MB(표준지 조각
138MB 포함)인데 브랜치 push 마다 미리보기가 생겨 사본이 쌓였다. Hobby 는 한도를
넘기면 새 배포를 받지 않는다.

한 일:
- 표준지 조각은 배포에서 뺐다. 같은 날 오후에 jsDelivr(공개 CDN) 대신 **Supabase
  비공개 버킷 `premium`** 으로 옮겼다 — 프리미엄 자료라 공개 CDN 은 자물쇠가 아니었다
  (docs/membership-grades.md §3). 저장소에서도 지웠다.
- 작업 브랜치는 미리보기 배포를 만들지 않는다(`vercel.json git.deploymentEnabled`).
  main 만 배포된다. 검사: `scripts/test_deploy_size.py`.

계정 주인이 할 것 (한 번):
1. Vercel → toji-gogo → **Deployments** → 오래된 것부터 ⋯ → **Delete**. 10GB 아래로
   내려가야 새 배포를 받는다 (약 60개를 지워야 한다 — 미리보기부터).
2. 또는 Settings → General → **Deployment Retention** 이 보이면 Preview/Errored/
   Canceled 를 가장 짧게 두면 저절로 지워진다.
3. 지운 뒤 main 이 자동으로 안 올라가면 Settings → Git → Deploy Hooks 로 main 훅을
   만들어 URL 을 한 번 연다.

이 절의 '계정 주인이 할 것' 은 같은 날 저녁에 끝났다 — VERCEL_TOKEN 시크릿으로
`scripts/vercel_cleanup.py` 가 722개를 지웠고, 매주 일요일 03:00 KST 에 다시 돈다
(`.github/workflows/vercel-cleanup.yml`).

## 함수 호출 한도 — api/tile (2026-09-11)

Usage 화면(9월 11일): **Function Invocations 522K / 1M**, Edge Requests 785K / 1M,
Fast Origin Transfer 7.06 / 10GB. Hobby 는 한도를 넘기면 기능을 멈춘다 (배포 저장
한도처럼 조용히). 함수는 사실상 `api/tile` 하나다 — 배경(브이월드)·용도지역·필지
경계선·필지 조회가 모두 이 함수를 지난다.

실측 (런타임 로그): 지도를 한 번 움직이면 **1초 안에 40장**이 함수를 돌렸고 전부
`cache=MISS` 였다. 엣지 요청 중 함수 호출이 66% 라는 것은 캐시가 거의 못 받아
준다는 뜻이다 — 사람마다 다른 동네를 보고, 배율을 손가락으로 바꾸는 동안 Leaflet
이 정수 배율마다 한 벌씩 새로 받는다.

한 일 (커밋 참조):
- **엣지 캐시 한 달** (`s-maxage=2592000`) + 브라우저 한 주 + `stale-while-revalidate`
  하루. 전에는 이레·하루였다. 두 번째 사람부터 함수가 안 돈다.
- **층 옵션** (`app.js TILE_OPTS`): `updateWhenZooming:false` (배율 바꾸는 동안 안 받음
  — z10→16 이면 여섯 벌이 한 벌로), `updateWhenIdle:true`, `keepBuffer:4`. OSM 은
  남의 서버라 그대로.
- **지도 전용 브이월드 키 자리** (`config.js vworldMapKey`). 넣으면 배경 타일이
  브라우저에서 브이월드로 바로 가고 우리 함수는 0회다. 로그 한 줄
  (`tile kind=… z=…`) 로 층별 호출 수를 센다.

계정 주인이 할 것 (선택, 효과가 가장 크다):
1. 브이월드 콘솔에서 **키를 하나 더** 발급한다 (서비스 URL `https://toji.fyi`). 지금
   키는 지오코딩(하루 3만 건)과 같이 쓰므로 페이지에 실으면 안 된다 — 새 키가 새면
   지도만 하루 멈추고 수집은 안 선다.
2. `public/app/config.js` 의 `vworldMapKey: ''` 에 넣고 main 에 올린다. 이 파일은
   공개되지만, 브이월드 키는 서비스 주소에 묶여 Referer 를 본다.
3. 용도지역 색면과 경계선은 계속 함수를 거친다 (WMS/WFS 는 키를 물음표 뒤에 실어야
   해 같은 방법이 안 된다). 색면은 기본 꺼짐, 경계선은 z16 부터라 양이 적다.

한도를 넘기면: Usage 에서 어느 항목인지 보고, 함수 호출이면 `vworldMapKey` 를 넣는
것이 유일한 큰 손잡이다. Cloudflare 로 옮기는 길은 브이월드가 그쪽 IP 를 502 로
막아 닫혀 있다 (docs/cloudflare-migration.md).
