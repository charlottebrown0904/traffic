# 도메인 이사 — toji.fyi 를 Vercel 로

## 결론 (2026-09-09)

**Cloudflare 로의 완전 이사는 접었습니다.** 도메인만 옮깁니다.

    도메인 등록·DNS   Cloudflare  (그대로)
    호스팅·함수       Vercel      (regions: icn1 = 서울)
    주소              toji.fyi

## 왜 접었나 — 실측

Cloudflare Pages 로 다 옮겨 붙여서 **실제로 재 봤습니다.** 거의 다
됐는데 하나가 막혔습니다.

| 한국 API (Cloudflare 중계기 경유) | 결과 |
| --------------------------------- | ---- |
| 실거래 `data.go.kr`               | 200 정상 |
| KOSIS                             | 200 정상 |
| 도로공사 `data.ex.co.kr`          | 서버 응답함 |
| **브이월드 `api.vworld.kr`**      | **502 거부** |

한국에서 휴대폰으로 열어도 502 였습니다. 즉 **Cloudflare 는 어디서
돌든 브이월드에 못 닿습니다.**

브이월드는 세 곳에 쓰입니다 — 실거래 **지오코딩**, 지적편집도
**타일**, **필지 조회**(레이더의 재료). 이 셋이 죽으면 제품의 절반이
죽습니다.

Vercel 은 `regions: ["icn1"]` 로 서울에 못박을 수 있고, Cloudflare
Workers 에는 그 못이 없습니다. **그 한 줄이 이 제품이 도는 이유입니다.**

## 요금제 — 결정 (2026-09-09)

Vercel **Hobby 는 상업적 이용을 금지**합니다
([plans/hobby](https://vercel.com/docs/plans/hobby) ·
[fair-use](https://vercel.com/docs/limits/fair-use-guidelines)).
정의가 넓어 결제뿐 아니라 제품·서비스 광고까지 포함합니다.

요구사항: **"유료는 나중에 서비스 확장 시 결정한다."**
지금 라이브는 광고도 결제도 없는 무료 분석 도구라 당장은 Hobby 로
둡니다. **경계선은 매물 기능을 켜거나 돈을 받기 시작하는 날**입니다.
그날 Pro($20/월)로 올립니다.

---

## 사람이 해야 할 일 — 대시보드 두 곳

제 컨테이너는 조직 망 정책이 `vercel.com` · `dash.cloudflare.com` ·
`api.vercel.com` 을 막습니다(403). 브라우저를 띄워도 못 갑니다. Vercel
MCP 에도 '기존 도메인을 프로젝트에 붙이는' 도구가 없습니다(구매만).
**아래 둘은 계정 소유자만 할 수 있습니다.**

### 1. Cloudflare Pages 에서 도메인을 뗀다 (붙이셨다면)

`toji-gogo` 프로젝트 → Custom domains → `toji.fyi` 제거.
한 도메인이 두 곳에 동시에 붙을 수 없습니다.

**프로젝트 자체는 아직 지우지 마세요.** 되돌릴 자리로 남겨 둡니다.

### 2. Vercel 에 도메인을 붙인다

프로젝트 → **Settings → Domains → Add** → `toji.fyi`
그리고 `www.toji.fyi` 도 함께.

Vercel 이 **필요한 DNS 레코드를 화면에 띄웁니다.**

### 3. Cloudflare DNS 에 그 레코드를 넣는다

Cloudflare → `toji.fyi` → **DNS → Records → Add record**

일반적으로 이렇습니다 (**화면에 뜬 값이 우선입니다**):

| Type  | Name  | Content                | Proxy status        |
| ----- | ----- | ---------------------- | ------------------- |
| A     | `@`   | `76.76.21.21`          | **DNS only (회색)** |
| CNAME | `www` | Vercel 이 알려주는 값  | **DNS only (회색)** |

Vercel 문서가 "카드에 뜬 값이 진짜다(the card is the source of truth)"
라고 못박고 있습니다. 제가 적은 값은 참고용입니다.

### ⚠️ 주황 구름이면 안 됩니다

Cloudflare 프록시(주황 구름)를 켜면 **인증서 발급이 실패**합니다 —
`Failed to Generate Cert` · `Invalid Configuration` ·
`ERR_SSL_VERSION_OR_CIPHER_MISMATCH` · Error 526 · 리다이렉트 루프.
Vercel 자신도 앞단 리버스 프록시를 권하지 않습니다.

**반드시 `DNS only`(회색 구름).**

### 4. 붙은 뒤 — 바깥 서비스 세 곳

| 어디 | 무엇 | 안 하면 |
| ---- | ---- | ------- |
| 브이월드 | 서비스URL `https://toji.fyi/` | 이미 하셨습니다 ✅ |
| Supabase | Redirect URLs 에 `https://toji.fyi/**` **추가** | 로그인 불가 |
| 카카오·구글 | OAuth 리디렉션에 새 주소 **추가** | 로그인 불가 |

**추가**입니다. 옛 주소(`toji-gogo.vercel.app`)는 **2026-09-10 에
뗐습니다** — 그 주소로는 이제 아무것도 안 열립니다.

### 5. 마지막 — 수집 파이프라인

GitHub → Settings → Secrets → Actions

    REDT_RELAY_URL = https://toji.fyi

**`/api/relay` 를 붙이지 않습니다.** 코드가 알아서 붙입니다 —
`config.py` 가 도메인만 받고 `http.py` 의 `_via_relay()` 가
`f"{cfg.url}/api/relay"` 로 이어 붙입니다. 붙여서 넣으면 실제 호출이
`https://toji.fyi/api/relay/api/relay` 가 되어 404 납니다.

> 이 문서에 한동안 `https://toji.fyi/api/relay` 로 적혀 있었고,
> 2026-09-10 에 실제로 그 값을 넣어 수집이 한 번 더 멈췄습니다.
> 응답 본문이 두 오류를 갈라 줬습니다 —
> `DEPLOYMENT_NOT_FOUND` 는 도메인이 없는 것이고,
> `The page could not be found` 는 도메인은 살아 있고 경로가 없는
> 것입니다. 상태코드(둘 다 404)만 보면 이 구분을 못 합니다.

**4번까지 확인된 뒤에** 바꿉니다. 토큰(`REDT_RELAY_TOKEN`)은 값이
그대로라 안 건드립니다.

---

## 확인은 제가 합니다

`.github/workflows/sitecheck.yml` 을 `base=https://toji.fyi` 로 돌리면
정적 화면·헤더·환경변수·중계기·타일·한국 API 넷을 한 번에 훑고 판정을
냅니다. **화면을 캡쳐할 필요 없습니다.**

## 남겨 둔 것 — Cloudflare 자산

지우지 않았습니다. Vercel 은 이것들을 보지 않습니다.

    functions/_adapter.js · functions/api/*   Vercel 핸들러를 그대로 돌리는 껍데기
    public/_headers · public/_routes.json     Pages 설정
    wrangler.toml                             Pages 설정
    scripts/test_cloudflare.js                양쪽이 같은 것을 내놓는지 검사

브이월드 말고 다른 길이 생기거나(예: 한국 VPS 중계, 브이월드가
Cloudflare 를 허용) 요금 사정이 바뀌면 **하루 안에 다시 갈 수 있습니다.**
그 값어치가 유지비보다 큽니다.

## 이번에 얻은 것 (버려지지 않음)

  sitecheck 워크플로   배포 확인이 러너에서 자동으로 — 캡쳐 왕복이 사라짐
  envcheck             변수가 어디까지 닿았는지 이름만으로 진단
  relay.js 지연 평가   환경변수를 요청 시점에 읽는다 (Vercel 에서도 더 안전)
  실측표               브이월드가 어디서 되고 어디서 안 되는지
