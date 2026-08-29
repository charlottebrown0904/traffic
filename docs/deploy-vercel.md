# Vercel 배포 — sado-toji.vercel.app

## 구조

```
web/                     ← Vercel Output Directory
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

## ⚠️ 배포 전 반드시 — 프로모션 페이지부터 옮기세요

`web/index.html` 은 **자리만 잡아둔 임시 페이지**입니다.
지금 라이브인 프로모션 페이지를 보지 못한 상태로 만든 것이라,
**이대로 기존 Vercel 프로젝트를 이 저장소에 연결하면 라이브 프로모션이 덮어써집니다.**

순서를 지키세요.

1. 기존 프로모션 페이지의 소스를 가져옵니다 (기존 저장소 또는 Vercel 프로젝트에서)
2. 그 내용으로 `web/index.html` 을 **통째로 교체**합니다
3. 교체한 페이지 안에 `/app` 으로 가는 링크 하나만 넣습니다
   ```html
   <a href="/app">서비스 바로가기</a>
   ```
4. 그 다음에 아래 연결 작업을 합니다

> 프로모션 소스를 저에게 붙여주시면 `/app` 링크를 넣어 정리해 드리겠습니다.

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
| Output Directory | `web` — `vercel.json` 에 이미 지정됨 |
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

그때 바꿀 것은 `web/app/config.js` 한 줄입니다.

```js
apiBase: 'https://<프로젝트>.supabase.co/rest/v1',
```

---

## 데이터 갱신

`web/app/data/*.json` 은 **커밋된 파일**입니다. Vercel 에 빌드가 없으므로
저장소에 있는 그대로 배포됩니다.

분석을 다시 돌린 뒤에는 갱신해서 커밋하세요.

```bash
make web          # 스코어 계산 + JSON 생성
git add web/app/data && git commit -m "데이터 갱신" && git push
```

푸시하면 Vercel 이 자동 재배포합니다.

> 나중에 GitHub Actions 로 월 1회 자동 갱신·커밋하도록 만들 수 있습니다
> ([who-does-what.md](who-does-what.md) C6).

---

## 프로모션 페이지를 없앨 때

1. `web/index.html` 삭제
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

3. `web/app/config.js` 에서 `homeUrl` 을 `null` 로 — 앱의 **← 홈으로** 버튼이 사라집니다

이 셋이면 `/` 가 바로 앱이 됩니다. 앱을 옮기지 않으므로 `/app` 링크도 계속 삽니다.
