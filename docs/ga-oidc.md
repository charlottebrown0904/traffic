# GA 숫자를 어드민으로 — 키 파일 없이 (OIDC)

GA 는 이미 켜져 있다(측정 ID `G-RW6MCG84SF`, 스트림 '토지랩'). 이 문서는
그 숫자를 **구글 화면에 들어가지 않고 /admin 에서 보는** 설정이다.

**아직 안 돼 있다.** /admin 의 GA 칸이 "환경변수가 아직 없습니다" 와 함께
빠진 이름을 적어 준다. 아래를 마치면 그 자리가 숫자로 바뀐다.

## 왜 키 파일을 안 쓰나

흔한 방법은 서비스 계정 JSON 키를 환경변수에 통째로 넣는 것이다. 그러면
**영구 자격증명이 하나 더 생긴다** — 새면 회수할 때까지 계속 유효하다.

대신 Vercel 이 배포마다 발급하는 OIDC 토큰으로 구글에게 "나는 이 프로젝트의
production 이다" 를 증명하고, **한 시간짜리 토큰**을 받아 쓴다(Vercel OIDC
토큰의 `exp - iat` 가 3600 초다). 키가 없으니 샐 키도 없다.

    Vercel OIDC → STS 토큰 교환 → 서비스 계정 가장 → GA Data API

`api/ga.js` 가 이 넷을 fetch 로 직접 한다. 라이브러리를 안 쓴다 — 이 저장소에
`package.json` 이 없고 없는 편이 배포가 단순하며, 덤으로 google-auth-library
에서 흔한 audience 어긋남(`invalid_grant`)이 애초에 안 생긴다(우리가 audience
를 직접 적는다).

## 할 일

### 1. Vercel — OIDC 켜기

프로젝트 → Settings → **Secure Backend Access**(OIDC Federation) →
토큰 발급을 켠다. 켜지면 배포에 `VERCEL_OIDC_TOKEN` 이 자동으로 들어온다.

**켜졌다(2026-09-16 확인).** Issuer Mode 는 **Team**. 그 화면이 보여 주는
클레임이 아래 3·4번에 그대로 들어간다 — 이 저장소의 실제 값:

| 클레임 | 값 |
|---|---|
| `iss` | `https://oidc.vercel.com/brown21` |
| `aud` | `https://vercel.com/brown21` |
| `sub` | `owner:brown21:project:toji-gogo:environment:production` |

팀 슬러그는 `brown21`, Vercel 프로젝트명은 `toji-gogo`(예전 이름 그대로.
브랜드와 무관하고 바꾸면 위 `sub` 가 함께 바뀌므로 건드리지 않는다).
Issuer Mode 를 Global 로 바꾸면 `iss` 가 `https://oidc.vercel.com` 이 되어
4번을 다시 맞춰야 한다.

### 2. GCP — 프로젝트

**`sado-toji` 프로젝트가 이미 있다.** 그대로 쓴다(이름은 내부용이라 밖에서
안 보인다). **결제 계정을 연결하지 않는다** — GA Data API 는 무료 할당량으로
충분하고, 콘솔 위쪽의 "결제 사용 설정" 띠는 닫으면 된다.

프로젝트 **번호**(이름·ID 가 아니라 숫자 열두 자리)를 적어 둔다.
`console.cloud.google.com/welcome` 의 「프로젝트 정보」 카드 가운데 줄이다.

### 3. GCP — API 둘 켜기

API 및 서비스 → 라이브러리 → 사용 설정. 주소로 바로 가는 편이 빠르다:

- **Google Analytics Data API** — `console.cloud.google.com/apis/library/analyticsdata.googleapis.com`
- **IAM Service Account Credentials API** — `console.cloud.google.com/apis/library/iamcredentials.googleapis.com`

버튼이 「사용」에서 「관리」로 바뀌면 켜진 것이다. Agent Platform 설정의
**API 키는 만들지 않는다** — 그건 다른 제품이고 우리 경로에 쓰이지 않는다.

> 막 켠 직후에는 "API가 사용되지 않았거나 비활성 상태" 오류가 뜰 수 있다.
> 전파에 몇 분 걸린다. 그때는 기다렸다 다시 부른다.

### 4. GCP — Workload Identity 연합

IAM → Workload Identity 제휴 → 풀 만들기.

| 칸 | 값 |
|---|---|
| 풀 ID | `vercel` |
| 공급자 ID | `vercel-oidc` |
| 공급자 종류 | OpenID Connect (OIDC) |
| 발급기관(Issuer) | `https://oidc.vercel.com/brown21` |
| 허용된 대상(Audience) | `https://vercel.com/brown21` |
| 속성 매핑 | `google.subject` = `assertion.sub` |

발급기관·대상은 1번 화면의 `iss`·`aud` 와 **글자까지 같아야 한다.**

### 5. GCP — 서비스 계정

서비스 계정을 하나 만든다(예: `ga-reader`). **키를 만들지 않는다.**

권한은 **서비스 계정의 「권한」 탭이 아니라 4번의 풀 화면에서** 준다.
그 탭의 「액세스 관리」는 반대 방향이다 — *서비스 계정에게* 다른 자원의
역할을 주는 칸이고, 우리가 할 일은 *그 서비스 계정을 가장할 주 구성원을
추가*하는 것이다. 2026-09 콘솔에는 그 탭에 부여 단추가 아예 없다.

풀(`vercel`) 을 열고 → **액세스 권한 부여** → *서비스 계정 가장을 사용하여* →
서비스 계정 `ga-reader` → **필터와 일치하는 ID만**:

| 칸 | 값 |
|---|---|
| 속성 이름 | `subject` |
| 속성 값 | `owner:brown21:project:toji-gogo:environment:production` |

「풀의 모든 ID」를 고르지 않는다 — 그러면 미리보기 배포와 다른 프로젝트까지
GA 를 읽는다. 저장 뒤 구성 파일을 받으라는 창이 뜨면 닫는다. 쓰지 않는다.

이 길이 권하는 길인 이유는 **긴 주 구성원 문자열을 콘솔이 대신 조립**하기
때문이다. 화면이 다르면 Cloud Shell 에서 같은 일을 한 줄로 할 수 있다:

```
gcloud iam service-accounts add-iam-policy-binding \
  ga-reader@<프로젝트ID>.iam.gserviceaccount.com \
  --role=roles/iam.workloadIdentityUser \
  --member="<아래 문자열>"
```

그 **주 구성원** 문자열은 `<프로젝트번호>` 만 채우면 된다. 뒤쪽은 1번 화면의
`sub` 를 그대로 붙인 것이다:

```
principal://iam.googleapis.com/projects/<프로젝트번호>/locations/global/workloadIdentityPools/vercel/subject/owner:brown21:project:toji-gogo:environment:production
```

`principal://`(한 주체)이지 `principalSet://`(집합)이 아니다. 이 한 줄이
전체에서 가장 틀리기 쉬운 값이고, 틀리면 아래 표의 `invalid_grant` 가 난다.

### 6. GA — 서비스 계정을 뷰어로

Google Analytics → 관리 → 속성 액세스 관리 → 서비스 계정 이메일을
**뷰어**로 추가. 그 이상은 주지 않는다 — 우리는 읽기만 한다.

**속성 ID**(숫자. 측정 ID `G-…` 와 다르다)를 적어 둔다.

### 7. Vercel — 환경변수 다섯 (Production 에만)

| 이름 | 값 |
|---|---|
| `GA_PROPERTY_ID` | GA 속성 ID (숫자) |
| `GCP_PROJECT_NUMBER` | GCP 프로젝트 번호 |
| `GCP_WIF_POOL_ID` | 4번의 풀 ID |
| `GCP_WIF_PROVIDER_ID` | 4번의 공급자 ID |
| `GCP_SERVICE_ACCOUNT_EMAIL` | 5번의 서비스 계정 이메일 |

**다섯 개 다 비밀이 아니다.** 식별자일 뿐이라 새어도 그것만으로는 아무것도
못 한다 — 실제 권한은 OIDC 토큰이 증명한다. 그래도 Production 에만 둔다.

넣고 **재배포**하면 /admin 의 GA 칸이 숫자로 바뀐다.

## 막혔을 때

/admin 의 GA 칸이 **오류 본문을 자르지 않고 그대로** 보여 준다. 흔한 것:

| 증상 | 원인 | 조치 |
|---|---|---|
| `환경변수가 아직 없습니다: …` | 7번을 안 했거나 재배포 안 함 | 이름을 그대로 맞추고 재배포 |
| `VERCEL_OIDC_TOKEN` 이 빠졌다고 나옴 | 1번이 안 켜짐 | Vercel 설정에서 켠다 |
| `sts.googleapis.com 400 … invalid_grant` | 발급기관·대상·주체 문자열이 안 맞음 | 4번의 `iss`·`aud`, 5번의 주 구성원을 1번 화면의 클레임과 글자까지 대조 |
| `iamcredentials… 403` | 서비스 계정을 가장할 주 구성원이 없음 | 5번을 풀 화면에서 다시 |
| `analyticsdata… 403` | GA 속성에 뷰어로 안 넣음 | 6번 다시 |
| `… has not been used` | API 를 안 켰거나 전파 중 | 3번, 몇 분 뒤 재시도 |

## 확인하지 못한 것

이 문서를 쓸 때 작업 환경에서 **GCP·Vercel·GA 콘솔에 접속하지 못했다**
(외부 접속 차단). 절차는 공개 문서와 API 규격으로 적었지만 **화면의 메뉴
이름은 다를 수 있다.** 화면에서 다르면 화면이 맞다. `api/ga.js` 가 부르는
주소와 본문은 코드에 그대로 있으니 대조할 수 있다.
