/* Cloudflare Pages 껍데기가 Vercel 과 **같은 것을 내놓는가.**
 *
 * 병렬로 띄우는 동안 가장 무서운 것은 '두 사이트가 다르게 군다' 가
 * 아니라 '다른데 안 보인다' 이다. 상태 코드 하나, 헤더 하나가 어긋나면
 * 재는 값이 통째로 헛것이 된다.
 *
 * 그래서 같은 요청을 양쪽에 넣고 **결과를 맞대어 본다.**
 */
const path = require('path');
const fs = require('fs');
const ROOT = path.resolve(__dirname, '..');

let failed = 0;
const check = (label, ok, note = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${note ? ` — ${note}` : ''}`);
  if (!ok) failed++;
};

/* ── 어댑터를 Node 에서 돌린다 ──────────────────────────────────
   functions/_adapter.js 는 ESM 이고 이 검사는 CommonJS 다. 파일을
   읽어 export 만 떼고 평가한다 — 어댑터를 두 벌로 적으면 검사가 보는
   것과 배포되는 것이 달라진다. */
function loadAdapter() {
  const src = fs.readFileSync(path.join(ROOT, 'functions', '_adapter.js'), 'utf8')
    .replace(/^export function adapt/m, 'function adapt');
  const mod = { exports: {} };
  new Function('module', 'exports', 'process', `${src}\nmodule.exports = adapt;`)
    (mod, mod.exports, process);
  return mod.exports;
}
const adapt = loadAdapter();

/* Vercel 쪽 res 흉내 — api/*.js 가 기대하는 모양. */
function fakeRes() {
  const r = { code: 200, headers: {}, body: null };
  r.setHeader = (k, v) => { r.headers[k.toLowerCase()] = String(v); return r; };
  r.status = (c) => { r.code = c; return r; };
  r.json = (o) => { r.body = JSON.stringify(o); return r; };
  r.send = (b) => { r.body = b; return r; };
  return r;
}

/* 같은 핸들러를 양쪽 모양으로 한 번씩 부르고 결과를 견준다. */
async function both(handler, url, { method = 'GET', headers = {} } = {}) {
  const u = new URL(url);
  const query = {};
  for (const [k, v] of u.searchParams) if (!(k in query)) query[k] = v;

  const vres = fakeRes();
  await handler({ method, query, headers: { host: u.host, ...headers } }, vres);

  const cres = await adapt(handler)({
    request: new Request(url, { method, headers }),
    env: {},
  });
  const ctext = await cres.text();
  return {
    vercel: { code: vres.code, body: vres.body, headers: vres.headers },
    cf: { code: cres.status, body: ctext, headers: cres.headers },
  };
}

(async () => {
  console.log('Cloudflare 껍데기 — Vercel 과 같은 것을 내놓는가');
  console.log();
  console.log('1. 중계기 (api/relay.js)');
  const relay = require(path.join(ROOT, 'api', 'relay.js'));

  // 토큰이 없으면 401. 양쪽 다.
  process.env.RELAY_TOKEN = 'test-token-1234567890';
  let r = await both(relay, 'https://x.pages.dev/api/relay?target=https%3A%2F%2Fkosis.kr%2Fa');
  check('토큰 없으면 401 — 양쪽 같다',
        r.vercel.code === 401 && r.cf.code === 401,
        `vercel ${r.vercel.code} · cf ${r.cf.code}`);
  check('본문도 같다', r.vercel.body === r.cf.body, r.cf.body);

  // 허용 안 된 목적지는 403.
  r = await both(relay, 'https://x.pages.dev/api/relay?target=https%3A%2F%2Fevil.example.com%2Fa',
                 { headers: { 'x-relay-token': 'test-token-1234567890' } });
  check('허용 안 된 목적지는 403 — 양쪽 같다',
        r.vercel.code === 403 && r.cf.code === 403,
        `vercel ${r.vercel.code} · cf ${r.cf.code}`);
  check('막힌 호스트 이름을 말해 준다', /evil\.example\.com/.test(r.cf.body), r.cf.body);

  // POST 는 405.
  r = await both(relay, 'https://x.pages.dev/api/relay?target=https%3A%2F%2Fkosis.kr%2Fa',
                 { method: 'POST' });
  check('POST 는 405 — 양쪽 같다',
        r.vercel.code === 405 && r.cf.code === 405,
        `vercel ${r.vercel.code} · cf ${r.cf.code}`);

  // target 이 없으면 400.
  r = await both(relay, 'https://x.pages.dev/api/relay',
                 { headers: { 'x-relay-token': 'test-token-1234567890' } });
  check('target 없으면 400 — 양쪽 같다',
        r.vercel.code === 400 && r.cf.code === 400,
        `vercel ${r.vercel.code} · cf ${r.cf.code}`);

  console.log();
  console.log('2. 타일 (api/tile.js)');
  const tile = require(path.join(ROOT, 'api', 'tile.js'));

  r = await both(tile, 'https://x.pages.dev/api/tile?layer=nope&z=1&x=1&y=1');
  check('없는 레이어는 400 — 양쪽 같다',
        r.vercel.code === 400 && r.cf.code === 400,
        `vercel ${r.vercel.code} · cf ${r.cf.code}`);

  r = await both(tile, 'https://x.pages.dev/api/tile?layer=zoning&z=1&x=9&y=0');
  check('격자 밖은 400 — 양쪽 같다',
        r.vercel.code === 400 && r.cf.code === 400,
        `vercel ${r.vercel.code} · cf ${r.cf.code}`);

  // **캐시 헤더가 같아야 한다.** 이것이 어긋나면 두 사이트의 함수 호출
  // 수가 달라지고, 우리가 재려는 바로 그 숫자가 헛것이 된다.
  check('캐시 헤더가 같다',
        r.vercel.headers['cache-control'] === r.cf.headers.get('cache-control'),
        `vercel "${r.vercel.headers['cache-control']}" · cf "${r.cf.headers.get('cache-control')}"`);

  console.log();
  console.log('3. 어댑터 자체');
  // 어느 쪽이 응답했는지 화면에서 알 수 있어야 한다.
  check('cf 응답에 x-served-by 가 붙는다',
        r.cf.headers.get('x-served-by') === 'cloudflare-pages',
        r.cf.headers.get('x-served-by') || '(없음)');

  // 같은 이름이 여러 번 오면 첫 값만. 배열이 들어가면 String(...) 이
  // "a,b" 가 되어 조용히 엉뚱한 값이 된다.
  const echo = async (req, res) => res.status(200).json({ z: req.query.z });
  const dup = await adapt(echo)({
    request: new Request('https://x.pages.dev/api/tile?z=3&z=9'), env: {},
  });
  check('같은 이름이 겹치면 첫 값만 쓴다',
        JSON.parse(await dup.text()).z === '3');

  // 환경변수가 process.env 로 넘어와야 한다. 안 넘어오면 키를 못 찾아
  // 500 이 나는데, 원인이 '키가 없다' 로 보여 엉뚱한 데를 뒤지게 된다.
  const peek = async (req, res) => res.status(200).json({ v: process.env.__CF_TEST || null });
  const withEnv = await adapt(peek)({
    request: new Request('https://x.pages.dev/api/x'), env: { __CF_TEST: 'hello' },
  });
  check('Pages 환경변수가 process.env 로 넘어온다',
        JSON.parse(await withEnv.text()).v === 'hello');

  // 헤더 이름은 소문자로. 핸들러가 req.headers["x-relay-token"] 으로 읽는다.
  const hdr = async (req, res) => res.status(200).json({ t: req.headers['x-relay-token'] || null });
  const cased = await adapt(hdr)({
    request: new Request('https://x.pages.dev/api/x', { headers: { 'X-Relay-Token': 'ABC' } }),
    env: {},
  });
  check('헤더 이름을 소문자로 맞춘다', JSON.parse(await cased.text()).t === 'ABC');

  console.log();
  console.log('4. 환경변수를 **요청 시점에** 읽는가');
  /* 이것이 이 어댑터의 급소다.
   *
   * Vercel 은 process.env 를 채워 둔 뒤에 파일을 읽으므로, 모듈 맨
   * 위에서 process.env.X 를 상수로 받아 두어도 잘 돈다. Cloudflare 는
   * 반대다 — 파일을 먼저 읽고, 환경변수는 요청이 와야 들어온다
   * (context.env). 그래서 상수로 받아 두면 **영원히 undefined** 이고,
   * 옆에 적어 둔 기본값이 이긴다.
   *
   * api/relay.js 의 브이월드 Referer 가 정확히 그 모양이었다. 그대로
   * 두었으면 VWORLD_REFERER 를 아무리 넣어도 무시되고, 브이월드가
   * Referer 를 보고 거절해 지도가 통째로 비었을 것이다. Vercel 에서는
   * 멀쩡히 도니 **눈으로는 절대 못 잡는다.** */
  const vworld = 'https://api.vworld.kr/req/wfs?a=1';
  let sent = null;
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (_u, init) => {
    sent = (init && init.headers) || {};
    return new Response('ok', { status: 200, headers: { 'content-type': 'text/plain' } });
  };
  try {
    process.env.VWORLD_KEY = 'k';
    delete process.env.VWORLD_REFERER;
    await adapt(relay)({
      request: new Request(
        `https://toji.fyi/api/relay?target=${encodeURIComponent(vworld)}`,
        { headers: { 'x-relay-token': 'test-token-1234567890' } }),
      env: { VWORLD_REFERER: 'https://toji.fyi/', RELAY_TOKEN: 'test-token-1234567890' },
    });
    check('Pages 환경변수의 Referer 가 실제로 실린다',
          sent.Referer === 'https://toji.fyi/', sent.Referer || '(안 실림)');

    sent = null;
    await adapt(relay)({
      request: new Request(
        `https://toji.fyi/api/relay?target=${encodeURIComponent(vworld)}`,
        { headers: { 'x-relay-token': 'test-token-1234567890' } }),
      env: { VWORLD_REFERER: 'https://다른곳.example/', RELAY_TOKEN: 'test-token-1234567890' },
    });
    check('값을 바꾸면 바뀐 값이 실린다 (한 번 읽고 굳지 않는다)',
          sent.Referer === 'https://다른곳.example/', sent.Referer || '(안 실림)');
  } finally {
    globalThis.fetch = realFetch;
    delete process.env.VWORLD_KEY;
  }

  console.log();
  console.log('5. _routes.json — 정적 파일이 Worker 를 안 거치는가');
  /* **이것이 없으면 이사가 통째로 무의미해진다.**
   *
   * Pages 는 functions/ 디렉터리가 있으면 기본적으로 **모든 요청**을
   * Function 으로 보낸다. 그러면 정적 파일 447개와 화면 자료 JSON 까지
   * 전부 Worker 호출로 세어, 무료 10만/일을 하루도 못 가 태운다.
   *
   * _routes.json 으로 /api/* 만 남기면 나머지는 정적 요청이 되어
   * **무제한·무료**다. 자동 생성해 준다고 문서에 적혀 있지만, 재려는
   * 숫자가 걸린 파일을 자동 생성에 맡기지 않는다. */
  const routes = JSON.parse(
    fs.readFileSync(path.join(ROOT, 'public', '_routes.json'), 'utf8'));
  check('include 가 /api/* 하나뿐이다',
        Array.isArray(routes.include) && routes.include.length === 1
        && routes.include[0] === '/api/*',
        JSON.stringify(routes.include));
  // functions/ 에 있는 길이 모두 include 에 덮이는가. 새 함수를 만들고
  // 여기를 안 고치면 그 길만 조용히 404 가 된다.
  const fnPaths = fs.readdirSync(path.join(ROOT, 'functions', 'api'))
    .filter((f) => f.endsWith('.js')).map((f) => `/api/${f.replace(/\.js$/, '')}`);
  check('functions/ 의 길이 모두 include 안에 든다',
        fnPaths.length > 0 && fnPaths.every((p2) => p2.startsWith('/api/')),
        fnPaths.join(', '));
  // 정적 자료가 실수로 딸려 들어가면 안 된다.
  check('화면 자료(/app/data)는 include 밖이다',
        !routes.include.some((p2) => p2.startsWith('/app')),
        JSON.stringify(routes.include));

  console.log();
  console.log('6. _headers 가 vercel.json 과 같은 것을 말하는가');
  const vj = JSON.parse(fs.readFileSync(path.join(ROOT, 'vercel.json'), 'utf8'));
  const hdrs = fs.readFileSync(path.join(ROOT, 'public', '_headers'), 'utf8');
  const vAll = (vj.headers || []).find((h) => h.source === '/(.*)');
  const names = (vAll.headers || []).map((h) => h.key);
  check('보안 헤더 셋이 _headers 에도 있다',
        names.every((n) => new RegExp(`^\\s*${n}:`, 'im').test(hdrs)),
        names.join(', '));
  const vData = (vj.headers || []).find((h) => h.source === '/app/data/(.*)');
  const want = vData.headers[0].value;
  check('화면 자료 캐시 규칙이 글자까지 같다',
        new RegExp(`/app/data/\\*\\s*\\n\\s*Cache-Control:\\s*${want.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'm').test(hdrs),
        want);

  console.log();
  if (failed) { console.log(`실패 ${failed}건`); process.exit(1); }
  console.log('모두 통과');
})();
