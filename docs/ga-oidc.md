# GA 숫자를 어드민으로 — 키 파일 없이 (OIDC)

GA 는 이미 켜져 있다(측정 ID `G-RW6MCG84SF`, 스트림 '토지랩'). 이 문서는
그 숫자를 **구글 화면에 들어가지 않고 /admin 에서 보는** 설정이다.

**아직 안 돼 있다.** /admin 의 GA 칸이 "환경변수가 아직 없습니다" 와 함께
빠진 이름을 적어 준다. 아래를 마치면 그 자리가 숫자로 바뀐다.

## 왜 키 파일을 안 쓰나

흔한 방법은 서비스 계정 JSON 키를 환경변수에 통째로 넣는 것이다. 그러면
**영구 자격증명이 하나 더 생긴다** — 새면 회수할 때까지 계속 유효하다.

대신 Vercel 이 배포마다 발급하는 OIDC 토큰으로 구글에게 "나는 이 프로젝트의
production 이다" 를 증명하고, **10분짜리 토큰**을 받아 쓴다. 키가 없으니 샐
키도 없다.

    Vercel OIDC → STS 토큰 교환 → 서비스 계정 가장 → GA Data API

`api/ga.js` 가 이 넷을 fetch 로 직접 한다. 라이브러리를 안 쓴다 — 이 저장소에
`package.json` 이 없고 없는 편이 배포가 단순하며, 덤으로 google-auth-library
에서 흔한 audience 어긋남(`invalid_grant`)이 애초에 안 생긴다(우리가 audience
를 직접 적는다).

## 할 일

### 1. Vercel — OIDC 켜기

프로젝트 → Settings → **Secure Backend Access**(또는 OIDC Federation) →
토큰 발급을 켠다. 켜지면 배포에 `VERCEL_OIDC_TOKEN` 이 자동으로 들어온다.

**팀 슬러그를 적어 둔다.** 아래에서 쓴다.

### 2. GCP — 프로젝트

새 프로젝트를 만든다. **결제 계정을 연결하지 않는다** — GA Data API 는
무료 할당량으로 충분하다.

프로젝트 **번호**(이름이 아니라 숫자)를 적어 둔다.

### 3. GCP — API 둘 켜기

API 및 서비스 → 사용 설정:

- **Google Analytics Data API**
- **IAM Service Account Credentials API**

> 막 켠 직후에는 "API가 사용되지 않았거나 비활성 상태" 오류가 뜰 수 있다.
> 전파에 몇 분 걸린다. 그때는 기다렸다 다시 부른다.

### 4. GCP — Workload Identity 연합

IAM → Workload Identity 제휴 → 풀 만들기.

| 칸 | 값 |
|---|---|
| 풀 ID | 예: `vercel` |
| 공급자 ID | 예: `vercel-oidc` |
| 공급자 종류 | OpenID Connect (OIDC) |
| 발급기관(Issuer) | `https://oidc.vercel.com/<팀슬러그>` |
| 허용된 대상(Audience) | `https://vercel.com/<팀슬러그>` |
| 속성 매핑 | `google.subject` = `assertion.sub` |

### 5. GCP — 서비스 계정

서비스 계정을 하나 만든다(예: `ga-reader`). **키를 만들지 않는다.**

그 서비스 계정 → 권한 → 액세스 권한 부여 →
**주 구성원**에 아래를 넣고 역할은 **Workload Identity 사용자**:

```
principal://iam.googleapis.com/projects/<프로젝트번호>/locations/global/workloadIdentityPools/<풀ID>/subject/owner:<팀슬러그>:project:<Vercel프로젝트명>:environment:production
```

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
| `sts.googleapis.com 400 … invalid_grant` | 발급기관·대상·주체 문자열이 안 맞음 | 4·5번의 `<팀슬러그>`·`<프로젝트명>` 을 글자까지 대조 |
| `iamcredentials… 403` | 서비스 계정에 Workload Identity 사용자 역할이 없음 | 5번 다시 |
| `analyticsdata… 403` | GA 속성에 뷰어로 안 넣음 | 6번 다시 |
| `… has not been used` | API 를 안 켰거나 전파 중 | 3번, 몇 분 뒤 재시도 |

## 확인하지 못한 것

이 문서를 쓸 때 작업 환경에서 **GCP·Vercel·GA 콘솔에 접속하지 못했다**
(외부 접속 차단). 절차는 공개 문서와 API 규격으로 적었지만 **화면의 메뉴
이름은 다를 수 있다.** 화면에서 다르면 화면이 맞다. `api/ga.js` 가 부르는
주소와 본문은 코드에 그대로 있으니 대조할 수 있다.
