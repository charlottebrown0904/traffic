/* 첫 화면에 넣을 **실제 화면 캡쳐**를 만든다 (지시 2026-09-12).
 *
 * 왜 스크립트로 만드나. 손으로 찍으면 화면이 바뀔 때마다 첫 화면의 그림이
 * 조용히 옛것이 된다. 여기서 만들면 `node scripts/build_shots.js` 한 줄로
 * 다시 찍는다. 그리고 무엇을 찍었는지가 코드로 남는다 — 어느 탭, 어느
 * 필터, 어느 자료였는지.
 *
 * 진짜 화면이다. 앱 코드도, /app/data 의 자료도 배포된 것과 같은 것을
 * 쓴다. 가짜로 채운 것은 셋뿐이고 모두 이 상자에서 나갈 길이 막혀 있어서다
 * (egress 차단):
 *   1. Leaflet — CDN 대신 npm 으로 받은 같은 버전(1.9.4)을 끼운다.
 *   2. 로그인 — Supabase 를 부를 수 없으니 '승인된 회원' 으로 둔다.
 *   3. 필지 하나 — 브이월드를 부를 수 없으니 test_map.js 와 같은 예시
 *      필지·표준지를 쓴다. 그 캡쳐는 첫 화면에서 **예시라고 적는다.**
 *
 * 못 찍는 것: 배경 지도(브이월드·OSM 타일). 타일 서버로 나갈 수 없다.
 * 그래서 지도 캡쳐는 우리가 그리는 것(땅값 태그·밴드·거래 점)만 보인다.
 * 배경까지 있는 지도 그림이 필요하면 사람이 찍어 public/brand/shots/
 * 아래 같은 이름으로 덮어쓰면 된다 — 첫 화면은 파일 이름만 본다.
 */
const path = require('path');
const fs = require('fs');
const { spawn, execFileSync } = require('child_process');

function loadPlaywright() {
  for (const m of ['playwright', '/tmp/node_modules/playwright',
                   '/opt/node22/lib/node_modules/playwright']) {
    try { return require(m); } catch (e) { /* 다음 후보 */ }
  }
  return null;
}
/* test_map.js 와 같은 규칙. **headless_shell 을 먼저 찾는다** — 설치된
   playwright 가 낡으면 chrome 을 `--headless=old` 로 띄우려 하고, 요즘
   chrome 은 그 스위치를 지워서 통째로 안 뜬다. */
function chromiumPath() {
  const base = '/opt/pw-browsers';
  if (!fs.existsSync(base)) return undefined;
  for (const d of fs.readdirSync(base)) {
    const p = `${base}/${d}/chrome-linux/headless_shell`;
    if (d.startsWith('chromium_headless_shell') && fs.existsSync(p)) return p;
  }
  for (const d of fs.readdirSync(base)) {
    const p = `${base}/${d}/chrome-linux/chrome`;
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

/* **사람이 찍어 보낸 캡쳐는 덮어쓰지 않는다.** 이 상자는 타일 서버로 나갈
   수 없어 배경 지도가 없는 그림밖에 못 만든다 — 배경이 살아 있는 그림이
   이미 있으면 그쪽이 낫다. 여기 적힌 이름의 .webp 가 있으면 건너뛴다.
   다시 찍고 싶으면 그 파일을 지우고 돌리면 된다. */
const HUMAN = new Set(['map', 'region', 'cadastral', 'parcel']);

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'public', 'brand', 'shots');
const PORT = 8311;
const BASE = `http://127.0.0.1:${PORT}`;

/* Leaflet 은 배포에서 CDN 으로 온다. 이 상자는 CDN 에 못 나가므로 같은
   버전을 npm 으로 받아 끼운다 (없으면 받는다 — registry.npmjs.org 는 열려
   있다). 가짜 지도를 만드는 것이 아니라 **같은 지도 라이브러리**다. */
function leafletDir() {
  const cache = path.join(ROOT, 'node_modules', 'leaflet', 'dist');
  if (fs.existsSync(path.join(cache, 'leaflet.js'))) return cache;
  console.log('Leaflet 1.9.4 를 받습니다 (node_modules)…');
  execFileSync('npm', ['install', '--no-save', '--no-audit', '--no-fund', 'leaflet@1.9.4'],
               { cwd: ROOT, stdio: 'inherit' });
  return cache;
}

/* 예시 필지 하나. test_map.js 가 쓰는 것과 같다 — 브이월드를 부를 수 없어
   필지 조회(mode=parcel)와 표준지 조각을 대신한다. 이 캡쳐는 첫 화면에서
   '예시 자료' 라고 적는다. */
const PARCEL_RES = {
  parcel: {
    pnu: '4111110300100010000', jimok: '전', land_use: '계획관리지역',
    land_use2: '지정되지않음', use_situation: '전', area_m2: 1653,
    road_side: '중로한면', shape: '가로장방형', slope: '평지',
    official_price: 250000, stdr_year: '2025', stdr_month: '01',
    register: '1', jibun_label: '1-1전',
  },
  zones: [
    { label: '농업진흥지역', detail: null,
      note: '농업 관련 시설 외에는 어렵습니다. 진흥구역이 보호구역보다 더 엄합니다.' },
  ],
  addr: { jibun: '경기도 광주시 초월읍 지월리 14-1', road: null,
          sido: '경기도', sigungu: '광주시', umd: '초월읍', ri: '지월리' },
  geom: { type: 'Polygon', coordinates: [[
    [127.0108, 37.3035], [127.0114, 37.3035],
    [127.0114, 37.3044], [127.0108, 37.3044], [127.0108, 37.3035],
  ]] },
};
const VAL = {
  road_index: [['맹지', 0.8], ['광대', 1.25], ['중로', 1.18], ['소로', 1.1],
               ['(불)', 0.88], ['불가', 0.88], ['(가)', 1], ['가능', 1]],
  road_corner_bonus: 0.03,
  shape_index: [['정방', 1], ['가장', 1], ['가로장방', 1], ['세장', 1], ['세로장방', 1],
                ['장방', 1], ['사다리', 0.98], ['삼각', 0.93], ['역삼각', 0.93],
                ['부정', 0.95], ['자루', 0.9]],
  slope_index: { '임야지대': [['평지', 1], ['완경사', 0.95], ['급경사', 0.82]],
                 '*': [['평지', 1], ['완경사', 0.97], ['급경사', 0.88]] },
  use_mismatch: { '임야|대': [0.9, '지목 임야'] },
  special: { '현황도로': [0.33, '현황이 도로'], '자연취락지구': [1.15, '자연취락지구 안'] },
  must_match: ['개발제한구역', '농업진흥', '보전산지'], std_known: ['개발제한구역'],
  area_rules: { '주택지대': [[0, 0.5, 0.95, '과소 필지'], [0.5, 3, 1, null],
                             [3, null, 0.95, '과대 필지']] },
  other: { '관리|전·답': {
    '*': { median: 2.34, q1: 1.82, q3: 2.45, n: 6, level: '전국 · 용도지역군 · 지목군', source: '평가선례' },
    '41': { median: 2.32, q1: 1.82, q3: 2.45, n: 5, level: '같은 시·도 · 용도지역군 · 지목군', source: '평가선례' } } },
  time_clamp: [0.98, 1.03],
  zone_groups: [['관리', ['관리']], ['녹지', ['녹지']], ['농림', ['농림', '자연환경']],
                ['주거', ['주거', '일주', '전주']], ['상업', ['상업']], ['공업', ['공업']]],
  use_groups: [['임야', ['임야', '자연림']], ['전·답', ['전', '답']], ['대', ['대', '주거']],
               ['공장·도로', ['공장', '도로']]],
};
const STD = { sigungu: '41111', n: 3, rows: [
  { pnu: '4111110300100050000', ld: '4111110300', nm: '경기도 광주시 초월읍 지월리', jb: '5',
    y: 2025, pr: 150000, jm: '전', ar: 1500, lu: '계획관리지역', lu2: null, dz: null,
    us: '전', rs: '세로한면(가)', sh: '부정형', sl: '평지', lon: null, lat: null },
  { pnu: '4111110400100070000', ld: '4111110400', nm: '경기도 광주시 초월읍 대쌍령리', jb: '7',
    y: 2025, pr: 200000, jm: '전', ar: 1600, lu: '계획관리지역', lu2: null, dz: null,
    us: '전', rs: '중로한면', sh: '가로장방', sl: '평지', lon: null, lat: null },
  { pnu: '4111110300100090000', ld: '4111110300', nm: '경기도 광주시 초월읍 지월리', jb: '9',
    y: 2025, pr: 300000, jm: '전', ar: 1500, lu: '자연녹지지역', lu2: null, dz: null,
    us: '전', rs: '중로한면', sh: '가로장방', sl: '평지', lon: null, lat: null },
] };

async function main() {
  const pw = loadPlaywright();
  if (!pw) { console.log('건너뜀 — playwright 가 없습니다.'); return 0; }
  const LEAF = leafletDir();
  fs.mkdirSync(OUT, { recursive: true });

  const srv = spawn('npx', ['http-server', '-p', String(PORT), '-s', path.join(ROOT, 'public')],
                    { stdio: 'ignore' });
  const done = [];
  try {
    await new Promise((r) => setTimeout(r, 2500));
    const b = await pw.chromium.launch({ executablePath: chromiumPath() });
    const ctx = await b.newContext({
      viewport: { width: 1180, height: 820 },
      deviceScaleFactor: 2,
      colorScheme: 'light',          // 첫 화면 그림은 밝은 테마로 고정
    });
    const page = await ctx.newPage();

    await page.route('**/leaflet*.js*', (r) => r.fulfill({ status: 200,
      contentType: 'application/javascript', body: fs.readFileSync(`${LEAF}/leaflet.js`, 'utf8') }));
    await page.route('**/leaflet*.css*', (r) => r.fulfill({ status: 200,
      contentType: 'text/css', body: fs.readFileSync(`${LEAF}/leaflet.css`, 'utf8') }));
    for (const pat of ['**/supabase-js*/**', '**/lib/supabase-init.js*', '**/app/supabase.js*'])
      await page.route(pat, (r) => r.fulfill({ status: 200, body: '' }));
    await page.route('**/api/tile?mode=parcel*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(PARCEL_RES) }));
    await page.route('**/app/data/valuation.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(VAL) }));
    await page.route('**/app/data/stdland-41111.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(STD) }));

    await page.addInitScript(() => {
      window.REDT_CONFIG = { apiBase: '', homeUrl: '/' };
      window.SB = {
        channel() { const ch = { on: () => ch, subscribe: (cb) => { if (cb) cb('SUBSCRIBED'); return ch; },
                                 track: () => Promise.resolve(), presenceState: () => ({}) }; return ch; },
        removeChannel: () => Promise.resolve(),
        // 조회수는 진짜 서버 몫이다. 여기서는 **양수**로만 흉내낸다 —
        // 예전 식(46 - i*4)은 태그가 열둘을 넘으면 음수가 되어 캡쳐에
        // '-238명 조회 중' 이 찍혔다.
        rpc: (fn, a) => Promise.resolve({
          data: fn === 'place_view_stats'
            ? (a.keys || []).map((k, i) => ({ place_key: k, n24: 3 + (i * 7) % 41 })) : 1,
          error: null }),
        from() { const q = { select: () => q, eq: () => q,
                             maybeSingle: () => Promise.resolve({ data: null, error: null }) }; return q; },
        // storage 를 **일부러 두지 않는다.** premiumFetch 는 storage 가
        // 있으면 버킷만 보고 실패하면 null 을 돌려준다(폴백 없음). 여기서는
        // 버킷을 부를 수 없으니 storage 를 없애 /app/data 길로 보내고, 그
        // 주소에 예시 표(valuation·stdland)를 끼워 뒀다.
      };
      window.ME = { user: { id: 'u1' }, profile: { status: 'approved', grade: 'B' } };
      window.SBUtil = { me: async () => window.ME };
    });

    const errs = [];
    page.on('pageerror', (e) => errs.push(String(e)));

    const shoot = async (name, target, note) => {
      if (HUMAN.has(name) && fs.existsSync(path.join(OUT, `${name}.webp`))) {
        console.log(`  · ${name}.webp — 사람이 찍은 것을 그대로 둡니다 (배경 지도)`);
        return;
      }
      const el = typeof target === 'string' ? await page.$(target) : target;
      if (!el) { console.log(`  ✗ ${name} — 찍을 것이 없습니다 (${target})`); return; }
      const file = path.join(OUT, `${name}.png`);
      await el.screenshot({ path: file });
      const kb = Math.round(fs.statSync(file).size / 1024);
      done.push([name, kb, note]);
      console.log(`  ✓ ${name}.png  ${kb}KB  ${note}`);
    };

    // ── 1. 지도 — 시·도/시·군 땅값과 조회 중 배지 ─────────────────
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(3500);
    await page.evaluate(() => {
      // 실거래 점을 켜고 수도권 남부로 옮긴다 (물류 벨트)
      const cb = [...document.querySelectorAll('input[type=checkbox]')]
        .find((x) => /IC·영업소/.test(x.closest('label') ? x.closest('label').textContent : ''));
      if (cb && !cb.checked) cb.click();
    });
    await page.waitForTimeout(1500);
    await shoot('map', '#map', '전국 — 영업소 561곳과 시·도별 평당가');

    // ── 1-2. 한 시·군으로 들어가면 읍·면·동 평당가가 보인다 ──────
    //    지시가 말한 '시군구동별 실거래가 조회' 가 이 화면이다. 검색칸으로
    //    옮긴다 (지도 객체를 바깥에서 붙잡지 않는다).
    const went = await page.evaluate(async () => {
      const q = document.getElementById('find-q');
      if (!q) return null;
      q.value = '평택시';
      q.dispatchEvent(new Event('input'));
      await new Promise((ok) => setTimeout(ok, 700));
      const row = document.querySelector('#find-list li');
      if (!row) return null;
      const txt = (row.querySelector('b') || row).textContent.trim();
      // 후보 목록은 click 이 아니라 **mousedown** 을 듣는다 (칸에서 손이
      // 떠나기 전에 골라야 하므로). el.click() 으로는 아무 일도 안 난다.
      row.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      return txt;
    });
    await page.waitForTimeout(2200);
    // 검색은 시·군을 z11 로 잡아 준다. 태그가 **읍·면·동** 으로 갈리는
    // 것은 z13 부터라, 두 단 더 들어간다.
    for (let i = 0; i < 2; i++) {
      const zi = await page.$('.leaflet-control-zoom-in');
      if (!zi) break;
      await zi.click();
      await page.waitForTimeout(700);
    }
    await page.waitForTimeout(1800);
    await shoot('region', '#map', `읍·면·동 평당가 — ${went || '시·군'}`);

    // ── 2. 교통량 순위 — 차종을 골라 본다 ────────────────────────
    await page.evaluate(() => {
      document.querySelector('.tab[data-view="rank"]').click();
    });
    await page.waitForTimeout(900);
    await page.evaluate(() => {
      // 차종은 화물(2·3·4·5종) — 공장·물류 수요를 가장 직접 반영한다.
      const sel = document.getElementById('rank-vehicle');
      if (sel) {
        const opt = [...sel.options].find((o) => /화물/.test(o.textContent));
        if (opt) { sel.value = opt.value; sel.dispatchEvent(new Event('change')); }
      }
      // 연도는 **마지막으로 온전한 해**. 올해 칸은 아직 반년치라 순위가
      // 실제와 다르게 보인다 — 첫 화면에 걸 그림으로는 맞지 않다.
      const yr = document.getElementById('rank-year');
      if (yr) {
        const now = new Date().getFullYear();
        const opt = [...yr.options].find((o) => Number(o.value) === now - 1);
        if (opt) { yr.value = opt.value; yr.dispatchEvent(new Event('change')); }
      }
    });
    await page.waitForTimeout(900);
    await shoot('rank', '#view-rank', 'IC 차종별 통행량 — 화물(2·3·4·5종)');

    // ── 3. 추이 비교 — 한 영업소의 교통량과 용도지역별 땅값 ───────
    await page.evaluate(() => { document.querySelector('.tab[data-view="trend"]').click(); });
    await page.waitForTimeout(900);
    const picked = await page.evaluate(() => {
      const inp = document.getElementById('trend-search');
      const opts = [...document.querySelectorAll('#trend-list option')].map((o) => o.value);
      const want = opts.find((v) => /북평택|발안|덕평/.test(v)) || opts[0];
      if (!want) return null;
      inp.value = want;
      inp.dispatchEvent(new Event('input'));
      return want;
    });
    await page.waitForTimeout(1400);
    // 계열을 용도지역으로 바꿔 고른다 — 지시가 말한 '용도지역별 실거래가와
    // 추이' 가 이 화면의 핵심이다. 반경별(5-10km)은 끈다.
    const series = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#trend-series label')];
      const hit = (re) => rows.filter((l) => re.test(l.textContent));
      const on = [];
      rows.forEach((l) => {
        const cb = l.querySelector('input[type=checkbox]');
        if (!cb) return;
        const want = /계획관리지역|생산관리지역|화물/.test(l.textContent);
        if (want !== cb.checked) cb.click();
        if (want) on.push(l.textContent.trim().split('\n')[0]);
      });
      hit(/./);           // (사용 안 함 — 계열 이름만 돌려준다)
      return on;
    });
    await page.waitForTimeout(1200);
    await shoot('trend', '#view-trend',
                `추이 비교 — ${picked || '영업소'} · ${series.length}계열 (지수 기준=100)`);

    // ── 4. 필지 진단과 현재 가치 (예시 필지) ─────────────────────
    await page.evaluate(() => { document.querySelector('.tab[data-view="explore"]').click(); });
    await page.waitForTimeout(600);
    // 필지 카드는 z12 이상에서만 열린다 (ZONING_MIN_ZOOM). 확대 단추를
    // 눌러 올라간다 — 지도 객체를 바깥에서 붙잡지 않는다.
    // 어디를 누르든 예시 필지가 온다 (조각을 끼웠다). 표준지 조각은 클릭
    // 좌표가 아니라 필지의 PNU(41111…)로 고르므로 자리는 중요하지 않다.
    for (let i = 0; i < 6; i++) {
      const zi = await page.$('.leaflet-control-zoom-in');
      if (!zi) break;
      await zi.click();
      await page.waitForTimeout(350);
    }
    await page.waitForTimeout(800);
    const box = await page.$('#map');
    const bb = await box.boundingBox();
    await page.mouse.click(bb.x + bb.width / 2, bb.y + bb.height / 2);
    await page.waitForTimeout(1500);
    const gotCard = await page.evaluate(() => !!window.__parcel);
    if (!gotCard) console.log('  ! 필지 카드가 안 열렸습니다 — 캡쳐를 건너뜁니다.');
    else {
      await page.evaluate(async () => {
        const b = document.querySelector('.pc-val[data-val="now"]');
        if (b) { b.click(); await new Promise((ok) => setTimeout(ok, 900)); }
      });
      await page.waitForTimeout(700);
      // 필지 진단 — 여섯 축 레이더와 축별 백분위. 카드가 화면보다 길어서
      // 위쪽만 자른다 (자르기는 그림을 고치는 것이 아니다).
      //
      // **사람이 찍은 것이 있으면 건드리지 않는다.** 이 칸은 실제 필지
      // 화면(지번을 가린 것)을 쓰고 있어서, 여기서 다시 찍으면 그것을
      // 예시 필지로 덮어쓴다. shoot() 과 같은 규칙이다.
      if (HUMAN.has('parcel') && fs.existsSync(path.join(OUT, 'parcel.webp'))) {
        console.log('  · parcel.webp — 사람이 찍은 것을 그대로 둡니다 (지번 가림)');
      } else {
        const dbb = await (await page.$('#detail')).boundingBox();
        await page.screenshot({
          path: path.join(OUT, 'parcel.png'),
          clip: { x: dbb.x, y: dbb.y, width: dbb.width, height: Math.min(dbb.height, 470) },
        });
        console.log('  ✓ parcel.png  필지 진단 — 여섯 축 (예시 필지)');
      }
      // 현재 가치 산출표만 따로. #detail 은 스크롤 칸이라 잘리는데 이 안쪽
      // 상자는 제 높이를 갖고 있다.
      await shoot('value', '#pc-val-box', '현재 가치 — 공시지가기준법 다섯 마디 (예시 필지)');
    }

    if (errs.length) console.log('  ! 화면 오류:', errs.slice(0, 3));
    await b.close();
  } finally {
    srv.kill();
  }
  // 다듬기(자르기·줄이기·WebP)는 파이썬 쪽이 한다 — PIL 이 있다.
  try {
    execFileSync('python3', [path.join(ROOT, 'scripts', 'pack_shots.py')],
                 { stdio: 'inherit' });
  } catch (e) {
    console.log('  ! pack_shots.py 가 실패했습니다 — PNG 그대로 남습니다.');
  }
  console.log(`\n${done.length}장 → ${path.relative(ROOT, OUT)}`);
  return 0;
}

main().then((c) => process.exit(c)).catch((e) => { console.error(e); process.exit(1); });
