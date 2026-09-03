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
  const rec = { circles: [], markers: [], tiles: [] };
  window.__map = rec;
  const grp = () => {
    const g = { _n: 0,
      addLayer(x) { g._n++; if (x && x.__circle) rec.circles.push(x.__opts); return g; },
      clearLayers() { g._n = 0; rec.circles.length = 0; return g; },
      addTo() { return g; } };
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
      rec.markers.push(m.__opts);
      return m;
    },
    marker: () => chain(), divIcon: () => ({}),
    latLngBounds: () => ({ pad: () => ({}) }),
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
    await page.addInitScript(() => {
      window.SB = {};
      window.SBUtil = { me: async () => ({ user: { id: 'u1' }, profile: null }) };
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
    check('타일 주소가 하나다', tiles.length === 1, tiles.join(' '));
    check('API 키를 요구하는 서비스가 아니다',
          tiles.every((u) => !/carto|stadia|mapbox|thunderforest|apikey/i.test(u)),
          tiles.join(' '));

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
    check('실거래가 첫 묶음이다', legend.groups[0] === '실거래',
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
      check('미공개 마커가 있다', hollow.n === 1, `${hollow.n}개 · ${hollow.none}`);
      if (hollow.one) {
        check('속을 채우지 않는다 (구간 색이 아니다)',
              hollow.one.fillColor !== hollow.none
              && /^#?(fff|FFF)/.test(hollow.one.fillColor.replace('#', '#')),
              String(hollow.one.fillColor));
        check('테두리가 굵어 작은 배율에서도 보인다',
              hollow.one.weight >= 2, String(hollow.one.weight));
      }
      const label = await page.evaluate(() => {
        const b = [...document.querySelectorAll('#tier-filters .quad-btn')]
          .find((x) => x.dataset.tier === 'none');
        return b ? { text: b.textContent, n: b.querySelector('.n').textContent } : null;
      });
      check('필터에 미공개 칸이 있고 개수를 센다',
            !!label && /미공개/.test(label.text) && Number(label.n) === 1,
            label ? `${label.text}` : '없음');
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
