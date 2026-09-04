/* 지도 동작 검사 — 가짜 Leaflet 을 끼워 실제 코드 경로를 돌린다.
 *
 * 이 검사가 필요한 이유. 지도는 CDN 의 Leaflet 이 있어야 그려지는데,
 * 검사 환경에서는 그것이 없다. 그래서 지금까지 지도 코드는 사실상
 * 검사 밖에 있었고, 화면을 열어 눈으로 보는 수밖에 없었다.
 *
 * 보는 것
 *   1) 영업소 색이 교통량 4분위다 (평가가 아니다). 몇 곳에 색이 붙는지도 센다.
 *   2) 밴드가 선 + 음영이다.
 *   3) 큰 원부터 그린다 — 음영이 있으므로 순서를 뒤집으면 가까운 밴드가
 *      먼 밴드에 덮인다.
 *   4) '전체 IC 반경' 이 모든 영업소의 반경을 그린다.
 */
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

function loadPlaywright() {
  for (const m of ['playwright', '/tmp/node_modules/playwright',
                   '/opt/node22/lib/node_modules/playwright']) {
    try { return require(m); } catch (e) { /* 다음 후보 */ }
  }
  return null;
}
function chromiumPath() {
  const base = '/opt/pw-browsers';
  if (!fs.existsSync(base)) return undefined;
  for (const d of fs.readdirSync(base)) {
    const p = `${base}/${d}/chrome-linux/headless_shell`;
    if (d.startsWith('chromium_headless_shell') && fs.existsSync(p)) return p;
  }
  return undefined;
}
const pw = loadPlaywright();
if (!pw) { console.log('지도 검사 건너뜀 — playwright 가 없습니다.'); process.exit(0); }
const { chromium } = pw;

const ROOT = path.resolve(__dirname, '..');
const PORT = 8213;
const BASE = `http://127.0.0.1:${PORT}`;

let failed = 0;
const check = (label, ok, note = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${note ? ` — ${note}` : ''}`);
  if (!ok) failed++;
};

const FAKE_LEAFLET = () => {
  const rec = { circles: [], markers: [], tiles: [], tradeOpts: [], panes: {} };
  window.__map = rec;
  // 무리(layerGroup)마다 자기가 담은 것을 따로 들고 있어야 한다.
  // 예전에는 모두가 rec 하나에 밀어 넣어서, 밴드 무리가 clearLayers 를
  // 부르면 거래 점 기록까지 같이 지워졌다. 그러면 '거래가 안 그려진다'
  // 와 '다른 무리가 지웠다' 를 구분할 수 없다.
  const groups = [];
  const sync = () => {
    rec.circles.length = 0;
    rec.tradeOpts.length = 0;
    groups.forEach((g) => g._items.forEach((x) => {
      if (x.__circle) rec.circles.push(x.__opts);
      else if (x.__marker) rec.tradeOpts.push(x.__opts);
    }));
  };
  const grp = () => {
    const g = { _n: 0, _items: [],
      addLayer(x) { g._n++; if (x) g._items.push(x); sync(); return g; },
      clearLayers() { g._n = 0; g._items.length = 0; sync(); return g; },
      // 진짜 Leaflet 의 layerGroup 이 갖고 있는 것. 없으면 이것을 쓰는
      // 코드가 조용히 undefined 로 빠지고, 검사는 '건너뜀' 으로 초록이
      // 된다 — 건너뛴 검사는 통과가 아니라 **안 본 것**이다.
      getLayers() { return g._items; },
      addTo() { return g; } };
    groups.push(g);
    return g;
  };
  const chain = (extra) => Object.assign({
    addTo() { return this; }, on() { return this; },
    bindTooltip() { return this; }, setStyle() { return this; },
    getLatLng() { return { lat: 0, lng: 0 }; },
  }, extra);
  window.L = {
    map: () => chain({
      setView() { return this; }, fitBounds() { return this; },
      panTo() { return this; }, invalidateSize() { return this; },
      getZoom() { return 7; },
      // 진짜 Leaflet 의 판(pane). 없으면 createPane 이 undefined 를 돌려
      // .style 에서 터지고, 지도 전체가 안 그려진다.
      createPane(name) {
        const el = document.createElement('div');
        el.className = 'leaflet-pane leaflet-' + name;
        document.body.appendChild(el);
        rec.panes[name] = el;
        return el;
      },
    }),
    tileLayer: (url) => { rec.tiles.push(url); return chain(); },
    layerGroup: grp,
    circle: (ll, opts) => chain({ __circle: true, __opts: opts }),
    circleMarker: (ll, opts) => {
      const m = chain({
        setStyle(o) { Object.assign(this.__opts, o); return this; },
        openTooltip() { return this; }, unbindTooltip() { return this; },
      });
      m.__opts = Object.assign({}, opts);
      // 진짜 Leaflet 은 만들 때 준 값을 layer.options 로 들고 있다.
      m.options = m.__opts;
      m.__marker = true;
      rec.markers.push(m.__opts);
      return m;
    },
    // 거래는 이제 원이 아니라 divIcon 표식이다. 옵션을 안 들고 있으면
    // 검사가 '무슨 모양인지' 를 볼 수 없고, 그러면 초록으로 통과하면서
    // 화면은 예전 그대로일 수 있다.
    marker: (ll, opts) => {
      const m = chain();
      m.options = Object.assign({}, opts);
      return m;
    },
    divIcon: (opts) => ({ options: Object.assign({}, opts) }),
    latLngBounds: () => ({ pad: () => ({}) }),
    // 말풍선. 진짜 Leaflet 은 .leaflet-popup-content 안에 내용을 그리고
    // map.hasLayer(popup) 으로 아직 열려 있는지 알 수 있다. 그 두 가지가
    // 없으면 askZoning 이 조용히 아무것도 안 하고 끝난다 —
    // **검사가 초록인데 화면은 비는** 그 모양이 된다.
    popup: () => {
      const el = document.createElement('div');
      el.className = 'leaflet-popup-content';
      const p = {
        __popup: true, __open: false,
        setLatLng() { return p; },
        setContent(html) { el.innerHTML = html; return p; },
        openOn(m) {
          p.__open = true;
          document.body.appendChild(el);
          if (m && !m.hasLayer) m.hasLayer = (x) => !!(x && x.__open);
          return p;
        },
      };
      return p;
    },
  };
};

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PORT),
                                '--directory', path.join(ROOT, 'public')],
                    { stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 900));
  const browser = await chromium.launch({ executablePath: chromiumPath() });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    for (const pat of ['**/lib/supabase-init.js*', '**/app/supabase.js*',
                       '**/supabase-js*/**', '**/leaflet*.js', '**/leaflet*.css'])
      await page.route(pat, (r) => r.fulfill({ status: 200, body: '' }));

    // 영업소 하나를 '통행량 미공개' 로 표시해 내려준다. 실제 자료에는
    // 마도(805)처럼 도로공사 TCS 에 통행량이 없는 민자 영업소가 들어
    // 있는데, 아직 좌표가 안 붙어 커밋된 파일에는 없을 수 있다. 검사가
    // 자료의 우연에 기대면 안 되므로 여기서 한 곳을 만들어 넣는다.
    const TG_FILE = path.join(ROOT, 'public', 'app', 'data', 'tollgates.json');
    let hollowId = null;
    if (fs.existsSync(TG_FILE)) {
      const rows = JSON.parse(fs.readFileSync(TG_FILE, 'utf8'));
      if (rows.length) {
        rows[0].no_traffic = true;
        hollowId = String(rows[0].tollgate_id);
        await page.route('**/app/data/tollgates.json*', (r) => r.fulfill({
          status: 200, contentType: 'application/json',
          body: JSON.stringify(rows),
        }));
      }
    }
    // 매물 핀도 IC 아래 판에 들어가는지 본다. 정적 배포에는 매물 API 가
    // 없어 화면에 매물이 한 건도 안 뜨는데, 그러면 이 경로는 영영 검사
    // 밖에 남는다. API 를 흉내내 한 건 내려준다 — 검사가 자료의 우연에
    // 기대면 안 된다.
    const FAKE_LISTING = {
      id: 1, kind: 'land', title: '검사용 매물', price_manwon: 12000,
      lat: 37.2, lon: 127.05, status: 'active', memo: '', broker_name: '검사',
      address: '경기도 어딘가', area_m2: 1000,
    };
    // 세 가설 판정. 세 가지 판정 색과, 95% 구간이 0 을 품는 줄과 안 품는
    // 줄을 한꺼번에 넣는다 — 화면이 이 둘을 갈라 보여주는지가 이 탭의
    // 존재 이유다.
    const FAKE_VERDICTS = {
      generated_at: '2026-09-04T00:00:00+00:00',
      kind: 'land', volume_col: 'volume_freight',
      synthetic: false, controlled: false, controls: [],
      pre_trend_ok: false, alpha: 0.05, min_obs: 50, min_clusters: 10,
      hypotheses: [
        { key: 'H1', name: 'H1 IC 개통', claim: '개통하면 오른다',
          verdict: '아직 모름', why: '표본이 없습니다.', rows: [] },
        { key: 'H2', name: 'H2 교통량', claim: '교통량이 늘면 오른다',
          verdict: '지지', why: '3-5km 에서 유의, 위약은 깨끗합니다.',
          rows: [
            { label: '3-5km · 통제 전', band: '3-5', model: '통제 전', var: null,
              note: '', n: 2356, clusters: 210, beta: 0.387, se: 0.129,
              p: 0.003, ci_lo: 0.135, ci_hi: 0.639 },
            { label: '5-10km · 통제 전', band: '5-10', model: '통제 전', var: null,
              note: '위약', n: 2356, clusters: 210, beta: 0.102, se: 0.105,
              p: 0.332, ci_lo: -0.104, ci_hi: 0.308 },
          ] },
        { key: 'H3', name: 'H3 인구·산단', claim: '인구가 늘면 오른다',
          verdict: '기각', why: '계수가 0 과 구분되지 않습니다.', rows: [] },
      ],
    };
    // 행정구역 인구. 크기를 세 단으로 끊었으므로 **세 단에 하나씩** 넣는다.
    // 한 단이라도 비면 그 단이 제 크기로 그려지는지 볼 수 없다.
    const FAKE_REGIONS = [
      { sigungu_cd: '41110', name: '수원시', lat: 37.263, lon: 127.028,
        n_umd: 40, pop: { '2024': 1200000, '2025': 1000000 } },   // 50만 초과
      { sigungu_cd: '41460', name: '용인시', lat: 37.241, lon: 127.178,
        n_umd: 35, pop: { '2024': 350000, '2025': 340000 } },     // 20만~50만
      { sigungu_cd: '41220', name: '평택시', lat: 36.992, lon: 127.112,
        n_umd: 30, pop: { '2024': 120000, '2025': 118000 } },     // 5만~20만
      { sigungu_cd: '47940', name: '울릉군', lat: 37.484, lon: 130.905,
        n_umd: 3, pop: { '2024': 10000, '2025': 10000 } },        // 5만 이하
    ];
    await page.route('**/app/data/regions.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_REGIONS),
    }));
    await page.route('**/app/data/verdicts.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_VERDICTS),
    }));
    await page.route('**/api/fees*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ listing_fee_krw: 50000, listing_days: 30,
                             payment_connected: false, notice: '검사' }),
    }));
    await page.route('**/api/listings*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify([FAKE_LISTING]),
    }));
    await page.addInitScript(() => {
      // 정적 배포는 apiBase 가 비어 있어 매물 탭이 통째로 꺼진다.
      // 검사에서는 켜 두고 위에서 막아 둔 응답을 받게 한다.
      window.REDT_CONFIG = { apiBase: '/api', homeUrl: '/' };
      window.SB = {};
      // 승인된 회원으로 들어간다. 승인 관문 자체는 test_gate.js 가 본다.
      window.SBUtil = { me: async () => ({ user: { id: 'u1' },
        profile: { status: 'approved' } }) };
    });
    await page.addInitScript(FAKE_LEAFLET);
    const errs = [];
    page.on('pageerror', (e) => errs.push(String(e)));
    await page.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#all-bands', { timeout: 20000 });
    await page.waitForTimeout(3500);

    check('지도 코드가 예외 없이 돈다', errs.length === 0, errs.slice(0, 2).join(' / '));

    console.log();
    console.log('1. 영업소 색 = 교통량 4분위');
    const m = await page.evaluate(() => window.__map.markers);
    check('영업소 마커가 그려진다', m.length > 300, `${m.length}개`);
    const fills = new Set(m.map((x) => x.fillColor));
    // 4분위 + '자료 없음' = 최대 5가지. 분면(4가지)만 나오면 예전 코드다.
    check('색이 4분위 램프에서 온다',
          [...fills].filter((c) => /^rgb|^#/.test(c || '')).length >= 4,
          [...fills].join(' '));
    const sized = new Set(m.map((x) => x.radius));
    check('교통량이 많을수록 크다 (색 말고도 구별된다)', sized.size >= 4,
          [...sized].sort((a, b) => a - b).join(' '));

    console.log();
    console.log('2. 배경 지도에 키가 필요 없다');
    const tiles = await page.evaluate(() => window.__map.tiles);
    // 배경 지도(OSM) + 용도지역 색면 + 필지 경계선 = 3장.
    // 뒤의 둘은 우리 서버를 지난다(키를 페이지에 안 적기 위해).
    check('타일 원천이 셋이다 (배경 + 용도지역 + 필지선)', tiles.length === 3,
          tiles.join(' '));
    check('API 키를 요구하는 서비스가 아니다',
          tiles.every((u) => !/carto|stadia|mapbox|thunderforest|apikey/i.test(u)),
          tiles.join(' '));

    // ── 용도지역 배경이 실제로 붙어 있는가 ──
    //
    // 이 검사가 왜 있나. 이 기능을 한 번 '넣었다' 고 보고했는데 편집
    // 스크립트가 중간에 실패해서 **디스크에 안 써져 있었다.** 파일은
    // 문법상 멀쩡했고 아무도 그 함수를 부르지 않아서 다른 검사도 전부
    // 초록이었다. 없는 기능을 있다고 말한 셈이다.
    //
    // 그래서 '함수가 있다' 가 아니라 **'타일 층이 실제로 만들어졌다'** 를
    // 본다. 부르지 않으면 여기서 걸린다.
    const zone = tiles.find((u) => /layer=zoning/.test(u));
    const cad = tiles.find((u) => /layer=cadastral/.test(u));
    check('용도지역 타일 층이 실제로 만들어진다', !!zone, tiles.join(' '));
    check('필지 경계선 층도 만들어진다', !!cad, tiles.join(' '));
    if (zone) {
      check('브이월드를 직접 안 부른다 (키가 페이지에 없다)',
            !/vworld/i.test(zone), zone);
      check('z·y·x 자리를 Leaflet 이 채우게 둔다',
            /\{z\}/.test(zone) && /\{y\}/.test(zone) && /\{x\}/.test(zone), zone);
    }
    // 페이지에 실려 나가는 코드 어디에도 브이월드 키 모양이 없어야 한다.
    // 'key=' 뒤에 무언가 붙어 있으면 그것이 곧 노출이다.
    const leaked = await page.evaluate(async () => {
      const out = [];
      for (const f of ['/app/app.js', '/app/config.js']) {
        const t = await (await fetch(f)).text();
        if (/vworld[^\n]*key\s*[:=]\s*['"][^'"]+['"]/i.test(t)) out.push(f);
        if (/api\.vworld\.kr[^\n]*key=/i.test(t)) out.push(f);
      }
      return out;
    });
    check('클라이언트 파일에 브이월드 키가 없다', leaked.length === 0,
          leaked.join(' ') || '없음');

    // 끌 수 있어야 한다 — 용도지역을 깔면 지도가 확 복잡해진다.
    const toggled = await page.evaluate(() => {
      const b = document.getElementById('zoning-bg');
      if (!b) return null;
      const before = b.checked;
      b.checked = false;
      b.dispatchEvent(new Event('change', { bubbles: true }));
      const off = window.state ? window.state.zoning : null;
      b.checked = before;
      b.dispatchEvent(new Event('change', { bubbles: true }));
      return { off, back: window.state ? window.state.zoning : null };
    });
    check('용도지역 스위치가 있다', toggled !== null,
          toggled === null ? '#zoning-bg 가 없음' : '');

    // 색면만 깔면 지적편집도가 아니라 색칠이다. 눌렀을 때 이름이 떠야
    // 색이 뜻을 갖는다. 브이월드는 GetLegendGraphic 을 안 주므로
    // (2026-09-04 탐침) 이 경로가 유일하다.
    const asked = await page.evaluate(async () => {
      if (typeof window.askZoning !== 'function') return { missing: true };
      const seen = [];
      const realFetch = window.fetch;
      window.fetch = async (u) => {
        seen.push(String(u));
        return { json: async () => ({ zoning: {
          uname: '계획관리지역', ucode: 'UQB200',
          sido_name: '경기도', sigg_name: '용인시',
          bon_bun: '0052', bu_bun: '000' } }) };
      };
      try {
        await window.askZoning({ lat: 37.132, lng: 127.353 });
      } finally {
        window.fetch = realFetch;
      }
      const pop = document.querySelector('.leaflet-popup-content');
      return { seen, text: pop ? pop.innerText : null };
    });

    check('누르면 서버에 이름을 묻는다',
          !asked.missing && asked.seen.some((u) => /mode=info/.test(u)),
          asked.missing ? 'askZoning 이 없음' : asked.seen.join(' '));
    check('브이월드를 브라우저가 직접 부르지 않는다',
          !asked.missing && !asked.seen.some((u) => /vworld/i.test(u)));
    check('용도지역 이름을 화면에 띄운다',
          !!asked.text && /계획관리지역/.test(asked.text),
          asked.text || '말풍선 없음');
    check('어디인지도 함께 보여준다',
          !!asked.text && /용인시/.test(asked.text), asked.text || '');

    console.log();
    console.log('3. 밴드 = 선 + 음영, 큰 원부터');
    // 영업소 하나를 고른다. 가짜 마커는 못 누르므로 스코어보드 행을
    // 눌러 같은 경로(selectTollgate)를 탄다. SVG 요소도 걸리므로
    // dispatchEvent 를 쓴다 — SVG 에는 .click() 이 없다.
    const picked = await page.evaluate(() => {
      const el = document.querySelector('tr[data-id], [data-id]');
      if (!el) return null;
      el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return el.getAttribute('data-id');
    });
    check('영업소를 고를 수 있다', !!picked, String(picked));
    await page.waitForTimeout(800);
    let circles = await page.evaluate(() => window.__map.circles);
    check('밴드가 그려진다', circles.length >= 3, `${circles.length}개`);
    if (circles.length) {
      // 면은 채우지 않는다. 넓은 색면은 한국 토지이용계획도의 용도지역
      // (주거 노랑·상업 빨강·공업 보라·녹지 초록)처럼 읽히는데, 우리
      // 밴드는 용도와 아무 상관이 없다.
      check('면을 채우지 않는다 (용도지역으로 오독되지 않게)',
            circles.every((c) => !c.fill),
            circles.map((c) => `${c.radius}:${c.fill}`).join(' '));
      const radii = circles.map((c) => c.radius);
      check('큰 원부터 그린다 (작은 원이 위에 온다)',
            radii.every((r, i) => i === 0 || radii[i - 1] >= r),
            radii.join(' → '));
      // 위약 대조 밴드(가장 바깥)는 화면에 안 그린다. 분석 절차이지
      // 사용자가 볼 것이 아니다 — 화면에 '위약 대조' 라고 적어두면
      // 무슨 말인지 모르는 채로 지도만 복잡해진다.
      const cfgBands = await page.evaluate(() => (window.__bands || []).length);
      check('위약 대조 밴드는 안 그린다 (분석 전용)',
            circles.length === cfgBands - 1,
            `그린 ${circles.length}개 vs 설정 ${cfgBands}개`);
      // 실선은 행정경계나 도로처럼 보여 배경 지도의 선과 섞인다.
      // 점선이라야 '우리가 그은 선' 으로 읽힌다.
      check('모든 밴드가 점선이다',
            circles.every((c) => !!c.dashArray),
            circles.map((c) => c.dashArray || '실선').join(' / '));
      // 사장님 지적(2026-09-04): "IC 선택 후 범위가 표시되면 범위 내로
      // 들어가는 인근 IC가 클릭 불가."
      //
      // fill:false 로는 안 막힌다. canvas 방식에서 Leaflet 은 원의 누름
      // 판정을 **중심에서의 거리**로만 한다(Circle._containsPoint) —
      // 채웠는지는 안 본다. 그래서 속이 빈 5km 밴드가 그 원판 전체의
      // 누름을 가로챈다. 게다가 겹치면 **나중에 그린 것**이 이기는데,
      // 영업소는 처음 한 번, 밴드는 IC 를 고를 때마다 다시 그리므로
      // 밴드가 항상 나중이다. 판정 대상에서 빼는 것 말고는 길이 없다.
      check('밴드는 누름을 가로채지 않는다 (안쪽 IC를 고를 수 있다)',
            circles.every((c) => c.interactive === false),
            `${circles.filter((c) => c.interactive === false).length}/${circles.length}`);
      const tgClickable = await page.evaluate(() =>
        window.__map.markers.every((o) => o.interactive !== false));
      check('영업소는 그대로 누를 수 있다', tgClickable);
    }

    console.log();
    console.log('4. 범례 — 실거래·매물이 먼저, 스와치가 부풀지 않는다');
    await page.click('.legend-peek').catch(() => {});
    await page.waitForTimeout(250);
    const legend = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.map-legend .grp')]
        .map((e) => e.textContent.trim());
      const sw = document.querySelector('.map-legend .sw-listing');
      const box = sw ? sw.getBoundingClientRect() : null;
      return { groups: rows, listingW: box ? box.width : null };
    });
    check('실거래가 첫 묶음이다', legend.groups[0].startsWith('실거래'),
          legend.groups.join(' / '));
    check('매물이 둘째 묶음이다', legend.groups[1] === '매물',
          legend.groups.join(' / '));
    // 흔한 클래스 이름(.listing)을 재사용했다가 매물 카드의 display:grid 를
    // 물려받아 스와치가 39px 로 부푼 적이 있다. 규칙이 있는데도 안 먹는
    // 종류라 눈으로 보기 전에는 모른다.
    check('매물 스와치가 작은 마름모다 (카드 규칙을 안 물려받는다)',
          legend.listingW != null && legend.listingW < 20,
          `${legend.listingW}px`);
    await page.click('.legend-peek').catch(() => {});

    console.log();
    console.log('5. 전체 IC 반경');
    const before = (await page.evaluate(() => window.__map.circles)).length;
    await page.check('#all-bands');
    await page.waitForTimeout(1200);
    const after = (await page.evaluate(() => window.__map.circles)).length;
    check('켜면 원이 크게 늘어난다', after > before * 10, `${before} → ${after}`);
    await page.uncheck('#all-bands');
    await page.waitForTimeout(800);
    const off = (await page.evaluate(() => window.__map.circles)).length;
    check('끄면 되돌아온다', off < after / 10, `${after} → ${off}`);

    console.log();
    console.log('7. 거래 점이 배경에서 보인다 · 도로 위계가 살아 있다');
    // 사장님 지적: "토지, 공장 색상이 배경과 너무 구분이 안됩니다."
    // 원인은 반경 2.5 · 테두리 없음 · 불투명도 0.3~0.6 이었다.
    // 색을 더 진하게 하는 것으로는 못 이긴다 — 흰 테두리가 점을
    // 배경에서 끊어주는 것이 핵심이라 그것을 못박는다.
    // 사장님 지시(2026-09-04): "모든 실거래는 초기 기본설정은 표기 끄는 것."
    // 처음 화면이 2천 개 점으로 덮이면 IC 도 배경도 안 보인다.
    const offAtStart = await page.evaluate(() => ({
      drawn: (window.__tradeStyles || []).length,
      boxes: [...document.querySelectorAll('#kind-filters input')]
        .map((b) => b.checked),
    }));
    check('처음에는 실거래를 안 그린다', offAtStart.drawn === 0,
          `${offAtStart.drawn}개`);
    check('필터 칸도 꺼진 채로 시작한다 (화면과 상태가 같아야 한다)',
          offAtStart.boxes.length > 0 && offAtStart.boxes.every((b) => !b),
          offAtStart.boxes.join(','));

    // 여기서부터는 켜고 본다.
    for (const box of await page.$$('#kind-filters input')) await box.check();
    await page.waitForTimeout(600);
    const tradeStyle = await page.evaluate(() => window.__tradeStyles || []);
    if (tradeStyle.length) {
      // 사장님 지적(2026-09-04): "어느게 IC이고 어느게 거래건인지 구분이
      // 안됩니다." 색을 더 늘려 푸는 문제가 아니다 — **모양이 먼저
      // 종류를 말해야 한다.** 영업소는 원, 거래는 네모·마름모다.
      check('거래는 원이 아니다 (영업소와 모양으로 갈린다)',
            tradeStyle.every((o) => /trade-mark/.test(o.html)),
            `${tradeStyle.length}개 · 예: ${tradeStyle[0].html.slice(0, 60)}`);
      const land = tradeStyle.filter((o) => /trade-land/.test(o.html));
      const fac = tradeStyle.filter((o) => /trade-factory/.test(o.html));
      check('토지와 공장이 다른 모양이다', land.length + fac.length === tradeStyle.length
            && tradeStyle.every((o) => !(/trade-land/.test(o.html) && /trade-factory/.test(o.html))),
            `토지 ${land.length} · 공장 ${fac.length}`);
      check('종류대로 붙는다 (용도지역이 아니라)',
            land.every((o) => o.kind === 'land') && fac.every((o) => o.kind === 'factory'));
      // 법정동 중심점은 ±1~2km 라 '그 자리' 가 아니다. 옅게 찍어 구별한다.
      const coarse = tradeStyle.filter((o) => o.geocodeLevel !== 'parcel');
      check('거친 좌표는 옅게 찍는다',
            coarse.every((o) => /trade-coarse/.test(o.html)),
            `거친 것 ${coarse.length}개`);
      // 사장님 지적(2026-09-04): "실거래 및 매물 표시는 IC 아래로."
      // 무리를 붙이는 순서로는 못 고친다 — Leaflet 은 divIcon 마커를
      // markerPane(600)에, 원을 overlayPane(400)에 그려서 거래가 항상
      // 위로 온다. 판을 따로 파서 400 아래에 두는 것이 유일한 길이다.
      const pane = await page.evaluate(() => {
        const el = window.__map.panes && window.__map.panes.tradePane;
        return el ? { z: Number(el.style.zIndex) } : null;
      });
      check('거래·매물 전용 판을 판다', !!pane, pane ? `z-index ${pane.z}` : '없음');
      if (pane) {
        // Leaflet 기본값: 타일 200 · 오버레이(밴드·영업소) 400 · 마커 600.
        check('그 판이 영업소보다 아래다 (200 < z < 400)',
              pane.z > 200 && pane.z < 400, `z-index ${pane.z}`);
      }
      check('거래 표식을 전부 그 판에 그린다',
            tradeStyle.every((o) => o.pane === 'tradePane'),
            `${tradeStyle.filter((o) => o.pane === 'tradePane').length}/${tradeStyle.length}`);
      const listStyle = await page.evaluate(() => window.__listingStyles || []);
      check('매물 핀도 그려진다', listStyle.length >= 1, `${listStyle.length}개`);
      check('매물 핀도 같은 판에 그린다 (IC 아래)',
            listStyle.length >= 1 && listStyle.every((o) => o.pane === 'tradePane'),
            listStyle.map((o) => `${o.className}:${o.pane}`).join(' '));
    } else {
      console.log('  건너뜀 — 그려진 거래 점이 없습니다.');
    }
    // 여기까지는 **글자**만 봤다 — html 에 어떤 클래스가 붙었는가.
    // 그래서 클래스는 다 맞는데 화면에는 흰 막대가 서는 것을 통과시켰다
    // (<i> 는 inline 이라 width/height 가 무시돼 테두리만 남았다).
    // 클래스 이름이 맞는 것과 그려진 것이 맞는 것은 다른 일이다.
    // 아래는 진짜 브라우저에 실제 마크업을 넣고 **그려진 크기와 색**을 잰다.
    const drawn = await page.evaluate(() => {
      const box = document.createElement('div');
      box.style.cssText = 'position:absolute;left:-9999px;top:0';
      box.innerHTML =
        '<div class="trade-icon" style="width:9px;height:9px">' +
        '<i class="trade-mark trade-land"></i></div>' +
        '<div class="trade-icon" style="width:9px;height:9px">' +
        '<i class="trade-mark trade-factory"></i></div>' +
        '<div class="map-legend"><div class="legend-rows">' +
        '<div class="row"><span class="sw sw-trade trade-land"></span>토지</div>' +
        '<div class="row"><span class="sw sw-trade trade-factory"></span>공장</div>' +
        '</div></div>';
      document.body.appendChild(box);
      // 크기는 offsetWidth 로 잰다. getBoundingClientRect 는 **회전된 뒤의
      // 외접 사각형**이라, 45° 돌린 9px 마름모가 12.7px(=9×√2) 로 나온다.
      // 그러면 마름모는 영영 크기 검사를 통과하지 못한다.
      const read = (sel) => {
        const el = box.querySelector(sel);
        const cs = getComputedStyle(el);
        return { w: el.offsetWidth, h: el.offsetHeight,
                 bg: cs.backgroundColor, border: cs.borderTopColor,
                 bw: cs.borderTopWidth, radius: cs.borderTopLeftRadius,
                 transform: cs.transform };
      };
      const out = {
        land: read('.trade-mark.trade-land'),
        factory: read('.trade-mark.trade-factory'),
        swLand: read('.sw.sw-trade.trade-land'),
        swFactory: read('.sw.sw-trade.trade-factory'),
      };
      box.remove();
      return out;
    });
    const solid = (c) => c && c !== 'transparent' && !/rgba\(0, 0, 0, 0\)/.test(c);
    // 9px 칸을 꽉 채워야 한다. 0 이나 1~2px 이면 테두리만 그려진 것이다.
    for (const [name, o] of [['토지', drawn.land], ['공장', drawn.factory]]) {
      check(`지도 ${name} 표식이 9×9 로 그려진다`,
            Math.abs(o.w - 9) < .6 && Math.abs(o.h - 9) < .6, `${o.w}×${o.h}`);
      check(`지도 ${name} 표식에 속이 차 있다`, solid(o.bg), o.bg);
      check(`지도 ${name} 표식에 흰 테두리가 있다`,
            /rgb\(255, 255, 255\)/.test(o.border) && parseFloat(o.bw) >= 1,
            `${o.border} ${o.bw}`);
    }
    check('지도에서 토지와 공장의 색이 다르다', drawn.land.bg !== drawn.factory.bg,
          `${drawn.land.bg} vs ${drawn.factory.bg}`);
    check('공장은 마름모다 (회전이 걸린다)',
          drawn.factory.transform !== 'none' && drawn.land.transform === 'none',
          `공장 ${drawn.factory.transform}`);
    // 범례가 동그라미로 나온 것도 같은 부류의 실수였다 —
    // .map-legend .sw{border-radius:50%} 를 클래스 하나짜리 규칙으로 이기려 했다.
    for (const [name, o] of [['토지', drawn.swLand], ['공장', drawn.swFactory]]) {
      check(`범례 ${name} 스와치에 속이 차 있다`, solid(o.bg), o.bg);
      check(`범례 ${name} 스와치가 동그라미가 아니다`,
            parseFloat(o.radius) <= o.w / 4, `반지름 ${o.radius} / 폭 ${o.w}px`);
    }
    check('범례 색이 지도 색과 같다',
          drawn.swLand.bg === drawn.land.bg && drawn.swFactory.bg === drawn.factory.bg,
          `${drawn.swLand.bg} · ${drawn.swFactory.bg}`);
    // 가짜 Leaflet 은 .leaflet-tile-pane 을 만들지 않으므로 계산된
    // 스타일로는 볼 수 없다. 규칙 자체를 읽는다.
    const sat = await page.evaluate(async () => {
      const css = await (await fetch('/app/style.css')).text();
      const hit = /\.leaflet-tile-pane\s*\{([^}]*)\}/.exec(css);
      return hit ? hit[1] : '';
    });
    // saturate(.10) 은 OSM 이 갖고 있는 도로 위계 색(고속도로 분홍·
    // 국도 노랑)을 통째로 지운다. IC 주변 땅값을 보는 제품에서
    // 고속도로가 안 보이는 것은 앞뒤가 안 맞는다.
    const satHit = /saturate\(([\d.]+)\)/.exec(sat);
    check('배경 지도가 도로 색을 지우지 않는다',
          satHit && Number(satHit[1]) >= .5, sat || '(필터 없음)');

    console.log();
    console.log('9. 행정구역 인구 — 중심에 크기별로');
    const pop = await page.evaluate(() => {
      const circles = window.__map.circles || [];
      return {
        peek: window.__pop || {},
        pane: (window.__map.panes && window.__map.panes.popPane)
          ? Number(window.__map.panes.popPane.style.zIndex) : null,
        marks: (window.__map.markers || []).filter((o) => o.pane === 'popPane'),
        switchShown: !(document.getElementById('pop-switch') || {}).hidden,
        legend: document.querySelector('#map-legend').textContent,
      };
    });
    check('인구 스위치가 보인다 (자료가 있을 때만)', pop.switchShown);
    check('시군구마다 원을 하나씩 그린다', pop.marks.length === 4,
          `${pop.marks.length}개`);
    check('인구 원을 IC 아래 판에 그린다 (200 < z < 400)',
          pop.pane !== null && pop.pane > 200 && pop.pane < 400,
          `z-index ${pop.pane}`);
    if (pop.marks.length === 4) {
      // 크기는 **네 단**이다. 235가지 크기를 눈으로 가를 수는 없다.
      const R = pop.marks.map((m) => m.radius).sort((a, b) => b - a);
      check('크기가 네 단으로 끊긴다', new Set(R).size === 4, R.join(' / '));
      check('인구가 많을수록 크다',
            R.every((r, i) => i === 0 || R[i - 1] > r), R.join(' > '));
      // 넣은 넷이 각각 다른 단에 든다 — 경계(5만·20만·50만)가 맞다는 뜻이다.
      const bySize = {};
      pop.marks.forEach((m) => { bySize[m.radius] = (bySize[m.radius] || 0) + 1; });
      check('한 단에 하나씩 들어간다 (경계가 맞다)',
            Object.values(bySize).every((n) => n === 1), JSON.stringify(bySize));
    }
    // 범례 원은 지도 원과 **같은 크기**여야 한다. 크기가 곧 값이라
    // 그것이 유일한 단서인데, 둘이 다르면 짝을 못 맞춘다.
    const legendSizes = await page.evaluate(() =>
      [...document.querySelectorAll('#map-legend .sw-pop')]
        .map((el) => Math.round(el.getBoundingClientRect().width)));
    check('범례에 단이 네 개 있다', legendSizes.length === 4, legendSizes.join('/'));
    check('범례 원 크기가 지도와 같다',
          legendSizes.length === 4
          && legendSizes.every((w) => pop.marks.some((m) => Math.abs(m.radius * 2 - w) <= 1)),
          `범례 ${legendSizes.join('/')} vs 지도 ${pop.marks.map((m) => m.radius * 2).sort().join('/')}`);
    check('범례가 크기와 인구를 짝지어 말한다',
          ['행정구역 인구', '5만 이하', '20만 이하', '50만 이하', '50만 초과']
            .every((t) => pop.legend.includes(t)));
    check('어느 해 인구인지 적는다',
          !!pop.peek.year && pop.legend.includes(String(pop.peek.year)),
          String(pop.peek.year));

    console.log();
    console.log('8. 세 가설 판정 — 무엇을 말할 수 있고 없는지');
    // 이 탭은 숫자를 하나 더 보여주는 곳이 아니다. 계수가 유의해도 위약
    // 밴드가 같이 유의하면 IC 효과가 아니고, 표본이 모자라면 '효과 없음'
    // 이 아니라 '아직 모름' 이다. 그 구분이 화면에서 사라지면 사람은
    // 스스로 결론을 채워 넣는다 — 그래서 화면에 실제로 남아 있는지 본다.
    const vTab = await page.$('.tab[data-view="verdict"]');
    check('가설 판정 탭이 있다', !!vTab);
    if (vTab) {
      await vTab.click();
      await page.waitForTimeout(300);
      const v = await page.evaluate(() => {
        const cards = [...document.querySelectorAll('#verdict-card' + 's .verdict-card')];
        return {
          shown: !!document.querySelector('#view-verdict.is-active'),
          n: cards.length,
          badges: cards.map((c) => ({
            text: c.querySelector('.verdict-badge').textContent.trim(),
            cls: c.className,
          })),
          flags: [...document.querySelectorAll('.verdict-flag')]
            .map((f) => ({ cls: f.className, text: f.textContent.trim() })),
          nullCI: document.querySelectorAll('#verdict-cards .ci-null').length,
          awayCI: document.querySelectorAll('#verdict-cards .ci-away').length,
          stamp: (document.querySelector('#verdict-stamp') || {}).textContent || '',
          peek: window.__verdicts || [],
        };
      });
      check('누르면 판정 화면이 열린다', v.shown);
      check('가설 셋을 다 보여준다', v.n === 3, `${v.n}개`);
      // 색만으로 뜻을 말하면 색약·흑백에서 무너진다. 딱지에 글자가 있어야 한다.
      check('판정이 글자로 적혀 있다 (색만이 아니다)',
            v.badges.map((b) => b.text).join('·') === '아직 모름·지지·기각',
            v.badges.map((b) => b.text).join('·'));
      check('판정마다 색이 다르다',
            /is-unknown/.test(v.badges[0].cls) && /is-ok/.test(v.badges[1].cls)
            && /is-no/.test(v.badges[2].cls),
            v.badges.map((b) => b.cls.replace('verdict-card ', '')).join(' / '));
      // 통제가 없는데 계수를 그냥 보여주면 'IC 효과' 로 읽힌다.
      check('통제가 없으면 표 위에서 먼저 경고한다',
            v.flags.some((f) => /is-warn/.test(f.cls) && /통제/.test(f.text)),
            v.flags.map((f) => f.text.slice(0, 24)).join(' | ') || '경고 없음');
      check('평행추세가 깨진 것도 알린다',
            v.flags.some((f) => /평행추세/.test(f.text)));
      // 95% 구간이 0 을 품으면 '말할 수 없다' 다. 부호만 보고 읽으면 안 된다.
      check('0 을 품는 구간을 따로 표시한다', v.nullCI === 1 && v.awayCI === 1,
            `0 포함 ${v.nullCI} · 0 밖 ${v.awayCI}`);
      // 색과 굵기만으로 갈라 두면 흑백·색약에서 무너진다. ::after 로
      // 글자를 붙였는지 **그려진 결과**로 확인한다.
      const after = await page.evaluate(() => {
        const el = document.querySelector('#verdict-cards .ci-null');
        return el ? getComputedStyle(el, '::after').content : '';
      });
      check('그 줄에 글자로도 적는다 (0 포함)', /0 포함/.test(after), after);
      check('무엇으로 돌린 판정인지 적는다',
            /토지/.test(v.stamp) && /화물/.test(v.stamp), v.stamp);
    }

    console.log();
    console.log('6. 통행량 미공개 = 속이 빈 점');
    // 민자 운영사가 요금을 직접 걷는 노선은 도로공사 TCS 에 통행량이
    // 없다. 이때 0 으로 칠하면 '가장 한산한 IC' 로 보여서 정반대의
    // 결론이 나온다. 그래서 구간 색을 주지 않고 **속을 비운다**.
    if (hollowId) {
      const hollow = await page.evaluate(() => {
        const none = getComputedStyle(document.documentElement)
          .getPropertyValue('--tg-none').trim();
        const found = window.__map.markers.filter((o) => o.color === none);
        return { none, n: found.length, one: found[0] || null };
      });
      // '정확히 1개' 로 못박아 뒀다가 화석이 됐다. 그때는 실제 자료에
      // 미공개 영업소가 하나도 없어서 우리가 넣은 것 하나뿐이었는데,
      // run 21 이 명부에서 영업소를 등재하고 좌표를 붙이면서 **진짜
      // 미공개가 119곳** 생겼다. 기능이 작동한 것인데 검사만 빨개졌다.
      //
      // 지켜야 할 것은 개수가 아니라 **지도와 필터가 같은 것을 센다**는
      // 사실이다. 그것을 본다.
      check('미공개 마커가 있다', hollow.n >= 1, `${hollow.n}개 · ${hollow.none}`);
      if (hollow.one) {
        check('속을 채우지 않는다 (구간 색이 아니다)',
              hollow.one.fillColor !== hollow.none
              && /^#?(fff|FFF)/.test(hollow.one.fillColor.replace('#', '#')),
              String(hollow.one.fillColor));
        check('테두리가 굵어 작은 배율에서도 보인다',
              hollow.one.weight >= 2, String(hollow.one.weight));
        // 사장님 지적(2026-09-04): "통행량 정보 없음(민자)는 사이즈 최소로."
        // 크기는 이 지도에서 **교통량의 크기**를 말한다. 미공개를 크게
        // 그리면 값이 큰 곳처럼 눈에 먼저 드는데, 값이 큰 곳이 아니라
        // 값을 모르는 곳이다. 가장 작은 칸(1만대 이하)과 같게 둔다.
        const smallest = await page.evaluate(() => {
          const c1 = getComputedStyle(document.documentElement)
            .getPropertyValue('--tg-1').trim().toLowerCase();
          const m = window.__map.markers.find((o) =>
            String(o.fillColor).trim().toLowerCase() === c1);
          return m ? m.radius : null;
        });
        check('미공개가 가장 작다 (1만대 이하와 같은 크기)',
              smallest !== null && hollow.one.radius === smallest,
              `미공개 ${hollow.one.radius} vs 1만대 이하 ${smallest}`);
      }
      const label = await page.evaluate(() => {
        const b = [...document.querySelectorAll('#tier-filters .quad-btn')]
          .find((x) => x.dataset.tier === 'none');
        return b ? { text: b.textContent, n: b.querySelector('.n').textContent } : null;
      });
      check('필터에 미공개 칸이 있고 지도와 같은 수를 센다',
            !!label && /미공개/.test(label.text)
            && Number(label.n) === hollow.n,
            label ? `필터 ${label.n} vs 지도 ${hollow.n}` : '없음');
    } else {
      console.log('  건너뜀 — tollgates.json 이 없습니다.');
    }


    await page.close();
  } finally {
    await browser.close();
    srv.kill();
  }
  console.log();
  console.log(failed ? `실패 ${failed}건` : '모두 통과');
  process.exit(failed ? 1 : 0);
})();
