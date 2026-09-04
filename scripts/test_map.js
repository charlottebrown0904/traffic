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
  const rec = { circles: [], markers: [], tiles: [], tradeOpts: [] };
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
    marker: () => chain(), divIcon: () => ({}),
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
    await page.addInitScript(() => {
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
    const tradeStyle = await page.evaluate(() => window.__tradeStyles || []);
    if (tradeStyle.length) {
      check('거래 점에 테두리가 있다 (배경과 끊긴다)',
            tradeStyle.every((o) => o.weight >= 1 && o.color === '#fff'),
            `${tradeStyle.length}개 · 예: weight=${tradeStyle[0].weight} color=${tradeStyle[0].color}`);
      check('지번 좌표 점은 거의 불투명하다',
            tradeStyle.some((o) => o.fillOpacity >= .9),
            `최대 ${Math.max(...tradeStyle.map((o) => o.fillOpacity))}`);
      const fills = new Set(tradeStyle.map((o) => o.fillColor));
      check('용도지역 색을 쓴다 (한 가지 갈색이 아니다)', fills.size >= 2,
            [...fills].join(' '));
    } else {
      console.log('  건너뜀 — 그려진 거래 점이 없습니다.');
    }
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
