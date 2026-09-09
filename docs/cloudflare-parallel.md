# Cloudflare Pages 병렬 배포 — 재 보고 결정한다

## 왜

Vercel **Hobby 는 상업적 이용을 금지**합니다
([vercel.com/docs/plans/hobby](https://vercel.com/docs/plans/hobby) ·
[Fair Use Guidelines](https://vercel.com/docs/limits/fair-use-guidelines)).
정의가 넓어서 결제를 받는 것뿐 아니라 **제품·서비스를 광고하는 것**,
프로젝트에 관여한 누구든 금전적 이득을 얻는 것까지 포함합니다.

지금 라이브는 광고도 결제도 없는 무료 분석 도구라 아직은 괜찮습니다.
**경계선은 매물 기능을 켜는 날**입니다.

## 세 갈래 중 왜 Cloudflare 인가

|                | Vercel Pro | Cloudflare Pages | Netlify Free |
| -------------- | ---------- | ---------------- | ------------ |
| 비용           | $20/월     | 무료             | 무료         |
| 상업적 이용    | 가능       | **가능**         | 확인 필요    |
| 대역폭         | 1 TB       | **무제한**       | ≈ 15 GB      |
| 배포 횟수      | 넉넉       | 500회/월         | **≈ 20회/월** |
| 함수           | 100만/월   | **10만 요청/일** | 크레딧 차감  |

Netlify 는 2025-09 부터 크레딧 방식이라 **프로덕션 배포가 월 20회**
입니다. 우리는 하루에 세 번도 돕니다 — 여기서 끝입니다.

## 재려는 것 하나

**타일 요청이 Workers 무료 10만/일 안에 드는가.**

`api/tile.js` 가 브이월드 지적편집도를 중계합니다. 용도지역을 켜고
지도를 끌면 타일이 수십 장씩 나갑니다.

**Vercel 과 결정적으로 다른 점:** Vercel 은 `s-maxage` 를 보고 CDN 이
알아서 캐시해 주지만, **Cloudflare 는 Functions 응답을 저절로 캐시하지
않습니다.** 그래서 `functions/api/tile.js` 에서 Cache API 를 직접
씁니다.

그런데 **캐시에 맞아도 Worker 는 돕니다.** 캐시가 줄여 주는 것은
브이월드 호출과 응답 시간이지 **요청 수가 아닙니다.** 10만/일은
캐시로 줄지 않습니다. 이 구분을 흐리면 "캐시 걸었으니 괜찮겠지" 로
잘못 판단하게 됩니다.

거친 어림: 휴대폰 화면 한 번에 타일 12~20장, 10분 둘러보면 300~1,000장.
10만 ÷ 500 ≈ **하루 200세션쯤**이 한도입니다. 지금 규모에선 여유가
있지만 무한하지 않습니다. **어림 말고 실제로 재야 합니다.**

## 구조 — 함수를 복사하지 않았습니다

    api/relay.js          ← 알맹이 (인증키를 쥔 파일)
    api/tile.js           ← 알맹이
      ↑            ↑
      │            └── functions/api/*.js   (Cloudflare 껍데기)
      └─────────────── Vercel 이 그대로 씀

`functions/_adapter.js` 가 모양만 맞춥니다. 로직은 한 줄도 없습니다.
중계 규칙을 고칠 일이 있으면 `api/` 쪽 **한 곳만** 고칩니다.

키를 쥔 파일을 둘로 갈라 두면 한쪽만 고치는 날이 반드시 오고,
그날 새는 것은 키입니다.

## 사장님이 하실 일 (제가 못 하는 것)

계정과 결제가 걸린 일이라 제가 대신 할 수 없습니다.

1. **Cloudflare 계정** — dash.cloudflare.com (무료, 카드 불필요)
2. **Workers & Pages → Create → Pages → Connect to Git**
   - 저장소: `charlottebrown0904/traffic`
   - 브랜치: `main`
   - **빌드 명령: 비움** · **출력 디렉터리: `public`**
   - (`wrangler.toml` 이 저장소에 있어서 대부분 자동으로 잡힙니다)
3. **환경변수 (Settings → Variables and Secrets)** — Production 에
   아래를 넣습니다. **여기 값을 채팅에 붙여넣지 마세요.**

   | 이름              | 값                                    |
   | ----------------- | ------------------------------------- |
   | `DATA_GO_KR_KEY`  | Vercel 에 넣으신 것과 같은 값         |
   | `VWORLD_KEY`      | 같은 값                               |
   | `RELAY_TOKEN`     | 같은 값                               |
   | `KOSIS_KEY`       | 같은 값                               |
   | `EX_API_KEY`      | 같은 값                               |
   | `VWORLD_REFERER`  | `https://<프로젝트>.pages.dev/`       |

   `VWORLD_REFERER` 는 **브이월드 콘솔에 등록된 주소와 맞아야** 합니다.
   안 맞으면 타일이 통째로 안 나옵니다 — 새 주소를 브이월드 콘솔에도
   추가해 주세요.

4. **Supabase** — Authentication → URL Configuration 의 Redirect URLs 에
   `https://<프로젝트>.pages.dev/**` 를 **추가**합니다. 지우지 마세요.
   안 넣으면 새 주소에서 로그인이 안 됩니다.

**도메인은 건드리지 않습니다.** `toji-gogo.vercel.app` 은 그대로 돕니다.

## 확인할 것 (붙인 뒤)

| 보는 것        | 어떻게                                                     |
| -------------- | ---------------------------------------------------------- |
| 어느 쪽인지    | 응답 헤더 `x-served-by: cloudflare-pages`                   |
| 타일 캐시      | 응답 헤더 `x-tile-cache: hit` / `miss`                      |
| **함수 호출 수** | Cloudflare 대시보드 → Workers & Pages → 프로젝트 → Metrics |
| 깨끗한 주소    | `/app` 가 `/app/index.html` 없이 열리는가                   |
| 로그인         | 구글·카카오가 새 주소에서 되는가                            |

`/app` 은 회원 전용이라, 사장님이 직접 열어 보셔야 확인됩니다.

## 되돌리기

Cloudflare 프로젝트를 지우면 끝입니다. 저장소에 남는 것은
`functions/` · `wrangler.toml` · `public/_headers` 셋인데, **Vercel 은
이 셋을 무시합니다.** 지우지 않아도 지금 사이트에 아무 영향이 없습니다.
