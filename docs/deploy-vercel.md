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

## 프로모션 페이지 — 이관 완료 ✅

`web/index.html` 은 기존 **"사도 될까 — 토지 미래가치 무료 진단"** 페이지입니다.
외부 CSS·JS·이미지 참조가 없어 (전부 인라인) 경로 이동으로 깨진 곳은 없습니다.

원본에서 바뀐 것은 **`/app` 링크 3개 추가**뿐입니다.

| 위치 | 문구 | 의도 |
|---|---|---|
| "무엇을 보나" 섹션 끝 | 만들고 있는 도구 미리 보기 → | **차량·사람 유동량** 항목 바로 아래. 그 도구가 실제로 보여주는 것 |
| 마감 화면 | 만들고 있는 도구 미리 보기 → | 9월 1일 이후 신청이 닫히면 유일하게 남는 행동 |
| 푸터 | 도구 미리 보기 | |

카카오톡 신청 CTA 를 가리지 않도록 **보조 링크(외곽선 스타일)** 로 두었습니다.

### ⚠️ 출시 전 채워야 할 것

`web/index.html` 하단 스크립트의 **`KAKAO_LINK` 이 비어 있습니다.**
지금 상태로 배포하면 신청 버튼이 안내 alert 만 띄우고 아무 데도 가지 않습니다.

```js
var KAKAO_LINK = "https://open.kakao.com/o/...";   // ← 여기
```

### 자동 마감

`DEADLINE = 2026-09-07T23:59:59+09:00` (KST). 이 시각이 지나면 페이지가 자동으로
마감 화면으로 바뀌고, "9월 8일 추첨" 안내가 뜹니다.
마감 화면에도 `/app` 링크가 있어 방문자가 갈 곳이 남습니다.

날짜를 또 바꾸려면 **7곳**을 함께 고쳐야 합니다 (히어로, 조건 표, 안내 박스,
고정 CTA, 마감 화면, 주석, `DEADLINE`). 한 곳만 고치면 화면과 동작이 어긋납니다.

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
