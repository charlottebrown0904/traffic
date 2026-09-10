# 로그인 수단 붙이기 — 구글 · 애플 · 카카오

Supabase 가 로그인을 대신 처리하지만, **각 회사에 앱을 등록하고 발급받은 값을
Supabase 에 넣는 일**은 계정 소유자만 할 수 있습니다. 셋 다 방식이 같습니다.

```
① 각 회사 개발자 사이트에서 앱 등록
② Client ID / Secret 발급
③ Supabase 대시보드에 붙여넣기
④ 콜백 주소를 각 회사에 등록
```

**콜백 주소는 셋 다 같습니다.** 미리 복사해 두세요.

```
https://caykbxvnebpifcduqjre.supabase.co/auth/v1/callback
```

---

## ⚠️ 먼저 알아두실 것 — 애플만 유료입니다

| | 비용 | 소요 |
|---|---|---|
| 구글 | 무료 | 15분 |
| 카카오 | 무료 | 10분 |
| **애플** | **연 $99 (Apple Developer Program)** | 가입 심사 며칠 |

**Sign in with Apple 은 유료 개발자 계정이 있어야 합니다.** 웹에서 쓰려면
Services ID 를 만들어야 하는데 그게 유료 회원만 가능합니다.

아이폰 사용자도 **구글이나 카카오로 로그인할 수 있습니다.** 애플 로그인이 없다고
아이폰에서 못 쓰는 게 아닙니다. 그래서 **구글·카카오 먼저 붙이고, 애플은 나중에**
판단하시길 권합니다. 초기 이용자 수백 명 규모에서 연 $99 를 쓸 만한지는
써보고 정해도 늦지 않습니다.

---

## 1. 구글 (무료, 먼저 하세요)

**① https://console.cloud.google.com** 접속 → 프로젝트 만들기 (이름 `sado-toji`)

**② 왼쪽 메뉴 `API 및 서비스` → `OAuth 동의 화면`**

- User Type: **외부(External)**
- 앱 이름: `사도 토지`
- 사용자 지원 이메일: 본인 이메일
- 개발자 연락처: 본인 이메일
- 나머지는 기본값, `저장 후 계속`

**③ `사용자 인증 정보` → `사용자 인증 정보 만들기` → `OAuth 클라이언트 ID`**

- 애플리케이션 유형: **웹 애플리케이션**
- 승인된 리디렉션 URI 에 **위의 콜백 주소**를 붙여넣기

**④ 만들어지면 `클라이언트 ID` 와 `클라이언트 보안 비밀번호` 두 값이 나옵니다.**

**⑤ Supabase 대시보드 → `Authentication` → `Sign In / Providers` → `Google`**

- Enable 켜기
- Client ID / Client Secret 붙여넣기 → `Save`

---

## 2. 카카오 (무료) — PC 에서 할 것

> **모바일로 시도하다 막혔습니다 (2026-08-31).**
> 카카오 개발자 콘솔은 휴대폰 화면에서 일부 영역이 그려지지 않습니다.
> 실제로 `앱 → 일반` 에도 `플랫폼` 항목에도 웹 도메인 등록 자리가
> 나타나지 않았습니다. 메뉴 이름도 개편이 잦아서(아래 표) 화면을 못 보는
> 상태에서 경로를 짚어주는 것은 시간만 버립니다. PC 에서 하세요.
>
> 구글 로그인이 이미 동작하므로 이것은 **막힌 일이 아니라 미룬 일**입니다.

### 겪은 메뉴 개편 (2026-08 기준)

| 예전 이름 | 지금 위치 |
|---|---|
| `앱 설정 → 플랫폼` | `앱 설정 → 앱 → 일반` 안으로 들어간 것으로 보임 (모바일에서 미확인) |
| `앱 설정 → 앱 키` | `앱 설정 → 앱 → 플랫폼 키` |
| 모바일 상단 `☰` 의 `앱` | 곧 `내 애플리케이션` (https://developers.kakao.com/console/app) |

Supabase 쪽도 `Authentication → Providers` 가 `Sign In / Providers` 로 바뀌었습니다.


**① https://developers.kakao.com → `내 애플리케이션` → `애플리케이션 추가하기`**

- 앱 이름 `사도 토지`, 사업자명은 본인 이름

**② `앱 설정` → `플랫폼` → `Web` → 사이트 도메인 등록**

```
https://sado-toji.vercel.app
```

**③ `제품 설정` → `카카오 로그인` → 활성화 **ON**

Redirect URI 에 **위의 콜백 주소** 등록

**④ `제품 설정` → `카카오 로그인` → `동의항목`**

- 닉네임: 필수 동의
- 이메일: 선택 동의 (필수로 하려면 비즈니스 앱 전환 = 사업자등록증 필요)

**⑤ 키 두 개를 찾습니다**

- `앱 설정` → `앱 키` → **REST API 키** → 이것이 Client ID
- `제품 설정` → `카카오 로그인` → `보안` → **Client Secret** 을 생성하고 **활성화 ON**

**⑥ Supabase → `Authentication` → `Providers` → `Kakao` → 두 값 붙여넣기**

---

## 3. 애플 (유료 — 나중에)

Apple Developer Program (연 $99) 가입 후:

**① https://developer.apple.com/account → `Certificates, Identifiers & Profiles`**

**② `Identifiers` → App ID 하나, **Services ID** 하나 생성**

- Services ID 가 웹 로그인용 Client ID 가 됩니다
- Return URL 에 위의 콜백 주소 등록

**③ `Keys` → 새 키 생성, `Sign in with Apple` 체크 → `.p8` 파일 다운로드**

> `.p8` 파일은 **한 번만 내려받을 수 있습니다.** 잃어버리면 새로 만들어야 합니다.

**④ Supabase → `Providers` → `Apple`**

- Services ID, Team ID, Key ID, `.p8` 내용 붙여넣기

---

## 다 끝나면

Supabase → `Authentication` → `URL Configuration`

| 항목 | 값 |
|---|---|
| Site URL | `https://sado-toji.vercel.app` |
| Redirect URLs | `https://sado-toji.vercel.app/**` |

이걸 안 하면 로그인 후 엉뚱한 곳으로 튕깁니다.
