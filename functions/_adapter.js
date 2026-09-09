/* Vercel 함수를 Cloudflare Pages 에서 그대로 돌리는 어댑터.
 *
 * **함수를 복사하지 않는다.** api/relay.js 는 공공데이터 인증키를 쥔
 * 파일이고, api/tile.js 는 브이월드 키를 쥐고 있다. 이런 파일을 둘로
 * 갈라 두면 한쪽만 고치는 날이 반드시 오고, 그날 새는 것은 키다.
 * 그래서 **같은 파일**을 얇은 껍데기로 감싼다.
 *
 * 두 플랫폼의 모양이 다른 곳은 셋뿐이다.
 *
 *   요청    Vercel  req.query · req.headers (객체)
 *           CF      Request (URL 과 Headers 객체)
 *   응답    Vercel  res.setHeader / res.status / res.json / res.send
 *           CF      new Response(body, init) 를 **돌려준다**
 *   환경변수 Vercel  process.env
 *           CF      onRequest 의 context.env
 *
 * 마지막 것이 급소다. 우리 핸들러는 process.env 를 호출 시점에 읽으므로
 * (모듈을 읽을 때가 아니라), 첫 요청에서 context.env 를 process.env 에
 * 부어 주면 손댈 곳이 없다. nodejs_compat 플래그가 있어야 process 와
 * Buffer 가 있다 — wrangler.toml 에 켜 두었다.
 */

/** Pages 의 환경변수를 process.env 로 옮긴다. 문자열이 아닌
 *  바인딩(KV·R2 등)은 건드리지 않는다.
 *
 *  **한 번만 하고 마는 방식을 쓰지 않는다.** 처음엔 '값이 배포마다
 *  같으니 첫 요청에만' 하고 빗장을 걸어 두었는데, 그러면 **처음 들어온
 *  env 가 영원히 이긴다.** 어쩌다 빈 env 로 한 번 불리면 그 뒤로는
 *  키가 영영 안 채워지고, 화면에는 '키가 설정되지 않았습니다' 만 뜬다 —
 *  키는 멀쩡히 있는데. 검사가 바로 이 자리에서 걸렸다.
 *
 *  값 몇 개를 매번 덮어쓰는 비용은 없는 것과 같다.
 *
 *  **그리고 대입이 먹었는지 확인한다.** process.env 가 읽기 전용이면
 *  `process.env.X = v` 가 예외 없이 조용히 무시된다. 그러면 증상이
 *  '키를 안 넣었을 때' 와 **글자 하나까지 똑같아서**, 대시보드만
 *  들여다보며 넣었다 지웠다를 반복하게 된다. 무시된 것이 확인되면
 *  우리 것으로 갈아 끼운다. */
function copyEnv(env) {
  if (!env) return;
  const pairs = Object.entries(env).filter(([, v]) => typeof v === "string");
  if (!pairs.length) return;
  try {
    for (const [k, v] of pairs) process.env[k] = v;
    // 하나만 되짚어 본다. 먹었으면 나머지도 먹은 것이다.
    const [k0, v0] = pairs[0];
    if (process.env[k0] === v0) return;
  } catch { /* 아래에서 갈아 끼운다 */ }
  // 여기까지 왔다는 것은 process.env 에 못 썼다는 뜻이다.
  try {
    const bag = Object.fromEntries(pairs);
    globalThis.process = { ...(globalThis.process || {}), env: bag };
  } catch { /* 이것도 막히면 손쓸 것이 없다 — envcheck 가 알려 준다 */ }
}

/** Vercel 스타일 (req, res) 핸들러를 onRequest 로 바꾼다. */
export function adapt(handler) {
  return async function onRequest(context) {
    copyEnv(context.env);
    const url = new URL(context.request.url);

    const query = {};
    // 같은 이름이 여러 번 오면 **첫 값**을 쓴다. Vercel 은 배열로 주는데,
    // 우리 핸들러는 어디서도 배열을 기대하지 않는다 — 배열이 들어가면
    // String(...) 이 "a,b" 가 되어 조용히 엉뚱한 값이 된다.
    for (const [k, v] of url.searchParams) {
      if (!(k in query)) query[k] = v;
    }

    const headers = {};
    // Vercel 은 헤더 이름을 소문자로 준다. 핸들러가 req.headers["x-relay-token"]
    // 으로 읽으므로 여기서도 소문자로 맞춘다.
    for (const [k, v] of context.request.headers) headers[k.toLowerCase()] = v;
    if (!headers.host) headers.host = url.host;

    const req = { method: context.request.method, query, headers, url: context.request.url };

    // res 를 흉내 낸다. 핸들러는 res.status(...).json(...) 처럼 이어 부르고,
    // 어떤 자리에서는 res.status(...) 뒤에 send 를 따로 부른다.
    let status = 200;
    const out = new Headers();
    let body = null;
    let done = false;
    const finish = (payload) => {
      if (done) return;          // 두 번 보내면 첫 것만 나간다 (Node 와 같다)
      done = true;
      body = payload;
    };

    const res = {
      setHeader(name, value) { out.set(name, String(value)); return res; },
      getHeader(name) { return out.get(name); },
      status(code) { status = code; return res; },
      json(obj) {
        if (!out.has("content-type")) {
          out.set("content-type", "application/json; charset=utf-8");
        }
        finish(JSON.stringify(obj));
        return res;
      },
      send(payload) {
        // Buffer·Uint8Array 는 그대로 내보낸다. 문자열로 바꾸면 그림이 깨진다.
        finish(payload);
        return res;
      },
      end(payload) { finish(payload === undefined ? "" : payload); return res; },
    };

    await handler(req, res);

    // 어느 플랫폼이 응답했는지 화면에서 바로 알 수 있게 표시한다.
    // 병렬로 띄워 두는 동안 이것이 없으면 무엇을 보고 있는지 헷갈린다.
    out.set("x-served-by", "cloudflare-pages");
    return new Response(body, { status, headers: out });
  };
}
