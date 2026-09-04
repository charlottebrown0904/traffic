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
// GetFeatureInfo 의 실제 응답 모양 (2026-09-04 탐침, 화성 향남).
// 지어낸 것이 아니라 서버가 준 것을 그대로 줄인 것이다.
const INFO_TEXT = [
  "Results for FeatureType 'https://www.vworld.kr:lt_c_uq112':",
  "--------------------------------------------",
  "mnum = 64100004159020080001UQB3000530023",
  "alias = null",
  "remark = null",
  "std_sggcd = 41590",
  "sido_cd = 41",
  "dyear = 2008",
  "ucode = UQB300",
  "bon_bun = 0530",
  "bu_bun = 023",
  "sido_name = 경기도",
  "sigg_name = 화성시",
  "uname = 보전관리지역",
  "ag_geom = [GEOMETRY (MultiPolygon) with 123 points]",
  "--------------------------------------------",
  "",
].join("\n");

const infoReply = {
  ok: true, status: 200,
  headers: { get: (k) => (k.toLowerCase() === 'content-type'
    ? 'text/plain; charset=utf-8' : null) },
  text: async () => INFO_TEXT,
};
const emptyInfoReply = {
  ok: true, status: 200,
  headers: { get: (k) => (k.toLowerCase() === 'content-type'
    ? 'text/plain; charset=utf-8' : null) },
  text: async () => 'no features were found\n',
};
// 한도 초과·키 오류는 XML 로 온다. 본문에 우리가 보낸 요청 URL 이
// 실려 오는 경우가 있고, 거기에는 인증키가 붙어 있다.
const infoXmlReply = {
  ok: true, status: 200,
  headers: { get: (k) => (k.toLowerCase() === 'content-type'
    ? 'application/xml; charset=utf-8' : null) },
  text: async () => `<ServiceException>한도 초과 ... key=${KEY}</ServiceException>`,
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
  check('주소를 코드가 만든다 (api.vworld.kr WMS 고정)',
        /https:\/\/api\.vworld\.kr\/req\/wms/.test(src));
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
  console.log('8. 탐침으로 확정한 것을 지킨다');
  // 이 넷은 모두 추측이었다가 서버가 깨준 것이다. 되돌아가지 않게 못박는다.
  stubFetch(pngReply);
  await call({ z: '13', y: '3186', x: '6983' });
  const q = new URL(calls[0].url).searchParams;
  // ① 용도지역은 한 장이 아니라 넷이다. uq112(관리지역)가 빠지면
  //    계획관리·생산관리가 안 나온다 — 우리가 보는 땅이 통째로 빈다.
  const asked = (q.get('LAYERS') || '').split(',');
  check('용도지역 네 장을 함께 부른다',
        ['lt_c_uq111', 'lt_c_uq112', 'lt_c_uq113', 'lt_c_uq114']
          .every((l) => asked.includes(l)),
        asked.join(','));
  check('관리지역(uq112)이 반드시 들어 있다', asked.includes('lt_c_uq112'));
  // ② 레이어 이름은 소문자만 받는다. 대문자는 text/xml 오류가 온다.
  check('레이어 이름이 소문자다', !/[A-Z]/.test(q.get('LAYERS') || ''),
        q.get('LAYERS'));
  // ③ WMS 1.3.0 은 CRS 를 쓴다. SRS 로 보내면 빈 그림(1,784B)이 온다.
  check('CRS 로 보낸다 (SRS 는 빈 그림이 온다)',
        q.get('CRS') === 'EPSG:3857' && !q.has('SRS'),
        `CRS=${q.get('CRS')} SRS=${q.get('SRS')}`);
  check('WMS GetMap 이다 (WMTS 는 404 였다)',
        q.get('REQUEST') === 'GetMap' && q.get('VERSION') === '1.3.0',
        `${q.get('REQUEST')} ${q.get('VERSION')}`);
  // ④ 등록 도메인을 Referer 로 실어야 WMS 가 열린다.
  check('등록된 Referer 를 싣는다',
        calls[0].headers.Referer === 'https://sado-toji.vercel.app/');

  console.log();
  console.log('9. 타일 좌표 → 머케이터 bbox 가 맞는가');
  // 이 계산이 틀리면 그림은 오는데 **땅이 어긋난다.** 눈으로 잡기
  // 어려운 종류라 숫자로 못박는다.
  const EDGE = 20037508.342789244;
  const z0 = handler.mercBbox(0, 0, 0).split(',').map(Number);
  check('z=0 은 세상 전체다',
        Math.abs(z0[0] + EDGE) < 1 && Math.abs(z0[2] - EDGE) < 1, z0.join(','));
  const z1 = handler.mercBbox(1, 0, 0).split(',').map(Number);
  check('z=1 (0,0) 은 서쪽·북쪽 사분면이다',
        Math.abs(z1[0] + EDGE) < 1 && Math.abs(z1[1]) < 1
        && Math.abs(z1[2]) < 1 && Math.abs(z1[3] - EDGE) < 1, z1.join(','));
  // 화성 향남(126.90E, 37.085N)이 z=13 의 그 타일 안에 들어가야 한다.
  // 탐침에서 실제로 용도지역이 그려진 자리다.
  const lon = 126.90, lat = 37.085;
  const mx = lon * EDGE / 180;
  const my = Math.log(Math.tan((90 + lat) * Math.PI / 360)) * EDGE / Math.PI;
  const b = handler.mercBbox(13, 6983, 3186).split(',').map(Number);
  check('화성 향남이 z=13 의 그 타일 안에 있다',
        mx > b[0] && mx < b[2] && my > b[1] && my < b[3],
        `점(${Math.round(mx)},${Math.round(my)}) 타일(${b.map(Math.round).join(',')})`);

  console.log();
  console.log('10. 필지 경계선도 고를 수 있다');
  stubFetch(pngReply);
  const cad = await call({ layer: 'cadastral', z: '16', y: '27958', x: '55916' });
  check('연속지적도를 부른다', cad.code === 200
        && new URL(calls[0].url).searchParams.get('LAYERS') === 'lp_pa_cbnd_bubun',
        String(cad.code));

  console.log();
  console.log('11. 누르면 용도지역 이름이 온다 (GetFeatureInfo)');

  // 색면만 깔면 지적편집도가 아니라 색칠이다. 그 색이 무슨 뜻인지
  // 알 방법이 이 경로 하나뿐이다 — 브이월드는 GetLegendGraphic 을
  // 주지 않는다("유효한 범위 : [GetMap, GetFeatureInfo, GetCapabilities]").
  stubFetch(infoReply);
  const info = await call({ layer: 'zoning', mode: 'info',
                            lat: '37.100000', lon: '126.930000' });
  const iq = calls.length ? new URL(calls[0].url).searchParams : null;
  check('GetFeatureInfo 로 부른다', !!iq && iq.get('REQUEST') === 'GetFeatureInfo',
        iq && iq.get('REQUEST'));
  check('네 장을 함께 묻는다 (QUERY_LAYERS)',
        !!iq && iq.get('QUERY_LAYERS') === handler.LAYERS.zoning);
  check('CRS 로 보낸다 (SRS 는 빈 응답이 온다)',
        !!iq && iq.get('CRS') === 'EPSG:3857' && iq.get('SRS') === null);
  check('가장 작은 형식을 쓴다 (json 5.5KB → plain 466B)',
        !!iq && iq.get('INFO_FORMAT') === 'text/plain', iq && iq.get('INFO_FORMAT'));
  check('사각형 한가운데를 찍는다',
        !!iq && iq.get('I') === '50' && iq.get('J') === '50');
  check('용도지역 이름을 준다', info.body && info.json_.zoning
        && info.json_.zoning.uname === '보전관리지역',
        JSON.stringify(info.json_));
  check('시군구·지번·코드도 함께 준다',
        info.json_.zoning.sigg_name === '화성시'
        && info.json_.zoning.bon_bun === '0530'
        && info.json_.zoning.ucode === 'UQB300');
  // 도형은 5,571B 짜리 좌표 뭉치다. 화면이 쓰지 않으므로 실어 보내지 않는다.
  check('도형(ag_geom)은 안 싣는다', !('ag_geom' in info.json_.zoning));
  check('인증키가 응답에 안 섞인다', !info.body.includes(KEY));

  console.log();
  console.log('12. 빈 땅·오류·엉뚱한 좌표');

  stubFetch(emptyInfoReply);
  const none = await call({ layer: 'zoning', mode: 'info',
                            lat: '37.1', lon: '126.9' });
  // 빈 땅을 누른 것은 오류가 아니다. 200 에 null 로 답해야 화면이
  // "여기는 지정돼 있지 않습니다" 라고 말할 수 있다.
  check('아무것도 없으면 200 에 null', none.code === 200
        && none.json_ && none.json_.zoning === null, String(none.code));

  stubFetch(infoXmlReply);
  const xml = await call({ layer: 'zoning', mode: 'info',
                           lat: '37.1', lon: '126.9' });
  check('XML(한도 초과)은 502 로 알린다', xml.code === 502, String(xml.code));
  check('그 본문을 그대로 돌려주지 않는다 (키가 실려 있다)',
        !xml.body.includes(KEY));

  stubFetch(infoReply);
  const far = await call({ layer: 'zoning', mode: 'info',
                           lat: '48.85', lon: '2.35' });   // 파리
  check('한반도 밖은 부르지 않는다', far.code === 400 && calls.length === 0,
        `${far.code} · 호출 ${calls.length}회`);

  stubFetch(infoReply);
  const nan = await call({ layer: 'zoning', mode: 'info', lat: 'NaN', lon: '1e3' });
  check('숫자가 아니면 부르지 않는다', nan.code === 400 && calls.length === 0,
        `${nan.code} · 호출 ${calls.length}회`);

  console.log();
  console.log('13. 응답 모양이 바뀌면 검사가 먼저 안다');
  // 이 파서가 조용히 빈 값을 내면 화면에는 이름이 안 뜨는데 오류는
  // 안 난다. 그래서 파서를 직접 본다.
  check('덩어리가 여럿이면 이름 있는 것을 고른다',
        handler.parseInfo(
          "Results for FeatureType 'x:lt_c_uq111':\n--------\nalias = null\n"
          + INFO_TEXT).uname === '보전관리지역');
  check('아무것도 없으면 null', handler.parseInfo('no features were found') === null);

  console.log();
  console.log('7. GET 만 받는다');
  stubFetch(pngReply);
  const post = await call({ z: '12', y: '5', x: '5' }, 'POST');
  check('POST 는 405', post.code === 405 && calls.length === 0, String(post.code));

  console.log();
  console.log(failed ? `실패 ${failed}건` : '모두 통과');
  process.exit(failed ? 1 : 0);
})();
