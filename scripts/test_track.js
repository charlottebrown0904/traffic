/* 유입 경로(UTM)와 방문 통계(GA) 검사 — 네트워크 없음.
 *
 * 2026-09-16 지시: "admin 탭 대쉬보드에 UTM, GA 준비합시다".
 *
 * 여기서 잡고 싶은 것은 셋이다.
 *
 *   1) **첫 접점을 덮어쓰지 않는다.** 광고로 들어왔다가 며칠 뒤 검색으로
 *      돌아와 가입하면, 마지막만 보는 순간 그 가입이 '자연 검색' 이 되고
 *      광고비를 쓴 쪽이 공을 못 받는다. 조용히 틀리는 종류라 검사가 없으면
 *      아무도 모른다.
 *   2) **referrer 는 도메인만.** 경로·질의에는 검색어나 남의 사이트의
 *      개인정보가 붙어 오는 일이 있다.
 *   3) **측정 ID 가 비면 GA 스크립트를 아예 안 붙인다.** 붙여 놓고 ID 만
 *      비우면 구글로 요청은 나가면서 아무 데도 안 쌓인다 — 없는 것과
 *      고장난 것이 같은 얼굴이 되는 자리다.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

let failed = 0;
const check = (label, ok, note = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${note ? ` — ${note}` : ''}`);
  if (!ok) failed++;
};

const SRC = fs.readFileSync(
  path.join(__dirname, '..', 'public', 'lib', 'track.js'), 'utf8');

/** 브라우저 흉내. 저장소·주소·referrer 를 갈아 끼우며 돌린다. */
function run(url, referrer, analytics, store) {
  const mem = Object.assign({}, store || {});
  const head = [];
  const ctx = {
    localStorage: {
      getItem: (k) => (k in mem ? mem[k] : null),
      setItem: (k, v) => { mem[k] = String(v); },
    },
    document: {
      referrer: referrer || '',
      head: { appendChild: (el) => head.push(el) },
      createElement: () => ({ set src(v) { this._src = v; }, get src() { return this._src; } }),
    },
    URL, URLSearchParams, Date, encodeURIComponent, JSON,
  };
  const u = new URL(url);
  ctx.location = { search: u.search, pathname: u.pathname, hostname: u.hostname };
  ctx.window = ctx;
  ctx.ANALYTICS = analytics || {};
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { win: ctx, store: mem, head };
}

console.log('1. 첫 접점을 덮어쓰지 않는다');
const ad = run('https://toji.fyi/?utm_source=naver&utm_medium=cpc&utm_campaign=0916',
               '', {}, {});
check('광고로 들어오면 꼬리표를 담는다',
      ad.win.TRACK.first().utm_source === 'naver'
      && ad.win.TRACK.first().utm_campaign === '0916',
      JSON.stringify(ad.win.TRACK.first()));

// 며칠 뒤 검색으로 다시 와서 가입 — 여기서 덮어쓰면 광고가 공을 잃는다.
const again = run('https://toji.fyi/app', 'https://www.google.com/search?q=토지',
                  {}, ad.store);
check('나중에 다른 경로로 와도 **첫 접점은 그대로**',
      again.win.TRACK.first().utm_source === 'naver',
      String(again.win.TRACK.first().utm_source));
check('마지막 접점은 따로 남는다 (둘을 견줄 수 있게)',
      again.win.TRACK.last().referrer === 'www.google.com',
      String(again.win.TRACK.last().referrer));

console.log();
console.log('2. referrer 는 도메인만 담는다');
const ref = run('https://toji.fyi/', 'https://cafe.naver.com/xyz?q=내이름&id=123', {}, {});
check('경로·질의를 버리고 도메인만',
      ref.win.TRACK.first().referrer === 'cafe.naver.com',
      String(ref.win.TRACK.first().referrer));
check('저장된 글자 어디에도 질의가 없다',
      !JSON.stringify(ref.store).includes('내이름'),
      JSON.stringify(ref.store).slice(0, 80));
const inner = run('https://toji.fyi/app', 'https://toji.fyi/', {}, {});
check('우리 안에서의 이동은 유입이 아니다', inner.win.TRACK.first() === null,
      JSON.stringify(inner.win.TRACK.first()));

console.log();
console.log('3. 프로필에 넣을 모양');
const prof = ad.win.TRACK.forProfile();
check('utm 다섯 칸과 도착 자리를 낸다',
      prof.utm_source === 'naver' && prof.utm_medium === 'cpc'
      && prof.utm_campaign === '0916' && prof.landing_path === '/',
      JSON.stringify(prof));
const refProf = ref.win.TRACK.forProfile();
check("꼬리표 없이 눌러 온 것은 'referral' 로 센다",
      refProf.utm_source === 'referral' && refProf.landing_ref === 'cafe.naver.com',
      JSON.stringify(refProf));
check('아무 경로도 없으면 null (빈 값을 쓰지 않는다)',
      inner.win.TRACK.forProfile() === null);

console.log();
console.log('4. GA 는 측정 ID 가 있을 때만 붙는다');
const noGa = run('https://toji.fyi/', '', { ga4: '' }, {});
check('ID 가 비면 스크립트를 아예 안 붙인다', noGa.head.length === 0,
      `붙인 것 ${noGa.head.length}개`);
check('그때 gtag 도 안 만든다 (있으면 안 쌓이는데 쌓이는 척한다)',
      typeof noGa.win.gtag !== 'function');
const badGa = run('https://toji.fyi/', '', { ga4: 'UA-12345-1' }, {});
check('G- 로 시작하지 않는 값도 거절한다 (UA 는 끝난 규격)',
      badGa.head.length === 0, `붙인 것 ${badGa.head.length}개`);
const onGa = run('https://toji.fyi/', '', { ga4: 'G-ABC12345' }, {});
check('ID 가 있으면 붙인다', onGa.head.length === 1
      && /googletagmanager\.com\/gtag\/js\?id=G-ABC12345/.test(onGa.head[0].src),
      onGa.head.length ? onGa.head[0].src : '없음');
check('IP 를 줄여 보내라고 적는다',
      JSON.stringify(onGa.win.dataLayer).includes('anonymize_ip'),
      JSON.stringify(onGa.win.dataLayer).slice(0, 90));
check('GA 가 없어도 TRACK.event 가 터지지 않는다',
      (function () { try { noGa.win.TRACK.event('x'); return true; } catch (e) { return false; } })());

console.log();
console.log('5. 화면과 이주 파일이 맞물려 있다');
const pages = ['public/index.html', 'public/app/index.html', 'public/account/index.html',
               'public/board/index.html', 'public/admin/index.html'];
const missing = pages.filter((f) =>
  !fs.readFileSync(path.join(__dirname, '..', f), 'utf8').includes('lib/track.js'));
check('다섯 화면이 모두 track.js 를 부른다', missing.length === 0, missing.join(','));
const sql = fs.readFileSync(
  path.join(__dirname, '..', 'supabase', 'migrations', '0012_utm.sql'), 'utf8');
for (const col of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                   'utm_content', 'landing_ref', 'landing_path', 'landing_at']) {
  check(`이주 파일에 ${col} 칸이 있다`, sql.includes(col));
}
// profile_public(0002)은 id·nickname 두 칸만 내보내는 것이 RLS 를 우회해도
// 안전한 유일한 근거다. 유입 경로를 거기 붙이면 그 근거가 깨진다.
check('공개 뷰(profile_public)는 건드리지 않는다',
      !/create or replace view public\.profile_public/.test(sql));
check('집계 함수는 관리자만 (함수 안에서 다시 본다)',
      /is_admin\(\)/.test(sql) && /revoke all on function public\.admin_utm_stats/.test(sql));

console.log();
console.log(failed ? `실패 ${failed}건` : '모두 통과');
process.exit(failed ? 1 : 0);
