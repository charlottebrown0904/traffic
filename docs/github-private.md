# 저장소를 Private 으로 전환하기

## 0. 전환 전 확인 — 이미 끝난 것

공개 상태에서 비밀값이 한 번이라도 커밋됐다면, **private 으로 바꿔도 이미 노출된 것**입니다
(공개 기간 동안 누구나 클론·크롤링할 수 있었기 때문). 그래서 먼저 확인했습니다.

| 검사 | 결과 |
|---|---|
| `.env` · 인증서 · 키 파일이 커밋 이력에 있는가 | `config/.env.example` (빈 템플릿) 뿐 ✅ |
| 전체 커밋 이력에서 실제 키 패턴 | 없음 ✅ |
| `.gitignore` 가 `config/.env` 를 실제로 막는가 | 막음 ✅ |

**키를 재발급할 필요가 없습니다.** 처음부터 키를 `.env` 와 GitHub Secrets 에만 두는
구조라 그렇습니다.

---

## 1. 전환 절차

1. https://github.com/charlottebrown0904/traffic 접속
2. 상단 **`Settings`**
3. **General** 탭에서 맨 아래까지 스크롤 → **Danger Zone**
4. **`Change repository visibility`** → **`Change to private`**
5. 경고 목록을 읽고 체크
6. 확인창에 **`charlottebrown0904/traffic`** 을 그대로 입력
7. **`I understand, change repository visibility`**

> 전환 자체는 즉시 반영되고, 되돌리는 것도 같은 자리에서 가능합니다.

---

## 2. 전환 직후 확인할 것 (순서대로)

### ① Vercel 배포가 계속 되는가 ← 제일 중요

Vercel 은 private 저장소도 배포할 수 있지만, GitHub 연동 권한이 **선택한 저장소만**
으로 설정돼 있으면 끊길 수 있습니다.

1. Vercel → 프로젝트 → **Deployments** → **Redeploy** 로 한 번 강제 배포
2. 실패하면: Vercel → Settings → Git → **Disconnect** 후 다시 연결
3. 또는 GitHub → Settings → Applications → **Vercel** → 저장소 접근 권한 확인

### ② 이 저장소에 대한 Claude 접근

전환 후에도 제가 계속 읽고 푸시할 수 있어야 합니다.
안 되면 https://claude.ai/customize/connectors 에서 GitHub 연결을 다시 승인하세요.

### ③ 배포된 페이지

- `https://sado-toji.vercel.app/` — 프로모션
- `https://sado-toji.vercel.app/app` — 스크리닝 앱

**저장소가 private 이어도 배포된 사이트는 계속 공개**입니다. 둘은 별개입니다.

---

## 3. Private 으로 바뀌면 달라지는 것

### ⚠️ giscus 가 동작하지 않습니다

giscus 는 **GitHub Discussions 를 공개로 읽을 수 있어야** 하므로 **public 저장소 전용**입니다.
[who-does-what.md](who-does-what.md) 트랙 G(공개 분석 리포트 댓글)는 이대로는 불가능합니다.

대안 세 가지:

| 대안 | 설명 |
|---|---|
| **블로그용 저장소를 따로 public 으로** | 리포트 콘텐츠만 별도 저장소. 코드는 private 유지 ← 권장 |
| Supabase 로 댓글 구현 | GitHub 계정 없이도 쓸 수 있음. 스팸 대응은 직접 |
| 댓글 없이 발행 | SEO 유입만 노림 |

### GitHub Actions 사용량이 유료 구간으로

| | public | private |
|---|---|---|
| Actions 실행 시간 | 무제한 | 플랜별 월 무료 한도 + 초과분 과금 |

계획 중인 **일별 교통량 수집**은 하루 1회 × 약 5분 = **월 150분 내외**라
무료 한도 안에서 충분합니다.

다만 **초기 백필은 다릅니다.** 과거 4,000일을 한 번에 돌리면 워크플로 하나가
몇 시간이 되고, GitHub Actions 는 **작업 하나당 6시간 제한**이 있습니다.
→ 백필은 Actions 가 아니라 **로컬에서 돌리거나**, 연도별로 쪼개서 실행하세요.

현재 사용량: GitHub → Settings → Billing → **Plans and usage**
(무료 한도는 플랜마다 다르고 정책이 바뀌므로 이 페이지에서 확인하세요.)

### 그 밖에

| 항목 | 영향 |
|---|---|
| GitHub Pages | private 저장소는 무료 플랜에서 공개 발행 불가 — **Vercel 쓰므로 무관** |
| `raw.githubusercontent.com` 링크 | 전부 깨짐 — **의존하는 곳 없음** |
| Fork · Star | 기존 fork 는 분리되고 star 는 숨겨짐 — **해당 없음** |
| 협업자 | 초대된 사람만 볼 수 있음. 누군가와 함께 볼 계획이면 **Settings → Collaborators** 에서 초대 |
| 보안 기능 | public 전용 무료 기능(일부 코드 스캐닝 등)은 빠짐 |

---

## 4. 💰 Vercel 요금제 — 미리 알아두실 것

Vercel **Hobby 플랜은 비상업적 사용 전용**입니다.
지금은 무료 진단 프로모션이라 문제없지만,
**매물 등록 수수료를 받기 시작하면 상업적 사용**이 되어 유료 플랜이 필요합니다.

private 전환과는 별개 문제이고, 결제(트랙 E)를 붙일 때 함께 정리하면 됩니다.
현재 약관은 Vercel 요금 페이지에서 확인하세요.

---

## 5. 앞으로 키를 다룰 때

private 이 되어도 **키를 코드에 넣으면 안 됩니다.** 협업자·연동 앱·백업에 그대로 퍼지고,
나중에 public 으로 되돌릴 때 이력이 통째로 드러납니다.

| 용도 | 두는 곳 |
|---|---|
| 로컬 실행 | `config/.env` (gitignore 됨) |
| GitHub Actions | Settings → Secrets and variables → **Actions** |
| Vercel 런타임 | Vercel → Settings → **Environment Variables** |
| 브라우저에 노출돼도 되는 값 (Supabase `anon key` 등) | `web/app/config.js` |

`service_role key`, PG 시크릿, DB 비밀번호는 **어디에도 커밋하지 마세요.**
