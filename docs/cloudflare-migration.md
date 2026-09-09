# Cloudflare 로 완전 이사 — toji.fyi

## 왜

Vercel **Hobby 는 상업적 이용을 금지**합니다
([vercel.com/docs/plans/hobby](https://vercel.com/docs/plans/hobby) ·
[Fair Use Guidelines](https://vercel.com/docs/limits/fair-use-guidelines)).
정의가 넓어 결제뿐 아니라 **제품·서비스 광고**까지 포함합니다.

Cloudflare Pages 는 무료 요금제에서 **상업적 이용을 허용**하고 대역폭이
무제한입니다. 도메인도 같은 곳에 있으니 관리할 곳이 하나 줍니다.

## 이사 순서 — **옛 사이트를 먼저 끄지 않습니다**

    1. 코드          끝났습니다 (아래 '무엇이 바뀌었나')
    2. Pages 프로젝트 만들기 + 환경변수         ← 사장님
    3. *.pages.dev 로 먼저 확인                 ← 사장님 + 저
    4. toji.fyi 붙이기                          ← 사장님
    5. 바깥 서비스 세 곳에 새 주소 등록          ← 사장님
    6. 수집 파이프라인 전환 (REDT_RELAY_URL)     ← 사장님
    7. 다 되면 Vercel 내리기                     ← 마지막

**3번이 끝나기 전에는 아무것도 안 끕니다.** toji-gogo.vercel.app 은
6번까지 그대로 돕니다. 되돌리려면 Pages 프로젝트만 지우면 됩니다.

## 무엇이 바뀌었나 (코드)

    functions/_adapter.js       Vercel 핸들러를 Cloudflare 에서 그대로 돌린다
    functions/api/{relay,tile}  api/*.js 를 **복사하지 않고** 감싼다
    public/_headers             vercel.json 의 헤더
    wrangler.toml               프로젝트 이름 toji · nodejs_compat
    기본 주소                   toji-gogo.vercel.app → toji.fyi (14곳)

함수는 한 벌뿐입니다. `api/relay.js` 와 `api/tile.js` 가 알맹이고,
`functions/` 는 모양만 맞추는 껍데기입니다. 키를 쥔 파일을 둘로 갈라
두면 한쪽만 고치는 날이 반드시 오고, 그날 새는 것은 키입니다.

### 잡아 둔 함정 하나

Vercel 은 `process.env` 를 채운 **뒤에** 파일을 읽습니다. Cloudflare 는
반대로 파일을 먼저 읽고 환경변수는 요청이 와야 들어옵니다. 그래서
모듈 맨 위에서

    referer: process.env.VWORLD_REFERER || "https://…/"

처럼 **상수로 받아 두면 Cloudflare 에서는 영원히 undefined** 이고 옆에
적어 둔 기본값이 이깁니다. 브이월드가 Referer 를 보고 거절해 지도가
통째로 빕니다. **Vercel 에서는 멀쩡히 도니 눈으로는 못 잡습니다.**

함수로 바꿔 요청 시점에 읽게 했고, `scripts/test_cloudflare.js` 가
값을 바꿔 가며 실제로 실리는지 봅니다.

## 2. 사장님 — Pages 프로젝트

1. **dash.cloudflare.com → Workers & Pages → Create → Pages → Connect to Git**
2. 저장소 `charlottebrown0904/traffic`, 브랜치 **`main`**
3. **프로젝트 이름은 `toji`** — `wrangler.toml` 의 이름과 같아야 합니다
4. **빌드 명령 비움 · 출력 디렉터리 `public`**
5. **Settings → Variables and Secrets → Production** 에 여섯 개.
   Vercel 에 넣으신 것과 **같은 값**입니다.
   **값을 채팅에 붙여넣지 마세요.**

   | 이름              | 값                     |
   | ----------------- | ---------------------- |
   | `DATA_GO_KR_KEY`  | Vercel 것과 같음       |
   | `VWORLD_KEY`      | 같음                   |
   | `RELAY_TOKEN`     | 같음                   |
   | `KOSIS_KEY`       | 같음                   |
   | `EX_API_KEY`      | 같음                   |
   | `VWORLD_REFERER`  | `https://toji.fyi/`    |

## 3. 먼저 pages.dev 로 확인

주소를 알려 주시면 제가 헤더로 확인합니다.

| 보는 것          | 어떻게                                       |
| ---------------- | -------------------------------------------- |
| 어느 쪽이 응답했나 | 헤더 `x-served-by: cloudflare-pages`         |
| 타일 캐시        | 헤더 `x-tile-cache: hit` / `miss`            |
| **함수 호출 수** | 대시보드 → 프로젝트 → Metrics                |
| 깨끗한 주소      | `/app` 이 `.html` 없이 열리는가              |

## 4. toji.fyi 붙이기

프로젝트 → **Custom domains → Set up a domain → `toji.fyi`**.
도메인이 같은 Cloudflare 계정에 있어 DNS 는 자동으로 잡힙니다.
`www.toji.fyi` 도 함께 붙이시면 좋습니다.

## 5. 바깥 서비스 세 곳 — **여기를 빠뜨리면 조용히 고장납니다**

| 어디            | 무엇                                                              |
| --------------- | ----------------------------------------------------------------- |
| **브이월드**    | 서비스URL 에 `https://toji.fyi/` **추가**. 안 하면 지도 배경이 통째로 안 나옵니다 |
| **Supabase**    | Authentication → URL Configuration → Redirect URLs 에 `https://toji.fyi/**` **추가**. 안 하면 로그인이 안 됩니다 |
| **카카오·구글** | OAuth 리디렉션 주소에 새 도메인 **추가**                          |

셋 다 **추가**입니다. 옛 주소를 지우는 것은 7번에서 합니다.

## 6. 수집 파이프라인 전환

GitHub → Settings → Secrets and variables → Actions

    REDT_RELAY_URL = https://toji.fyi/api/relay

이걸 바꾸면 수집이 새 중계기를 씁니다. **바꾸기 전에 3번이 끝나
있어야 합니다** — 안 그러면 수집이 통째로 섭니다(2026-09-08 에 한 번
겪었습니다).

바꾸신 뒤 `점검 (키·네트워크)` 로 워크플로를 한 번 돌리면 중계기가
살아 있는지 확인됩니다.

## 7. 마지막 — Vercel 내리기

**3~6번이 다 확인된 뒤에** 합니다.

1. Vercel 프로젝트를 **Pause** (삭제 말고) — 며칠 두고 봅니다
2. 브이월드·Supabase·OAuth 에서 옛 주소를 지웁니다
3. 조용하면 Vercel 프로젝트 삭제, 저장소에서 `vercel.json` 제거

`api/` 는 **지우지 않습니다.** 알맹이가 거기 있습니다.

## 되돌리기

3번 전이면 Pages 프로젝트 삭제로 끝입니다. 저장소에 남는
`functions/`·`wrangler.toml`·`public/_headers` 는 Vercel 이 보지 않습니다.
