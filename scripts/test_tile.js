/* 용도지역 타일 중계 검사 (api/tile.js) — 네트워크 없음.
 *
 * 이 경로는 **브라우저가 직접 부르는 유일한 서버 경로**다. relay.js 는
 * 공유 토큰이 있어야 열리지만 여기는 토큰이 없다(<img> 태그가 헤더를 못
 * 붙인다). 그래서 다른 방식으로 닫혀 있어야 한다.
 *
 * 보는 것
 *   1) 목적지를 받지 않는다 — 열린 중계기가 되지 않는다.
 *   2) 인증키가 응답으로 새지 않는다 (오류 문구·헤더 어디에도).
 *   3) z/x/y 가 정수이고 그 배율의 격자 안일 때만 상류를 부른다.
 *   4) 그림이 아닌 응답(한도 초과·키 오류)을 그림인 척 돌려주지 않는다.
 *   5) 성공한 타일은 길게 캐시하고, 실패는 짧게만 캐시한다.
 */
const path = require('path');

let failed = 0;
const check = (label, ok, note = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${note ? ` — ${note}` : ''}`);
  if (!ok) failed++;
};

const KEY = 'SECRET-VWORLD-KEY-0000';
process.env.VWORLD_KEY = KEY;
process.env.VWORLD_REFERER = 'https://sado-toji.vercel.app/';

const handler = require(path.join('..', 'api', 'tile.js'));

function fakeRes() {
  const r = {
    code: null, body: null, headers: {}, json_: null,
    setHeader(k, v) { r.headers[k.toLowerCase()] = String(v); return r; },
    status(c) { r.code = c; return r; },
    send(b) { r.body = b; return r; },
    json(o) { r.json_ = o; r.body = JSON.stringify(o); return r; },
  };
  return r;
}

// 상류 호출을 가로챈다. 무엇을 어떤 주소로 불렀는지 기록한다.
let calls = [];
function stubFetch(reply) {
  calls = [];
  global.fetch = async (url, opts) => {
    calls.push({ url: String(url), headers: (opts && opts.headers) || {} });
    return reply;
  };
}
const pngReply = {
  ok: true, status: 200,
  headers: { get: (k) => (k.toLowerCase() === 'content-type' ? 'image/png' : null) },
  arrayBuffer: async () => new Uint8Array([0x89, 0x50, 0x4e, 0x47]).buffer,
};
const jsonReply = {
  ok: true, status: 200,
  headers: { get: (k) => (k.toLowerCase() === 'content-type' ? 'application/json' : null) },
  arrayBuffer: async () => new Uint8Array([0x7b, 0x7d]).buffer,
};

const call = async (query, method = 'GET') => {
  const res = fakeRes();
  await handler({ method, query }, res);
  return res;
};

(async () => {
  console.log('1. 목적지를 받지 않는다 (열린 중계기가 되지 않는다)');
  stubFetch(pngReply);
  // relay.js 는 target 을 받는다. 이쪽에 그런 문을 열면 토큰이 없으므로
  // 누구나 우리 서버를 통해 아무 곳이나 부를 수 있게 된다.
  const src = require('fs').readFileSync(
    path.join(__dirname, '..', 'api', 'tile.js'), 'utf8');
  check('target 파라미터를 읽지 않는다', !/query\.target/.test(src));
  check('주소를 코드가 만든다 (api.vworld.kr 고정)',
        /https:\/\/api\.vworld\.kr\/req\/wmts/.test(src));
  const evil = await call({ layer: 'evil', z: '10', y: '1', x: '1' });
  check('모르는 레이어는 거절한다', evil.code === 400 && calls.length === 0,
        `${evil.code} · 상류 호출 ${calls.length}회`);

  console.log();
  console.log('2. 인증키가 응답으로 새지 않는다');
  stubFetch(jsonReply);   // 한도 초과처럼 그림이 아닌 응답
  const bad = await call({ z: '10', y: '1', x: '1' });
  const dump = JSON.stringify({ b: bad.body, h: bad.headers });
  check('오류 문구에 키가 없다', !dump.includes(KEY), bad.body);
  check('헤더에도 키가 없다', !JSON.stringify(bad.headers).includes(KEY));
  check('상류 주소에는 키가 붙어 있다 (실제로 인증은 한다)',
        calls.length === 1 && calls[0].url.includes(KEY));
  check('등록된 Referer 를 실어 보낸다 (웹사이트 유형 키)',
        calls[0].headers.Referer === 'https://sado-toji.vercel.app/',
        String(calls[0].headers.Referer));

  console.log();
  console.log('3. z/y/x 를 검사한 뒤에만 상류를 부른다');
  for (const [q, why] of [
    [{ z: 'abc', y: '1', x: '1' }, '숫자가 아님'],
    [{ z: '10', y: '-1', x: '1' }, '음수'],
    [{ z: '10', y: '1.5', x: '1' }, '소수'],
    [{ z: '10', y: '1e3', x: '1' }, '지수 표기'],
    [{ z: '99', y: '1', x: '1' }, '배율 초과'],
    // 배율 10 의 격자는 한 변이 1024 다. 1024 는 그 밖이다.
    [{ z: '10', y: '1024', x: '1' }, '격자 밖'],
  ]) {
    stubFetch(pngReply);
    const r = await call(q);
    check(`거절: ${why}`, r.code === 400 && calls.length === 0,
          `${r.code} · 상류 ${calls.length}회`);
  }
  stubFetch(pngReply);
  const ok = await call({ z: '10', y: '1023', x: '0' });
  check('격자 안 경계값은 통과한다', ok.code === 200 && calls.length === 1,
        `${ok.code} · 상류 ${calls.length}회`);

  console.log();
  console.log('4. 그림이 아닌 것을 그림인 척 돌려주지 않는다');
  stubFetch(jsonReply);
  const notImg = await call({ z: '12', y: '5', x: '5' });
  check('502 로 알린다', notImg.code === 502, String(notImg.code));
  check('content-type 을 image 로 안 붙인다',
        !/^image\//.test(notImg.headers['content-type'] || ''),
        notImg.headers['content-type'] || '(없음)');

  console.log();
  console.log('5. 캐시 — 성공은 길게, 실패는 짧게');
  stubFetch(pngReply);
  const good = await call({ z: '12', y: '5', x: '5' });
  const cc = good.headers['cache-control'] || '';
  const maxAge = Number((/max-age=(\d+)/.exec(cc) || [])[1] || 0);
  check('성공 타일을 길게 캐시한다 (CDN 이 반복 요청을 받아준다)',
        maxAge >= 3600, cc);
  check('그림으로 돌려준다',
        /^image\//.test(good.headers['content-type'] || '') && Buffer.isBuffer(good.body),
        good.headers['content-type'] || '(없음)');
  const badAge = Number((/max-age=(\d+)/.exec(bad.headers['cache-control'] || '') || [])[1] || 999);
  // 실패를 길게 캐시하면 한도가 풀린 뒤에도 빈 화면이 오래 남는다.
  check('실패는 길게 캐시하지 않는다', badAge <= 60,
        bad.headers['cache-control'] || '(없음)');

  console.log();
  console.log('6. 키가 없으면 조용히 죽지 않고 말한다');
  delete process.env.VWORLD_KEY;
  stubFetch(pngReply);
  const noKey = await call({ z: '12', y: '5', x: '5' });
  check('503 으로 알린다', noKey.code === 503, String(noKey.code));
  check('상류를 부르지 않는다', calls.length === 0, `${calls.length}회`);
  process.env.VWORLD_KEY = KEY;

  console.log();
  console.log('7. GET 만 받는다');
  stubFetch(pngReply);
  const post = await call({ z: '12', y: '5', x: '5' }, 'POST');
  check('POST 는 405', post.code === 405 && calls.length === 0, String(post.code));

  console.log();
  console.log(failed ? `실패 ${failed}건` : '모두 통과');
  process.exit(failed ? 1 : 0);
})();
