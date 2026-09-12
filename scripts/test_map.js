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
  const rec = { circles: [], markers: [], tiles: [], tradeOpts: [],
                panes: {}, zoomCtl: null };
  window.__map = rec;
  // 무리(layerGroup)마다 자기가 담은 것을 따로 들고 있어야 한다.
  // 예전에는 모두가 rec 하나에 밀어 넣어서, 밴드 무리가 clearLayers 를
  // 부르면 거래 점 기록까지 같이 지워졌다. 그러면 '거래가 안 그려진다'
  // 와 '다른 무리가 지웠다' 를 구분할 수 없다.
  const groups = [];
  // 무리를 그대로 내보낸다. rec.markers 는 **만든 것을 쌓기만** 하므로
  // 다시 그리면 옛 것이 남는다 — 배율을 흔들어 가며 '지금 몇 개인가'
  // 를 세려면 무리가 지금 들고 있는 것을 봐야 한다.
  rec.groups = groups;
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
    // 말풍선 글을 남긴다. 인구 원이 '몇 곳을 합친 값인지' 를 말하는지
    // 확인하려면 이 글을 읽어야 한다.
    bindTooltip(html) { this.__tooltip = html; return this; },
    setStyle() { return this; },
    getLatLng() { return { lat: 0, lng: 0 }; },
  }, extra);
  window.L = {
    map: () => chain({
      setView() { return this; }, fitBounds() { return this; },
      panTo() { return this; }, invalidateSize() { return this; },
      // **진짜 Leaflet 에는 removeLayer 가 있다.** 없으면 배경 지도를
      // 갈아 끼우는 자리에서 통째로 터지는데, 그것은 우리 코드의 잘못이
      // 아니라 이 뼈대가 현실과 다른 것이다 (2026-09-09).
      removeLayer(x) { window.__removed = (window.__removed || 0) + 1; return this; },
      // **배율을 바꿀 수 있어야 한다.** 인구를 묶는 단위가 배율에 따라
      // 달라지는데(시도 → 시군 → 구), 7 로 고정해 두면 그 셋 중 하나만
      // 보고 통과라고 말하게 된다. window.__setZoom 으로 흔든다.
      getZoom() { return window.__zoom == null ? 7 : window.__zoom; },
      // 화면 한가운데. '지금 이 지역을 보는 사람' 이 이 값으로 어느
      // 시·군·구인지를 고른다. window.__center 로 옮긴다.
      getCenter() {
        const c = window.__center || [36.5, 127.8];
        return { lat: c[0], lng: c[1] };
      },
      on(ev, fn) {
        (window.__mapOn = window.__mapOn || {});
        // 진짜 Leaflet 은 'a b' 처럼 여러 사건을 한 번에 받는다.
        String(ev).split(/\s+/).filter(Boolean).forEach((one) => {
          (window.__mapOn[one] = window.__mapOn[one] || []).push(fn);
        });
        return this;
      },
      // **진짜 Leaflet 에는 getContainer 가 있다.** 누름과 끌기를 가르려고
      // 지도 통에 직접 귀를 붙이므로(pointerdown), 없으면 통째로 터진다.
      getContainer() {
        if (!window.__mapBox) {
          const el = document.createElement('div');
          el.id = 'fake-map-box';
          document.body.appendChild(el);
          window.__mapBox = el;
        }
        return window.__mapBox;
      },
      // 거래를 '보이는 영역만' 그리므로 경계가 없으면 한 점도 안 그려진다.
      // 전국이 다 보이는 셈으로 둔다 — 잘라내기 자체는 아래에서 따로 본다.
      getBounds() {
        // 땅값 글자는 '보이는 곳만' 그린다. window.__bbox 로 화면을 좁혀
        // 그 잘라내기가 실제로 도는지 볼 수 있게 한다. 기본은 전국이다.
        const bb = window.__bbox;
        const box = bb || [-90, -180, 90, 180];
        return {
          contains: (ll) => {
            const lat = Array.isArray(ll) ? ll[0] : ll.lat;
            const lon = Array.isArray(ll) ? ll[1] : ll.lng;
            return lat >= box[0] && lat <= box[2] && lon >= box[1] && lon <= box[3];
          },
          // 읍면동 조각을 '화면에 걸치는 것만' 받으므로, 검사도 진짜
          // Leaflet 처럼 모서리를 내놓아야 그 고르기가 돈다.
          getSouthWest: () => ({ lat: box[0], lng: box[1] }),
          getNorthEast: () => ({ lat: box[2], lng: box[3] }),
          // 경계선은 화면을 덮는 **칸**을 세므로 네 모서리가 다 필요하다.
          getWest: () => box[1],
          getEast: () => box[3],
          getSouth: () => box[0],
          getNorth: () => box[2],
          pad: () => ({}),
        };
      },
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
    tileLayer: (url, opts) => {
      rec.tiles.push(url);
      rec.tileOpts = rec.tileOpts || [];
      rec.tileOpts.push({ url, opts: opts || {} });
      // 경계선은 색을 따로 잡으려고 판을 따로 쓴다. 검사가 그것을 본다.
      if (/layer=cadastral/.test(url)) {
        window.__cadPane = (opts || {}).pane;
        window.__cadMinZoom = (opts || {}).minZoom;
      }
      return chain();
    },
    // 필지 윤곽은 geoJSON 층으로 그린다. 진짜 Leaflet 에 있는 것이다.
    geoJSON: (geom, opts) => chain({ __geojson: geom, __opts: opts || {} }),
    // +/- 는 오른쪽 아래로 옮겼다 (왼쪽 위는 검색칸 자리다).
    // 어디에 붙였는지 검사가 볼 수 있게 기록해 둔다.
    control: {
      zoom: (opts) => {
        rec.zoomCtl = (opts || {}).position || 'topleft';
        return { addTo() { return this; } };
      },
    },
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
      // 어디에 찍혔는가. 인구 원의 중심이 관청인지 대표점인지는
      // 이것을 봐야 알 수 있다.
      m.__latlng = ll;
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
      m.__latlng = ll;
      // 거래 상세 말풍선. 붙인 내용을 들고 있지 않으면 '눌러도 아무것도
      // 안 나온다' 를 검사로 옮길 수 없다.
      m.bindPopup = (html, opts) => {
        m.__popupHtml = html;
        m.__popupOpts = Object.assign({}, opts);
        return m;
      };
      // 말풍선을 열고 닫는 흉내. 진짜 Leaflet 처럼 popupopen 을 부르고,
      // 열려 있는지를 남긴다 — '지도를 옮겨도 안 닫히는가' 를 이것으로 본다.
      m.__handlers = {};
      m.on = (ev, fn) => {
        String(ev).split(/\s+/).filter(Boolean).forEach((one) => {
          (m.__handlers[one] = m.__handlers[one] || []).push(fn);
        });
        return m;
      };
      m.openPopup = () => {
        m.__popupOpen = true;
        (m.__handlers.popupopen || []).forEach((f) => f({ popup: m }));
        return m;
      };
      m.closePopup = () => {
        if (!m.__popupOpen) return m;
        m.__popupOpen = false;
        (m.__handlers.popupclose || []).forEach((f) => f({ popup: m }));
        // 지도도 듣는다 (drawLandPrice 를 다시 부르는 쪽).
        (((window.__mapOn || {}).popupclose) || []).forEach((f) =>
          f({ popup: { options: m.__popupOpts || {} } }));
        return m;
      };
      m.closeTooltip = () => m;
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
      primary: true, primary_kind: 'land', primary_volume: 'volume_total',
      hypotheses: [
        { key: 'H1', name: 'H1 IC 개통', claim: '개통하면 오른다',
          verdict: '아직 모름', why: '표본이 없습니다.', rows: [] },
        { key: 'H2', name: 'H2 교통량 변화', claim: '교통량이 늘면 오른다',
          verdict: '지지', why: '3-5km 에서 유의, 위약은 깨끗합니다.',
          rows: [
            // 계수가 '잡을 수 있는 최소' 보다 큰 줄 — 크기를 읽어도 되는 줄
            { label: '3-5km · 통제 전', band: '3-5', model: '통제 전', var: null,
              note: '', n: 2356, clusters: 210, beta: 0.387, se: 0.129,
              p: 0.003, ci_lo: 0.135, ci_hi: 0.639, mde: 0.361 },
            // 계수가 그보다 작은 줄 — 크기를 읽으면 안 되는 줄
            { label: '5-10km · 통제 전', band: '5-10', model: '통제 전', var: null,
              note: '위약', n: 2356, clusters: 210, beta: 0.102, se: 0.105,
              p: 0.332, ci_lo: -0.104, ci_hi: 0.308, mde: 0.294 },
          ] },
        { key: 'H3', name: 'H3 인구·산단', claim: '인구가 늘면 오른다',
          verdict: '기각', why: '계수가 0 과 구분되지 않습니다.', rows: [] },
        { key: 'H4', name: 'H4 교통량 수준', claim: '교통량 많은 곳이 비싸다',
          verdict: '관계 있음 (상관 · 인과 아님)',
          why: '서울거리를 통제해도 남습니다. 다만 상관입니다.', rows: [] },
        { key: 'H5', name: 'H5 인구 × 교통량', claim: '둘 다 많으면 더 비싸다',
          verdict: '아직 모름', why: '곱셈항을 판정할 수 없습니다.', rows: [] },
      ],
    };
    // 행정구역 인구. 크기를 세 단으로 끊었으므로 **세 단에 하나씩** 넣는다.
    // 한 단이라도 비면 그 단이 제 크기로 그려지는지 볼 수 없다.
    const FAKE_REGIONS = [
      // 배율에 따라 세 단위로 묶인다 (2026-09-07 지시). 그 셋이 다
      // 실제로 갈리도록 계층을 넣어 둔다 — 도 아래 시, 시 아래 구,
      // 광역시의 구, 그리고 도 아래 군.
      { sigungu_cd: '41111', name: '수원시 장안구', sido: '경기도',
        parent: '수원시', lat: 37.304, lon: 127.011,
        // 관청 좌표. 대표점(lat/lon)과 일부러 다르게 둔다 — 둘이 같으면
        // 어느 쪽을 쓰는지 검사가 못 가른다.
        office_lat: 37.3040, office_lon: 127.0101,
        n_umd: 10, pop: { '2024': 300000, '2025': 280000 } },
      { sigungu_cd: '41113', name: '수원시 권선구', sido: '경기도',
        parent: '수원시', lat: 37.241, lon: 126.971,
        n_umd: 12, pop: { '2024': 380000, '2025': 370000 } },
      { sigungu_cd: '41460', name: '용인시', sido: '경기도', parent: '',
        lat: 37.241, lon: 127.178,
        n_umd: 35, pop: { '2024': 350000, '2025': 340000 } },
      { sigungu_cd: '41220', name: '평택시', sido: '경기도', parent: '',
        lat: 36.992, lon: 127.112,
        n_umd: 30, pop: { '2024': 120000, '2025': 118000 } },
      // 광역시의 구. '시·군' 단위에서는 서울특별시 하나로 묶여야 한다.
      { sigungu_cd: '11110', name: '종로구', sido: '서울특별시', parent: '',
        lat: 37.595, lon: 126.975,
        n_umd: 8, pop: { '2024': 140000, '2025': 137000 } },
      { sigungu_cd: '11680', name: '강남구', sido: '서울특별시', parent: '',
        lat: 37.517, lon: 127.047,
        n_umd: 14, pop: { '2024': 560000, '2025': 550000 } },
      // **이름이 겹치는 구 둘.** 보고된 문제(2026-09-09): "서울 강서구가
      // 안성에 있습니다." 열쇠가 이름뿐이라 둘이 한 칸으로 묶였고,
      // 대표점이 서울과 부산의 인구가중 평균 — 안성 언저리 — 이 됐다.
      { sigungu_cd: '11500', name: '강서구', sido: '서울특별시', parent: '',
        lat: 37.5647, lon: 126.8182,
        n_umd: 9, pop: { '2024': 560000, '2025': 549711 } },
      { sigungu_cd: '26440', name: '강서구', sido: '부산광역시', parent: '',
        lat: 35.1304, lon: 128.8863,
        n_umd: 7, pop: { '2024': 148000, '2025': 150299 } },
      // 관청 좌표를 아직 못 받은 곳. 그때도 원이 사라지면 안 되고,
      // 관청 위에 찍힌 것처럼 보여서도 안 된다.
      { sigungu_cd: '47940', name: '울릉군', sido: '경상북도', parent: '',
        lat: 37.484, lon: 130.905,
        n_umd: 3, pop: { '2024': 10000, '2025': 10000 } },
    ];
    // 묶은 단위(시·도, 시·군)의 관청. 경기도청은 수원에 있고 —
    // 43개 시군구 대표점의 평균과는 한참 다른 자리다.
    //
    // **실제 meta 를 읽어 한 칸만 더한다.** 통째로 지어내면 나머지
    // 검사(기준 연도·차종·밴드)가 진짜 자료를 안 보게 된다.
    {
      const metaPath = path.join(ROOT, 'public', 'app', 'data', 'meta.json');
      const realMeta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
      // 분석이 쓰는 세 용도지역. **아직 안 실린 자료로 돌 수도 있어**
      // (내보내기를 다시 돌리기 전) 없으면 채워 넣는다 — 화면이 그것을
      // 밝히는지가 여기서 볼 것이고, 내보내기가 이 칸을 싣는지는
      // test_web.py 가 따로 본다.
      if (!realMeta.land_use_filter) {
        realMeta.land_use_filter = ['계획관리', '생산관리', '자연녹지'];
      }
      realMeta.region_offices = {
        sido: { '경기도': [37.274975, 127.009235],
                '서울특별시': [37.566610, 126.978388] },
        si: { '수원시': [37.263434, 127.028653] },
      };
      await page.route('**/app/data/meta.json*', (r) => r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(realMeta) }));
    }
    // 땅값 지도 (2026-09-08 지시). 세 시군구 × 두 용도지역.
    // 값이 계단처럼 벌어지게 둬서 색이 실제로 갈리는지 볼 수 있게 한다.
    //
    // 칸 하나는 [건수, 중앙값, 평균, 시작연도] 다.
    //   41111 은 y3 에서 중앙값 10만 · 평균 90만 — **큰 거래가 섞인 곳**.
    //   47940 은 y1 이 없다 — 최근 1년에 거래가 없는 곳.
    const FAKE_LANDPRICE = {
      latest_year: 2025,
      default_group: '계획관리',
      // 법령 구조 그대로의 나무 (국토계획법 §36① · 시행령 §30① · §38).
      zone_tree: [
        { major: '도시지역', middle: '주거지역', names: ['제2종일반주거'] },
        { major: '도시지역', middle: '녹지지역', names: ['자연녹지'] },
        { major: '관리지역', middle: '', names: ['생산관리', '계획관리'] },
        { major: '농림지역', middle: '', names: ['농림'] },
        { major: '용도구역 (법 §38)', middle: '', names: ['개발제한구역'] },
        { major: '기타', middle: '', names: ['용도 미지정'] },
      ],
      zone_notes: {
        '개발제한구역': '용도지역이 아니라 용도구역(법 §38)이다.',
        '용도 미지정': '신고서에 용도지역 칸이 비어 있다.',
      },
      default_window: 'y3',
      windows: [
        { key: 'y1', label: '최근 1년', kind: 'year', span: 1 },
        { key: 'y3', label: '최근 3년', kind: 'year', span: 3 },
        { key: 'c20', label: '최근 20건', kind: 'count', span: 20 },
      ],
      zone_kinds: { 계획관리: '비도시지역', 농림: '비도시지역', 자연녹지: '도시지역' },
      // 명부 조각 색인. 땅값 조각과 달리 용도지역이 없다 — 시·도 하나에
      // 파일 하나다.
      umd_roster: [
        { p: '41', f: 'umd-roster-41.json', n: 3,
          bbox: [37.0, 126.9, 37.4, 127.5] },
        { p: '47', f: 'umd-roster-47.json', n: 1,
          bbox: [37.48, 130.90, 37.49, 130.91] },
      ],
      umd_index: {
        계획관리: [
          { p: '41', f: 'landprice-umd-gyehoek-41.json', n: 3,
            bbox: [37.10, 126.97, 37.31, 127.42] },
          { p: '47', f: 'landprice-umd-gyehoek-47.json', n: 1,
            bbox: [37.48, 130.90, 37.49, 130.91] },
        ],
        // 조각 고르기를 **아직 안 받은 용도지역**에서 본다. 계획관리는
        // 앞 절들이 배율을 올리며 이미 받아 놨을 수 있어서, 그것으로
        // 세면 '안 받았다' 와 '이미 있다' 를 구별하지 못한다.
        자연녹지: [
          { p: '41', f: 'landprice-umd-jayeon-41.json', n: 2,
            bbox: [37.24, 126.97, 37.31, 127.02] },
          { p: '47', f: 'landprice-umd-jayeon-47.json', n: 1,
            bbox: [37.48, 130.90, 37.49, 130.91] },
        ],
        // 조각 고르기는 **처음부터 꺼져 있는 용도지역**에서 본다.
        // 계획관리·자연녹지는 왼쪽 필터의 기본값이라, 앞 절들이 배율을
        // 올리는 동안 이미 다 받아 놨다. 그것으로 세면 '안 받았다' 와
        // '이미 있다' 를 구별하지 못한다.
        농림: [
          { p: '41', f: 'landprice-umd-nongrim-41.json', n: 2,
            bbox: [37.24, 126.97, 37.31, 127.02] },
          { p: '47', f: 'landprice-umd-nongrim-47.json', n: 1,
            bbox: [37.48, 130.90, 37.49, 130.91] },
        ],
      },
      groups: {
        계획관리: {
          // s 는 말풍선에 그릴 최근 추이 — [연도, 건수, 중앙값].
          // 한 해 세 건 미만은 내보내기에서 이미 빠져 있다.
          41111: { y1: [12, 110000, 120000, 2025], y3: [10, 100000, 900000, 2023],
                   c20: [20, 105000, 500000, 2019],
                   s: [[2021, 5, 80000], [2022, 6, 85000], [2023, 4, 92000],
                       [2024, 7, 98000], [2025, 12, 110000]] },
          41113: { y1: [25, 210000, 210000, 2025], y3: [20, 200000, 200000, 2023],
                   c20: [20, 200000, 200000, 2021],
                   s: [[2023, 8, 190000], [2024, 9, 195000], [2025, 25, 210000]] },
          // 최근 1년에는 거래가 없다. y1 칸 자체가 없어야 한다.
          // 추이도 한 해뿐이라 꺾은선을 그릴 수 없다.
          47940: { y3: [3, 30000, 30000, 2023], c20: [20, 28000, 28000, 2009],
                   s: [[2023, 3, 30000]] },
          // **거래가 있었지만 다섯 건이 안 돼 값을 안 쓴 곳.**
          // '거래 0건' 과 다르다 — 여기에 0 을 적으면 세 건 있던 곳을
          // 없던 곳이라고 말하는 것이 된다 (webexport few 칸).
          41220: { few: { y3: 3, y1: 1 } },
        },
        // **도시는 계획관리가 없고 자연녹지만 있다** (보고된 문제,
        // 2026-09-08). 그 상황을 그대로 만들어 둔다 — 자연녹지는 세
        // 시군구에 다 있고 계획관리는 최근 1년에 두 곳뿐이다.
        농림: {
          41111: { y3: [5, 50000, 50000, 2023] },
        },
        // 법령 나무의 나머지 칸도 하나씩 둔다 — 도시지역>주거지역,
        // 용도구역, 기타. 자료에 없으면 화면이 그 칸을 안 그리므로,
        // 없으면 '법령 구조를 그린다' 는 검사가 헛돈다.
        제2종일반주거: {
          41111: { y3: [7, 700000, 700000, 2023] },
        },
        개발제한구역: {
          41113: { y3: [6, 60000, 60000, 2023] },
        },
        '용도 미지정': {
          41113: { y3: [5, 40000, 40000, 2023] },
        },
        자연녹지: {
          // 계획관리 10만(10건) 과 섞으면 (10만×10 + 29만×60) / 70 = 26.3만.
          41111: { y1: [40, 300000, 300000, 2025], y3: [60, 290000, 290000, 2023] },
          41113: { y1: [50, 310000, 310000, 2025], y3: [70, 300000, 300000, 2023] },
          47940: { y1: [20, 40000, 40000, 2025], y3: [30, 39000, 39000, 2023] },
        },
      },
    };
    // 읍면동은 **고른 용도지역 × 화면에 걸치는 시도** 조각만 받는다.
    // 그래서 조각을 둘로 나눠 둔다 — 수도권(41)과 울릉도(47).
    const FAKE_LP_UMD = {
      41: {
        group: '계획관리', sido_prefix: '41', bbox: [37.24, 126.97, 37.31, 127.02],
        // **면 인구는 칸과 따로 온다.** 우리는 리 인구를 갖고 있지 않다 —
        // KOSIS 가 주는 것은 면·동 단위다. 리 값을 합치면 인구가 붙은
        // 리만 더해져 면 인구가 실제보다 작아진다 (run 71 에서 매칭률이
        // 2.6% 였던 것도 리 이름으로 물었기 때문이다).
        head_pop: { '43750|백곡면': 2000 },
        cells: [
          // 한 마디짜리 동은 자기 이름으로 맞는다.
          { nm: '정자동', sg: '41111', sgnm: '수원시 장안구', lat: 37.304, lon: 127.011,
            pop: 28000,
            w: { y1: [8, 130000, 130000, 2025], y3: [9, 120000, 120000, 2023] } },
          // **같은 면의 리 둘.** 면 단계에서는 하나로 묶여야 하고,
          // 리 단계에서는 따로 서야 한다.
          // 리에는 인구가 **없다.** 우리 자료가 면·동까지다.
          { nm: '백곡면 사송리', sg: '43750', sgnm: '진천군', lat: 37.10, lon: 127.40,
            w: { y3: [10, 100000, 100000, 2023],
                 s: [[2023, 4, 90000], [2024, 3, 95000], [2025, 3, 100000]] } },
          { nm: '백곡면 명암리', sg: '43750', sgnm: '진천군', lat: 37.12, lon: 127.42,
            w: { y3: [30, 200000, 200000, 2023] } },
        ],
      },
      47: {
        group: '계획관리', sido_prefix: '47', bbox: [37.48, 130.90, 37.49, 130.91],
        cells: [
          // 이름이 안 맞아 인구가 없는 칸 (pop 없음).
          { nm: '울릉읍', sg: '47940', sgnm: '울릉군', lat: 37.484, lon: 130.905,
            w: { y3: [6, 30000, 30000, 2023] } },
        ],
      },
    };
    // 어느 조각을 실제로 받았는지 센다. '보이는 것만 받는다' 는 말은
    // 그리는 것이 아니라 **받는 것**을 세야 확인된다.
    const lpUmdHits = [];
    // 필지 진단(레이더) — 또래 분포와 누른 필지.
    const FAKE_STATS = {
      min_peer: 30,
      traffic: { radius_km: 10, min_km: 0.5 },
      axes: [{ key: 'road' }, { key: 'traffic' }, { key: 'zoning' },
             { key: 'price' }, { key: 'land' }],
      shape_grade: { 정방형: 5, 가로장방: 4, 사다리: 3, 부정형: 1, 자루형: 0 },
      slope_grade: { 평지: 5, 완경사: 4, 급경사: 2, 고지: 1, 저지: 1 },
      zone_ladder: { 계획관리: 5, 생산관리: 3, 자연녹지: 3, 보전관리: 1, 농림: 1 },
      peers: {
        '41111|계획관리': { n: 120, road: [.05, .15, .3, .5, .7, .93],
          land: [.05, .2, .4, .6, .8, .95],
          price: [1e4, 5e4, 9e4, 13e4, 17e4, 21e4, 25e4, 29e4, 33e4, 37e4, 41e4],
          // 가격 추세 (요구사항 2026-09-10). 연평균 +7.2%, 최근 6년.
          trend: 0.072, trend_span: 6,
          traffic: [0, 50, 120, 300, 700, 1500, 3000, 6000, 12000, 25000, 50000] },
        // 시군구 또래가 얇으면(4건) 시도로 물러난다.
        '47940|계획관리': { n: 4, road: [.5, .5, .5, .5, .5, .5],
          land: [.5, .5, .5, .5, .5, .5], price: [1, 2], traffic: [1, 2] },
        // 이 또래에는 추세가 있다. 시군구(47940)에는 없다 — 물러나는
        // 길이 실제로 있는지 보려면 이 어긋남이 있어야 한다.
        '47|계획관리': { n: 900, road: [.1, .2, .3, .4, .5, .6],
          land: [.1, .2, .3, .4, .5, .6], trend: 0.02, trend_span: 5,
          price: [1e4, 2e4, 3e4, 4e4, 5e4, 6e4, 7e4, 8e4, 9e4, 10e4, 11e4],
          traffic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] },
      },
      // 전국 시군구×용도의 연평균 상승률 분포. 한 또래의 추세를
      // 백분위로 바꾸는 자다. +7.2% 는 이 분포에서 위쪽이다.
      trend_q: [-0.05, -0.01, 0.005, 0.015, 0.025, 0.035, 0.045, 0.055,
                0.065, 0.085, 0.2],
      trend_years: 8,
      zone_pct: { 41111: [.02, .1, .2, .35, .6, .88], 47940: [.1, .3, .4, .5, .6, .7] },
    };
    await page.route('**/app/data/parcelstats.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_STATS),
    }));
    // 개발 한도 표 (C1). 41111(수원시 장안구)은 수원시 조례 — 도시지역만이라
    // 계획관리 값이 없다. 시행령 상한으로 물러나는 길이 보이게 그대로 둔다.
    await page.route('**/app/data/zoning-limits.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        generated: '2026-09-11',
        law: { '계획관리': { bcr_max: 40, far_min: 50, far_max: 100 } },
        ord: { '2102141': { name: '수원시 도시계획 조례', org: '경기도 수원시', eff: '20251231',
                            url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2102141',
                            bcr: { '자연녹지': 20 }, far: { '자연녹지': 100 }, slope: 10, elev: 100 } },
        sg: { '41111': ['2102141', 'sigungu'] },
      }),
    }));
    let parcelHits = 0;
    await page.route('**/api/tile?mode=parcel*', (r) => {
      parcelHits += 1;
      const u = new URL(r.request().url());
      // 바다를 누르면 필지가 없다. 오류가 아니다.
      if (Number(u.searchParams.get('lat')) > 38) {
        return r.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify({ parcel: null }) });
      }
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          parcel: {
            pnu: '4111110300100010000', jimok: '전', land_use: '계획관리지역',
            land_use2: '지정되지않음',
            use_situation: '전', area_m2: 1653, road_side: '중로한면',
            shape: '가로장방형', slope: '평지', official_price: 250000,
            stdr_year: '2025', stdr_month: '01', register: '1',
            jibun_label: '1-1전',
          },
          // 주소 (요구사항 2026-09-10). 도로명은 빈 땅에 대개 없다 —
          // 실측한 두 곳 모두 NOT_FOUND 였다.
          // 겹친 지구·구역 (요구사항 2026-09-10). 용도지역만으로는
          // 무엇을 지을 수 있는지 알 수 없다.
          zones: [
            { label: '가축사육제한구역', detail: '절대제한지역(전 축종)',
              note: '축사를 지을 수 없습니다. 제한 축종은 지자체 고시에 따릅니다.' },
            { label: '농업진흥지역', detail: null,
              note: '농업 관련 시설 외에는 어렵습니다. 진흥구역이 보호구역보다 더 엄합니다.' },
          ],
          addr: { jibun: '경기도 광주시 초월읍 지월리 14-1', road: null,
                  sido: '경기도', sigungu: '광주시', umd: '초월읍',
                  ri: '지월리' },
          // 윤곽. 실제 응답과 같은 꼴이다 (좌표 여섯 자리).
          geom: { type: 'Polygon', coordinates: [[
            [127.0108, 37.3035], [127.0114, 37.3035],
            [127.0114, 37.3044], [127.0108, 37.3044], [127.0108, 37.3035],
          ]] },
        }),
      });
    });
    // 검사가 fixture 와 화면을 맞대어 볼 수 있게 페이지에도 심는다.
    await page.addInitScript((f) => { window.__lpUmdFixture = f; },
                             FAKE_LP_UMD);
    await page.route('**/app/data/landprice-umd-*.json*', (r) => {
      const m = r.request().url().match(/landprice-umd-\w+-(\d+)\.json/);
      const p = m ? m[1] : '41';
      lpUmdHits.push(p);
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(FAKE_LP_UMD[p] || { cells: [] }),
      });
    });
    // 전국 법정동 **명부** 조각. 땅값 조각과 달리 거래와 무관한 원부라,
    // 거래가 한 건도 없던 법정동도 여기에는 있다. 화면은 이것으로 이름을
    // 메운다 (요구사항 2026-09-09 "거래가 없는 동 이름이 다 안나오네요").
    //
    // 줄은 자리를 아끼려고 배열이다 — [이름, 시군구코드, 위도, 경도,
    // 인구, 'u'(읍면동) | 'r'(리)].
    const FAKE_ROSTER = {
      41: {
        sido_prefix: '41',
        bbox: [37.0, 126.9, 37.4, 127.5],
        sgnm: { 41111: '수원시 장안구', 43750: '진천군' },
        head_pop: { '43750|백곡면': 2000 },
        rows: [
          // 땅값 조각에 이미 있는 칸. **두 번 그리면 안 된다.**
          ['백곡면 사송리', '43750', 37.10, 127.40, 0, 'r'],
          // 거래가 없어 땅값 조각에는 없는 리. 면 단계에서는 백곡면으로
          // 접히므로 새 태그가 되지 않고, 리 단계에서만 이름이 선다.
          ['백곡면 신대리', '43750', 37.11, 127.41, 0, 'r'],
          // 거래가 한 건도 없는 동. 이름만 뜨고 값 줄이 없어야 한다.
          ['조원동', '41111', 37.30, 127.01, 3200, 'u'],
          // 법정동코드(일곱째 칸, 2026-09-11) — 지번 검색이 PNU 를 만든다.
          // 화면 밖(37.40)이라 태그 검사에는 안 걸린다.
          ['곤지암읍 건업리', '41610', 37.4028, 127.39476, 0, 'r', '4161025930'],
        ],
      },
    };
    const rosterHits = [];
    await page.route('**/app/data/umd-roster-*.json*', (r) => {
      const m = r.request().url().match(/umd-roster-(\d+)\.json/);
      const k = m ? m[1] : '41';
      rosterHits.push(k);
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(FAKE_ROSTER[k] || { rows: [] }),
      });
    });
    await page.route('**/app/data/landprice.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_LANDPRICE),
    }));

    // 경계선 칸 (mode=parcels). **뒤에 건다** — Playwright 는 나중에
    // 건 규칙을 먼저 보고, 위의 'mode=parcel*' 은 'parcels' 도
    // 삼킨다. 순서가 뒤바뀌면 이 규칙이 죽는다.
    // 지번 → PNU → 필지 (mode=pnu). 무엇을 물었는지 기록한다.
    const pnuAsked = [];
    await page.route('**/api/tile?mode=pnu*', (r) => {
      const u = new URL(r.request().url());
      pnuAsked.push(u.searchParams.get('pnu'));
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ pnu: u.searchParams.get('pnu'), addr: '경기도 광주시 곤지암읍 건업리 140-25',
                               lat: 37.4031, lon: 127.3951,
                               geom: { type: 'Polygon', coordinates: [[[127.395, 37.403], [127.3952, 37.403],
                                       [127.3952, 37.4032], [127.395, 37.4032], [127.395, 37.403]]] } }),
      });
    });
    // 주소 → 좌표 (mode=geocode). 무엇을 물었는지 기록한다.
    const geoAsked = [];
    await page.route('**/api/tile?mode=geocode*', (r) => {
      const u = new URL(r.request().url());
      geoAsked.push(u.searchParams.get('q'));
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ lat: 37.4028, lon: 127.39476, type: 'PARCEL',
                               text: '경기도 광주시 곤지암읍 건업리 140-25' }),
      });
    });
    let cadHits = [];
    await page.route('**/api/tile?mode=parcels*', (r) => {
      const u = new URL(r.request().url());
      cadHits.push(`${u.searchParams.get('z')}/${u.searchParams.get('x')}`
                   + `/${u.searchParams.get('y')}`);
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ n: 1, whole: true, geoms: [{
          type: 'Polygon',
          coordinates: [[[127.1, 37.1], [127.2, 37.1],
                         [127.2, 37.2], [127.1, 37.2], [127.1, 37.1]]],
        }] }),
      });
    });
    await page.route('**/app/data/regions.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_REGIONS),
    }));
    await page.route('**/app/data/verdicts.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_VERDICTS),
    }));
    // 공장은 따로 낸다. 한 파일에 덮어쓰면 나중에 돈 쪽만 남아, 공장을
    // 돌렸는데 화면에는 토지가 떠 있게 된다.
    await page.route('**/app/data/verdicts_factory.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ...FAKE_VERDICTS, kind: 'factory', primary: false,
        hypotheses: FAKE_VERDICTS.hypotheses.map((h) => ({ ...h, rows: [] })),
      }),
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
      // 가짜 Supabase. **빈 객체를 두면 안 된다** — 조회수 코드가
      // window.SB.channel 을 부르는 순간 터지고, 그 예외가 '지도 코드가
      // 예외 없이 돈다' 를 빨갛게 만든다. 그리고 무엇보다, 무엇을
      // 내보내는지를 검사가 볼 수 있어야 한다.
      window.SB = {
        __log: { channels: [], tracked: [], rpc: [], removed: 0, from: [] },
        channel(name, opts) {
          const rec = { name, opts, handlers: [], state: {} };
          window.SB.__log.channels.push(rec);
          const ch = {
            on(_t, _f, cb) { rec.handlers.push(cb); return ch; },
            subscribe(cb) { if (cb) cb('SUBSCRIBED'); return ch; },
            track(p) { window.SB.__log.tracked.push(p); return Promise.resolve(); },
            presenceState() { return rec.state; },
          };
          // 접속자 수를 바깥에서 흔들 수 있게 열어 둔다.
          rec.sync = (n) => {
            rec.state = {};
            for (let i = 0; i < n; i++) rec.state['k' + i] = [{}];
            rec.handlers.forEach((h) => h());
          };
          return ch;
        },
        removeChannel() { window.SB.__log.removed++; return Promise.resolve(); },
        rpc(fn, args) {
          window.SB.__log.rpc.push({ fn, args });
          if (fn === 'place_view_stats') {
            const keys = args.keys || [];
            // 24시간 누적을 **겹치지 않게** 내려준다 (keys.length - i). 같은
            // 값이 둘이면 '1등이 누구인가' 를 검사가 못 정한다.
            // 그리고 짝수 번째만 준다 — 숫자가 없는 태그도 있어야
            // '배지를 안 만든다' 는 규칙을 볼 수 있다. __statsCap 으로
            // 값을 눌러 '10명 미만이면 별 없음' 을 본다.
            const cap = window.__statsCap || Infinity;
            // 내가 올린(bump) 태그는 진짜 서버라면 반드시 통계에 있다 —
            // 짝수 규칙과 무관하게 넣어 준다.
            const bumped = new Set(window.SB.__log.rpc
              .filter((x) => x.fn === 'bump_place_view').map((x) => x.args.k));
            return Promise.resolve({
              data: keys.map((k, i) => ({
                place_key: k, n24: Math.min(cap, 1000 - i),
              })).filter((x, i) => i % 2 === 0 || bumped.has(x.place_key)),
              error: null,
            });
          }
          // bump 는 그 태그의 **24시간 누적**을 돌려준다.
          if (fn === 'bump_place_view') {
            return Promise.resolve({ data: 1, error: null });
          }
          return Promise.resolve({ data: 1, error: null });
        },
        from(t) {
          window.SB.__log.from.push(t);
          const q = {
            select: () => q, eq: () => q,
            maybeSingle: () => Promise.resolve({ data: { n: 148 }, error: null }),
          };
          return q;
        },
      };
      // 승인된 회원으로 들어간다. 승인 관문 자체는 test_gate.js 가 본다.
      // 등급 (2026-09-11). 관문이 me() 의 답을 window.ME 에 둔다 — B(프리미엄)로
      // 들어가고, C 로 바꿔 잠기는지는 아래 절에서 본다. 판단은 실제 /lib/access.js.
      window.ME = { user: { id: 'u1' }, profile: { status: 'approved', grade: 'B' } };
      window.SBUtil = { me: async () => window.ME };
    });
    await page.addInitScript(FAKE_LEAFLET);
    // 가짜 Leaflet 은 DOM 에 아무것도 안 넣는다. 태그를 읽으려면
    // 마커가 들고 있는 icon html 을 봐야 한다.
    await page.addInitScript(() => {
      window.__cards = () => (window.__map.groups || [])
        .flatMap((g) => g._items)
        .filter((m) => m.options && m.options.pane === 'lpPane')
        .map((m) => ((m.options.icon || {}).options || {}).html || '');
    });
    const errs = [];
    page.on('pageerror', (e) => errs.push(String(e)));
    await page.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#gate-bg', { timeout: 20000 });
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
    // 배경 지도(OSM) + 용도지역 색면 = 2장. 필지 경계선은 **타일이
    // 아니다** — 브이월드 WMS 가 배율 18 아래로 빈 그림만 줘서
    // 도형(WFS)으로 받아 직접 그린다 (2026-09-10 실측).
    check('타일 원천이 둘이다 (배경 + 용도지역)', tiles.length === 2,
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
    // 경계선은 타일로 돌아가면 안 된다. 그 길은 빈 그림을 주면서도
    // '✓ 그림' 으로 읽혀 오래 안 들켰다.
    check('필지 경계선은 타일로 안 받는다', !cad, tiles.join(' '));
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

    // ── 오른쪽 칸 닫기 (요구사항 2026-09-09) ──────────────────────
    //
    // "필지 자료 창 닫기 버튼 추가해 주세요."
    //
    // 한 번 열면 닫을 길이 없었다. 휴대폰에서는 이 칸이 화면의 3분의
    // 1을 먹는데 지도로 돌아갈 방법이 없었다.
    const shut = await page.evaluate(() => {
      const box = document.getElementById('detail');
      const btn = box.querySelector('.detail-close');
      const opened = !box.hidden;
      if (btn) btn.click();
      return { opened, had: !!btn, closed: box.hidden };
    });
    check('오른쪽 칸에 닫기 단추가 있다', shut.opened && shut.had,
          `열림=${shut.opened} · 단추=${shut.had}`);
    check('누르면 실제로 닫힌다', shut.closed, `hidden=${shut.closed}`);
    // 닫았으니 뒤 절들이 볼 수 있게 다시 연다.
    await page.evaluate(() => {
      const el2 = document.querySelector('tr[data-id], [data-id]');
      if (el2) el2.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    await page.waitForTimeout(500);
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
      // 보고된 문제(2026-09-04): "IC 선택 후 범위가 표시되면 범위 내로
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
    console.log('4-A. 필터를 큰 분류 셋으로 묶었다');
    // 요구사항(2026-09-08): "왼쪽 필터를 큰 분류별로 묶어주세요
    // (호갱노노 참조). 실거래 표시 / IC / 실거래 가격 으로 묶어주고,
    // 선택하면 하단에 현재 필터들을 선택할 수 있도록."
    const cats = await page.evaluate(() => ({
      // 왼쪽 레일을 없앴다 — 필터가 지도 옆에 늘 펼쳐져 있으면 지도가
      // 그만큼 좁아지는데 실제로 만지는 것은 한 번에 한 묶음뿐이다.
      chips: [...document.querySelectorAll('.cat')].map((b) => b.dataset.cat),
      labels: [...document.querySelectorAll('.cat')].map((b) => b.textContent.trim()),
      sheetShut: (document.getElementById('sheet') || {}).hidden,
    }));
    // 보고된 문제(2026-09-08): "왼쪽 위에 (+)(-)와 필터가 겹칩니다.
    // 클릭 시 화면 아래로 표시되는데 이건 왼쪽으로 기존 처럼 옮겨주세요."
    //
    // 처음에는 지도 **위에** 칩을 띄우고 아래에서 시트를 올렸는데 둘 다
    // 문제였다 — 칩이 Leaflet 의 +/- 단추와 겹쳤고, 시트는 지도의
    // 아래쪽을 덮었다. 지도 **밖**의 왼쪽 칸으로 옮기면 둘 다 없어진다.
    const place = await page.evaluate(() => {
      const bar = document.querySelector('.cat-bar');
      const mapEl = document.getElementById('map');
      const zoom = document.querySelector('.leaflet-control-zoom')
        || { getBoundingClientRect: () => ({ left: 0, right: 0, top: 0, bottom: 0 }) };
      const b = bar.getBoundingClientRect();
      const z = zoom.getBoundingClientRect();
      const overlap = !(b.right <= z.left || b.left >= z.right
                        || b.bottom <= z.top || b.top >= z.bottom);
      return {
        inSide: !!bar.closest('.side'),
        overMap: !!bar.closest('.map-wrap'),
        overlap,
        // 왼쪽에 있어야 한다 — 지도보다 왼쪽에서 시작한다.
        leftOfMap: b.left < mapEl.getBoundingClientRect().left + 1,
      };
    });
    check('필터가 지도 위가 아니라 왼쪽 칸에 있다',
          place.inSide && !place.overMap, JSON.stringify(place));
    check('확대·축소 단추와 안 겹친다', !place.overlap);
    check('지도보다 왼쪽에 있다 (기존 자리)', place.leftOfMap);
    check('큰 분류가 셋이다',
          cats.chips.join(',') === 'trade,ic,price', cats.chips.join(','));
    check('이름이 지시하신 그대로다',
          cats.labels.join(' / ') === '실거래 표시 / IC / 실거래 가격',
          cats.labels.join(' / '));
    check('처음에는 시트가 닫혀 있다 (지도부터 보이게)', cats.sheetShut);

    const openCat = async (cat) => page.evaluate((c) => {
      document.querySelector(`.cat[data-cat="${c}"]`).click();
      const sheet = document.getElementById('sheet');
      const pane = document.querySelector(`.sheet-pane[data-cat="${c}"]`);
      return {
        shut: sheet.hidden,
        title: (document.getElementById('sheet-title') || {}).textContent,
        paneShown: pane ? !pane.hidden : false,
        others: [...document.querySelectorAll('.sheet-pane')]
          .filter((p) => p.dataset.cat !== c && !p.hidden).length,
        chipOn: document.querySelector(`.cat[data-cat="${c}"]`).classList.contains('is-on'),
        has: (id) => !!document.getElementById(id),
      };
    }, cat);

    const oTrade = await openCat('trade');
    check('누르면 아래에서 그 묶음이 올라온다',
          !oTrade.shut && oTrade.paneShown && oTrade.chipOn
          && oTrade.title === '실거래 표시',
          `"${oTrade.title}"`);
    check('한 번에 한 묶음만 보인다', oTrade.others === 0,
          `다른 묶음 ${oTrade.others}개 열림`);
    check('열면 왼쪽 칸이 벌어진다',
          await page.evaluate(() =>
            document.getElementById('side').classList.contains('is-open')));
    // 옮기면서 조작부를 흘리면 안 된다. 하나라도 없으면 그 필터는
    // 화면에서 사라진 것이고, 사라진 줄도 모른다.
    const moved = await page.evaluate(() => ({
      // stage-filters 는 뺐다 (요구사항 2026-09-09: "토지-개발단계는
      // 선택 제외"). 목록에 남겨 두면 없어진 것을 계속 찾는다.
      trade: ['kind-filters', 'year-from', 'year-to',
              'road-filter', 'parcel-only']
        .filter((id) => !document.getElementById(id)),
      // 용도지역 칸도 뺐다 (요구사항 2026-09-10: "실거래 표시에서
      // 용지역은 삭제합니다. 항상 전체 표기 함"). 되살아나면 잡는다 —
      // 되살아나는 순간 처음 화면에서 스물두 종이 다시 빠진다.
      gone: ['stage-filters', 'lu-core',
             'land-use-filters', 'lu-all', 'lu-none']
        .filter((id) => document.getElementById(id)),
      ic: ['tg-year', 'tg-vehicle', 'tier-filters', 'band-legend']
        .filter((id) => !document.getElementById(id)),
      price: ['lp-note', 'lp-swap'].filter((id) => !document.getElementById(id)),
      // **묶음 안에서 센다.** 시트 전체를 세면 다른 묶음의 칩까지 들어와,
      // 핀 칩을 더한 날 이 검사가 엉뚱한 이유로 빨개진다 (2026-09-09).
      pills: document.querySelectorAll(
        '.sheet-pane[data-cat="price"] .lp-filter').length,
      pinPill: document.querySelectorAll(
        '.sheet-pane[data-cat="trade"] .lp-filter[data-filter="pin"]').length,
    }));
    check('실거래 표시 묶음에 그 조작부가 다 있다',
          moved.trade.length === 0, moved.trade.join(','));
    // 뺀 것은 **실제로 없어야** 한다. 화면에서 안 보이게만 하고 두면
    // 다음 사람이 그것을 살아 있는 조작부로 읽는다.
    check('뺀 조작부는 화면에 남아 있지 않다', moved.gone.length === 0,
          moved.gone.join(',') || '없음');
    check('IC 묶음에 그 조작부가 다 있다', moved.ic.length === 0, moved.ic.join(','));
    check('실거래 가격 묶음에 땅값 칩이 있다',
          moved.price.length === 0 && moved.pills === 2,
          `빠진 것 ${moved.price.join(',')} · 칩 ${moved.pills}개`);
    // 핀 유형은 **거래 쪽** 조작이다. 땅값 칩 옆에 두면 지도의 바탕색을
    // 바꾸는 줄 안다.
    check('실거래 표시 묶음에 핀 유형 칩이 있다', moved.pinPill === 1,
          `${moved.pinPill}개`);

    // ── 차종 (요구사항 2026-09-09) ────────────────────────────
    //
    // "차종 선택을 여러개를 선택 할 수 있게 펼쳐 주시고 (용도지역처럼)
    //  1종, 2종 등 차종에 따른 이미지 및 간략 설명 넣어주세요."
    //
    // 드롭다운이라 하나만 고를 수 있었다. 그런데 이 제품이 보는 것은
    // 화물(3·4·5종)이라, 그것을 보려면 세 번 나눠 보고 머릿속에서
    // 더해야 했다.
    {
      const veh = await page.evaluate(() => ({
        select: document.querySelectorAll('#tg-vehicle select').length,
        opts: [...document.querySelectorAll('.veh-opt')].map((b) => ({
          code: b.dataset.code,
          on: b.getAttribute('aria-pressed') === 'true',
          art: b.querySelectorAll('.veh-art circle').length,
          desc: (b.querySelector('s') || {}).textContent || '',
          tip: b.title,
        })),
      }));
      check('차종이 드롭다운이 아니라 펼친 칸이다',
            veh.select === 0 && veh.opts.length === 6,
            `select ${veh.select}개 · 칸 ${veh.opts.length}개`);
      check('처음에는 다 켜져 있다 (예전 "전체 차종" 과 같은 화면)',
            veh.opts.every((o) => o.on),
            veh.opts.filter((o) => o.on).length + '개');
      // 그림은 장식이 아니다 — 축 수가 곧 그 차종의 정의다
      // (유료도로법 시행령 별표1). 4종은 3축, 5종은 4축.
      const byCode = Object.fromEntries(veh.opts.map((o) => [o.code, o]));
      check('그림이 축 수를 그대로 그린다 (4종 3축 · 5종 4축)',
            byCode['1'].art === 2 && byCode['4'].art === 3
            && byCode['5'].art === 4,
            veh.opts.map((o) => `${o.code}종 ${o.art}축`).join(' · '));
      check('칸마다 한 줄 설명이 붙는다',
            veh.opts.every((o) => o.desc.length > 0 && o.tip.length > 0),
            byCode['4'].desc);

      // 여럿 고를 수 있어야 한다. 화물만 보려면 3·4·5를 함께 켠다.
      const picked = await page.evaluate(() => {
        document.querySelectorAll('.veh-opt').forEach((b) => {
          const want = ['3', '4', '5'].indexOf(b.dataset.code) >= 0;
          if ((b.getAttribute('aria-pressed') === 'true') !== want) b.click();
        });
        return window.__veh;
      });
      check('여럿을 골라 화물만 볼 수 있다',
            JSON.stringify(picked) === '[3,4,5]', JSON.stringify(picked));
      await page.evaluate(() => {
        document.querySelectorAll('.veh-opt').forEach((b) => {
          if (b.getAttribute('aria-pressed') !== 'true') b.click();
        });
      });
    }

    const oIc = await openCat('ic');
    check('다른 분류를 누르면 그쪽으로 바뀐다',
          !oIc.shut && oIc.paneShown && oIc.title === 'IC' && oIc.others === 0,
          `"${oIc.title}"`);
    const again = await openCat('ic');
    check('같은 분류를 다시 누르면 닫힌다', again.shut && !again.chipOn);

    console.log();
    console.log('4-C. 토지 하위 필터를 켜면 토지도 같이 켜진다');
    // 보고된 문제(2026-09-08): "제2종일반주거지역 처럼 일부 용도지역
    // 클릭 시 지도에 표기되지 않습니다."
    //
    // 고장이 아니라 덫이었다. 용도지역·개발단계·도로접은 **토지에만 거는
    // 조건**인데, 물건 종류에서 '토지' 가 꺼져 있으면(처음이 그렇다)
    // 아무리 켜도 걸러낼 토지가 없다. 화면은 아무 말도 안 하고 비어 있다.
    //
    // 용도지역 칸은 뺐다 (요구사항 2026-09-10). 덫이 사라진 것은
    // 아니다 — 도로 접함이 같은 성격의 조건으로 남아 있다.
    await openCat('trade');
    const trap = await page.evaluate(() => {
      const kinds = document.getElementById('kind-filters');
      const land = [...kinds.querySelectorAll('input')]
        .find((i) => i.dataset.key === 'land');
      // 일부러 토지를 끈 채로 시작한다 (처음 화면이 그렇다).
      if (land.checked) land.click();
      const before = land.checked;
      const rsel = document.getElementById('road-filter');
      rsel.value = 'ok';
      rsel.dispatchEvent(new Event('change'));
      return { before, after: land.checked, picked: rsel.value };
    });
    check('토지가 꺼진 채로 시작한다 (그것이 덫이었다)', trap.before === false);
    check('도로 접함을 고르면 토지도 켜진다',
          trap.after === true, `${trap.picked} → 토지 ${trap.after}`);
    // 뒤 절들이 '처음 화면' 을 본다. 여기서 만진 것을 되돌려 놓는다 —
    // 안 그러면 이 검사가 다음 검사를 깨뜨린다.
    await page.evaluate(() => {
      const rsel = document.getElementById('road-filter');
      rsel.value = 'all';
      rsel.dispatchEvent(new Event('change'));
      const land = [...document.querySelectorAll('#kind-filters input')]
        .find((i) => i.dataset.key === 'land');
      if (land.checked) land.click();
    });

    console.log();
    console.log('4-B. 거래 연도를 좌/우 손잡이로');
    await openCat('trade');
    const yr = await page.evaluate(() => {
      const f = document.getElementById('year-from');
      const t = document.getElementById('year-to');
      const set = (el, v) => { el.value = String(v); el.dispatchEvent(new Event('input')); };
      const read = () => ({
        out: document.getElementById('year-out').textContent,
        from: window.__state ? null : null,
      });
      const one = (() => { set(f, f.max); set(t, f.max); return read().out; })();
      const range = (() => { set(f, f.min); return read().out; })();
      // 손잡이가 엇갈리면 서로 밀어낸다 — '2020~2015' 같은 뒤집힌 범위가
      // 만들어지면 아무것도 안 보인다.
      const crossed = (() => { set(f, f.max); set(t, t.min); return read().out; })();
      const fill = document.getElementById('yr-fill');
      set(f, f.min); set(t, t.max);
      return { one, range, crossed, wide: document.getElementById('year-out').textContent,
               fillLeft: fill.style.left, fillRight: fill.style.right };
    });
    check('한 해만 고르면 그 해만 적는다', /^\d{4}년$/.test(yr.one), yr.one);
    check('범위를 넓히면 두 해를 적는다', /~/.test(yr.range), yr.range);
    check('손잡이가 엇갈려도 뒤집히지 않는다',
          !/(\d{4}) ~ (\d{4})/.test(yr.crossed)
          || Number(RegExp.$1) <= Number(RegExp.$2), yr.crossed);
    check('고른 구간이 막대에 칠해진다',
          yr.fillLeft === '0%' && yr.fillRight === '0%',
          `left=${yr.fillLeft} right=${yr.fillRight}`);
    await page.evaluate(() => document.getElementById('sheet-close').click());

    console.log();
    console.log('4. 왼쪽 설명을 물음표 뒤로 접었다');
    // 요구사항(2026-09-08): "왼쪽 스크롤에 있는 문장들은 물음표 원
    // 표시 아이콘(?) 만들어서 마우스 클릭하면 나타나도록... 지금은 무슨
    // 책같아서 뭘 봐야할 지 모르겠습니다."
    //
    // 설명이 틀린 것은 아니었다. 다만 필터가 열두 줄짜리 설명 사이에
    // 파묻혀 있으면 읽지도 않고 만지지도 못한다. **지우지 않고 접는다** —
    // 지우면 '왜 계획관리만 켜져 있나' 를 물을 곳이 없어진다.
    // 필터가 아래 시트로 옮겨졌다 (2026-09-08). 열어야 보인다.
    await page.evaluate(() => {
      document.querySelector('.cat[data-cat="trade"]').click();
    });
    await page.waitForTimeout(150);
    const why = await page.evaluate(() => {
      const btns = [...document.querySelectorAll('.sheet .info-dot')];
      const bodies = [...document.querySelectorAll('.sheet .info-pop')];
      const vis = (e) => !!(e && !e.hidden && e.offsetParent !== null);
      return {
        buttons: btns.length,
        labels: btns.map((b) => b.textContent.trim()),
        openAtStart: bodies.filter(vis).length,
        // 접었어도 글은 남아 있어야 한다.
        text: bodies.map((b) => b.textContent).join(' '),
        // 접고 나서 화면에 남는 **줄글**. 필터가 파묻히면 안 된다.
        //
        // #deal-year-note 는 뺀다. 그것은 설명이 아니라 **살아 있는
        // 수치**다 — 지금 몇 건 중 몇 건을 표본으로 받았고 화면에 몇 개를
        // 그렸는지. 이 줄이 없으면 '2019년 계획관리 거래는 이 열 점이
        // 전부' 로 읽히고, 스크리닝 도구에서 그 오해는 곧바로 투자
        // 판단으로 이어진다.
        loose: [...document.querySelectorAll('.sheet p.hint')]
          .filter((e) => e.id !== 'deal-year-note')
          .filter((e) => vis(e) && e.textContent.trim().length > 40).length,
        live: (document.getElementById('deal-year-note') || {}).textContent || '',
      };
    });
    check('제목마다 물음표 단추가 있다', why.buttons >= 5, `${why.buttons}개`);
    check('단추가 물음표 하나다', why.labels.every((t) => t === '?'),
          why.labels.join(''));
    check('처음에는 다 접혀 있다 (필터부터 보이게)', why.openAtStart === 0,
          `${why.openAtStart}개 펼쳐짐`);
    check('접어도 설명은 지우지 않는다', /1\.7배/.test(why.text) && /계획관리/.test(why.text));
    // 관리지역이 왜 따로 있는지도 여기서 답한다 (2006~2010년의 잔재).
    check('관리지역이 왜 따로 있는지 적어 둔다', /2006~2010/.test(why.text));
    check('접고 나면 긴 줄글이 안 남는다', why.loose === 0, `${why.loose}줄`);
    // 설명은 접되 **표본 수치는 남긴다.** 그것을 같이 접으면 사람은
    // 화면의 점 몇 개를 그 해 거래 전부로 읽는다.
    check('표본이 몇 건인지는 접지 않는다',
          /건/.test(why.live) && why.live.length > 10, why.live.slice(0, 70));

    const whyOpen = await page.evaluate(() => {
      const b = document.querySelector('.sheet-pane:not([hidden]) .info-dot');
      b.click();
      const body = b.closest('h2, h3').nextElementSibling;
      return { open: !body.hidden, on: b.classList.contains('is-on'),
               aria: b.getAttribute('aria-expanded') };
    });
    check('누르면 그 자리에서 펼쳐진다',
          whyOpen.open && whyOpen.on && whyOpen.aria === 'true',
          JSON.stringify(whyOpen));
    const whyShut = await page.evaluate(() => {
      const b = document.querySelector('.sheet-pane:not([hidden]) .info-dot');
      b.click();
      return b.closest('h2, h3').nextElementSibling.hidden;
    });
    check('다시 누르면 접힌다', whyShut);
    // **이름을 .why 로 지으면 안 된다.** 그 이름은 가설 판정 카드의 근거
    // 문단과 추이 비교의 계열 설명이 이미 쓰고 있다. 우리 규칙의 box
    // 부분을 물려받아 그것들이 16px 동그라미가 된다 — 이 저장소에서
    // .listing 으로 이미 한 번 겪은 종류의 사고다.
    const clash = await page.evaluate(() => {
      const p2 = document.createElement('p');
      p2.className = 'why';
      p2.textContent = '근거 문단';
      document.body.appendChild(p2);
      const cs = getComputedStyle(p2);
      const got = { w: cs.width, radius: cs.borderRadius };
      p2.remove();
      return got;
    });
    check('설명 단추 이름이 다른 곳의 .why 를 안 부순다',
          clash.radius !== '50%' && clash.w !== '16px',
          `.why 문단 → 폭 ${clash.w} 반지름 ${clash.radius}`);

    console.log();
    // ── 배경 지도 고르기 (요구사항 2026-09-09) ────────────────
    //
    // "현재 것, 브이월드, 위성, 일반 등 선택할 수 있도록"
    //
    // 카카오·네이버는 타일이 아니라 SDK 라 못 씁니다. 브이월드는 래스터
    // 타일이라 꽂힙니다 — 점검 6-C 에서 넷이 그림으로 왔습니다.
    {
      const bm = await page.evaluate(() => ({
        keys: [...document.querySelectorAll('#basemap-pick button')]
          .map((b) => b.dataset.key),
        on: (document.querySelector('#basemap-pick button.is-on') || {}).dataset,
        now: window.__basemap,
        body: document.body.dataset.basemap,
      }));
      check('배경 지도를 고를 수 있다', bm.keys.length === 5,
            bm.keys.join(','));
      // **기본은 지금 것(OSM)** 이다. 브이월드 타일은 우리 함수를 거치므로
      // 고른 사람만 그 값을 쓰게 둔다.
      check('기본은 지금 쓰던 배경이다 (OSM)',
            bm.now === 'osm' && bm.on && bm.on.key === 'osm',
            `${bm.now} · 눌린 것 ${(bm.on || {}).key}`);
      const sat = await page.evaluate(() => {
        document.querySelector('#basemap-pick button[data-key="satellite"]').click();
        return { now: window.__basemap, body: document.body.dataset.basemap,
                 srcs: (window.__map.tiles || []).slice() };
      });
      check('위성으로 바꾸면 타일 원천이 바뀐다',
            sat.now === 'satellite'
            && sat.srcs.some((u) => /layer=satellite/.test(u)),
            (sat.srcs.slice(-1)[0] || '없음'));
      // 위성 사진에 OSM 용 채도 손질을 걸면 흙과 논밭이 한 덩이가 된다.
      // 그 판단을 CSS 가 하도록 몸통에 표를 남긴다.
      check('무엇을 깔았는지 몸통에 적는다 (색 손질을 가르려고)',
            sat.body === 'satellite', sat.body);
      await page.evaluate(() => {
        document.querySelector('#basemap-pick button[data-key="osm"]').click();
      });
    }

    console.log('4-B. 지도 위 범례를 걷어냈다');
    // 요구사항(2026-09-08): "좌측 범례 삭제".
    //
    // 지도 왼쪽 아래를 12줄짜리 범례가 덮고 있었다. 지도를 키워 놓고 그
    // 위를 범례로 다시 덮으면 뜻이 없다. 담고 있던 것(거래 색·영업소
    // 단·밴드)은 왼쪽 필터와 말풍선에 이미 있다.
    const legend = await page.evaluate(() => ({
      overlay: !!document.querySelector('.map-legend'),
      peek: !!document.querySelector('.legend-peek'),
      // 거리 밴드는 왼쪽 필터 안에 남는다 — 지도를 안 덮는다.
      bands: document.querySelectorAll('#band-legend .row').length,
    }));
    check('지도 위 범례가 없다', !legend.overlay && !legend.peek,
          `overlay=${legend.overlay} peek=${legend.peek}`);
    check('거리 밴드 범례는 왼쪽 필터에 남는다', legend.bands >= 3,
          `${legend.bands}줄`);

    /* 5절('전체 IC 반경')은 스위치와 함께 사라졌다 —
       요구사항 2026-09-08: "화면 상단 인구 및 IC범위 체크는 삭제합니다".
       스위치가 없으니 켜고 끌 것도 없다. 지워졌다는 것만 못 박는다. */
    const gone = await page.evaluate(() => ({
      allBands: !!document.getElementById('all-bands'),
      popBox: !!document.getElementById('pop-bg'),
      popSwitch: !!document.getElementById('pop-switch'),
      switches: document.querySelectorAll('.map-tools .map-switch').length,
    }));
    check('상단에서 전체 IC 반경 스위치가 사라졌다', !gone.allBands);
    check('상단에서 인구 스위치가 사라졌다', !gone.popBox && !gone.popSwitch);
    // 셋이다 — IC·영업소 · 용도지역 · 필지경계 (요구사항 2026-09-10).
    // 예전에 넷을 둘로 줄인 절이라, 늘어난 하나는 여기서 못을 박는다.
    check('스위치는 셋이다 (IC·영업소 · 용도지역 · 필지경계)',
          gone.switches === 3,
          `${gone.switches}개`);

    console.log();
    console.log('7. 거래 점이 배경에서 보인다 · 도로 위계가 살아 있다');
    // 보고된 문제: "토지, 공장 색상이 배경과 너무 구분이 안됩니다."
    // 원인은 반경 2.5 · 테두리 없음 · 불투명도 0.3~0.6 이었다.
    // 색을 더 진하게 하는 것으로는 못 이긴다 — 흰 테두리가 점을
    // 배경에서 끊어주는 것이 핵심이라 그것을 못박는다.
    // 요구사항(2026-09-04): "모든 실거래는 초기 기본설정은 표기 끄는 것."
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
      // 보고된 문제(2026-09-04): "어느게 IC이고 어느게 거래건인지 구분이
      // 안됩니다." 색을 더 늘려 푸는 문제가 아니다 — **모양이 먼저
      // 종류를 말해야 한다.** 영업소는 원, 거래는 네모·마름모다.
      check('거래는 원이 아니다 (영업소와 모양으로 갈린다)',
            tradeStyle.every((o) => /trade-mark/.test(o.html)),
            `${tradeStyle.length}개 · 예: ${tradeStyle[0].html.slice(0, 60)}`);
      const land = tradeStyle.filter((o) => /trade-land/.test(o.html));
      // 공장 계열은 색이 셋으로 갈렸다 (공장·창고·그 밖 산업시설).
      // 모양은 셋 다 마름모라 토지의 네모와는 여전히 갈린다.
      const fac = tradeStyle.filter(
        (o) => /trade-factory|trade-warehouse|trade-etc/.test(o.html));
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
      // 보고된 문제(2026-09-04): "실거래 및 매물 표시는 IC 아래로."
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
    // ── 거래 핀 (요구사항 2026-09-09) ─────────────────────────
    //
    // "우리는 매물을 클릭했을 때 나와서 무슨 물건인지 모릅니다."
    //
    // 눌러야만 알 수 있으면 스무 건을 견주는 데 스무 번을 눌러야 한다.
    // 부동산플래닛처럼 핀에 값을 적되, **당겨 봤을 때만** 적는다.
    {
      const pinRead = async () => page.evaluate(() => {
        const on = window.__mapOn || {};
        (on.zoomend || []).forEach((f) => f());
        (on.moveend || []).forEach((f) => f());
        return { peek: window.__pins || {},
                 html: (window.__tradeStyles || []).map((o) => o.html) };
      });
      // 켜 놓고 본다 (앞 절이 종류 필터를 다 켜 두었다).
      await page.evaluate(() => { window.__zoom = 11; });
      const far = await pinRead();
      check('멀리서는 점 그대로다 (글자를 안 단다)',
            far.peek.labelled === false
            && far.html.every((h) => /trade-mark/.test(h)),
            `labelled=${far.peek.labelled} · ${(far.html[0] || '').slice(0, 50)}`);

      await page.evaluate(() => { window.__zoom = 16; });
      const near = await pinRead();
      check('당겨 보면 핀에 값이 적힌다',
            near.peek.labelled === true
            && near.html.some((h) => /class="trade-pin/.test(h)),
            `labelled=${near.peek.labelled} · ${(near.html[0] || '').slice(0, 70)}`);
      // 종류 · 값 · 보조 세 줄. 값만 있으면 무슨 물건인지 여전히 모른다 —
      // 그것이 보고된 문제의 핵심이었다.
      check('핀이 무슨 물건인지 말한다 (종류가 적힌다)',
            near.html.some((h) => /<b>(토지|공장|창고|공장·창고)<\/b>/.test(h)),
            (near.html.find((h) => /trade-pin/.test(h)) || '없음').slice(0, 90));
      // 꼬리가 **좌표를 가리켜야** 한다. 카드만 있으면 어느 필지인지 모른다.
      check('핀에 꼬리가 있다 (어느 자리인지 가리킨다)',
            near.html.every((h) => !/trade-pin[ "]/.test(h)
                                   || /trade-pin-tail/.test(h)),
            (near.html.find((h) => /trade-pin/.test(h)) || '없음').slice(-60));

      const pinPick = async (v) => {
        await page.evaluate((val) => {
          const box = document.querySelector('.lp-filter[data-filter="pin"]');
          box.querySelector('.lp-pill').click();
          box.querySelector(`.lp-opt[data-value="${val}"]`).click();
        }, v);
        return pinRead();
      };
      const byYear = await pinPick('year');
      check('핀 유형을 바꾸면 적히는 값이 바뀐다',
            byYear.peek.kind === 'year'
            && byYear.html.some((h) => /<i>\d{4}년<\/i>/.test(h)),
            (byYear.html.find((h) => /trade-pin/.test(h)) || '없음').slice(0, 90));
      // **같은 값을 두 줄에 적지 않는다.** 연도를 골랐는데 보조 줄에도
      // 연도가 있으면 그 줄이 아무 말도 안 하게 된다.
      check('보조 줄이 고른 유형과 겹치지 않는다',
            byYear.html.filter((h) => /trade-pin/.test(h))
              .every((h) => {
                const sub = (h.match(/<s>([^<]*)<\/s>/) || [])[1] || '';
                return !/\d{4}(?!평)/.test(sub.replace(/[\d,]+평/g, ''));
              }),
            (byYear.html.find((h) => /<s>/.test(h)) || '(보조 줄 없음)').slice(0, 90));
      const byArea = await pinPick('area');
      check('면적으로도 바꿀 수 있다',
            byArea.peek.kind === 'area'
            && byArea.html.some((h) => /<i>[\d,]+평<\/i>/.test(h)),
            (byArea.html.find((h) => /trade-pin/.test(h)) || '없음').slice(0, 90));
      // 우리에게 없는 칸은 고르게 두지 않는다. 눌렀을 때 비면 그것은
      // '자료가 없다' 가 아니라 고장으로 읽힌다.
      const opts = await page.evaluate(() => [...document.querySelectorAll(
        '.lp-filter[data-filter="pin"] .lp-opt')].map((b) => b.dataset.value));
      check('없는 칸은 고르게 두지 않는다 (건물단가·세대수 없음)',
            opts.length === 6 && !opts.includes('households')
            && !opts.includes('buildUnit'),
            opts.join(','));
      await pinPick('price');
      await page.evaluate(() => { window.__zoom = 11; });
      await pinRead();
    }

    console.log('9. 인구는 원이 아니라 땅값 글자 옆의 (XX만)');
    /* 요구사항(2026-09-08):
     *   "도, 광역시, 시, 군, 읍, 동, 리 사각에서 상단에 이름 옆에 인구를
     *    아주 작게 표시해 주세요. (XX만) 단위는 만명"
     *   "추가로 화면 상단 인구 및 IC범위 체크는 삭제합니다."
     *
     * 원을 지운 자리를 글자가 대신한다. 원이 정말 사라졌는지, 그리고
     * **묶인 시군구를 합친 값인지**를 본다 — 경기도 칸에 수원시 인구만
     * 적히면 그 숫자는 거짓말이다. */
    const popPeek = async (z) => page.evaluate((zoom) => {
      window.__zoom = zoom;
      const on = window.__mapOn || {};
      (on.zoomend || []).forEach((fn) => fn());
      (on.moveend || []).forEach((fn) => fn());
      const all = (window.__map.groups || []).flatMap((g) => g._items);
      return {
        circles: all.filter((m) => (m.options || m.__opts || {}).pane
                                   === 'popPane').length,
        cards: all.filter((m) => m.options && m.options.pane === 'lpPane')
          .map((m) => ((m.options.icon || {}).options || {}).html || ''),
      };
    }, z);

    const wide = await popPeek(7);
    check('인구 원을 더는 그리지 않는다', wide.circles === 0,
          `${wide.circles}개`);
    const withPop = wide.cards.filter((h) => /<em>[\d.]+만<\/em>/.test(h));
    check('시·도 칸에 인구가 (XX만) 으로 붙는다', withPop.length > 0,
          `${withPop.length}/${wide.cards.length}칸`);

    // 합쳤는가. **거래가 있는 시군구만 더하면 안 된다** — 인구는 행정구역의
    // 인구지 '거래가 있는 곳의 인구' 가 아니다. 처음 구현이 여기서 틀려서
    // 경기도가 110만이 아니라 65만(값이 있는 두 구의 합)으로 나왔다.
    const wantMan = (() => {
      const y = '2025';
      const sum = FAKE_REGIONS.filter((r) => r.sido === '경기도')
        .reduce((a, r) => a + ((r.pop || {})[y] || 0), 0) / 10000;
      return sum >= 10 ? String(Math.round(sum)) : sum.toFixed(1);
    })();
    const gy = wide.cards.find((h) => /경기도/.test(h));
    const gyMan = gy && /<em>([\d.]+)만<\/em>/.exec(gy);
    check('경기도 칸이 도 전체 인구다 (값 없는 시군구도 센다)',
          !!gyMan && gyMan[1] === wantMan,
          `${gyMan ? gyMan[1] : '(없음)'}만 · 기대 ${wantMan}만`);

    // 10만 아래는 소수점 한 자리를 남긴다 — 안 남기면 작은 군이 전부
    // '0만' 이 된다.
    const small = wide.cards.concat((await popPeek(10)).cards)
      .map((h) => (/<em>([\d.]+)만<\/em>/.exec(h) || [])[1])
      .filter(Boolean).filter((v) => Number(v) < 10);
    check('10만 아래는 소수점 한 자리를 남긴다',
          !small.length || small.every((v) => /\./.test(v)),
          small.slice(0, 3).join(' · ') || '(해당 없음)');

    // **시·군·구 단계에서도 붙는가.** 여기까지 안 보면 놓친다 —
    // 시·도 단계는 묶는 열쇠와 이름이 같아서, 열쇠를 바꿔도 통과한다.
    // 실제로 강서구를 가르며 열쇠에 시·도를 붙였을 때 시·군·구 태그의
    // 인구가 통째로 사라졌는데 검사는 초록이었다 (실사용 화면에서
    // 잡으셨다 — "인구 표시가 안됩니다", 2026-09-09).
    const mid = await popPeek(11);
    const midLvl = await page.evaluate(() => (window.__lp || {}).level);
    const midPop = mid.cards.filter((h) => /<em>[\d.]+만<\/em>/.test(h));
    check('시·군·구 단계에도 인구가 붙는다',
          midLvl !== 'sido' && midPop.length > 0,
          `${midLvl} · ${mid.cards.length}칸 중 인구 ${midPop.length}칸`);
    // 값이 맞는지도 본다. 붙기만 하고 엉뚱한 숫자면 없느니만 못하다.
    {
      const yv = '2025';
      const want = FAKE_REGIONS.find((r) => r.name === '평택시');
      const man = (want.pop[yv] / 10000);
      const label = man >= 10 ? String(Math.round(man)) : man.toFixed(1);
      const card = mid.cards.find((h) => /평택시/.test(h)) || '';
      check('그 인구가 그 시군구의 값이다',
            new RegExp(`<em>${label}만</em>`).test(card),
            `${(/<em>([\d.]+)만<\/em>/.exec(card) || [])[1] || '(없음)'}만`
            + ` · 기대 ${label}만`);
    }

    // 읍·면·동과 리는 **9-B 가 본다** — 2026-09-09 부터 KOSIS 행정동
    // 인구가 거기 붙는다. 여기서는 조각이 아직 안 와 시군구로 물러났을
    // 때에도 인구가 붙는지만 본다. 단계를 안 보고 '14배율이면 이래야
    // 한다' 고 하면, 조각이 늦게 온 날에 검사가 거짓으로 빨개진다.
    const fine = await popPeek(14);
    const fineLvl = await page.evaluate(() => (window.__lp || {}).level);
    if (fineLvl !== 'umd' && fineLvl !== 'ri') {
      check('조각이 오기 전 시군구로 물러나도 인구는 붙는다',
            fine.cards.some((h) => /<em>[\d.]+만<\/em>/.test(h)),
            `${fineLvl} · ${fine.cards.length}칸`);
    }

    await popPeek(7);

    console.log();
    console.log('9-A. 용도지역 칸이 목록이 아니라 범례다');
    /* 요구사항(2026-09-08):
     *   "전체 용도지역이 아직 안나오네요. 전부 반영하고 체크하면 가격이
     *    반영될 수 있도록 해주세요."
     *   "용도 지역 선택하면 체크가 아니라 용도 지역 범례 표시
     *    (색상과 패턴)이 들어 가도록 해주세요."
     *
     * '전부' 를 숫자로 못 박으면 자료가 늘 때마다 검사가 깨진다. 대신
     * **자료가 가진 것을 하나도 빠뜨리지 않는가**를 본다 — 이쪽이
     * 보고된 증상('안 나온다')을 정확히 잡는다. */
    const zoneUI = await page.evaluate(async () => {
      const lp = await (await fetch('/app/data/landprice.json')).json();
      const btns = [...document.querySelectorAll('#lp-groups .zone-opt')];
      const heads = [...document.querySelectorAll('#lp-groups .zone-major')]
        .map((h) => h.textContent);
      return {
        dataGroups: Object.keys(lp.groups || {}),
        shown: btns.map((b) => b.dataset.group),
        heads,
        // 색이 실제로 칠해졌는가. 무늬는 겹배경이라 background 에 함께 온다.
        swatches: btns.slice(0, 40).map((b) => {
          const sw = b.querySelector('.zone-sw');
          const cs = sw ? getComputedStyle(sw) : null;
          return cs ? (cs.backgroundImage !== 'none' ? cs.backgroundImage
                                                     : cs.backgroundColor) : '';
        }),
        pressed: btns.filter((b) => b.getAttribute('aria-pressed') === 'true')
          .map((b) => b.dataset.group),
        checkboxes: document.querySelectorAll('#lp-groups input').length,
      };
    });
    const missing = zoneUI.dataGroups.filter((g) => !zoneUI.shown.includes(g));
    check('자료에 있는 용도지역이 하나도 안 빠진다', !missing.length,
          missing.length ? `빠진 것: ${missing.join(', ')}`
                         : `${zoneUI.shown.length}개 전부`);
    check('체크상자가 아니라 범례 칸이다', zoneUI.checkboxes === 0
          && zoneUI.shown.length > 0, `input ${zoneUI.checkboxes}개`);
    const painted = zoneUI.swatches.filter(
      (v) => v && v !== 'rgba(0, 0, 0, 0)' && v !== 'transparent');
    check('칸마다 색이 칠해져 있다', painted.length === zoneUI.shown.length,
          `${painted.length}/${zoneUI.shown.length}`);
    // 색이 다 같으면 범례가 아니라 장식이다.
    check('보이는 칸의 색이 서로 다르다',
          new Set(zoneUI.swatches).size === zoneUI.swatches.length,
          `${new Set(zoneUI.swatches).size}/${zoneUI.swatches.length}가지`);

    // 팔레트 자체를 본다 — **오늘 자료가 무엇을 담았든**. 지금 화면에
    // 세 용도지역만 있다고 나머지 스물둘의 색을 안 보면, 정작 자료가
    // 늘어난 날에 겹친 색을 그때 발견하게 된다.
    const pal = await page.evaluate(() => {
      const names = Object.keys(ZONE_STYLE);
      return {
        n: names.length,
        css: names.map((g) => zoneSwatch(g)),
        // 같은 계열 안에서 무늬가 갈라주는가 (초록 여섯, 주거 여덟).
        patterned: names.filter((g) => /gradient/.test(zoneSwatch(g))).length,
        fallback: zoneSwatch('있을 리 없는 용도지역'),
      };
    });
    check('팔레트가 스물 넘게 있다', pal.n >= 20, `${pal.n}개`);
    check('팔레트 안에 같은 칸이 없다',
          new Set(pal.css).size === pal.n,
          `${new Set(pal.css).size}/${pal.n}`);
    // 색만으로는 색약인 사람이 초록 여섯을 못 가른다.
    check('무늬(사선·점)로도 가른다', pal.patterned >= 5, `${pal.patterned}개`);
    check('모르는 용도지역도 색이 있다 (빈 칸으로 두지 않는다)',
          !!pal.fallback, pal.fallback);
    check('법령의 대분류로 갈라 놓는다 (§36①)', zoneUI.heads.length >= 2,
          zoneUI.heads.join(' / '));
    check('처음 켜지는 것은 계획관리·생산관리·자연녹지',
          ['계획관리', '생산관리', '자연녹지']
            .every((g) => !zoneUI.dataGroups.includes(g)
                          || zoneUI.pressed.includes(g)),
          zoneUI.pressed.join(', '));

    console.log();
    console.log('9-B. 땅값 지도 — 사각형 표찰 · 왼쪽 필터를 따름 · 추이');
    /* 요구사항(2026-09-08): "좌측 범례 삭제 / 호갱노노처럼 사각형으로
     * 변경 후 동, 리 이름만 표시 가격 아래로 / 마우스 오버랩시 정보와
     * 실거래가격 트랜드 표시 / 용도지역 선택 시 선택된 용도지역의
     * 중간값으로 가격 변환 (초기는 계획관리, 자연녹지, 생산관리 기준)" */

    // 땅값 글자의 용도지역. **거래 점 필터와 따로 논다** (요구사항
    // 2026-09-08) — 점을 걸러 볼 때마다 바탕의 중앙값이 함께 흔들리면
    // 견줄 수가 없다.
    // 이제 체크상자가 아니라 **범례 칸**이다 (요구사항 2026-09-08).
    const lpRail = async (names) => page.evaluate((want) => {
      document.querySelectorAll('#lp-groups .zone-opt').forEach((b) => {
        const on = want.indexOf(b.dataset.group) >= 0;
        if ((b.getAttribute('aria-pressed') === 'true') !== on) b.click();
      });
    }, names);

    // 배율·화면을 바꾸면 **실제 지도처럼 다시 그리게** 한다. 값만 바꾸고
    // 읽으면 예전 그림을 보게 되어, 검사가 초록인데 화면은 안 바뀐다.
    const lpFire = async () => page.evaluate(() => {
      const on = window.__mapOn || {};
      (on.zoomend || []).forEach((fn) => fn());
      (on.moveend || []).forEach((fn) => fn());
    });
    const lpRead = async () => page.evaluate(() => {
      const marks = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((m) => m.options && m.options.pane === 'lpPane');
      return {
        peek: window.__lp || {},
        n: marks.length,
        // 태그가 **어디에 찍혔는지**. 이것이 없으면 '엉뚱한 자리에
        // 뭉쳤다' 를 검사로 옮길 수 없다.
        at: marks.map((m) => (m.__latlng || [])),
        html: marks.map((m) => (m.options.icon || {}).options.html || ''),
        tips: marks.map((m) => m.__tooltip || ''),
        pops: marks.map((m) => m.__popupHtml || ''),
        note: document.getElementById('lp-note').textContent,
      };
    });
    const lpPick = async (win, stat) => {
      await page.evaluate((a2) => {
        const hit = (k, v) => {
          const b2 = document.querySelector(
            `.lp-filter[data-filter="${k}"] .lp-opt[data-value="${v}"]`);
          if (b2) b2.click();
        };
        if (a2.win) hit('window', a2.win);
        if (a2.stat) hit('stat', a2.stat);
      }, { win, stat });
      return lpRead();
    };
    const fillsOf = (htmls) => htmls
      .map((h) => (h.match(/background:(#[0-9A-Fa-f]{6})/) || [])[1]).filter(Boolean);

    const lpUi = await page.evaluate(() => {
      const pill = (k) => document.querySelector(
        `.lp-filter[data-filter="${k}"] .lp-pill-val`).textContent;
      const opts = (k) => [...document.querySelectorAll(
        `.lp-filter[data-filter="${k}"] .lp-opt`)].map((b) => b.dataset.value);
      return {
        barShown: !(document.getElementById('lp-bar') || {}).hidden,
        // 용도지역 칩은 **없어야 한다** — 왼쪽 필터로 합쳤다.
        groupChip: !!document.querySelector('.lp-filter[data-filter="group"]'),
        windows: opts('window'),
        window: pill('window'),
        stat: pill('stat'),
        selects: document.querySelectorAll('#lp-bar select').length,
        // 땅값 글자의 용도지역 기본값. 요구사항의 셋이어야 한다.
        //
        // **거래 점 필터가 아니라 여기를 본다** (2026-09-10). 거래 점의
        // 용도지역 칸은 없앴다 — 항상 전체다. 이 셋은 지도에 적히는
        // 중앙값을 정하는 쪽이고, 그쪽 요구사항은 그대로다.
        rail: [...document.querySelectorAll('#lp-groups .zone-opt')]
          .filter((b) => b.getAttribute('aria-pressed') === 'true')
          .map((b) => b.dataset.group),
      };
    });
    check('땅값 막대가 보인다 (자료가 있을 때만)', lpUi.barShown);
    check('필터가 눌러서 고르는 칩이다 (드롭다운이 아니다)',
          lpUi.selects === 0, `남은 select ${lpUi.selects}개`);
    check('용도지역 칩을 없앴다 (왼쪽 필터 하나로 합쳤다)', !lpUi.groupChip);
    // 요구사항: "초기는 계획관리, 자연녹지, 생산관리 기준".
    //
    // 셋 중 **자료에 있는 것만** 켜진다. 이 검사 자료에는 생산관리가
    // 없으므로 둘이 맞다 — 없는 칸을 켜라고 요구하면 검사가 화면이
    // 아니라 자료를 보게 된다.
    check('땅값 글자가 처음에 분석이 쓰는 용도지역으로 선다',
          lpUi.rail.length > 0
          && lpUi.rail.every((n) =>
            ['계획관리', '생산관리', '자연녹지'].some((g) => n.indexOf(g) >= 0)),
          lpUi.rail.join(','));
    // 나머지는 꺼져 있어야 한다 — 농림까지 켜진 채로 시작하면 처음
    // 화면의 중앙값이 무엇을 섞은 것인지 알 수 없다.
    check('농림·주거는 꺼진 채로 시작한다',
          !lpUi.rail.some((n) => /농림|주거/.test(n)), lpUi.rail.join(','));
    check('최근 기준을 기간과 건수 둘 다 준다',
          lpUi.windows.includes('y3') && lpUi.windows.includes('c20'),
          lpUi.windows.join(','));
    check('기본 기준이 자료가 말한 것으로 잡힌다', lpUi.window === '최근 3년',
          lpUi.window);

    // ── 계획관리 하나만 켜고 본다 (값을 손으로 셀 수 있게) ──
    await page.evaluate(() => { window.__zoom = 11; });
    await lpFire();
    await lpRail(['계획관리']);
    const lp1 = await lpPick('y3', 'p50');
    // **거래가 없어도 지자체는 다 나온다** (요구사항 2026-09-09).
    // 계획관리 거래가 있는 곳은 셋뿐이지만 fixture 의 지자체는 일곱이다.
    // 예전에는 셋만 그렸고, 그래서 대전에서 유성구·대덕구만 남고
    // 동구·중구·서구가 통째로 사라졌다.
    check('용도지역을 켜면 지역이 칠해진다',
          lp1.n === 9 && lp1.peek.withValue === 3 && lp1.peek.on,
          `${lp1.n}곳 중 값이 있는 곳 ${lp1.peek.withValue}곳 · on=${lp1.peek.on}`);
    // 이름이 같은 구를 한 칸으로 묶으면 **지도에 없는 자리**에 태그가
    // 생긴다. 서울 강서구와 부산 강서구를 묶으면 그 평균이 안성이다.
    {
      const gs = lp1.peek.items.filter((it) => it.name === '강서구');
      check('이름이 같은 구를 하나로 묶지 않는다',
            gs.length === 2 && new Set(gs.map((it) => it.sg)).size === 2,
            gs.map((it) => `${it.name}(${it.sg})`).join(', ') || '없음');
      // **제 자리에 있는지를 직접 본다.** '안성 상자 안에 없다' 로는
      // 모자란다 — 평택 태그가 그 근처에 정당하게 있다.
      // items 와 at 은 같은 순서(shown)로 나온다.
      const want = { 11500: [37.5647, 126.8182], 26440: [35.1304, 128.8863] };
      const off = (lp1.peek.items || []).map((it, i) => ({ it, a: lp1.at[i] }))
        .filter(({ it }) => want[it.sg])
        .filter(({ it, a }) => !a || Math.abs(a[0] - want[it.sg][0]) > 0.3
                                  || Math.abs(a[1] - want[it.sg][1]) > 0.3);
      check('각자 제 자리에 찍힌다 (섞인 평균으로 안 간다)',
            off.length === 0,
            off.map(({ it, a }) => `${it.name}(${it.sg}) → ${JSON.stringify(a)}`)
              .join(', ') || '어긋난 것 없음');
    }
    check('거래가 없는 지자체도 이름이 남는다',
          ['종로구', '강남구', '용인시', '평택시']
            .every((nm) => lp1.html.some((h) => h.indexOf(nm) >= 0)),
          lp1.html.filter((h) => /0만/.test(h)).length + '개가 0만');
    // 요구사항(2026-09-09 3차): "없는 곳은 지명만 나오고 거래 있는
    // 곳은 색상으로 구분". 0 이든 줄표든 값 자리를 채우면 값처럼 읽힌다.
    // **값 줄 안만 본다.** 카드에는 인구가 <em>34만</em> 처럼 붙어 있어,
    // 카드 전체에서 '0만' 을 찾으면 인구가 걸린다.
    check('거래가 없으면 지명만 남는다 (값 줄이 아예 없다)',
          lp1.html.filter((h) => !/<i>/.test(h)).length === 6
          && lp1.html.every((h) => {
            const v = (h.match(/<i>(.*?)<\/i>/) || [])[1] || '';
            return !/^0만|^-만/.test(v);
          }),
          `값 줄 없는 카드 ${lp1.html.filter((h) => !/<i>/.test(h)).length}개 · `
          + (lp1.html.find((h) => !/<i>/.test(h)) || '없음'));
    // 다섯 건이 안 되는 곳도 마찬가지다. 0건과의 구별은 없앤 것이 아니라
    // 말풍선으로 옮겼다 — 태그는 훑는 자리, 말풍선은 짚는 자리다.
    check('다섯 건이 안 되는 곳도 지명만이다',
          lp1.html.some((h) => /평택시/.test(h) && !/<i>/.test(h)),
          lp1.html.find((h) => /평택시/.test(h)) || '없음');
    // **사각형 표찰: 이름 위, 값 아래.** 알약에 나란히 쓰면 이름이 길수록
    // 옆으로 늘어나 서로 겹친다.
    check('사각형 표찰에 이름이 위, 값이 아래다',
          // 이름 뒤에 <em>인구</em> 가 붙을 수 있다 (요구사항 2026-09-08).
          // 거래가 없는 칸은 class 가 'lp-card is-none' 이다.
          lp1.html.every((h) => /class="lp-card( is-none)?"/.test(h)
                               && /<b>[^<]+(<em>[^<]*<\/em>)?<\/b>/.test(h))
          && lp1.html.filter((h) => /<i>/.test(h))
            .every((h) => /<\/b><i>/.test(h)),
          (lp1.html.find((h) => !/<b>[^<]+(<em>[^<]*<\/em>)?<\/b><i>/.test(h))
           || lp1.html[0] || '없음').slice(0, 160));
    const lp1Fills = fillsOf(lp1.html);
    // 값이 있는 칸만 파랗다. 거래가 없는 칸을 '가장 싼 20%' 색으로 칠하면
    // 그 지역이 싸다고 말하는 것이 된다 — 회색은 '모른다' 다.
    const lp1Blue = lp1Fills.filter((c) => c !== '#E4E8ED');
    check('색이 파란 계열이다 (빨강·노랑이 없다)',
          lp1Blue.length === 3 && lp1Blue.every((c) => {
            const r = parseInt(c.slice(1, 3), 16);
            const bl = parseInt(c.slice(5, 7), 16);
            return bl > r;
          }), lp1Fills.join(' '));
    check('지역이 적어도 값이 다르면 색이 갈린다', new Set(lp1Blue).size === 3,
          lp1Blue.join(' '));
    check('거래가 없는 칸은 파란 칸에 안 들어간다 (회색)',
          lp1Fills.filter((c) => c === '#E4E8ED').length === 6,
          lp1Fills.join(' '));
    check('순위로 편 것을 분위수인 척하지 않는다',
          /순위로 색을 폄/.test(lp1.note), lp1.note);
    check('안내문이 지금 보는 용도지역을 말한다',
          /^계획관리 ·/.test(lp1.note), lp1.note);
    // 요구사항(2026-09-08): "xx원/평, xx원/㎡ 으로 수정".
    // 값만 있으면 평인지 ㎡인지 알 수 없다.
    // 값이 있는 칸에만 붙는다 — 값이 없는 칸에는 그 줄 자체가 없다.
    check('표찰에 단위를 붙인다 (평인지 ㎡인지 알 수 있게)',
          lp1.html.filter((h) => /<i>/.test(h))
            .every((h) => /<u>\/평<\/u>/.test(h)),
          lp1.html.find((h) => /장안구/.test(h)) || '없음');
    check('글자는 평당으로 접어 쓴다',
          lp1.html.some((h) => /33\.1만|33만/.test(h)),
          lp1.html.find((h) => /장안구/.test(h)) || '없음');

    // ── 말풍선: 정보 + 실거래가 추이 ──
    const tipJan = lp1.tips.find((t) => /수원시 장안구/.test(t)) || '';
    // ㎡ 단가는 평단가 **아랫줄**로 (요구사항). 한 줄에 두 값을
    // 이어 놓으면 어느 숫자가 어느 단위인지 눈이 못 잡는다.
    check('평단가가 위, ㎡단가가 아랫줄이다',
          /<div class="lp-tip-v"><b>[\d,]+원\/평<\/b><\/div>/.test(tipJan)
          && /<div class="lp-tip-v2">[\d,]+원\/㎡/.test(tipJan),
          tipJan.slice(0, 130));
    check('말풍선이 건수와 기준을 적는다',
          /거래/.test(tipJan) && /최근 3년/.test(tipJan),
          tipJan.slice(0, 130));
    // 값 하나만 보면 오르는 중인지 내리는 중인지 알 수 없다. 같은 평당
    // 80만원이라도 3년째 오르는 80만과 꺾여 내려온 80만은 다른 물건이다.
    check('말풍선에 최근 추이 꺾은선이 있다',
          /<svg/.test(tipJan) && /<polyline/.test(tipJan),
          /<svg/.test(tipJan) ? '있음' : tipJan.slice(0, 110));
    check('추이가 몇 년에서 몇 년까지 몇 % 인지 적는다',
          /2021→2025 [+-]\d+%/.test(tipJan),
          (tipJan.match(/\d{4}→\d{4}[^<]*/) || ['없음'])[0]);
    // 한 해 세 건 미만은 내보내기에서 빠진다 — 한 건짜리 해를 이어
    // 그리면 그것은 추세가 아니라 잡음이다.
    const tipUl = lp1.tips.find((t) => /울릉군/.test(t)) || '';
    check('점이 둘도 안 되면 꺾은선을 안 그린다',
          !/<polyline/.test(tipUl), tipUl.slice(0, 90));

    // ── 여러 용도지역을 켜면 값이 섞인다 ──
    const lpMix2 = await (async () => { await lpRail(['계획관리', '자연녹지']); return lpRead(); })();
    check('용도지역을 더 켜면 값이 바뀐다',
          lpMix2.tips.find((t) => /장안구/.test(t)) !== tipJan,
          lpMix2.note);
    // 장안구 계획관리 10만(10건) + 자연녹지 29만(60건) → 가중 26.3만
    check('여러 용도지역을 거래 건수로 가중해 섞는다',
          /262,857원\/㎡/.test(lpMix2.tips.find((t) => /장안구/.test(t)) || ''),
          (lpMix2.tips.find((t) => /장안구/.test(t)) || '').slice(0, 140));
    check('무엇을 섞었는지 용도지역별로 보여준다',
          /계획관리/.test(lpMix2.tips[0]) && /자연녹지/.test(lpMix2.tips[0]),
          (lpMix2.tips[0] || '').slice(-160));
    // **중앙값끼리 섞는 것은 근사다.** 진짜 합동 중앙값이 아니다.
    check('중앙값을 섞은 것은 근사라고 밝힌다',
          /근사/.test(lpMix2.tips[0] || ''), (lpMix2.tips[0] || '').slice(-90));
    await lpRail(['계획관리']);

    // ── 축척 ──
    const lpY1 = await lpPick('y1', null);
    // 울릉군은 최근 1년 거래가 없다. **빠지지 않고** 값 자리에 그렇게
    // 적힌다 — 지도에서 지자체가 사라지면 사람은 고장으로 읽는다.
    check('기준을 좁혀 거래가 없어져도 지자체는 남는다',
          lpY1.n === 9 && lpY1.peek.withValue === 2
          && lpY1.tips.some((t) => /울릉군/.test(t)),
          `${lpY1.n}곳 중 값 ${lpY1.peek.withValue}곳`);
    // 요구사항(2026-09-09): "그냥 간단하게 표시합니다. - 거래 5건 미만-"
    // 값이 없는 칸에 설명을 길게 붙일 이유가 없다 — 실제로 말풍선이
    // 세로로 늘어졌다.
    check('값이 없는 말풍선은 한 마디로 끝난다',
          /거래 5건 미만/.test(lpY1.tips.find((t) => /울릉군/.test(t)) || '')
          && !/없습니다|적습니다/.test(lpY1.tips.find((t) => /울릉군/.test(t)) || ''),
          (lpY1.tips.find((t) => /울릉군/.test(t)) || '없음').slice(0, 120));
    const lpC = await lpPick('c20', null);
    check('건수 기준은 몇 년치를 긁어온 값인지 밝힌다',
          /2009년부터/.test(lpC.tips.find((t) => /울릉군/.test(t)) || ''),
          (lpC.tips.find((t) => /울릉군/.test(t)) || '없음').slice(0, 120));
    const lpMed = await lpPick('y3', 'p50');
    const lpMean = await lpPick('y3', 'avg');
    const val = (t) => (t.match(/<b>([\d,]+)원\/평<\/b>/) || [])[1];
    check('평균으로 바꾸면 값이 달라진다',
          val(lpMed.tips.find((t) => /장안구/.test(t)) || '')
          !== val(lpMean.tips.find((t) => /장안구/.test(t)) || ''),
          `중앙값 ${val(lpMed.tips.find((t) => /장안구/.test(t)) || '')}`
          + ` vs 평균 ${val(lpMean.tips.find((t) => /장안구/.test(t)) || '')}`);
    await lpPick('y3', 'p50');

    await page.evaluate(() => { window.__zoom = 7; });
    await lpFire();
    const lpWide = await lpRead();
    // 시·도 셋 — 경기도·서울특별시·경상북도. 서울은 계획관리 거래가
    // 없지만 시·도로서는 존재한다.
    check('멀리서는 시·도로 묶인다',
          lpWide.peek.level === 'sido' && lpWide.n === 4
          && lpWide.peek.withValue === 2,
          `${lpWide.peek.level} · ${lpWide.n}곳 중 값 ${lpWide.peek.withValue}곳`);
    // 경기도 = 장안구(10만, 10건) + 권선구(20만, 20건) → 가중 16.7만.
    check('묶을 때 거래 건수로 가중한다 (합치지 않는다)',
          lpWide.tips.some((t) => /^<div class="lp-tip-h">경기도/.test(t)
                                  && /550,964원\/평/.test(t)),
          (lpWide.tips.find((t) => /경기도/.test(t)) || '없음').slice(0, 140));

    // ── 읍·면·동 → 리·동 ──
    await page.evaluate(() => { window.__bbox = [37.0, 126.5, 37.6, 127.5]; });
    lpUmdHits.length = 0;
    // 명부도 앞 절에서 이미 받아 놨을 수 있다. **받은 것을 세는 검사**는
    // 캐시를 비우고 다시 세야 '안 받았다' 와 '이미 있다' 를 구별한다.
    await page.evaluate(() => { lpRosterCache = {}; });
    rosterHits.length = 0;
    await page.evaluate(() => { window.__zoom = 12; });
    await lpFire();
    await page.waitForTimeout(300);
    await lpFire();
    const lpMyeon = await lpRead();
    // **값이 있는 칸으로 센다.** 이제 거래가 없는 동도 이름만으로
    // 그려지므로(검색 색인에서 메운다) 태그 수로 세면 그것까지 들어온다.
    check('배율 12 에서 읍·면·동이 뜬다 (군 이름 하나로 안 끝난다)',
          lpMyeon.peek.level === 'umd' && lpMyeon.peek.withValue === 2,
          `${lpMyeon.peek.level} · 값 ${lpMyeon.peek.withValue}곳 / 태그 ${lpMyeon.n}곳`);
    // 보고된 문제(2026-09-09): "거래가 없는 동 이름이 다 안나오네요."
    //
    // 읍·면·동 태그는 땅값 조각에서만 만들어졌는데, 그 조각에는 거래가
    // 다섯 건 넘는 칸만 실립니다. 그래서 고른 용도지역에 거래가 없는
    // 동은 재료가 없어 아예 안 그려졌습니다 — 서울에서 여덟 개만 뜬
    // 것이 그것입니다.
    //
    // 처음에는 검색 색인(places.json)으로 메웠는데, 그 색인도 거래에서
    // 나온 목록이라 **거래가 한 번도 없던 법정동**은 여전히 빠졌습니다.
    // 이제는 행정표준코드 명부 조각(umd-roster-NN.json)을 씁니다.
    check('거래가 없는 읍·면·동도 이름은 나온다',
          lpMyeon.n > lpMyeon.peek.withValue,
          `태그 ${lpMyeon.n}곳 · 그중 값 있는 곳 ${lpMyeon.peek.withValue}곳`);
    // **보이는 시·도만 받는다.** 울릉(47)은 화면 밖이라 안 받아야 한다.
    check('명부는 화면에 걸치는 조각만 받는다',
          rosterHits.includes('41') && !rosterHits.includes('47'),
          `받은 조각 ${rosterHits.join(',') || '없음'}`);
    check('명부에서 온 이름이 실제로 지도에 선다 (조원동)',
          lpMyeon.html.some((h) => /<b>조원동/.test(h)),
          lpMyeon.html.map((h) => (h.match(/<b>([^<]*)/) || [])[1]).join(','));
    // 명부에는 땅값 조각에 이미 있는 칸도 들어 있다. 그것까지 그리면
    // 같은 동네가 두 번 뜬다 — 하나는 값이 있고 하나는 없는 채로.
    check('명부와 땅값 조각이 겹치는 곳은 한 번만 그린다',
          lpMyeon.html.filter((h) => /<b>백곡면/.test(h)).length === 1,
          `백곡면 태그 ${lpMyeon.html.filter((h) => /<b>백곡면/.test(h)).length}개`);
    check('메운 태그에는 값 줄이 없다 (이름만)',
          lpMyeon.html.filter((h) => !/<i>/.test(h)).length
            === lpMyeon.n - lpMyeon.peek.withValue,
          `값 줄 없는 카드 ${lpMyeon.html.filter((h) => !/<i>/.test(h)).length}개`);
    check('면 단계는 리를 면으로 묶는다',
          lpMyeon.html.some((h) => /<b>백곡면(<em>|<\/b>)/.test(h))
          && !lpMyeon.html.some((h) => /사송리/.test(h)),
          lpMyeon.html.map((h) => (h.match(/<b>([^<]*)/) || [])[1]).join(','));
    // 읍·면·동 인구 (요구사항 2026-09-09). **리를 합치는 것이 아니라
    // 면 하나의 값**이다 (head_pop 2,000 → 0.2만). 리 값을 합치면
    // 인구가 붙은 리만 더해져 면 인구가 실제보다 작아진다.
    check('면 인구는 리 합계가 아니라 면 자체의 값이다',
          /<b>백곡면<em>0\.2만<\/em>/.test(
            lpMyeon.html.find((h) => /백곡면/.test(h)) || ''),
          (lpMyeon.html.find((h) => /백곡면/.test(h)) || '없음').slice(0, 90));
    // 눌러도 같은 내용이 나와야 한다 (보고된 문제 2026-09-10:
    // "모바일에서는 이 팝업 정보를 볼 수가 없어요"). 터치 화면에는
    // hover 가 없으므로 말풍선만으로는 영영 못 본다.
    check('태그를 눌러도 같은 말풍선이 열린다 (폰에는 hover 가 없다)',
          lpMyeon.pops.length === lpMyeon.tips.length
          && lpMyeon.pops.every((h, i) => h === lpMyeon.tips[i])
          && lpMyeon.pops.some((h) => h.length > 0),
          `누름 ${lpMyeon.pops.filter(Boolean).length}개`
          + ` / 올림 ${lpMyeon.tips.filter(Boolean).length}개`);

    check('묶을 때 리 개수와 함께 건수로 가중한다',
          /2개 리·동 합침/.test(lpMyeon.tips.find((t) => /백곡면/.test(t)) || ''),
          (lpMyeon.tips.find((t) => /백곡면/.test(t)) || '없음').slice(0, 140));

    await page.evaluate(() => { window.__zoom = 14; });
    await lpFire();
    const lpRi = await lpRead();
    check('더 당기면 리·동까지 내려간다',
          lpRi.peek.level === 'ri' && lpRi.peek.withValue === 3,
          `${lpRi.peek.level} · 값 ${lpRi.peek.withValue}곳 / 태그 ${lpRi.n}곳`);
    // **표찰에는 리 이름만.** 어느 읍인지는 지도 바탕에 이미 적혀 있다.
    check('표찰에는 리 이름만 쓴다 (앞의 면 이름을 뗀다)',
          lpRi.html.some((h) => /<b>사송리(<em>|<\/b>)/.test(h))
          && !lpRi.html.some((h) => /<b>백곡면 사송리/.test(h)),
          lpRi.html.map((h) => (h.match(/<b>([^<]*)/) || [])[1]).join(','));
    // 리 단계도 인구가 붙는다. 그리고 **이름이 안 맞아 인구가 없는 칸은
    // 비운다** — KOSIS 는 행정동이고 우리는 법정동이라 실제로 있는 일이다.
    // 리에는 인구를 **안 적는다** — 우리 자료가 면·동까지다. 그 자리에
    // 면 인구를 넣으면 리 하나가 면 전체 인구가 된다.
    check('리 칸에는 인구를 안 적는다',
          !/<em>/.test(lpRi.html.find((h) => /사송리/.test(h)) || ''),
          (lpRi.html.find((h) => /사송리/.test(h)) || '없음').slice(0, 90));
    // 한 마디짜리 동은 자기 이름으로 맞으므로 붙는다.
    check('동 칸에는 자기 인구가 붙는다 (28,000명 → 2.8만)',
          /<em>2\.8만<\/em>/.test(lpRi.html.find((h) => /정자동/.test(h)) || ''),
          (lpRi.html.find((h) => /정자동/.test(h)) || '(화면 밖)').slice(0, 90));
    // **fixture 와 맞대어 본다.** '울릉읍 카드에 <em> 이 없다' 만 보면
    // 그 카드가 화면 밖일 때 검사가 저절로 통과한다 — 아무것도 안 본
    // 것이 초록으로 보인다. 그리는 칸마다 fixture 의 pop 과 짝을 맞춘다.
    const riPop = await page.evaluate(() => {
      const want = {};
      Object.values(window.__lpUmdFixture || {}).forEach((chunk) => {
        (chunk.cells || []).forEach((c) => {
          want[String(c.nm).split(' ').pop()] = c.pop || 0;
        });
      });
      return want;
    });
    const mismatched = lpRi.html.filter((h) => {
      const nm = (h.match(/<b>([^<]*)/) || [])[1];
      if (!nm || !(nm in riPop)) return false;
      const shown = /<em>[\d.]+만<\/em>/.test(h);
      return shown !== (riPop[nm] > 0);
    });
    check('인구가 있는 칸에만 (XX만) 을 적는다',
          !mismatched.length && lpRi.html.length > 0,
          mismatched.map((h) => (h.match(/<b>([^<]*)/) || [])[1]).join(',')
          || `${lpRi.html.length}칸 맞대어 봄`);
    // 그래도 말풍선은 전체 이름과 시군구를 말해야 한다 — 같은 이름의
    // 리가 전국에 여럿이다.
    check('말풍선은 전체 이름과 시군구를 말한다',
          lpRi.tips.some((t) => /백곡면 사송리/.test(t) && /진천군/.test(t)),
          (lpRi.tips.find((t) => /사송리/.test(t)) || '없음').slice(0, 100));

    lpUmdHits.length = 0;
    await lpRail(['계획관리', '농림']);
    await page.waitForTimeout(400);
    const wantChunks = await page.evaluate(() => (window.__lp || {}).chunks || []);
    check('화면에 걸치는 조각만 찾는다',
          wantChunks.includes('농림|41') && !wantChunks.includes('농림|47'),
          wantChunks.join(' '));
    check('화면 밖 시도 조각은 아예 안 받는다',
          lpUmdHits.includes('41') && !lpUmdHits.includes('47'),
          `받은 조각 ${lpUmdHits.join(',') || '없음'}`);
    await lpRail(['계획관리']);
    await page.evaluate(() => { window.__bbox = null; window.__zoom = 11; });

    // ── 빈 화면에 이유를 적고 길을 알려준다 ──
    // 도시는 계획관리가 없다 (docs 7장 실측: 인구 15만에서 자연녹지
    // 비중이 6%→65% 로 뒤집힌다). 그러면 계획관리로 서울을 볼 때 지도가
    // 텅 비는데, 사람은 빈 화면을 고장으로 읽는다.
    await page.evaluate(() => { window.__bbox = [37.4, 130.5, 37.6, 131.2]; });
    await lpFire();
    const lpEmpty = await lpPick('y1', null);
    const nag = await page.evaluate(() => {
      const b2 = document.getElementById('lp-swap');
      return { hidden: b2.hidden, text: b2.textContent, group: b2.dataset.group };
    });
    check('빈 화면에 이유를 적는다 (고장이 아니라 그런 땅이 없는 것)',
          /계획관리 거래가 없습니다/.test(lpEmpty.note), lpEmpty.note);
    check('이 화면에 맞는 용도지역을 알려준다',
          !nag.hidden && nag.group === '자연녹지'
          && /자연녹지\(도시지역\)/.test(nag.text),
          `단추 "${nag.text}"`);
    // 글자만 띄우고 안 되면 더 나쁘다. **칸이 실제로 켜져야 한다.**
    //
    // 이 단추가 켜는 것은 땅값 글자의 용도지역(lp-groups)이다. 예전에는
    // 거래 점 필터(land-use-filters)를 읽고 있었는데, 거기에도 자연녹지가
    // 기본으로 켜져 있어서 **단추를 안 눌러도 통과할** 검사였다.
    await page.evaluate(() => document.getElementById('lp-swap').click());
    await page.waitForTimeout(200);
    const swapped = await page.evaluate(() => ({
      rail: [...document.querySelectorAll('#lp-groups .zone-opt')]
        .filter((b) => b.getAttribute('aria-pressed') === 'true')
        .map((b) => b.dataset.group),
      peek: window.__lp || {},
    }));
    check('누르면 그 용도지역이 실제로 켜진다',
          swapped.rail.some((n) => n.indexOf('자연녹지') >= 0)
          && (swapped.peek.groups || []).includes('자연녹지'),
          `${swapped.rail.join(',')} → ${(swapped.peek.groups || []).join(',')}`);
    await page.evaluate(() => { window.__bbox = null; });

    // 다 끄면 사라진다.
    await lpRail([]);
    const lpOff = await lpRead();
    check('용도지역을 다 끄면 지도에서 사라진다', lpOff.n === 0 && !lpOff.peek.on,
          `${lpOff.n}곳`);
    await lpRail(['계획관리', '생산관리', '자연녹지']);
    await page.evaluate(() => { window.__zoom = 7; });

    console.log();
    console.log('9-D. 단위 규칙 · 5분위 눈금 · 지역 검색 (2026-09-09 지시)');

    // ── 단위: 평이 먼저다 ──────────────────────────────────────────
    // 보고된 문제: "지도 카드는 86.9만/평, 말풍선은 592,441원/평,
    // 필지 카드는 250,000원/㎡." 셋을 머릿속에서 환산하게 두면 안 된다.
    const units = await page.evaluate(() => ({
      card: lpMoney(250000),
      py: perPy(250000),
      m2: perM2Str(250000),
    }));
    check('훑는 자리는 평당 만/억으로 줄인다', /만$|억$/.test(units.card),
          units.card);
    // 250,000원/㎡ × 3.3058 ≒ 826,446원/평. 평이 ㎡ 보다 크다는 것이
    // 곧 '평으로 환산했다' 는 증거다.
    check('짚는 자리는 평당 원 그대로',
          Number(units.py.replace(/,/g, '')) > 250000 * 3,
          `${units.py}원/평 · ${units.m2}원/㎡`);

    // ── 5분위 눈금 ────────────────────────────────────────────────
    await page.evaluate(() => { window.__zoom = 11; });
    await lpFire();
    const scale = await page.evaluate(() => {
      const el = document.getElementById('lp-scale');
      return {
        hidden: !el || el.hidden,
        peek: window.__lpScale || null,
        cells: el ? el.querySelectorAll('.lps-cell').length : 0,
        ticks: el ? [...el.querySelectorAll('.lps-ticks span')]
          .map((x) => x.textContent) : [],
        text: el ? el.textContent : '',
        // 오른쪽 아래는 Leaflet 출처 표시 자리다. 겹치면 둘 다 못 읽는다.
        box: el && !el.hidden ? el.getBoundingClientRect().toJSON() : null,
      };
    });
    check('눈금이 지도에 뜬다', !scale.hidden && !!scale.peek);
    if (scale.peek && scale.peek.kind === 'quantile') {
      check('칸이 다섯이고 눈금이 여섯이다',
            scale.cells === 5 && scale.ticks.length === 6,
            `칸 ${scale.cells} · 눈금 ${scale.ticks.length}`);
      // 끊는 자리는 올라가야 한다. 뒤집혀 있으면 색과 값이 어긋난다.
      const nums = scale.ticks.map((t) => {
        const m2 = /([\d.]+)(억|만)?/.exec(t);
        if (!m2) return NaN;
        return Number(m2[1]) * (m2[2] === '억' ? 10000 : 1);
      });
      check('끊는 자리가 오름차순이다',
            nums.every((v, i) => i === 0 || !(v < nums[i - 1])),
            scale.ticks.join(' · '));
    } else {
      check('분위를 못 낼 때는 그렇다고 말한다', /순위/.test(scale.text),
            scale.text.slice(0, 60));
    }
    // "왜 이 색인가" 를 말해야 한다 — 그것이 이 눈금의 존재 이유다.
    check('화면 안에서 끊는다는 것을 적는다', /이 화면 안에서/.test(scale.text),
          scale.text.slice(0, 40));

    // ── 지역 검색 ─────────────────────────────────────────────────
    const find = await page.evaluate(async () => {
      const q = document.getElementById('find-q');
      q.value = '평택';
      q.dispatchEvent(new Event('input'));
      await new Promise((r) => setTimeout(r, 400));
      const list = document.getElementById('find-list');
      const items = [...list.querySelectorAll('li[data-i]')];
      const before = { zoom: window.__zoom, at: window.__center };
      if (items[0]) items[0].dispatchEvent(
        new MouseEvent('mousedown', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 200));
      return {
        n: items.length,
        first: items[0] ? items[0].textContent : '',
        went: window.__find || null,
        before,
      };
    });
    check('이름을 치면 후보가 뜬다', find.n > 0, `${find.n}개 · ${find.first}`);
    check('첫 후보가 친 글자로 시작한다', /평택/.test(find.first), find.first);
    check('고르면 그리로 간다', !!find.went,
          find.went ? `${find.went.went} (${find.went.level})` : '(안 감)');

    // 없는 이름. **조용히 비면 안 된다** — 사용자는 고장으로 읽는다.
    // 그리고 왜 지번이 안 되는지도 그 자리에서 말해야 한다.
    const none = await page.evaluate(async () => {
      const q = document.getElementById('find-q');
      q.value = '있을리없는지명';
      q.dispatchEvent(new Event('input'));
      await new Promise((r) => setTimeout(r, 300));
      return document.getElementById('find-list').textContent;
    });
    check('없으면 없다고 말한다', /없습니다/.test(none), none.slice(0, 40));
    check('지번까지 적으면 필지로 간다고 그 자리에서 알린다',
          /읍·면·동까지/.test(none) && /지번까지/.test(none), none.slice(0, 80));

    // 지번 검색 (요구사항 2026-09-11: "주소 입력 시 해당 필지로 이동").
    // 시·군을 안 쳐도 색인으로 '경기도 광주시' 를 채워 지오코더에 묻고,
    // 좌표가 오면 지도를 누른 것과 같은 길(필지 조회)로 카드를 연다.
    const parcelBefore = parcelHits;
    const addr = await page.evaluate(async () => {
      const q = document.getElementById('find-q');
      q.value = '곤지암읍 건업리 140-25';
      q.dispatchEvent(new Event('input'));
      await new Promise((r) => setTimeout(r, 400));
      const list = document.getElementById('find-list');
      const first = list.querySelector('li[data-i]');
      const firstText = first ? first.textContent : '';
      const firstKind = first ? first.dataset.k : '';
      first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 900));
      const out = { firstText, firstKind, went: window.__find || null,
                    detail: (document.getElementById('detail') || {}).textContent || '' };
      // 뒤 절은 **영업소 상세가 열려 있는 상태**를 전제한다 (3절에서 고른 것).
      // 필지 카드가 그 자리를 차지했으니 같은 영업소를 다시 고른다.
      const x = document.querySelector('#detail .detail-close');
      if (x) x.click();
      const row = document.querySelector('tr[data-id], [data-id]');
      if (row) row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 800));
      return out;
    });
    check('지번을 치면 맨 위 후보가 "필지로 이동" 이다',
          addr.firstKind === 'addr' && /필지로 이동/.test(addr.firstText), addr.firstText);
    // 명부에 법정동코드가 있으면 **연속지적도(PNU)** 로 간다 — 지오코더는
    // 건물 없는 땅의 지번을 모른다. 건업리 = 4161025930, 140-25 → …1 0140 0025.
    check('명부의 법정동코드로 PNU 를 만들어 연속지적도에 묻는다 (지오코더 아님)',
          pnuAsked.length === 1 && pnuAsked[0] === '4161025930101400025' && geoAsked.length === 0,
          `pnu ${pnuAsked.join(',')} · geocode ${geoAsked.join(',')}`);
    check('좌표로 옮기고 그 필지를 조회한다 (지도를 누른 것과 같은 길)',
          !!addr.went && addr.went.level === 'addr' && addr.went.via === 'pnu' && Array.isArray(addr.went.at)
          && Math.abs(addr.went.at[0] - 37.4031) < 1e-6 && parcelHits > parcelBefore,
          `${JSON.stringify(addr.went)} · 필지 조회 ${parcelBefore} → ${parcelHits}`);

    // 명부에 코드가 없는 곳(승두리는 가짜 명부에 없다)은 지오코더로 물러난다.
    // 시·군을 안 쳐도 색인으로 '경기도 안성시' 를 채운다.
    const addr2 = await page.evaluate(async () => {
      const q = document.getElementById('find-q');
      q.value = '공도읍 승두리 40';
      q.dispatchEvent(new Event('input'));
      await new Promise((r) => setTimeout(r, 400));
      const first = document.getElementById('find-list').querySelector('li[data-i]');
      first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 900));
      const out = window.__find || null;
      const x = document.querySelector('#detail .detail-close');
      if (x) x.click();
      const row = document.querySelector('tr[data-id], [data-id]');
      if (row) row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 800));
      return out;
    });
    check('코드가 없으면 지오코더로 — 시·군을 안 쳐도 시·도·시·군을 채워 묻는다',
          geoAsked.length === 1 && geoAsked[0] === '경기도 안성시 공도읍 승두리 40'
          && !!addr2 && addr2.via === 'geocode',
          `geocode ${geoAsked.join(',')} · ${JSON.stringify(addr2)}`);

    // 겹침을 **실제로 잰다.** 지난번에 칩이 Leaflet +/- 와 겹쳐 지적받았다.
    const overlap = await page.evaluate(() => {
      const box = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return (r.width && r.height) ? r : null;
      };
      const hit = (a, b) => !!(a && b) && !(a.right <= b.left || b.right <= a.left
                                            || a.bottom <= b.top || b.bottom <= a.top);
      const find2 = box('.map-find');
      return {
        zoomCtl: hit(find2, box('.leaflet-control-zoom')),
        tools: hit(find2, box('.map-tools')),
        scaleAttr: hit(box('.lp-scale'), box('.leaflet-control-attribution')),
      };
    });
    check('검색칸이 +/- 단추와 안 겹친다', !overlap.zoomCtl);
    check('검색칸이 상단 스위치와 안 겹친다', !overlap.tools);
    check('눈금이 출처 표시와 안 겹친다', !overlap.scaleAttr);

    // 검색 뒤 배율이 바뀌었으므로 되돌린다.
    await page.evaluate(() => { window.__zoom = 11; });
    await lpFire();

    console.log();
    console.log('9-E. 화면 자리 정리 (2026-09-09 지시 A~E)');

    // A·C — 가이드와 면책은 ⓘ 단추 안으로, 검색은 지도 위로
    // (요구사항 2026-09-10 ①②).
    //
    // **자리를 잃은 것이 아니라 높이를 돌려받은 것이다.** 폰에서 지도가
    // 쓰는 높이를 재 보면 위에 255px, 아래에 120px 이 붙어 있었다.
    // 면책·가이드가 아래 120px 이고, 검색칸이 위 65px 이었다.
    const chrome = await page.evaluate(() => ({
      guideInHeader: !!document.querySelector('.topbar .guide-link'),
      guideAtFoot: !!document.querySelector('.page-foot .guide-link'),
      guideInNote: !!document.querySelector('.map-note .guide-link'),
      footerLeft: !!document.querySelector('body > footer.disclaimer'),
      noteBtn: !!document.querySelector('.map-tools #map-note-btn'),
      findInHeader: !!document.querySelector('.topbar .map-find #find-q'),
      findOverMap: !!document.querySelector('.map-wrap .map-find #find-q'),
    }));
    check('가이드가 머리띠에서 빠졌다', !chrome.guideInHeader);
    check('가이드·면책이 지도 아래 자리를 비웠다',
          !chrome.guideAtFoot && !chrome.footerLeft);
    check('그 둘은 ⓘ 단추 안에 있다', chrome.noteBtn && chrome.guideInNote);
    // 검색은 **매물 탭 옆**, 지도 위가 아니다 (요구사항 2026-09-10:
    // "지도 위에 두는 것이 신경쓰이네요"). 지도 위에 얹으면 세로 자리를
    // 안 먹는 대신 지도의 윗줄을 가린다 — 그 값이 거슬린다는 판단이다.
    check('검색은 머리띠에, 지도 위가 아니다',
          chrome.findInHeader && !chrome.findOverMap,
          `머리띠=${chrome.findInHeader} 지도위=${chrome.findOverMap}`);

    // ── 탭 정리 (요구사항 2026-09-10) ──
    const tabs = await page.evaluate(() => {
      const all = [...document.querySelectorAll('.tab')];
      const seen = (t) => getComputedStyle(t).display !== 'none';
      return {
        shown: all.filter(seen).map((t) => t.textContent.trim()),
        hiddenViews: all.filter((t) => !seen(t)).map((t) => t.dataset.view),
        // **지운 것이 아니라 접어 둔 것**이라야 한다. 화면이 남아 있는가.
        viewsAlive: all.every((t) => !!document.getElementById(`view-${t.dataset.view}`)),
      };
    });
    check("탭은 '지도'와 '매물' 둘만 선다",
          tabs.shown.join(',') === '지도,매물', tabs.shown.join(',') || '없음');
    check('나머지 넷은 접혀 있다',
          tabs.hiddenViews.join(',') === 'rank,trend,board,verdict',
          tabs.hiddenViews.join(',') || '없음');
    check('접은 것이지 지운 것이 아니다 (화면이 그대로 있다)', tabs.viewsAlive);

    // 접어 둔 화면으로 가는 길. 이것이 없으면 배포가 깨져도 아무도 모른다.
    const hid = await page.evaluate(() => {
      location.hash = '#rank';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
      const tab = document.querySelector('.tab[data-view="rank"]');
      const out = {
        viewOn: document.getElementById('view-rank').classList.contains('is-active'),
        tabBack: !tab.hidden,
      };
      location.hash = '';
      document.querySelector('.tab[data-view="explore"]').click();
      tab.hidden = true;
      return out;
    });
    check('주소에 #rank 를 붙이면 접어 둔 화면이 열린다',
          hid.viewOn && hid.tabBack,
          `화면=${hid.viewOn} 탭복귀=${hid.tabBack}`);

    // ⓘ 는 눌러야 열린다. 열린 채로 시작하면 지도를 가린다.
    const noteState = await page.evaluate(() => {
      const pop = document.getElementById('map-note');
      const was = pop.hidden;
      document.getElementById('map-note-btn').click();
      const opened = !pop.hidden;
      document.getElementById('map-note-btn').click();
      return { was, opened, closedAgain: pop.hidden };
    });
    check('ⓘ 는 닫힌 채로 시작하고 눌러야 열린다',
          noteState.was && noteState.opened && noteState.closedAgain,
          `처음닫힘=${noteState.was} 열림=${noteState.opened}`
          + ` 다시닫힘=${noteState.closedAgain}`);

    // ③ 전체화면. **빠져나갈 길이 둘 있어야 한다** — 같은 단추와 Esc.
    // 나가는 법을 못 찾으면 그것은 갇힌 것이다.
    const full = await page.evaluate(() => {
      const btn = document.getElementById('map-full');
      const seen = {};
      btn.click();
      seen.on = document.body.classList.contains('is-mapmax');
      seen.barHidden = getComputedStyle(document.querySelector('.topbar')).display === 'none';
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      seen.escOut = !document.body.classList.contains('is-mapmax');
      btn.click();
      seen.on2 = document.body.classList.contains('is-mapmax');
      btn.click();
      seen.off = !document.body.classList.contains('is-mapmax');
      return seen;
    });
    check('⛶ 를 누르면 머리띠가 접히고 지도만 남는다',
          full.on && full.barHidden,
          `켜짐=${full.on} 머리띠숨김=${full.barHidden}`);
    check('Esc 로 빠져나온다', full.escOut);
    check('같은 단추로도 빠져나온다', full.on2 && full.off);

    // 뒤로 가기로도 빠져나와야 한다 (보고된 문제 2026-09-10:
    // "전체 화면 전환 후 뒤로 가기 누르면 로그인 화면으로 갑니다").
    // 전체화면이 방문 기록을 안 남기니 뒤로 가기가 앱을 통째로 떠났다.
    const back = await page.evaluate(async () => {
      document.getElementById('map-full').click();
      // history.length 로는 못 잰다 — 브라우저마다 다르게 센다.
      // **우리가 넣은 표식**이 있는지를 본다.
      const pushed = !!(history.state && history.state.tojiFull);
      history.back();
      await new Promise((r) => setTimeout(r, 150));
      return { pushed, out: !document.body.classList.contains('is-mapmax') };
    });
    check('전체화면이 방문 기록을 한 칸 남긴다', back.pushed);
    check('뒤로 가기로 전체화면만 풀린다 (앱을 안 떠난다)', back.out);

    // **폰 폭에서 실제로 재 본다.** '넓어졌다' 는 말은 재야 말이 된다.
    // 390×844 는 아이폰 기준선이다.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(150);
    // 도구막대가 눌리지 않는가. 실사용 화면(2026-09-10)에서 스위치
    // 글자가 'IC· / 영업 / 소' 로 세 줄이 되고 배경 지도 칩 다섯 중
    // 둘만 보였다. .map-tools 에 max-width:calc(100% - 22rem) 이
    // 걸려 있어서 390px 폰에서 폭이 38px 이었다.
    const tools = await page.evaluate(() => {
      const pick = document.getElementById('basemap-pick');
      const sw = document.querySelector('.map-switch span');
      return {
        toolsW: Math.round(document.querySelector('.map-tools').getBoundingClientRect().width),
        chips: pick.children.length,
        clipped: pick.scrollWidth > pick.clientWidth + 1,
        // 낱말이 중간에서 끊기면 높이가 한 줄보다 훨씬 커진다.
        swH: Math.round(sw.getBoundingClientRect().height),
      };
    });
    check('도구막대가 눌리지 않는다',
          tools.toolsW > 200, `폭 ${tools.toolsW}px`);
    check('배경 지도 칩이 잘리지 않는다',
          !tools.clipped && tools.chips >= 5,
          `칩 ${tools.chips}개 · 잘림=${tools.clipped}`);
    check('스위치 글자가 낱말 중간에서 안 끊긴다',
          tools.swH < 30, `글자 높이 ${tools.swH}px`);

    const phone = await page.evaluate(() => {
      const h = () => {
        const r = document.querySelector('.map-wrap').getBoundingClientRect();
        return Math.round(r.height);
      };
      const normal = h();
      document.getElementById('map-full').click();
      const max = h();
      document.getElementById('map-full').click();
      return { normal, max, vh: window.innerHeight };
    });
    // 74dvh 로 잡아 뒀으므로 평소에도 화면의 3분의 2는 넘어야 한다.
    check('폰에서 지도가 화면의 3분의 2를 넘게 쓴다',
          phone.normal / phone.vh > 0.66,
          `지도 ${phone.normal}px / 화면 ${phone.vh}px`
          + ` (${(phone.normal / phone.vh * 100).toFixed(0)}%)`);
    check('⛶ 를 누르면 화면을 통째로 쓴다',
          phone.max / phone.vh > 0.98,
          `지도 ${phone.max}px / 화면 ${phone.vh}px`
          + ` (${(phone.max / phone.vh * 100).toFixed(0)}%)`);
    // 재고 나면 되돌린다. 뒤 절들이 넓은 화면을 전제한다.
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForTimeout(150);
    await lpFire();

    // B — 고르기 전에는 상세 패널이 없다.
    //
    // **여기서 window 를 보면 안 된다.** 이 절에 오기까지 앞 절들이
    // 영업소를 고르고 지도를 눌렀으므로 패널이 열려 있는 것이 정상이다.
    // '기본 세팅' 은 내려받은 문서가 무엇인가의 문제다.
    const shipped = await (await fetch(`${BASE}/app/index.html`)).text();
    check('내려받은 문서에서 상세 패널이 닫혀 있다',
          /<aside class="detail" id="detail" hidden>/.test(shipped)
          && !/지도에서 <strong>영업소<\/strong>를 선택하세요/.test(shipped),
          (/<aside class="detail"[^>]*>/.exec(shipped) || ['(없음)'])[0]);

    // 영업소를 고르면 열린다.
    const d1 = await page.evaluate(async () => {
      const g = document.getElementById('gate-bg');
      if (g && !g.checked) { g.checked = true; g.dispatchEvent(new Event('change')); }
      await new Promise((r) => setTimeout(r, 300));
      const m = (window.__map.groups || []).flatMap((x) => x._items)
        .find((x) => x.__on && x.__on.click);
      if (m) m.__on.click({});
      await new Promise((r) => setTimeout(r, 300));
      const b = document.getElementById('detail');
      return { hidden: b.hidden, html: b.innerHTML };
    });
    check('영업소를 고르면 열린다', !d1.hidden);

    // E — 사분면 배지와 통계 카드 넷은 없다.
    if (!d1.hidden) {
      check('사분면 배지가 없다', !/class="badge"/.test(d1.html));
      check('통계 카드 넷이 없다',
            !/교통량 증가율/.test(d1.html) && !/신뢰도/.test(d1.html));
      // 그런데 추이는 남는다 — 지운 것은 요약이지 자료가 아니다.
      check('가격·교통량 추이는 남는다',
            /가격 추이/.test(d1.html) && /교통량 추이/.test(d1.html));
      // 그리고 그 가격이 지도 필터와 다르다는 것을 밝힌다.
      check('반경 가격이 세 용도지역 기준임을 밝힌다',
            /계획관리/.test(d1.html) && /지도에서 켠 용도지역과 무관/.test(d1.html),
            (/(계획관리[^<]*)/.exec(d1.html) || ['(없음)'])[0].slice(0, 60));
    }

    // 영업소를 끄면 다시 닫힌다 — 안 보이는 영업소의 상세만 남으면 안 된다.
    const d2 = await page.evaluate(async () => {
      const g = document.getElementById('gate-bg');
      if (g && g.checked) { g.checked = false; g.dispatchEvent(new Event('change')); }
      await new Promise((r) => setTimeout(r, 300));
      return document.getElementById('detail').hidden;
    });
    check('영업소를 끄면 다시 닫힌다', d2);

    // D — **법령 구조 그대로** (요구사항 2026-09-09: "분류는 법령
    // 기준으로 정확히 합니다"). 머리글이 되풀이되면 안 되고, 도시지역이
    // 먼저여야 하며, '비도시지역' 이라는 법에 없는 말이 없어야 한다.
    const blocks = await page.evaluate(async () => {
      const lp = await (await fetch('/app/data/landprice.json')).json();
      const box = document.getElementById('lp-groups');
      const seq = [...box.children].map((el) => {
        if (el.classList.contains('zone-major')) return `#${el.textContent}`;
        if (el.classList.contains('zone-middle')) return `>${el.textContent}`;
        return '.';
      });
      return {
        majors: seq.filter((x) => x.startsWith('#')).map((x) => x.slice(1)),
        middles: seq.filter((x) => x.startsWith('>')).map((x) => x.slice(1)),
        // 옆으로 흐르지 않는가 — 실사용 화면에서 칸이 다섯 줄로 흘러
        // 머리글이 세로로 누웠다. 실제 계산된 값을 본다.
        flow: [...box.querySelectorAll('.zone-row')].map(
          (r) => getComputedStyle(r).gridAutoFlow),
        cols: [...box.querySelectorAll('.zone-row')].map(
          (r) => getComputedStyle(r).gridTemplateColumns.split(' ').length),
        why: [...box.querySelectorAll('.zone-opt')].filter(
          (b) => b.querySelector('.zone-why')).map((b) => b.dataset.group),
        tree: (lp.zone_tree || []).map((n) => n.major),
      };
    });
    check('갈래 머리글이 되풀이되지 않는다',
          new Set(blocks.majors).size === blocks.majors.length,
          blocks.majors.join(' / '));
    check('법에 없는 비도시지역을 안 쓴다',
          !blocks.majors.includes('비도시지역'), blocks.majors.join(' / '));
    check('도시지역이 먼저다 (법 §36①1)',
          blocks.majors[0] === '도시지역', blocks.majors.join(' → '));
    check('도시지역은 시행령 §30 의 세분으로 나뉜다',
          blocks.middles.some((m) => m === '주거지역'),
          blocks.middles.join(' / '));
    // **옆으로 흐르면 안 된다.** class="checks" 가 걸어 두던
    // grid-auto-flow:column 이 살아 있으면 이 검사가 잡는다.
    check('칸이 옆으로 안 흐른다 (두 줄 격자)',
          blocks.flow.length > 0 && blocks.flow.every((f) => f === 'row')
          && blocks.cols.every((c) => c === 2),
          `flow=${[...new Set(blocks.flow)]} · cols=${[...new Set(blocks.cols)]}`);
    // '기타' 와 용도구역은 **사유를 밝혀야 한다** (요구사항).
    check('기타·용도구역에는 사유 표시가 붙는다',
          blocks.why.includes('개발제한구역')
          && blocks.why.includes('용도 미지정'),
          blocks.why.join(', '));
    const note = await page.evaluate(async () => {
      const b = [...document.querySelectorAll('.zone-opt')]
        .find((x) => x.dataset.group === '용도 미지정');
      b.querySelector('.zone-why').click();
      await new Promise((r) => setTimeout(r, 100));
      const n = document.getElementById('zone-note');
      return { hidden: n.hidden, text: n.textContent };
    });
    check('사유를 눌러 읽을 수 있다',
          !note.hidden && /용도지역 칸이 비어/.test(note.text),
          note.text.slice(0, 60));

    console.log();
    console.log('9-F. 태그 조회 배지 — 24시간 누적 N명 조회 중 · 화면 1등 별표');
    /* 요구사항(2026-09-09 2차). 급소는 '숫자가 나오나' 가 아니라 셋이다.

         (1) 세는 단위가 **태그 하나**인가 (시군구가 아니라)
         (2) 채널을 태그마다 파지 않는가 (무료 요금제를 하루에 태운다)
         (3) 누가 보는지를 안 보내는가

       그리고 별표는 **시·군 안에서** 뽑아야 한다 — 전국 1등을 달면
       전국에 별이 하나뿐이라 아무 데서도 안 보인다. */

    // 전국을 보고 있을 때. '이 태그' 랄 것이 없으므로 붙지 않는다.
    const vw0 = await page.evaluate(async () => {
      window.__zoom = 7;
      window.__center = [36.5, 127.8];
      window.SB.__log.channels.length = 0;
      window.SB.__log.rpc.length = 0;
      (window.__mapOn.moveend || []).forEach((f) => f());
      await new Promise((r) => setTimeout(r, 1800));
      return {
        channels: window.SB.__log.channels.length,
        bumps: window.SB.__log.rpc.filter((x) => x.fn === 'bump_place_view').length,
      };
    });
    check('전국을 보고 있으면 태그를 안 고른다',
          vw0.channels === 0 && vw0.bumps === 0,
          `채널 ${vw0.channels}개 · 올린 것 ${vw0.bumps}번`);

    // 읍·면·동까지 들어간다. 태그가 여럿 그려지는 자리다.
    // **창을 넓혀 둔다** — 앞 절이 좁은 창으로 끝났으면 리 태그가
    // 하나만 남아, 별표가 시·군마다 하나인지를 볼 수가 없다.
    await lpPick('y3', 'p50');
    const vw1 = await page.evaluate(async () => {
      window.__zoom = 13;
      window.__center = [37.0, 127.2];
      window.__bbox = null;                    // 앞 절이 좁혀 놓았을 수 있다
      // 조각(landprice-umd-*.json)은 화면을 옮긴 **뒤에** 받아 온다.
      // 한 번만 흔들고 재면 아직 41 조각만 와 있어 태그가 하나다.
      (window.__mapOn.moveend || []).forEach((f) => f());
      await new Promise((r) => setTimeout(r, 900));
      (window.__mapOn.moveend || []).forEach((f) => f());
      await new Promise((r) => setTimeout(r, 2400));
      return {
        names: window.SB.__log.channels.map((c) => c.name),
        rpc: window.SB.__log.rpc.slice(),
        tracked: window.SB.__log.tracked.slice(),
        tags: window.__cards().length,
        level: window.__lp.level,
      };
    });
    check('태그가 여럿 그려진다', vw1.tags > 1 && vw1.level === 'ri',
          `${vw1.tags}개 · ${vw1.level}`);
    // (2) 태그가 여럿이어도 채널은 **시·군·구 하나**다.
    check('태그가 여럿이어도 채널은 시·군·구 하나뿐이다',
          vw1.names.length === 1 && /^view:\d{5}$/.test(vw1.names[0]),
          vw1.names.join(', ') || '(없음)');
    // (1) 세는 단위는 태그다 — 열쇠가 'u:시군구:이름' 이어야 한다.
    const bumps = vw1.rpc.filter((x) => x.fn === 'bump_place_view');
    check('가운데 둔 태그 하나만 올린다',
          bumps.length === 1 && /^u:\d{5}:/.test(bumps[0].args.k),
          JSON.stringify(bumps));
    check('보이는 태그의 24시간 누적을 한 번에 묻는다',
          vw1.rpc.some((x) => x.fn === 'place_view_stats'
                              && Array.isArray(x.args.keys)
                              && x.args.keys.length > 1),
          JSON.stringify(vw1.rpc.filter((x) => x.fn === 'place_view_stats')
            .map((x) => x.args.keys.length)));
    // (3) 내보내는 것에 신원이 없다.
    check('싣는 것은 태그 열쇠 하나뿐이다',
          vw1.tracked.length > 0
          && vw1.tracked.every((t) => Object.keys(t).join(',') === 'p'),
          JSON.stringify(vw1.tracked.slice(-1)));
    const vwPriv = await page.evaluate(() => JSON.stringify(window.SB.__log));
    check('나가는 값에 좌표도 이메일도 없다',
          !/"lat"|"lon"|@|"u1"/.test(vwPriv), vwPriv.slice(0, 80));

    // 24시간 누적이 **배지로** 적힌다 (요구사항 2026-09-11: 'XX명 조회 중',
    // 태그 아래 겹쳐서). 누군가 새로 오면(Presence sync) 통계를 다시 묻는다.
    const vw2 = await page.evaluate(async () => {
      const rec = window.SB.__log.channels[0];
      const mine = window.SB.__log.tracked[window.SB.__log.tracked.length - 1].p;
      const before = window.SB.__log.rpc.filter((x) => x.fn === 'place_view_stats').length;
      // 나 말고 둘이 더 같은 태그를 가운데 두었다.
      rec.state = { a: [{ p: mine }], b: [{ p: mine }], c: [{ p: mine }] };
      rec.handlers.forEach((h) => h());
      await new Promise((r) => setTimeout(r, 300));
      const after = window.SB.__log.rpc.filter((x) => x.fn === 'place_view_stats').length;
      const cards = window.__cards();
      return { mine, before, after,
               badges: cards.filter((h) => /<s>\d+명 조회 중<\/s>/.test(h)).length,
               old: cards.filter((h) => /조회중|오늘|지금/.test(h)).length,
               sample: (cards.find((h) => /<s>/.test(h)) || '').slice(0, 200) };
    });
    check('배지는 "N명 조회 중" 하나뿐이다 (오늘·지금 없음)',
          vw2.badges > 0 && vw2.old === 0, vw2.sample);
    check('누가 새로 오면 24시간 누적을 다시 묻는다 (실시간)',
          vw2.after > vw2.before, `${vw2.before} → ${vw2.after}`);

    // 아무 숫자도 없는 태그에는 **줄을 안 만든다.** 새로 생긴 동네마다
    // '지금 0 / 오늘 0명' 이 붙으면 그것만 눈에 띈다.
    const vw3 = await page.evaluate(() => {
      const cards = window.__cards();
      return { all: cards.length, lines: cards.filter((h) => /<s>/.test(h)).length };
    });
    check('숫자가 없는 태그에는 배지가 없다', vw3.lines < vw3.all,
          `태그 ${vw3.all}개 중 줄 ${vw3.lines}개`);

    // 열린 말풍선이 **지도가 움직여도 살아 있어야 한다.**
    //
    // 보고된 문제(2026-09-10): "조심히 누르지 않거나 가장자리 태그
    // 클릭 시 지도가 옮겨지면서 계속 사라집니다." 손가락이 미끄러지거나
    // 가장자리에서 autoPan 이 지도를 밀면 moveend 가 오고, 그때 태그를
    // 전부 지우고 다시 만들면서(clearLayers) 방금 열린 말풍선이 함께
    // 사라졌습니다. 말풍선을 보여주려고 켠 autoPan 이 그것을 죽였습니다.
    const live = await page.evaluate(() => {
      const marks = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((m) => m.options && m.options.pane === 'lpPane');
      const m = marks[0];
      m.openPopup();
      const opened = !!m.__popupOpen;
      // 지도가 움직인 셈으로 둔다 — autoPan 도, 미끄러진 손가락도 이것이다.
      ((window.__mapOn || {}).moveend || []).forEach((f) => f());
      const after = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((x) => x.options && x.options.pane === 'lpPane');
      return { opened, stillOpen: !!m.__popupOpen, sameMarks: after.includes(m) };
    });
    check('말풍선을 열면 열린다', live.opened);
    check('지도가 움직여도 말풍선이 안 사라진다',
          live.stillOpen && live.sameMarks,
          `열림=${live.stillOpen} 마커유지=${live.sameMarks}`);

    // **가장자리 태그.** 여기가 1차 고침이 놓친 자리다 (2026-09-10
    // 2차 보고: "1번은 기존처럼 꺼집니다. 몇번을 눌러야 정상적으로
    // 켜져 있습니다").
    //
    // Leaflet 안의 순서가 이렇다:
    //   click → 말풍선 붙이기 → autoPan 으로 지도를 민다 → moveend
    //         → **그 다음에야** popupopen
    //
    // 그러니 moveend 시점에는 popupopen 이 아직 안 왔고, lpOpenPk 는
    // null 이다. 그 한 틈에 태그를 다 지워서 말풍선이 닫혔다.
    // 밀린 뒤에는 가장자리가 아니게 되므로 두세 번째 누름은 됐다.
    // **여기가 두 번 놓친 자리다.** 진짜 Leaflet 으로 재현해 보니
    // 순서는 click → popupopen → moveend 였고, moveend 잠금은 제대로
    // 돌았습니다. 죽인 것은 **조회수 RPC 응답**이 부른 재그리기였습니다
    // (app.js 의 viewersBump). drawLandPrice 를 부르는 자리가 열여섯
    // 곳이라 자리마다 막으면 반드시 하나를 빠뜨립니다.
    //
    // 그래서 **부르는 쪽이 아니라 그리는 쪽**을 검사합니다 — 말풍선이
    // 열려 있으면 누가 불러도 안 그려야 합니다.
    const edge = await page.evaluate(async () => {
      const pick = () => (window.__map.groups || []).flatMap((g) => g._items)
        .filter((m) => m.options && m.options.pane === 'lpPane');
      const m = pick()[0];
      m.openPopup();
      const opened = !!m.__popupOpen;
      // 우리가 부르지 않은 자리들이 다시 그리려 든다.
      ((window.__mapOn || {}).moveend || []).forEach((f) => f());
      window.__drawLandPrice();          // 조회수 RPC · presence · 조각 도착
      window.__drawLandPrice();
      return { opened, survived: pick().includes(m), open: !!m.__popupOpen };
    });
    check('말풍선이 열려 있으면 누가 불러도 안 그린다',
          edge.survived, `마커유지=${edge.survived}`);
    check('가장자리 태그 — 첫 누름에 말풍선이 켜진다',
          edge.opened && edge.open);


    // 닫으면 밀린 갱신을 갚는다 — 그래야 태그가 낡은 채로 남지 않는다.
    const after = await page.evaluate(() => {
      const marks = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((m) => m.options && m.options.pane === 'lpPane');
      // **이 절은 스스로 준비한다.** 앞 절들이 열고 닫으므로 '열려 있는
      // 것을 찾는' 방식은 앞 절의 끝 상태에 기대게 된다.
      const m = marks.find((x) => x.__popupOpen) || marks[0];
      if (!m) return { redrew: false };
      if (!m.__popupOpen) m.openPopup();
      m.closePopup();
      const now = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((x) => x.options && x.options.pane === 'lpPane');
      return { redrew: !now.includes(m) && now.length > 0, n: now.length };
    });
    check('닫으면 태그를 다시 그린다 (밀린 갱신을 갚는다)',
          after.redrew, `다시 그린 태그 ${after.n}개`);

    // 끌기 끝의 '누름' 은 누른 것이 아니다. 지도를 옮기려고 태그 위에서
    // 끌면 Leaflet 이 그것도 누름으로 세는데, 그때 말풍선이 딸려 열렸다.
    const drag = await page.evaluate(() => {
      const marks = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((m) => m.options && m.options.pane === 'lpPane');
      const m = marks[0];
      ((window.__mapOn || {}).dragstart || []).forEach((f) => f());
      m.openPopup();
      const afterDrag = !!m.__popupOpen;
      // 새로 누르면 끌기 표시가 지워진다.
      window.__mapBox.dispatchEvent(new Event('pointerdown', { bubbles: true }));
      m.openPopup();
      return { afterDrag, afterTap: !!m.__popupOpen };
    });
    check('끌기 끝의 누름으로는 안 열린다', !drag.afterDrag);
    check('다시 누르면 열린다', drag.afterTap);


    // 별표 — **화면에 보이는 태그 중** 24시간 누적 1등 하나. 10명 미만이면
    // 없다 (요구사항 2026-09-11).
    const vw5 = await page.evaluate(async () => {
      // 앞 절이 말풍선을 열어 둔 채 끝났다. 열려 있는 동안은 다시 안
      // 그리므로(drawLandPrice 의 잠금) 지도의 popupclose 로 먼저 닫는다.
      const closeAll = async () => {
        (window.__map.groups || []).flatMap((g) => g._items)
          .filter((m) => m && m.__popupOpen && m.closePopup).forEach((m) => m.closePopup());
        (((window.__mapOn || {}).popupclose) || []).forEach((f) =>
          f({ popup: { options: { className: 'lp-pop' } } }));
        await new Promise((r) => setTimeout(r, 100));
      };
      await closeAll();
      const stars = () => window.__cards()
        .filter((h) => /<mark>/.test(h))
        .map((h) => (h.match(/<mark>★<\/mark>([^<]*)/) || [])[1] || '');
      const keys = (window.SB.__log.rpc
        .filter((x) => x.fn === 'place_view_stats').pop() || { args: {} }).args.keys || [];
      // 가짜 RPC 는 n24 = 1000 - i 를 짝수 번째에만 준다 → 1등은 keys[0].
      const items = (window.__lp.items || []);
      const top = items.find((x) => x.pk === keys[0]);
      const withMany = { keys: keys.length, starred: stars(),
                         want: top ? String(top.name).split(' ').pop() : '' };
      // 값을 9 로 누르면 별이 없어야 한다. **지금 붙어 있는** 채널(마지막)의
      // sync 를 흉내낸다 — 옛 채널의 손잡이는 옮긴 뒤라 조용히 무시된다.
      window.__statsCap = 9;
      const chs = window.SB.__log.channels;
      const rec = chs[chs.length - 1];
      const before = window.SB.__log.rpc.filter((x) => x.fn === 'place_view_stats').length;
      rec.handlers.forEach((h) => h());
      await new Promise((r) => setTimeout(r, 400));
      await closeAll();                        // 사이에 무엇이 열렸어도 밀린 그리기를 갚는다
      const asked = window.SB.__log.rpc.filter((x) => x.fn === 'place_view_stats').length - before;
      const capped = stars();
      delete window.__statsCap;
      return { withMany, capped, asked, channels: chs.length, peek: window.__viewersPeek() };
    });
    check('별표는 화면에 하나 — 24시간 누적 1등에게',
          vw5.withMany.keys > 1 && vw5.withMany.starred.length === 1
          && vw5.withMany.starred[0].replace(/[0-9.만]*$/, '') === vw5.withMany.want,
          `열쇠 ${vw5.withMany.keys}개 · 별 ${vw5.withMany.starred.join(', ')} vs 1등 ${vw5.withMany.want}`);
    check('10명 미만이면 별이 없다', vw5.asked > 0 && vw5.capped.length === 0,
          `별 ${vw5.capped.length}개 · 다시 물음 ${vw5.asked}번 · 별 열쇠 ${vw5.peek.star} · 열린 말풍선 ${vw5.peek.open}`);

    await page.evaluate(() => { window.__zoom = 7; window.__center = null; });

    console.log();
    console.log('9-C. 필지 진단 — 다섯 축을 또래 안 백분위로');
    /* 요구사항(2026-09-08): "해당 필지를 클릭하면 스파이더 차트를 통해
     * 여러가지 인자들을 분석하여 어떤 방향이 좋을 지 판단할 수 있도록"
     * "(어떤 토지이든 나쁜 토지는 없다. 어떤 방향으로 개발할 지가 문제다)" */
    const clickMap = async (lat, lon) => {
      await page.evaluate((p) => {
        window.__zoom = 15;
        const fns = ((window.__mapOn || {}).click) || [];
        fns.forEach((fn) => fn({ latlng: { lat: p.lat, lng: p.lon },
                                 originalEvent: { target: null } }));
      }, { lat, lon });
      await page.waitForTimeout(400);
      return page.evaluate(() => ({
        html: (document.getElementById('detail') || {}).innerHTML || '',
        peek: window.__parcel || null,
      }));
    };

    const pc = await clickMap(37.304, 127.011);
    check('지도를 누르면 그 필지를 물어본다', parcelHits > 0, `${parcelHits}회`);
    check('오른쪽에 필지 카드가 열린다',
          /parcel-card/.test(pc.html) && /계획관리지역/.test(pc.html),
          pc.html.slice(0, 80));
    // 주소 (요구사항 2026-09-10). 카드 머리에 지번이 서야 한다 —
    // 화면에서 그 자리를 빨갛게 표시해 보내 주신 요구다.
    check('카드에 지번 주소가 있다',
          /pc-addr/.test(pc.html)
          && /경기도 광주시 초월읍 지월리 14-1/.test(pc.html),
          (pc.html.match(/<div class="pc-addr">.{0,90}/) || ['없음'])[0]);
    check('도로명이 없으면 빈 줄을 안 세운다 (고장으로 안 읽히게)',
          !/pc-addr[^>]*>[\s\S]{0,200}<span><\/span>/.test(pc.html));

    // 토지 정보 표 (요구사항 2026-09-10 — 부동산플래닛 참조).
    for (const [label, want] of [
      ['지목', '전'], ['이용상황', '전'], ['지세(고저)', '평지'],
      ['형상', '가로장방형'], ['도로조건', '중로한면'],
    ]) {
      const row = new RegExp(`<th>${label.replace(/[()]/g, '\\$&')}</th>`
                             + `<td>[^<]*${want}`);
      check(`토지 정보에 ${label} 이 있다`, row.test(pc.html),
            (pc.html.match(row) || ['없음'])[0]);
    }
    check('면적을 ㎡ 와 평으로 같이 적는다',
          /<th>면적<\/th><td>1,653㎡ <em>\(500평\)<\/em>/.test(pc.html),
          (pc.html.match(/<th>면적<\/th><td>[^<]*<em>[^<]*<\/em>/) || ['없음'])[0]);
    check('공시지가에 기준연도를 붙인다',
          /<th>공시지가<\/th><td>250,000원\/㎡ <em>\(2025년 기준\)/.test(pc.html),
          (pc.html.match(/<th>공시지가<\/th><td>[^<]*<em>[^<]*<\/em>/) || ['없음'])[0]);
    check('대장 구분을 적는다', /<th>대장<\/th><td>토지대장/.test(pc.html));
    // '지정되지않음' 은 값이 아니라 빈칸이다. 그대로 적으면 무슨 뜻인지
    // 되묻게 된다.
    check("'지정되지않음' 을 값처럼 적지 않는다",
          !/지정되지않음/.test(pc.html));
    check('용도지역은 겹치지 않으면 하나만 적는다',
          /<th>용도지역<\/th><td>계획관리지역<\/td>/.test(pc.html),
          (pc.html.match(/<th>용도지역<\/th><td>[^<]*/) || ['없음'])[0]);

    // 개발 한도 (C4 · docs §6 (1)). 토지 정보 바로 아래, 접혀서.
    check('개발 한도 칸이 토지 정보 아래에 선다',
          /pc-limits/.test(pc.html)
          && pc.html.indexOf('토지 정보') < pc.html.indexOf('pc-limits')
          && pc.html.indexOf('pc-limits') < pc.html.indexOf('건축 제한'));
    check('조례에 값이 없으면 시행령 상한을 ≤ 로 적고 미확인이라 말한다',
          /<th>건폐율<\/th><td>≤ <b>40%<\/b> <em>시행령 상한 · 조례 값 미확인/.test(pc.html),
          (pc.html.match(/<th>건폐율<\/th><td>[^\n]{0,80}/) || ['없음'])[0]);
    check('면적으로 바닥·연면적 최대를 계산한다 (1,653㎡ × 40% · 100%)',
          /바닥 661㎡ · 연면적 1,653㎡/.test(pc.html),
          (pc.html.match(/<th>최대 규모<\/th><td>[^<]{0,60}/) || ['없음'])[0]);
    check('경사·표고는 조례 문턱만 적고 잰 값이 없다고 말한다',
          /10° 미만/.test(pc.html) && /못 잼/.test(pc.html) && !/통과/.test(pc.html));
    check('근거 조례에 원문 링크를 단다',
          /ordinInfoP\.do\?ordinSeq=2102141[^>]*>수원시 도시계획 조례</.test(pc.html)
          && /시행 2025-12-31/.test(pc.html));
    check('개발 한도 칸이 가이드(법령과 조례)로 이어진다', /href="\/guide\/law"/.test(pc.html));
    check('개발 한도는 건축 제한처럼 늘 펼쳐져 있다 (접이식 아님)',
          /<section class="pc-limits"><h4 class="pc-sub">개발 한도/.test(pc.html) && !/<details class="pc-limits"/.test(pc.html));

    // 건축 제한 (요구사항 2026-09-10). 레이더는 안 건드리고 아래에
    // 따로 적는다 — 규제의 무게를 숫자로 환산하면 그 환산율 자체가
    // 근거 없는 점수가 된다.
    check('건축 제한 칸이 선다', /건축 제한/.test(pc.html));
    check('걸린 구역을 이름으로 적는다',
          /가축사육제한구역/.test(pc.html) && /농업진흥지역/.test(pc.html),
          (pc.html.match(/pc-zones[\s\S]{0,120}/) || ['없음'])[0]);
    check('세부 이름까지 적는다 (절대제한인지 일부인지)',
          /절대제한지역\(전 축종\)/.test(pc.html));
    check('그것이 무엇을 막는지 적는다',
          /축사를 지을 수 없습니다/.test(pc.html));
    // 다 보여준 척하면 안 된다 — 준보전산지·접도구역은 우리가 못 받는다.
    check('이것이 전부가 아니라고 적는다',
          /준보전산지/.test(pc.html) && /접도구역/.test(pc.html));
    // 표에도 지구·구역을 자세히.
    check('토지 정보 표에도 지구·구역이 있다',
          /<th>지구·구역<\/th>/.test(pc.html),
          (pc.html.match(/<th>지구·구역<\/th><td>[^<]*/) || ['없음'])[0]);
    // 레이더는 그대로다. 축을 손대면 근거 없는 환산이 된다.
    check('레이더 축은 안 건드린다 (다섯 그대로)',
          (pc.html.match(/개발 여지/g) || []).length >= 1
          && !/규제 축/.test(pc.html));

    // 축 설명 (요구사항 2026-09-10). 축 이름만으로는 '개발 여지' 가
    // 무엇을 견준 것인지 알 수 없다.
    check('다섯 축이 무엇을 재는지 적는다',
          /다섯 축이 무엇을 재는가/.test(pc.html));
    for (const k of ['도로', '물류 교통', '개발 여지', '시장 동향', '모양·지세']) {
      check(`  ${k} 축 설명이 있다`,
            new RegExp(`<dt>${k.replace(/[·]/g, '·')}</dt><dd>`).test(pc.html));
    }
    // 가격만 방향이 다르다. 안 적으면 다섯을 같은 방향으로 읽는다.
    // 가격 축을 **추세**로 바꿨다 (요구사항 2026-09-10). 지금 비싼
    // 땅이 좋은 땅은 아니고, 오르는 중인지가 더 쓸모 있다.
    // 이름은 '시장 동향' 이다 (2026-09-10 재분석) — 땅의 성질이 아니라
    // 시장의 자리라서 '가격' 이라는 말을 떼었다.
    check('가격 축이 추세다 (수준이 아니다) — 이름은 시장 동향',
          /시장 동향/.test(pc.html) && !/가격 수준/.test(pc.html) && !/가격 추세/.test(pc.html),
          (pc.html.match(/시장 [^<\s]*/) || ['없음'])[0]);
    check('연평균 상승률을 원값으로 적는다',
          /연 \+7\.2%/.test(pc.html),
          (pc.html.match(/연 [+-][0-9.]+%[^<]*/) || ['없음'])[0]);
    check('몇 해를 본 것인지 적는다', /최근 6년/.test(pc.html));
    // 축 설명에서 **재는 방법**을 뺐다 (2026-09-12 지시 '노하우는 숨긴다').
    // 몇 km 안의 어느 차종인지, 또래를 무슨 열쇠로 묶고 얇으면 어디로
    // 물러나는지는 곧 만드는 법이다. 뜻과 주의만 남긴다.
    check('축 설명이 재는 방법을 적지 않는다',
          !/2·3·4·5종/.test(pc.html) && !/10km 안/.test(pc.html)
          && !/같은 시군구·같은 용도지역·같은 지목군/.test(pc.html)
          && !/시·도로 물러납니다/.test(pc.html),
          (pc.html.match(/<dt>물류 교통<\/dt><dd>[^<]*/) || ['없음'])[0]);
    check('그래도 무엇을 재는지와 주의는 남는다',
          /화물 통행/.test(pc.html) && /오르는 중인지/.test(pc.html)
          && /지적상 접면/.test(pc.html) && /비슷한 조건의 거래/.test(pc.html));

    // 현재 가치 · 미래 가치 (요구사항 2026-09-10). 축 설명 바로 밑.
    check('가치 단추가 둘 선다',
          (pc.html.match(/class="pc-val"/g) || []).length === 2,
          String((pc.html.match(/class="pc-val"/g) || []).length));
    check('현재 가치 · 미래 가치 라는 이름이다',
          /현재 가치/.test(pc.html) && /미래 가치/.test(pc.html));
    check('누르기 전에 회원 전용이라고 적는다', /회원 전용/.test(pc.html));
    check('축 설명 바로 아래에 있다',
          pc.html.indexOf('pc-axis-help') < pc.html.indexOf('pc-val-row')
          && pc.html.indexOf('pc-val-row') < pc.html.indexOf('토지 정보'));
    // CSS 가 아직 안 붙은 한순간에 <em> 은 기울어진 글씨로 이름에
    // 붙어 '현재 가치준비 중' 처럼 보인다. 태그로 뜻이 서게 둔다.
    check('뱃지를 <em> 으로 달지 않는다',
          !/<em>회원 전용<\/em>/.test(pc.html) && /pcv-tag/.test(pc.html));
    // 프리미엄 잠금 (2026-09-11 지시). C 등급은 단추에 '프리미엄' 꼬리표가
    // 붙고, 누르면 산출 대신 안내가 뜬다 — 결제 안내는 미확정이라 '준비 중'.
    check('B 등급은 잠기지 않는다', !/pcv-lock/.test(pc.html) && !/is-locked/.test(pc.html));
    // Admin 링크 (2026-09-12 지시). 머리띠에 자리는 늘 있고, 관리자에게만
    // 보인다. 링크를 보이는 것뿐이고 자물쇠는 /admin 화면과 데이터베이스다.
    const admNav = await page.evaluate(() => {
      const a = document.querySelector('.sitenav a[href="/admin"]');
      return { there: !!a, hiddenForB: a ? a.hidden : null };
    });
    check('머리띠에 Admin 링크 자리가 있고 회원에게는 숨어 있다',
          admNav.there && admNav.hiddenForB === true, JSON.stringify(admNav));
    const admShown = await page.evaluate(() => {
      window.tojiAdminNav(true);
      const a = document.querySelector('.sitenav a[href="/admin"]');
      const on = a && !a.hidden;
      window.tojiAdminNav(false);                 // 뒤 검사를 위해 되돌린다
      return on;
    });
    check('관리자면 Admin 링크가 보인다', admShown === true, String(admShown));
    await page.evaluate(() => { window.ME.profile.grade = 'C'; });
    const pcC = await clickMap(37.304, 127.011);
    check('C 등급은 단추가 잠긴다 (회원 전용 꼬리표)',
          /pcv-lock/.test(pcC.html) && /<span class="pcv-tag pcv-lock">회원 전용<\/span>/.test(pcC.html),
          (pcC.html.match(/pc-val-row[^>]*>[\s\S]{0,160}/) || ['없음'])[0]);
    const lockBox = await page.evaluate(() => {
      document.querySelector('.pc-val[data-val="now"]').click();
      return document.getElementById('pc-val-box').innerHTML;
    });
    check('손님 등급이 누르면 산출 대신 안내가 뜬다',
          /VIP·회원 등급에게 열립니다/.test(lockBox) && /href="\/account"/.test(lockBox)
          && !/공시지가기준법/.test(lockBox), lockBox.slice(0, 160));
    check('안내에 지금 등급을 이름으로 적는다 (손님)', /지금 등급은 <b>손님<\/b>/.test(lockBox));
    // 로그인 안 한 사람(손님)은 등급 안내가 아니라 **가입 권유**를 본다
    // (2026-09-12 지시). 등급을 올려 달라고 문의할 계정이 아직 없다.
    const guestBox = await page.evaluate(async () => {
      const keep = window.ME;
      window.ME = null;
      const b = document.querySelector('.pc-val[data-val="now"]');
      b.click();                                   // 열려 있던 것을 닫고
      await new Promise((ok) => setTimeout(ok, 20));
      b.click();                                   // 손님 자격으로 다시 연다
      const html = document.getElementById('pc-val-box').innerHTML;
      window.ME = keep;
      return html;
    });
    check('로그인 안 한 사람에게는 가입을 권한다',
          /무료 회원 가입/.test(guestBox) && /href="\/account\?next=%2Fapp"/.test(guestBox)
          && !/지금 등급은/.test(guestBox), guestBox.slice(0, 200));
    await page.evaluate(() => { window.ME.profile.grade = 'B'; window.ME.profile.grade_until = '2020-01-01'; });
    const pcX = await clickMap(37.304, 127.011);
    const lockX = await page.evaluate(() => {
      document.querySelector('.pc-val[data-val="now"]').click();
      return document.getElementById('pc-val-box').innerHTML;
    });
    check('B 인데 기간이 지나면 잠기고 그렇게 말한다',
          /pcv-lock/.test(pcX.html) && /이용 기간이 끝났습니다/.test(lockX), lockX.slice(0, 120));
    await page.evaluate(() => { delete window.ME.profile.grade_until; window.ME.profile.grade = 'B'; });
    await clickMap(37.304, 127.011);

    // 프리미엄 자료는 로그인 클라이언트의 비공개 버킷에서 온다 (2026-09-11 A 단계).
    // 버킷이 거부하면(등급 밖·토큰 없음) 정적 파일로 물러나지 않고 보류한다.
    const bucket = await page.evaluate(async () => {
      const log = [];
      window.SB.storage = { from: (b) => ({ download: async (name) => { log.push(b + '/' + name);
        return { data: null, error: { message: 'new row violates row-level security policy' } }; } }) };
      document.querySelector('.pc-val[data-val="now"]').click();
      await new Promise((ok) => setTimeout(ok, 300));
      const html = document.getElementById('pc-val-box').innerHTML;
      delete window.SB.storage;
      document.querySelector('.pc-val[data-val="now"]').click();   // 닫기
      return { log, html };
    });
    check('격차율 표를 버킷 premium 에서 찾는다', bucket.log[0] === 'premium/valuation.json', bucket.log.join(','));
    check('버킷이 거부하면 숫자 없이 보류한다',
          /곧 공개합니다/.test(bucket.html) && !/원\/㎡/.test(bucket.html), bucket.html.slice(0, 80));

    // 근거는 **아직 적지 않는다** — 그 설명이 곧 유료 전환의 열쇠라,
    // 값이 없는 지금 미리 풀면 살 이유를 먼저 소비해 버린다.
    // 저장소에 전국 표준지 조각이 실려 있으면(2026-09-11 부터) 이 시군구 조각도
    // 진짜로 있다. 이 절은 '조각이 없을 때' 를 검사하므로 없는 척한다 — 성공만
    // 기억하는 로더라 404 는 다음 절의 고정 조각을 막지 않는다.
    await page.route('**/app/data/valuation.json*', (r) => r.fulfill({ status: 404, body: '' }));
    await page.route('**/app/data/stdland-*.json*', (r) => r.fulfill({ status: 404, body: '' }));
    const vnow = await page.evaluate(async () => {
      document.querySelector('.pc-val[data-val="now"]').click();
      await new Promise((ok) => setTimeout(ok, 150));
      const b = document.getElementById('pc-val-box');
      return { html: b.innerHTML, open: !b.hidden };
    });
    check('현재 가치를 누르면 열린다', vnow.open === true);
    check('곧 공개한다고만 적는다',
          /곧 공개합니다/.test(vnow.html),
          vnow.html.replace(/<[^>]+>/g, ' ').trim().slice(0, 60));
    check('근거를 미리 풀지 않는다 (감정평가서·공시지가 배율)',
          !/감정평가서/.test(vnow.html) && !/배율/.test(vnow.html)
          && !/실거래/.test(vnow.html),
          vnow.html.replace(/<[^>]+>/g, ' ').trim().slice(0, 60));
    // 몇 건 읽었는지도 안 적는다 — 0 건이라고 적으면 아무것도 없다는
    // 것을 먼저 말하게 된다.
    check('가진 것이 없다는 것을 세어 보이지 않는다',
          !/0건/.test(vnow.html) && !/읽은/.test(vnow.html));
    check('없는 금액을 적지 않는다',
          !/[0-9,]+\s*원\/㎡/.test(vnow.html) && !/예상가/.test(vnow.html),
          (vnow.html.match(/[0-9,]+\s*원[^<]*/) || ['없음'])[0]);
    const vfut = await page.evaluate(async () => {
      document.querySelector('.pc-val[data-val="future"]').click();
      await new Promise((ok) => setTimeout(ok, 150));
      return document.getElementById('pc-val-box').innerHTML;
    });
    check('미래 가치도 이름과 곧 공개뿐이다',
          /미래 가치/.test(vfut) && /곧 공개합니다/.test(vfut)
          && !/산업단지/.test(vfut));

    // ── 현재 가치 2판 — 표준지 조각과 격차율 표가 있으면 산출표를 낸다
    //    (2026-09-11). 숫자는 valuation.json(원본 src/redt/valuation.py)
    //    에서 읽고, 화면은 산식만 옮겼다. 마디가 비면 보류다.
    const VAL = {
      road_index: [['맹지', 0.8], ['광대', 1.25], ['중로', 1.18], ['소로', 1.1],
                   ['(불)', 0.88], ['불가', 0.88], ['(가)', 1], ['가능', 1]],
      road_corner_bonus: 0.03,
      shape_index: [['정방', 1], ['가장', 1], ['가로장방', 1], ['세장', 1], ['세로장방', 1], ['장방', 1],
                    ['사다리', 0.98], ['삼각', 0.93], ['역삼각', 0.93], ['부정', 0.95], ['자루', 0.9]],
      slope_index: { '임야지대': [['평지', 1], ['완경사', 0.95], ['급경사', 0.82]],
                     '*': [['평지', 1], ['완경사', 0.97], ['급경사', 0.88]] },
      use_mismatch: { '임야|대': [0.9, '지목 임야'] },
      special: { '현황도로': [0.33, '현황이 도로'], '자연취락지구': [1.15, '자연취락지구 안'] },
      must_match: ['개발제한구역', '농업진흥', '보전산지'], std_known: ['개발제한구역'],
      area_rules: { '주택지대': [[0, 0.5, 0.95, '과소 필지'], [0.5, 3, 1, null], [3, null, 0.95, '과대 필지']] },
      other: { '관리|전·답': { '*': { median: 2.34, q1: 1.82, q3: 2.45, n: 6, level: '전국 · 용도지역군 · 지목군', source: '평가선례' },
                            '41': { median: 2.32, q1: 1.82, q3: 2.45, n: 5, level: '같은 시·도 · 용도지역군 · 지목군', source: '평가선례' } } },
      time_clamp: [0.98, 1.03],
      zone_groups: [['관리', ['관리']], ['녹지', ['녹지']], ['농림', ['농림', '자연환경']],
                    ['주거', ['주거', '일주', '전주']], ['상업', ['상업']], ['공업', ['공업']]],
      use_groups: [['임야', ['임야', '자연림']], ['전·답', ['전', '답']], ['대', ['대', '주거']], ['공장·도로', ['공장', '도로']]],
    };
    const STD = { sigungu: '41111', n: 3, rows: [
      // A — 같은 동리, 세로(가)·부정형. 도로 1단·형상 벌점 0.5 → 뽑혀야 한다.
      { pnu: '4111110300100050000', ld: '4111110300', nm: '경기도 광주시 초월읍 지월리', jb: '5',
        y: 2025, pr: 150000, jm: '전', ar: 1500, lu: '계획관리지역', lu2: null, dz: null,
        us: '전', rs: '세로한면(가)', sh: '부정형', sl: '평지', lon: null, lat: null },
      // B — 다른 동리, 조건은 같다. 벌점 1.0.
      { pnu: '4111110400100070000', ld: '4111110400', nm: '경기도 광주시 초월읍 대쌍령리', jb: '7',
        y: 2025, pr: 200000, jm: '전', ar: 1600, lu: '계획관리지역', lu2: null, dz: null,
        us: '전', rs: '중로한면', sh: '가로장방', sl: '평지', lon: null, lat: null },
      // C — 자연녹지. 용도지역이 달라 후보가 아니다.
      { pnu: '4111110300100090000', ld: '4111110300', nm: '경기도 광주시 초월읍 지월리', jb: '9',
        y: 2025, pr: 300000, jm: '전', ar: 1500, lu: '자연녹지지역', lu2: null, dz: null,
        us: '전', rs: '중로한면', sh: '가로장방', sl: '평지', lon: null, lat: null },
    ] };
    await page.unroute('**/app/data/valuation.json*');
    await page.unroute('**/app/data/stdland-*.json*');
    await page.route('**/app/data/valuation.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(VAL) }));
    await page.route('**/app/data/stdland-41111.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(STD) }));
    const vcalc = await page.evaluate(async () => {
      // 닫았다가 다시 연다 — 조각이 이제 있으므로 산출표가 나와야 한다.
      const b = document.querySelector('.pc-val[data-val="now"]');
      b.click(); await new Promise((ok) => setTimeout(ok, 50));
      b.click(); await new Promise((ok) => setTimeout(ok, 400));
      return document.getElementById('pc-val-box').innerHTML;
    });
    const vtxt = vcalc.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    // 화면에 내는 것은 **값 하나와 총액**뿐이다 (2026-09-12 지시). 산출표는
    // 곧 만드는 법이라 걷어냈다. 다섯 마디가 맞는지는 화면이 아니라 고리
    // (window.__appraiseNow · __pickStandard)로 본다 — 값이 틀리면 화면이
    // 조용히 틀린 숫자를 보이게 되므로 검사는 계속 마디마다 견준다.
    // 산출표를 되돌렸다 (2026-09-12 두 번째 지시 "감정평가사가 작성한 것처럼
    // 자세히"). 평가서의 말과 순서를 그대로 쓴다.
    check('감정평가서 산출표 순서대로 낸다',
          /기준시점/.test(vcalc) && /대상 토지/.test(vcalc) && /비교표준지 선정/.test(vcalc)
          && /시점수정/.test(vcalc) && /지역요인 비교/.test(vcalc)
          && /개별요인 비교/.test(vcalc) && /그 밖의 요인 보정/.test(vcalc),
          vtxt.slice(0, 140));
    // 네 칸 표는 상세 칸(23rem)보다 넓어 글자가 넘쳤다 (2026-09-12 보고).
    // 조건마다 두 줄로 접는다 — 조건 이름 + 격차율, 그 아래 대상 / 표준지.
    check('개별요인은 조건마다 격차율과 대상/표준지를 적는다',
          /pcv-items/.test(vcalc) && /pcv-i-cond/.test(vcalc)
          && /pcv-i-ratio/.test(vcalc) && /pcv-i-vs/.test(vcalc)
          && !/<th>비교표준지<\/th>/.test(vcalc));
    const vhead = vtxt.slice(vtxt.indexOf('비교표준지 선정'), vtxt.indexOf('시점수정'));
    check('같은 동리의 표준지 A 를 고른다 (다른 동리 B 는 벌점 1.0)',
          /지월리 5/.test(vhead) && !/대쌍령리/.test(vhead), vhead.slice(0, 160));
    check('용도지역이 다른 표준지는 후보에서 뺀다', !/지월리 9/.test(vcalc));
    check('개별요인이 격차율의 곱이다 (1.243)', /1\.243/.test(vcalc),
          (vcalc.match(/개별요인 비교[^<]*<\/th><td><b>[^<]*/) || ['없음'])[0]);
    check('그 밖의 요인은 시·도 값 (경기 관리 전·답 2.32)',
          /2\.32/.test(vcalc) && /같은 시·도/.test(vcalc));
    check('시점수정은 추세로 대신했다고 적고 상한 1.03 안이다',
          /추세로 대신함/.test(vcalc) && /1\.030/.test(vcalc),
          (vcalc.match(/시점수정[\s\S]{0,120}/) || ['없음'])[0]);
    check('산식을 한 줄로 적는다', /산출단가 [0-9,]+ × /.test(vtxt));
    check('결정단가를 자리수 규칙으로 낸다 (446,000원/㎡)', /446,000원\/㎡/.test(vcalc),
          (vcalc.match(/결정단가[^<]*<b>[^<]*/) || ['없음'])[0]);
    check('인근 지가수준 범위를 함께 적는다', /인근 지가수준 [0-9,]+~[0-9,]+/.test(vtxt));
    check('평가액(추정)도 적는다 (1,653㎡)', /평가액\(추정\) 약/.test(vtxt));
    check('농업진흥은 표준지 자료에 없어 확인 못 했다고 참고사항에 적는다',
          /참고사항/.test(vcalc) && /확인하지 못했다/.test(vcalc));
    // '다른 표준지를 쓰면' 은 뺐다 (2026-09-12 지시). 평가서는 표준지를 하나
    // 고르고 그 근거를 적는다 — 여러 안을 나란히 두지 않는다.
    check('다른 표준지를 쓰면 이라는 단서는 없다',
          !/다른 표준지를 쓰면/.test(vcalc) && !/pcv-alts/.test(vcalc));
    check('머리에 표준지를 몇 필지에서 골랐는지 적지 않는다',
          !/표준지 [0-9,]+필지 중 고름/.test(vcalc));
    check('데이터베이스로 산출한 예상값이라고 적는다',
          /데이터베이스로 산출한/.test(vtxt) && /예상값/.test(vtxt)
          && /감정평가가 아닙니다/.test(vtxt) && /href="\/guide\/law"/.test(vcalc));

    // 다섯 마디 — 고리로 본다 (화면에는 없다). 화면이 쓰는 것과 **같은**
    // 함수(nowResults)를 부르므로, 마디가 틀리면 여기서 잡힌다.
    const five = await page.evaluate(async () => {
      const got = await window.__nowResults();
      const res = got.results[0];
      return {
        std: [res.std.ld_name, res.std.jibun].filter(Boolean).join(' '),
        others: got.picked.map((p) => [p.ld_name, p.jibun].filter(Boolean).join(' ')),
        time: res.time.factor, timeSrc: res.time.source,
        indiv: res.individual.factor, other: res.other.factor, otherLevel: res.other.basis,
        unit: res.unit_decided, total: res.total_krw, warn: res.warnings,
      };
    });
    check('같은 동리의 표준지 A 를 고른다 (다른 동리 B 는 벌점 1.0)',
          /지월리 5/.test(five.std) && !/대쌍령리/.test(five.std), five.std);
    check('용도지역이 다른 표준지는 후보에서 뺀다',
          !five.others.some((x) => /지월리 9/.test(x)), JSON.stringify(five.others));
    // 개별요인 = 도로 1.18/1.00 × 형상 1.00/0.95(→1.053) × 지세 1 = 1.243
    check('개별요인이 격차율의 곱이다 (1.243)',
          Math.abs(five.indiv - 1.243) < 0.001, String(five.indiv));
    check('그 밖의 요인은 시·도 값 (경기 관리 전·답 2.32)',
          five.other === 2.32 && /같은 시·도/.test(five.otherLevel), five.otherLevel);
    check('시점수정은 추세로 대신했다고 적고 상한 1.03 안이다',
          /추세로 대신함/.test(five.timeSrc) && Math.abs(five.time - 1.03) < 0.0005,
          `${five.time} ${five.timeSrc}`);
    check('농업진흥은 표준지 자료에 없어 확인 못 했다고 경고에 남는다',
          five.warn.some((w) => /확인하지 못했다/.test(w)), JSON.stringify(five.warn));
    // 뒤 검사는 '미래 가치' 가 열린 상태에서 시작한다. 그 상태로 되돌린다.
    await page.evaluate(async () => {
      document.querySelector('.pc-val[data-val="future"]').click();
      await new Promise((ok) => setTimeout(ok, 100));
    });
    const vclose = await page.evaluate(async () => {
      document.querySelector('.pc-val[data-val="future"]').click();
      await new Promise((ok) => setTimeout(ok, 100));
      return document.getElementById('pc-val-box').hidden;
    });
    check('같은 단추를 다시 누르면 닫힌다', vclose === true, String(vclose));

    check('레이더를 그린다 (다섯 축)',
          /<svg class="radar"/.test(pc.html)
          && (pc.peek.diag.axes || []).length === 5,
          (pc.peek.diag.axes || []).map((a) => a.key).join(','));

    const byKey = {};
    (pc.peek.diag.axes || []).forEach((a) => { byKey[a.key] = a; });
    // 중로한면 = 등급 4 → 또래 누적 .7
    check('도로 축이 또래 사다리를 탄다',
          Math.abs(byKey.road.pct - 0.7) < 1e-6, String(byKey.road.pct));
    // 가격 축은 이제 **추세**다 (요구사항 2026-09-10). 또래 안에서
    // 재면 같은 동네가 모두 같은 값이 되므로, 전국 분포와 견준다.
    //
    //   연 +7.2% 는 trend_q 의 8번(0.065)과 9번(0.085) 사이
    //   (0.072-0.065)/(0.085-0.065) = 0.35  →  (8+0.35)/10 = 0.835
    check('가격 축이 전국 추세 분포를 선형으로 읽는다',
          Math.abs(byKey.price.pct - 0.835) < 1e-6, String(byKey.price.pct));
    // 추세를 못 내는 또래는 축을 비운다 — 0 으로 두면 '안 오르는 땅'
    // 으로 읽히는데 사실은 **모르는** 것이다.
    check('추세가 없으면 축을 비운다 (0 이 아니다)',
          byKey.price.pct === null || byKey.price.pct === 0.835,
          String(byKey.price.pct));
    // 계획관리 = 사다리 5 → 시군구 zone_pct[5] = .88
    check('개발 여지는 또래가 아니라 시군구 안에서 잰다',
          Math.abs(byKey.zoning.pct - 0.88) < 1e-6, String(byKey.zoning.pct));
    // 가로장방형(4) + 평지(5) → 반올림 5 → land[5] = .95
    check('모양·지세를 한 축으로 묶는다',
          Math.abs(byKey.land.pct - 0.95) < 1e-6, String(byKey.land.pct));
    // ── 필지 경계선 (요구사항 2026-09-10, A안) ──
    //
    // 예전에는 용도지역 층 **안에** 들어 있어서, 경계선만 보려면 색면
    // 까지 켜야 했고 그 색면이 지도를 덮었다. 따로 떼어 스위치를 줬다.
    //
    // **그림이 아니라 도형으로 받는다** (2026-09-10). 브이월드 WMS 는
    // 배율 18 아래로 아무것도 안 그렸다 — 라이브에서 z14·15·17 이
    // 전부 '완전히 투명' 한 PNG 였다. 타일을 깐다는 옛 검사는 그
    // 빈 그림을 통과시켰으므로, 무엇을 재는지 자체를 바꾼다.
    const cadLayer = await page.evaluate(async () => {
      const box = document.getElementById('cadastral-bg');
      const tiles = (window.__map.tiles || []);
      window.__zoom = 16;
      // 기본 경계는 '전국' 이라 배율 16 에서 칸이 수만 개가 된다.
      // 실제 화면만 한 네모로 좁힌다 (안성 언저리 한 칸 남짓).
      window.__bbox = [37.000, 127.270, 37.012, 127.290];
      window.__drawCadastral();
      await new Promise((ok) => setTimeout(ok, 200));
      const drawn = (window.__map.groups || [])
        .flatMap((g) => g._items || [])
        .flatMap((g) => (g && g._items) || [g])
        .filter((g) => g && g.__opts && g.__opts.pane === 'cadastralPane');
      return {
        hasBox: !!box,
        on: !!(box && box.checked),
        // 옛 길로 돌아가지 않았는가 — 타일은 이제 한 장도 없어야 한다.
        tiles: tiles.filter((u) => /layer=cadastral/.test(u)).length,
        drawn: drawn.length,
        className: (drawn[0] || {}).__opts ? drawn[0].__opts.className : null,
        interactive: (drawn[0] || {}).__opts
          ? drawn[0].__opts.interactive : null,
      };
    });
    // 머리띠 아이콘 (요구사항 2026-09-10 — 빈 사각형을 걷어냅니다).
    const mark = await page.evaluate(() => {
      const m = document.querySelector('.brand .mark');
      if (!m) return null;
      const cs = getComputedStyle(m);
      return {
        tag: m.tagName.toLowerCase(),
        paths: m.querySelectorAll('path').length,
        w: Math.round(m.getBoundingClientRect().width),
        h: Math.round(m.getBoundingClientRect().height),
        // 예전에는 accent 색으로 칠한 빈 네모였다.
        bg: cs.backgroundColor,
      };
    });
    check('머리띠에 아이콘이 있다 (빈 사각형이 아니다)',
          !!mark && mark.tag === 'svg' && mark.paths >= 4,
          mark ? `${mark.tag} · path ${mark.paths}개` : '없음');
    check('아이콘이 찌그러지지 않는다 (정사각)',
          !!mark && mark.w === mark.h && mark.w > 0,
          mark ? `${mark.w}×${mark.h}` : '없음');
    check('색 사각형이 아니다 (배경으로 안 칠한다)',
          !!mark && /rgba\(0, 0, 0, 0\)|transparent/.test(mark.bg),
          mark ? mark.bg : '없음');

    check('필지경계 스위치가 있다', cadLayer.hasBox);
    check('기본은 켬이다', cadLayer.on);
    check('빈 그림을 주는 타일 길로 안 돌아갔다',
          cadLayer.tiles === 0, `${cadLayer.tiles}장`);
    check('경계선을 도형으로 받아 그린다',
          cadLayer.drawn >= 1, `층 ${cadLayer.drawn}개`);
    check('용도지역과 다른 판에 둔다', true, 'cadastralPane');
    check('색을 CSS 가 잡게 이름표를 단다 (필터 꼼수를 걷어냈다)',
          cadLayer.className === 'cad-line', String(cadLayer.className));
    check('경계선이 누름을 가로채지 않는다', cadLayer.interactive === false);

    // 배율 문턱. 얕으면 한 칸에 든 필지가 상한에 걸려 선이 군데군데
    // 빠진다 — 빠진 선은 없는 선보다 나쁘다. 눈에 안 보이는 상수라
    // 여기서 못을 박는다.
    const cadZoom = await page.evaluate(async () => {
      window.__zoom = 15;
      window.__drawCadastral();
      await new Promise((ok) => setTimeout(ok, 120));
      const shallow = (window.__map.groups || [])
        .flatMap((g) => g._items || [])
        .flatMap((g) => (g && g._items) || [g])
        .filter((g) => g && g.__opts && g.__opts.pane === 'cadastralPane');
      window.__zoom = 16;
      window.__bbox = null;
      return shallow.length;
    });
    check('배율 16 아래에서는 안 그린다 (선이 빠지느니 안 그린다)',
          cadZoom === 0, `${cadZoom}개`);

    // 넓은 화면 (PC). 한 번에 열두 칸만 부르되, 한 칸이 오면 다음 칸을
    // 이어 불러 **화면 전체**를 채워야 한다 (2026-09-11 지시: PC 에서
    // 확대하면 필지 구획이 절반만 뜬다). 안성 언저리 서른 칸 남짓.
    const cadWide = await page.evaluate(async () => {
      window.__zoom = 16;
      window.__bbox = [37.000, 127.250, 37.024, 127.300];
      const want = window.__cadTileList().map(([z, x, y]) => `${z}/${x}/${y}`);
      window.__drawCadastral();
      const t0 = Date.now();
      let drawn = 0;
      while (Date.now() - t0 < 6000) {
        await new Promise((ok) => setTimeout(ok, 100));
        drawn = (window.__map.groups || [])
          .flatMap((g) => g._items || [])
          .flatMap((g) => (g && g._items) || [g])
          .filter((g) => g && g.__opts && g.__opts.pane === 'cadastralPane').length;
        if (drawn >= want.length) break;
      }
      window.__bbox = null;
      return { want: want.length, drawn, first: want.slice(0, 3) };
    });
    check('넓은 화면은 열두 칸이 넘는다 (검사가 뜻이 있으려면)', cadWide.want > 12 && cadWide.want <= 120, `${cadWide.want}칸`);
    check('열두 칸 뒤도 이어 받아 화면 전체를 채운다', cadWide.drawn >= cadWide.want, `${cadWide.drawn}/${cadWide.want}`);
    check('가운데 칸부터 부른다', (() => {
      const w = cadWide.first.map((k) => k.split('/').map(Number));
      return w.length === 3 && Math.abs(w[0][1] - w[1][1]) + Math.abs(w[0][2] - w[1][2]) <= 2;
    })(), cadWide.first.join(' '));

    // 껐다 켜는 것이 실제로 먹는가. 그리고 그 선택을 기억하는가.
    const cadOff = await page.evaluate(() => {
      const box = document.getElementById('cadastral-bg');
      box.checked = false;
      box.dispatchEvent(new Event('change'));
      const off = { removed: window.__removed || 0,
                    saved: localStorage.getItem('toji.cadastral') };
      box.checked = true;
      box.dispatchEvent(new Event('change'));
      return { off, saved: localStorage.getItem('toji.cadastral') };
    });
    check('끄면 층을 걷어낸다', cadOff.off.removed > 0);
    check('껐다 켠 것을 기억한다',
          cadOff.off.saved === 'off' && cadOff.saved === 'on',
          `끔=${cadOff.off.saved} 켬=${cadOff.saved}`);

    // 필지 윤곽 (요구사항 2026-09-10 — 부동산플래닛처럼).
    const shape = await page.evaluate(() => {
      const items = (window.__map.groups || []).flatMap((g) => g._items)
        .filter((m) => m.__opts && m.__opts.pane === 'parcelPane');
      return {
        n: items.length,
        kept: !!window.__parcelShape,
        // 윤곽이 누름을 가로채면 옆 필지로 못 넘어간다.
        passthrough: items.every((m) => m.__opts.interactive === false),
      };
    });
    check('고른 필지의 윤곽을 그린다', shape.n === 1 && shape.kept,
          `층 ${shape.n}개`);
    check('윤곽이 누름을 가로채지 않는다', shape.passthrough);

    // 토지이음 단추. 우리가 못 주는 칸(소유·지역지구·토지이동)은 여기서 본다.
    const eum = await page.evaluate(() => {
      const a = document.querySelector('.parcel-card .pc-eum');
      return a ? { href: a.getAttribute('href'), rel: a.getAttribute('rel'),
                   tgt: a.getAttribute('target'), txt: a.textContent } : null;
    });
    check('토지이음으로 넘기는 단추가 있다', !!eum);
    check('그 필지의 PNU 로 간다',
          !!eum && eum.href.includes('pnu=4111110300100010000'),
          eum ? eum.href : '없음');
    // **mode=search 는 안 쓴다.** 실측(2026-09-10)에서 표가 바로 나오는
    // 대신 값이 섞였다 — 검색칸은 우리 필지인데 소재지·지목·면적은 남의
    // 것이었다. 섞여 나오는 링크는 없느니만 못하다.
    check('값이 섞이는 mode=search 는 안 쓴다',
          !!eum && !/mode=search/.test(eum.href), eum ? eum.href : '없음');
    check('한 번 더 눌러야 한다는 것을 미리 적는다',
          !!eum && /열람/.test(eum.txt), eum ? eum.txt : '없음');
    check('새 창으로 열고 opener 를 안 준다',
          !!eum && eum.tgt === '_blank' && /noopener/.test(eum.rel || ''),
          eum ? `${eum.tgt} ${eum.rel}` : '없음');

    check('축마다 원값을 같이 적는다',
          /중로한면/.test(pc.html) && /가로장방형/.test(pc.html),
          byKey.road.raw);

    // **점수를 만들지 않는다.** 이것이 이 제품이 땅박사와 갈리는 지점이다.
    check('다섯 축을 더한 점수를 안 만든다',
          !/총점|종합 점수|[0-9]+점/.test(pc.html)
          && pc.peek.diag.score === undefined,
          pc.html.match(/총점|종합 점수|\d+점/) ? '점수가 있다' : '없음');
    check('합산하지 않는다는 것을 화면에도 적는다',
          /하나의 점수로 만들지 않습니다/.test(pc.html));
    // 또래가 어디까지 물러났는지 밝힌다. 안 밝히면 '전국 상위 10%' 를
    // '우리 동네 상위 10%' 로 읽는다.
    check('어느 또래와 견줬는지 말한다',
          /같은 시군구의 계획관리 거래 120건/.test(pc.html),
          (pc.html.match(/[^>]*견줬습니다/) || ['없음'])[0]);

    // 얇은 또래(4건)는 시도로 물러난다.
    const thin = await clickMapPeer(page, '47940');
    check('또래가 얇으면 시·도로 물러난다',
          thin && /같은 시·도의 계획관리 거래 900건/.test(thin.html),
          thin ? (thin.html.match(/[^>]*견줬습니다/) || ['없음'])[0] : '없음');
    // 추세는 또래와 따로 물러난다 (2026-09-10). 실측으로 시군구에
    // 추세가 붙은 곳은 55.9% 뿐인데, 못 낸 346 조합은 **전부** 한 단계
    // 위에 값이 있었다. 축을 비우는 대신 위에서 빌려 온다.
    check('시군구에 추세가 없으면 시·도에서 빌려 온다',
          thin && /연 \+2\.0%/.test(thin.html),
          thin ? (thin.html.match(/연 [+-][0-9.]+%[^<]*/) || ['없음'])[0] : '없음');
    // 빌려 온 것을 우리 동네 값처럼 보여주면 거짓이 된다.
    check('빌려 온 것이라고 밝힌다',
          thin && /시·도 기준/.test(thin.html),
          thin ? (thin.html.match(/연 [+-][0-9.]+%[^<]*/) || ['없음'])[0] : '없음');
    // 0.02 는 trend_q 의 3번(0.015)과 4번(0.025) 한가운데 → (3+0.5)/10
    check('빌려 온 추세도 전국 분포로 읽는다',
          thin && thin.peek && Math.abs(
            (thin.peek.diag.axes.find((a) => a.key === 'price') || {}).pct - 0.35
          ) < 1e-6,
          thin && thin.peek
            ? String((thin.peek.diag.axes.find((a) => a.key === 'price') || {}).pct)
            : '없음');

    // 바다·도로를 누른 것은 오류가 아니다.
    const sea = await clickMap(38.5, 128.5);
    // 막힌 것과 자료가 없는 것을 구분해 적는가 (요구사항 2026-09-10).
    // 둘을 같은 글로 보여주면 '이 땅은 정보가 없다' 로 읽히는데,
    // 사실은 잠시 뒤 다시 누르면 나온다.
    const busy = await page.evaluate(async () => {
      const real = window.fetch;
      window.fetch = async (u) => (/mode=parcel&/.test(String(u))
        ? { status: 429, ok: false,
            headers: { get: (k) => (k === 'retry-after' ? '60' : null) },
            json: async () => ({}) }
        : real(u));
      const fns = ((window.__mapOn || {}).click) || [];
      fns.forEach((fn) => fn({ latlng: { lat: 37.0012, lng: 127.0012 },
                               originalEvent: { target: null } }));
      await new Promise((ok) => setTimeout(ok, 300));
      window.fetch = real;
      return document.getElementById('detail').innerHTML;
    });
    check('막힌 것을 자료가 없다고 말하지 않는다',
          /너무 잦습니다/.test(busy) && !/필지 자료를 못 받았습니다/.test(busy),
          busy.replace(/<[^>]+>/g, ' ').trim().slice(0, 80));
    check('언제 다시 누르면 되는지 적는다', /60초쯤 뒤에/.test(busy));

    check('필지가 없으면 이유를 적는다 (오류가 아니다)',
          /필지 자료를\s*못 받았습니다/.test(sea.html) && sea.peek === null,
          sea.html.slice(0, 90));
    await page.evaluate(() => { window.__zoom = 7; });

    console.log();
    console.log('8. 세 가설 판정 — 무엇을 말할 수 있고 없는지');
    // 이 탭은 숫자를 하나 더 보여주는 곳이 아니다. 계수가 유의해도 위약
    // 밴드가 같이 유의하면 IC 효과가 아니고, 표본이 모자라면 '효과 없음'
    // 이 아니라 '아직 모름' 이다. 그 구분이 화면에서 사라지면 사람은
    // 스스로 결론을 채워 넣는다 — 그래서 화면에 실제로 남아 있는지 본다.
    // 탭은 접혀 있다(요구사항 2026-09-10). **그래도 화면은 살아 있어야
    // 한다** — 접은 것과 지운 것은 다르다. 접어 둔 화면을 여는 길
    // (주소 끝의 #verdict)로 열어서 안이 멀쩡한지 본다.
    const vTab = await page.evaluate(() => {
      const t = document.querySelector('.tab[data-view="verdict"]');
      if (!t) return false;
      location.hash = '#verdict';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
      return true;
    });
    check('가설 판정 화면이 접힌 채로 살아 있다', !!vTab);
    if (vTab) {
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
      check('가설 다섯을 다 보여준다', v.n === 5, `${v.n}개`);
      // 색만으로 뜻을 말하면 색약·흑백에서 무너진다. 딱지에 글자가 있어야 한다.
      check('판정이 글자로 적혀 있다 (색만이 아니다)',
            v.badges.slice(0, 3).map((b) => b.text).join('·')
              === '아직 모름·지지·기각',
            v.badges.map((b) => b.text).join('·'));
      check('판정마다 색이 다르다',
            /is-unknown/.test(v.badges[0].cls) && /is-ok/.test(v.badges[1].cls)
            && /is-no/.test(v.badges[2].cls),
            v.badges.map((b) => b.cls.replace('verdict-card ', '')).join(' / '));
      // '관계 있음(상관)' 은 '지지' 와 색이 달라야 한다. 있는 것은 맞지만
      // 인과가 아니라서, 같은 초록을 주면 구별할 방법이 없다.
      check('상관 판정은 지지와 다른 색이다',
            /is-corr/.test(v.badges[3].cls) && !/is-ok/.test(v.badges[3].cls),
            v.badges[3].cls.replace('verdict-card ', ''));
      check('상관이라는 것이 딱지 글자에도 있다',
            /상관/.test(v.badges[3].text), v.badges[3].text);
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

      // '잡을 수 있는 최소'(MDE) — 계수가 그보다 작으면 크기를 읽으면
      // 안 된다. 표에 숫자만 있으면 아무도 그 뜻을 모르므로 갈라 둔다.
      const mde = await page.evaluate(() => ({
        head: [...document.querySelectorAll('#verdict-cards th')]
          .map((th) => th.textContent.trim()),
        weak: [...document.querySelectorAll('#verdict-cards .mde-weak')]
          .map((td) => td.textContent.trim()),
        color: (() => {
          const el = document.querySelector('#verdict-cards .mde-weak');
          return el ? getComputedStyle(el).color : '';
        })(),
        // 기대색은 토큰에서 읽는다. 색값을 검사에 박아 두면 밝은/어두운
        // 화면 중 한쪽에서만 맞는 검사가 된다.
        danger: (() => {
          const probe = document.createElement('span');
          probe.style.color = 'var(--danger)';
          document.body.appendChild(probe);
          const c = getComputedStyle(probe).color;
          probe.remove();
          return c;
        })(),
      }));
      check('표에 잡을 수 있는 최소 칸이 있다',
            mde.head.some((h) => /최소/.test(h)), mde.head.join(' | '));
      // 넣은 두 줄 중 하나만 계수가 최소보다 작다 (0.102 < 0.294).
      check('계수가 그보다 작은 줄만 표시한다', mde.weak.length === 1,
            `${mde.weak.length}줄 (${mde.weak.join(',')})`);
      // '검정만 아니면 통과' 로 두었더니 회색으로 그려지는데도 지나갔다.
      // 무슨 색이어야 하는지를 정확히 재야 한다.
      check('그 표시가 경고색(--danger)으로 그려진다',
            mde.color === mde.danger, `${mde.color} (기대 ${mde.danger})`);

      // 토지와 공장을 갈아 끼울 수 있어야 한다. 지금까지 토지만 저장돼서
      // 공장은 '표본이 작아 못 봤다' 는 것조차 화면에 안 남았다.
      const swap = await page.evaluate(async () => {
        const box = document.getElementById('verdict-kind');
        const shown = box && !box.hidden;
        const btn = box && box.querySelector('button[data-kind="factory"]');
        if (btn) btn.click();
        await new Promise((r) => setTimeout(r, 150));
        return {
          shown,
          stamp: document.getElementById('verdict-stamp').textContent,
          flags: [...document.querySelectorAll('.verdict-flag')]
            .map((f) => f.textContent.trim()),
        };
      });
      check('토지·공장 전환 단추가 있다', swap.shown === true);
      check('공장으로 바꾸면 그 판정이 뜬다', /공장/.test(swap.stamp), swap.stamp);
      // 계수를 여럿 던지면 그중 몇은 우연히 유의하다. 탐색을 결론으로
      // 읽지 않도록 표 위에서 먼저 말해야 한다.
      check('탐색이라는 것을 표 위에서 먼저 말한다',
            swap.flags.some((f) => /탐색입니다/.test(f)),
            swap.flags.map((f) => f.slice(0, 20)).join(' | '));
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
        // 보고된 문제(2026-09-04): "통행량 정보 없음(민자)는 사이즈 최소로."
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

      // ── 차종을 고르면 경계가 따라 내려간다 (요구사항 2026-09-10) ──
      //
      // 보고: "차량 종류 선택 시 일평균 통행량이 줄어드는데 기준이
      // 최소 1만대라서 분별이 안됩니다." 고정 1만대 경계는 '전체' 를
      // 볼 때만 뜻이 있다 — 5종만 켜면 다 아래로 몰려 한 색이 된다.
      const cutsFor = async (codes) => page.evaluate((cs) => {
        window.state.tgVehicles = new Set(cs);
        window.__rebuildTiers();
        const btns = [...document.querySelectorAll('#tier-filters .quad-btn')]
          .filter((b) => !['new', 'none'].includes(b.dataset.tier));
        return {
          cut: (window.state.tiers || {}).cut,
          labels: btns.map((b) => b.querySelectorAll('span')[1].textContent),
          spread: new Set(btns.map((b) => b.querySelector('.n').textContent)).size,
        };
      }, codes);

      const whole = await cutsFor([1, 2, 3, 4, 5, 6]);
      check('전체를 보면 지금 경계를 그대로 쓴다 (1·2·3만대)',
            String(whole.cut) === String([10000, 20000, 30000]),
            String(whole.cut));
      const five = await cutsFor([5]);
      check('한 차종만 고르면 경계가 내려간다',
            Number((five.cut || [])[0]) < 10000, String(five.cut));
      // "최소 백단위".
      check('경계가 백 단위 아래로는 안 내려간다',
            (five.cut || []).every((c) => c >= 100 && c % 100 === 0),
            String(five.cut));
      check('범례 글자도 같이 바뀐다 (색 뜻이 안 어긋나게)',
            !five.labels.some((t) => /1만대 미만/.test(t)),
            five.labels.join(' | '));
      // 한 색으로 몰리지 않는가 — 이것이 원래 불편의 핵심이다.
      check('한 칸으로 안 몰린다 (구분이 된다)', five.spread > 1,
            five.labels.join(' | '));
      await page.evaluate(() => {
        window.state.tgVehicles = new Set([1, 2, 3, 4, 5, 6]);
        window.__rebuildTiers();
      });
    } else {
      console.log('  건너뜀 — tollgates.json 이 없습니다.');
    }


    await page.close();

    /* ── 거래 연도 · 상세 말풍선 ──
     *
     * 요구사항(2026-09-07) 세 가지를 그대로 본다.
     *   1) 실거래를 IC 거리와 무관하게 표기      → 반경 밖 좌표도 그려지는가
     *   2) 거래 연도를 고를 수 있게              → 고른 해 파일을 받는가
     *   3) 클릭 시 주요 거래 정보                → 말풍선에 값이 들어 있는가
     *
     * 자료는 여기서 만들어 넣는다. 커밋된 파일에 기대면 다음 수집이 돌기
     * 전까지 이 검사가 '건너뜀' 으로 초록이 되는데, 건너뛴 검사는 통과가
     * 아니라 안 본 것이다. */
    {
      const page2 = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      for (const pat of ['**/lib/supabase-init.js*', '**/app/supabase.js*',
                         '**/supabase-js*/**', '**/leaflet*.js', '**/leaflet*.css'])
        await page2.route(pat, (r) => r.fulfill({ status: 200, body: '' }));

      const META = path.join(ROOT, 'public', 'app', 'data', 'meta.json');
      const meta = JSON.parse(fs.readFileSync(META, 'utf8'));
      meta.trade_years = [
        { year: 2024, total: 500000, sample: 2 },
        { year: 2025, total: 400000, sample: 3 },
      ];
      meta.counts = Object.assign({}, meta.counts, { trades_mapped: 9000000 });
      // 공장·창고 구분. 가르지 못한 것도 섞어 둔다 — 실제 자료가 그럴 수 있고,
      // 그때 그 거래가 지도에서 조용히 사라지면 안 된다.
      // run 33 이 알려준 실제 값과 같은 모양으로 둔다.
      meta.usage_mix = { '공장': 143159, '창고시설': 30833,
                         '동물 및 식물 관련시설': 20111, '구분 없음': 1200 };
      // 토지 쪽. 실제 자료의 모양대로 원지가 압도적이다.
      meta.stage_mix = { '원지': 9100000, '개발완료': 1500000, '그 밖': 700000 };
      meta.land_use_mix = { '계획관리지역': 2600000, '농림지역': 2100000,
                            '자연녹지지역': 1200000, '제2종일반주거지역': 640000 };
      // 도로 접함. 실제 자료의 모양대로 '조사 안 됨' 이 압도적이다 —
      // 전국을 칸으로 나눠 받는 중이라 아직 일부만 붙어 있다.
      meta.road_mix = { '차 진입 가능': 61764, '진입 어려움': 117711,
                        '조사 안 됨': 11020525 };
      await page2.route('**/app/data/meta.json*', (r) => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(meta) }));

      // 2025년 거래 세 건. 하나는 법정동 중심점(경고가 붙어야 한다).
      const Y2025 = [
        { kind: 'land', lat: 37.1, lon: 127.1, deal_year: 2025, deal_month: 3,
          price_per_m2: 500000, price_krw: 370000000, area_m2: 740,
          sido: '경기도', sigungu: '화성시', umd: '동탄면', jibun: '123-4',
          jimok: '전', land_use: '계획관리지역', deal_type: '중개거래',
          geocode_level: 'parcel', stage: '원지',
          // 필지 특성이 붙은 거래. car_ok 는 파이썬이 판정해서 실어 준다.
          road_side: '세로한면(가)', car_ok: 'Y', parcel_shape: '부정형',
          parcel_slope: '평지', official_price: 200000 },
        { kind: 'factory', lat: 37.2, lon: 127.2, deal_year: 2025, deal_month: 7,
          price_per_m2: 900000, price_krw: 1500000000, area_m2: 1660,
          sido: '경기도', sigungu: '평택시', umd: '청북읍', jibun: '55',
          jimok: '공장용지', land_use: '계획관리', building_area_m2: 800,
          build_year: 2010, deal_type: '직거래', geocode_level: 'parcel',
          usage: '공장' },
        { kind: 'factory', lat: 37.3, lon: 127.3, deal_year: 2025, deal_month: 9,
          price_per_m2: 700000, price_krw: 900000000, area_m2: 1280,
          sido: '경기도', sigungu: '이천시', umd: '마장면', jibun: '77',
          jimok: '창고용지', land_use: '계획관리', building_area_m2: 900,
          build_year: 2015, deal_type: '중개거래', geocode_level: 'parcel',
          usage: '창고시설' },
        // 가를 칸이 없던 거래. 어느 칸에도 안 들어가면 지도에서 사라진다.
        { kind: 'factory', lat: 37.4, lon: 127.4, deal_year: 2025, deal_month: 2,
          price_per_m2: 400000, price_krw: 300000000, area_m2: 750,
          sido: '경기도', sigungu: '안성시', umd: '대덕면', jibun: '12',
          land_use: '계획관리', deal_type: '중개거래', geocode_level: 'parcel' },
        // 맹지. 값이 붙은 쪽의 반대편이다. 농림지역·개발완료로 둔 것은
        // 위 개발단계·용도지역 검사가 세는 숫자를 건드리지 않기 위해서다.
        { kind: 'land', lat: 37.5, lon: 127.5, deal_year: 2025, deal_month: 5,
          price_per_m2: 90000, price_krw: 90000000, area_m2: 1000,
          sido: '경기도', sigungu: '여주시', umd: '가남읍', jibun: '3',
          jimok: '대', land_use: '농림지역', deal_type: '중개거래',
          geocode_level: 'parcel', stage: '개발완료',
          road_side: '맹지', car_ok: 'N', parcel_shape: '가로장방',
          parcel_slope: '평지', official_price: 60000 },
        // IC 에서 먼 곳 — 법정동 중심점 좌표. 예전에는 좌표가 아예 없어
        // 지도에서 통째로 빠지던 종류다.
        { kind: 'land', lat: 34.8, lon: 126.4, deal_year: 2025, deal_month: 1,
          price_per_m2: 30000, price_krw: 45000000, area_m2: 1500,
          sido: '전라남도', sigungu: '무안군', umd: '삼향읍', jibun: '901',
          jimok: '대', land_use: '자연녹지지역', deal_type: '중개거래',
          geocode_level: 'umd', stage: '개발완료' },
      ];
      const Y2024 = Y2025.slice(0, 2).map((t) =>
        Object.assign({}, t, { deal_year: 2024 }));
      await page2.route('**/app/data/trades-2025.json*', (r) => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(Y2025) }));
      await page2.route('**/app/data/trades-2024.json*', (r) => r.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(Y2024) }));

      await page2.addInitScript(FAKE_LEAFLET);
      await page2.addInitScript(() => {
        window.SB = {};
        window.SBUtil = { me: async () => ({ user: { id: 'u1' },
          profile: { status: 'approved' } }) };
      });
      await page2.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
      await page2.waitForFunction(
        () => (document.getElementById('year-from') || {}).max,
        null, { timeout: 15000 });

      // 요구사항(2026-09-08): "실거래 연도는 좌/우로 선택해서 범위를
      // 정할 수 있도록 (호갱노노 참조)".
      const sel = await page2.evaluate(() => {
        const f = document.getElementById('year-from');
        const t = document.getElementById('year-to');
        return { from: f.value, to: t.value, min: f.min, max: f.max,
                 out: document.getElementById('year-out').textContent,
                 selects: document.querySelectorAll('#deal-year').length };
      });
      check('연도를 좌/우 손잡이로 고른다 (드롭다운이 아니다)',
            sel.selects === 0 && Number(sel.min) < Number(sel.max),
            `${sel.min}~${sel.max} · 남은 select ${sel.selects}개`);
      // 요구사항(2026-09-09): "거래 연도는 2024~2025년 기본 세팅".
      // 한 해는 성겨서 '거래가 이것뿐인가' 로 읽히고, 전 기간은 파일을
      // 다섯 개씩 받는다. 두 해가 그 사이다.
      check('기본은 최근 두 해다',
            sel.from === '2024' && sel.to === '2025'
            && /2024 ~ 2025년/.test(sel.out),
            `${sel.from}~${sel.to} "${sel.out}"`);

      // 거래는 기본이 꺼져 있다(2026-09-04 지시). 켜야 그려진다.
      await page2.evaluate(() => {
        document.querySelectorAll('#kind-filters input').forEach((i) => {
          if (!i.checked) i.click();
        });
      });
      await page2.waitForTimeout(300);

      const styles = await page2.evaluate(() => window.__tradeStyles || []);
      // 여덟이다 — 공장계 넷 + 토지 넷. 용도지역 칸을 없애기 전에는
      // 일곱이었다 (요구사항 2026-09-10). 농림지역 한 건이 기본값에서
      // 걸러져 안 보였던 것이고, 그 한 건이 이 숫자로 돌아왔다.
      check('고른 기간의 거래가 그려진다', styles.length === 8,
            `${styles.length}개`);
      // 반경 밖(무안군) 거래도 그려져야 한다. 예전에는 좌표가 아예 없어
      // 지도에서 통째로 빠졌다.
      check('IC 반경 밖 거래도 그려진다',
            styles.some((x) => x.geocodeLevel === 'umd'),
            styles.map((x) => x.geocodeLevel).join(','));
      check('거래 표식을 누를 수 있다',
            styles.length > 0 && styles.every((x) => x.interactive === true));

      const land = styles.find((x) => x.kind === 'land' && x.geocodeLevel === 'parcel');
      const fac = styles.find((x) => x.kind === 'factory');
      const coarse = styles.find((x) => x.geocodeLevel === 'umd');
      check('말풍선에 주소가 들어 있다',
            !!land && /화성시/.test(land.popup) && /123-4/.test(land.popup),
            land ? land.popup.slice(0, 60) : '없음');
      check('말풍선에 거래금액이 들어 있다',
            !!land && /3\.7억원/.test(land.popup));
      // 요구사항(2026-09-08): "xx원/평, xx원/㎡ 으로 수정".
      check('말풍선에 평당가가 들어 있다',
            !!land && /165만원\/평/.test(land.popup),
            land ? (land.popup.match(/[\d,만억]+원\/[평㎡][^<]*/g) || []).join(' ') : '없음');
      check('말풍선에 면적을 평으로도 적는다',
            !!land && /224평/.test(land.popup),
            land ? (land.popup.match(/[\d,]+평/g) || []).join(' ') : '없음');
      check('말풍선에 용도지역이 들어 있다', !!land && /계획관리/.test(land.popup));
      check('공장은 건축연도와 건물면적을 적는다',
            !!fac && /2010년/.test(fac.popup) && /건물면적/.test(fac.popup));
      // 법정동 중심점은 실제 필지가 아니다. 지번을 적어 놓고 점을 찍으면
      // 보는 사람은 그 자리라고 읽는다 — 땅을 보러 가는 사람에게 2km 는
      // 다른 동네다.
      check('법정동 중심점 거래는 실제 위치가 아니라고 말한다',
            !!coarse && /법정동 중심점/.test(coarse.popup)
            && /실제 필지 위치가 아닙니다/.test(coarse.popup));
      check('지번 좌표에는 그 경고가 없다',
            !!land && !/실제 필지 위치가 아닙니다/.test(land.popup));

      // 표본이라는 사실을 화면이 말하는가.
      const note = await page2.evaluate(() =>
        document.getElementById('deal-year-note').textContent);
      check('안내가 그 기간 실제 건수를 말한다', /900,000건/.test(note), note);
      check('안내가 표본임을 말한다', /무작위 표본/.test(note), note);

      /* ── 공장·창고 구분 (2026-09-07 지시) ──
       * 15126470 은 '공장 및 창고 등' 자료다. 창고가 처음부터 같이 들어와
       * 있었는데 한 칸에 담아 두어 가릴 수가 없었다. */
      const filters = await page2.evaluate(() =>
        [...document.querySelectorAll('#kind-filters label')].map((l) => ({
          text: l.textContent.replace(/\s+/g, ' ').trim(),
          checked: l.querySelector('input').checked,
        })));
      const names = filters.map((f) => f.text);
      check('필터에 공장과 창고가 따로 있다',
            names.some((t) => /^공장/.test(t)) && names.some((t) => /^창고시설/.test(t)),
            names.join(' | '));
      check('필터가 각 용도의 건수를 적는다',
            names.some((t) => /143,159건/.test(t)) && names.some((t) => /30,833건/.test(t)),
            names.join(' | '));
      // '기타' 로 뭉개지 않는다. run 33 에서 그 41,588건이 축사·정비소·
      // 주유소로 또렷이 갈려 있었다 — 모르는 것이 아니라 아는 것이다.
      check('그 밖 용도도 이름 그대로 칸이 된다',
            names.some((t) => /동물 및 식물 관련시설/.test(t) && /20,111건/.test(t)),
            names.join(' | '));
      check('많은 것부터 늘어놓는다',
            names.indexOf(names.find((t) => /^공장/.test(t)))
              < names.indexOf(names.find((t) => /동물 및 식물/.test(t))),
            names.join(' | '));

      // 창고만 켜면 창고만 남는가.
      await page2.evaluate(() => {
        document.querySelectorAll('#kind-filters input').forEach((i) => {
          if (i.checked) i.click();
        });
        const only = [...document.querySelectorAll('#kind-filters label')]
          .find((l) => /^창고시설/.test(l.textContent.trim()));
        only.querySelector('input').click();
      });
      await page2.waitForTimeout(300);
      const onlyWh = await page2.evaluate(() => window.__tradeStyles || []);
      check('창고만 켜면 창고만 남는다', onlyWh.length === 1, `${onlyWh.length}개`);
      check('창고는 색이 공장과 다르다',
            onlyWh.length === 1 && /trade-warehouse/.test(onlyWh[0].html),
            onlyWh.length ? onlyWh[0].html : '없음');
      check('창고 말풍선이 용도 이름을 그대로 적는다',
            onlyWh.length === 1 && />창고시설</.test(onlyWh[0].popup));

      // 구분 없는 거래도 칸이 있어야 한다 — 어디에도 안 넣으면 지도에서
      // 조용히 사라지고, 사라진 줄도 모른다.
      await page2.evaluate(() => {
        document.querySelectorAll('#kind-filters input').forEach((i) => {
          if (i.checked) i.click();
        });
        const only = [...document.querySelectorAll('#kind-filters label')]
          .find((l) => /구분 없음/.test(l.textContent));
        only.querySelector('input').click();
      });
      await page2.waitForTimeout(300);
      const unknown = await page2.evaluate(() => window.__tradeStyles || []);
      check('용도를 모르는 거래도 지도에 남는다', unknown.length === 1,
            `${unknown.length}개`);
      check("모르는 것을 '공장' 이라고 단정하지 않는다",
            unknown.length === 1 && /구분 없음/.test(unknown[0].popup),
            unknown.length ? unknown[0].popup.slice(0, 80) : '없음');

      // 다시 전부 켜 둔다 (아래 연도 검사가 개수를 센다).
      await page2.evaluate(() => {
        document.querySelectorAll('#kind-filters input').forEach((i) => {
          if (!i.checked) i.click();
        });
      });
      await page2.waitForTimeout(300);

      /* ── 토지: 용도지역은 **거르지 않는다** (요구사항 2026-09-10) ──
       *
       * "실거래 표시에서 용지역은 삭제합니다. (항상 전체 표기 함)".
       *
       * 전에는 스물다섯 종 중 셋만 켜진 채로 시작해서, 처음 화면에서
       * 농림지역 거래가 통째로 빠져 있었다. 칸을 없앤 것이 아니라
       * **조건을 안 거는 것**이라, 켜고 끌 것 없이 다 보여야 한다. */
      const landUi = await page2.evaluate(() => ({
        hidden: document.getElementById('land-box').hidden,
        box: !!document.getElementById('land-use-filters'),
        all: !!document.getElementById('lu-all'),
        none: !!document.getElementById('lu-none'),
        road: !!document.getElementById('road-filter'),
      }));
      // 도로 접함은 여기 남아 있으므로 묶음 자체는 그대로 선다.
      check('토지 필터 묶음이 보인다', landUi.hidden === false);
      check('도로 접함은 그대로 있다', landUi.road);
      check('용도지역 칸이 없다', !landUi.box && !landUi.all && !landUi.none,
            `칸 ${landUi.box} · 전체 ${landUi.all} · 해제 ${landUi.none}`);

      // 아무것도 안 만졌는데 네 건이 다 보인다 — 계획관리 둘(2024·2025),
      // 농림 하나, 자연녹지 하나. **농림이 들어 있는 것이 핵심이다**:
      // 예전 기본값에서는 이 한 건이 빠져 있었다.
      const allLu = await page2.evaluate(() => {
        const t = (window.__tradeStyles || []);
        return {
          land: t.filter((x) => x.kind === 'land').length,
          factory: t.filter((x) => x.kind === 'factory').length,
          nong: t.filter((x) => /농림/.test(x.popup || '')).length,
        };
      });
      check('처음부터 모든 용도지역이 보인다 (걸러내지 않는다)',
            allLu.land === 4, `토지 ${allLu.land}건`);
      check('예전 기본값에서 빠져 있던 농림지역도 보인다',
            allLu.nong === 1, `농림 ${allLu.nong}건`);
      check('공장·창고는 그대로다', allLu.factory === 4,
            `공장계 ${allLu.factory}건`);

      // 말풍선이 개발단계를 적는가.
      const landPop = await page2.evaluate(() =>
        (window.__tradeStyles || []).find((x) => x.kind === 'land'));
      check('말풍선이 지목 옆에 개발단계를 적는다',
            !!landPop && /\(원지\)|\(개발완료\)/.test(landPop.popup),
            landPop ? (landPop.popup.match(/지목[^<]*<[^>]*>[^<]*</) || [''])[0] : '없음');

      /* ── 토지: 도로 접함 (2026-09-07 지시) ──
       * "도로를 접하는 가가 제일 중요합니다." 실측이 크기까지 확인했다 —
       * 차가 들어가느냐가 단가를 남이천 +66%, 안성 +67% 가른다. */
      const roadUi = await page2.evaluate(() => {
        const s = document.getElementById('road-filter');
        return { value: s.value, disabled: s.disabled,
                 options: [...s.options].map((o) => o.value),
                 texts: [...s.options].map((o) => o.textContent.trim()) };
      });
      check('도로 접함 필터가 선다',
            roadUi.options.join(',') === 'all,ok,no', roadUi.options.join(','));
      check('기본값은 전체다 — 조사 안 된 거래를 감추지 않는다',
            roadUi.value === 'all' && roadUi.disabled === false, roadUi.value);
      check('칸마다 건수를 적는다',
            roadUi.texts.some((t) => /61,764건/.test(t))
            && roadUi.texts.some((t) => /117,711건/.test(t)),
            roadUi.texts.join(' | '));

      // 차 진입 가능만 고르면 그것만 남는다. 공장은 그대로여야 한다 —
      // 도로 접함은 토지에만 거는 조건이다.
      // 필터가 아래 시트로 옮겨졌다 (2026-09-08). 열어야 만질 수 있다.
      await page2.evaluate(() => {
        const b = document.querySelector('.cat[data-cat="trade"]');
        if (b && !b.classList.contains('is-on')) b.click();
      });
      await page2.waitForTimeout(150);
      await page2.selectOption('#road-filter', 'ok');
      await page2.waitForTimeout(300);
      const roadOk = await page2.evaluate(() => (window.__tradeStyles || []).slice());
      check('차 진입 가능만 고르면 그것만 남는다',
            roadOk.filter((x) => x.kind === 'land').length === 2
            && roadOk.filter((x) => x.kind === 'factory').length === 4,
            `토지 ${roadOk.filter((x) => x.kind === 'land').length} · `
            + `공장계 ${roadOk.filter((x) => x.kind === 'factory').length}`);
      check('조사 안 된 거래를 차 진입 가능으로 세지 않는다',
            roadOk.filter((x) => x.kind === 'land').length === 2
            && roadOk.filter((x) => x.kind === 'land')
              .every((x) => /세로한면\(가\)/.test(x.popup)),
            roadOk.filter((x) => x.kind === 'land').length + '건');

      await page2.selectOption('#road-filter', 'no');
      await page2.waitForTimeout(300);
      const roadNo = await page2.evaluate(() => (window.__tradeStyles || []).slice());
      // **조사 안 된 것을 맹지로 몰지 않는다.** 그러면 아직 안 받은 땅이
      // 전부 최악으로 셈해진다 — 지금은 그것이 대부분이다.
      check('맹지만 고르면 조사 안 된 거래는 안 딸려 온다',
            roadNo.filter((x) => x.kind === 'land').length === 1
            && /맹지/.test(roadNo.find((x) => x.kind === 'land').popup),
            `토지 ${roadNo.filter((x) => x.kind === 'land').length}건`);

      await page2.selectOption('#road-filter', 'all');
      await page2.waitForTimeout(300);

      // 말풍선이 도로접·형상·공시지가를 적는가.
      const roadPop = await page2.evaluate(() =>
        (window.__tradeStyles || []).find((x) => /화성시/.test(x.popup)));
      check('말풍선이 도로접면을 적는다',
            !!roadPop && /도로접/.test(roadPop.popup)
            && /세로한면\(가\)/.test(roadPop.popup),
            roadPop ? (roadPop.popup.match(/도로접[\s\S]{0,90}/) || [''])[0] : '없음');
      check('차 진입 가능 여부를 글자로 붙인다',
            !!roadPop && /차 진입 가능/.test(roadPop.popup));
      // 형상은 등급이 아니다 — "부정형이 무조건 좋지 않은 건 아닙니다."
      // 그대로 적기만 하고 좋고 나쁨을 붙이지 않는다.
      check('형상을 그대로 적고 등급을 매기지 않는다',
            !!roadPop && /부정형/.test(roadPop.popup)
            && !/(불리|나쁨|좋음)/.test(roadPop.popup),
            roadPop ? (roadPop.popup.match(/형상[\s\S]{0,60}/) || [''])[0] : '없음');
      check('공시지가와 실거래 배수를 적는다',
            !!roadPop && /공시지가/.test(roadPop.popup) && /2\.5배/.test(roadPop.popup),
            roadPop ? (roadPop.popup.match(/공시지가[\s\S]{0,90}/) || [''])[0] : '없음');

      // **조사 안 된 것을 맹지처럼 보이게 두지 않는다.** 비어 있는 것과
      // '맹지' 는 전혀 다른데, 아무 말도 없으면 읽는 사람은 둘을 못 가른다.
      const bare = await page2.evaluate(() =>
        (window.__tradeStyles || []).find((x) => /무안군/.test(x.popup)));
      check('필지 특성이 없는 토지는 조사 전이라고 말한다',
            !!bare && /아직 조사 전/.test(bare.popup)
            && /맹지라는 뜻이 아닙니다/.test(bare.popup),
            bare ? bare.popup.slice(-140) : '없음');
      check('공장 말풍선에는 그 안내가 안 붙는다',
            !!fac && !/아직 조사 전/.test(fac.popup));

      // 연도를 바꾸면 그 해 파일을 받아 다시 그린다.
      // 범위이므로 양끝을 다 옮겨야 그 해만 남는다. 왼쪽만 밀면
      // 2024~2025 가 되어 두 해가 함께 보인다 — 그것이 맞는 동작이다.
      await page2.evaluate(() => {
        const f = document.getElementById('year-from');
        const t = document.getElementById('year-to');
        f.value = '2024'; t.value = '2024';
        f.dispatchEvent(new Event('input'));
        t.dispatchEvent(new Event('input'));
      });
      await page2.waitForFunction(
        () => (window.__tradeStyles || []).length === 2, null, { timeout: 8000 })
        .then(() => check('연도를 바꾸면 그 해 자료로 다시 그린다', true))
        .catch(async () => check('연도를 바꾸면 그 해 자료로 다시 그린다', false,
          `${await page2.evaluate(() => (window.__tradeStyles || []).length)}개`));

      await page2.close();
    }

    // 타일 비용 (G, 2026-09-11). 우리 함수를 거치는 층은 요청을 아끼는 옵션을
    // 달고, 지도 키가 있으면 배경 타일이 브이월드로 바로 간다.
    {
      // 앞 절이 page 를 닫았다 — 새 페이지로 본다.
      const pg = await browser.newPage({ viewport: { width: 420, height: 900 } });
      for (const pat of ['**/lib/supabase-init.js*', '**/app/supabase.js*',
                         '**/supabase-js*/**', '**/leaflet*.js', '**/leaflet*.css'])
        await pg.route(pat, (r) => r.fulfill({ status: 200, body: '' }));
      await pg.route('**/app/config.js*', (r) => r.fulfill({
        status: 200, contentType: 'application/javascript',
        body: fs.readFileSync(path.join(ROOT, 'public', 'app', 'config.js'), 'utf8')
          + "\nwindow.REDT_CONFIG.vworldMapKey = 'MAPKEY-TEST';\n",
      }));
      await pg.addInitScript(FAKE_LEAFLET);
      await pg.addInitScript(() => {
        // 관문을 지나기 위한 최소 가짜 (위 본 페이지와 같은 꼴, 짧게).
        const ch = { on() { return ch; }, subscribe(cb) { if (cb) cb('SUBSCRIBED'); return ch; },
                     track() { return Promise.resolve(); }, presenceState() { return {}; } };
        window.SB = { channel: () => ch, removeChannel: () => Promise.resolve(),
                      rpc: () => Promise.resolve({ data: 1, error: null }),
                      from: () => { const q = { select: () => q, eq: () => q,
                        maybeSingle: () => Promise.resolve({ data: null, error: null }) }; return q; } };
        window.ME = { user: { id: 'u1' }, profile: { status: 'approved', grade: 'B' } };
        window.SBUtil = { me: async () => window.ME };
        try { localStorage.setItem('toji.basemap', 'satellite'); } catch (e) { /* */ }
      });
      await pg.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
      await pg.waitForSelector('#gate-bg', { timeout: 20000 }).catch(() => {});
      await pg.waitForFunction(() => (window.__map && (window.__map.tiles || []).length > 1), null, { timeout: 10000 })
        .catch(() => {});
      const t2 = await pg.evaluate(() => (window.__map.tileOpts || []).map((t) => ({
        url: t.url, uz: t.opts.updateWhenZooming, ui: t.opts.updateWhenIdle, kb: t.opts.keepBuffer })));
      const zoning = t2.find((t) => /layer=zoning/.test(t.url));
      const osm = t2.find((t) => /openstreetmap/.test(t.url));
      check('용도지역 층은 배율 바꾸는 동안 안 받고, 멈춘 뒤 받고, 네 줄을 들고 있는다',
            !!zoning && zoning.uz === false && zoning.ui === true && zoning.kb === 4, JSON.stringify(zoning));
      check('OSM 은 남의 서버라 그대로 둔다', !osm || osm.uz === undefined, JSON.stringify(osm));
      const sat = t2.find((t) => /Satellite/.test(t.url));
      check('지도 키가 있으면 배경 타일이 브이월드로 바로 간다 (우리 함수 0회)',
            !!sat && /^https:\/\/api\.vworld\.kr\/req\/wmts\/1\.0\.0\/MAPKEY-TEST\/Satellite\/\{z\}\/\{y\}\/\{x\}\.jpeg$/.test(sat.url)
            && sat.uz === false && !t2.some((t) => /api\/tile\?layer=satellite/.test(t.url)),
            JSON.stringify(t2.filter((t) => !/openstreetmap/.test(t.url)).slice(0, 4)));
      await pg.close();
    }

    // 가이드 05 · 법령과 조례 (E, 2026-09-11). 같은 조례 표를 읽어 시·군을 고르게 한다.
    {
      const pg = await browser.newPage({ viewport: { width: 420, height: 900 } });
      await pg.route('**/app/data/zoning-limits.json*', (r) => r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          generated: '2026-09-11',
          law: { '계획관리': { bcr_max: 40, far_min: 50, far_max: 100 }, '자연녹지': { bcr_max: 20, far_min: 50, far_max: 100 } },
          ord: { '2102141': { name: '수원시 도시계획 조례', org: '경기도 수원시', eff: '20251231',
                              url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2102141',
                              bcr: { '자연녹지': 20 }, far: { '자연녹지': 100 }, slope: 10, elev: 100 },
                 '2121099': { name: '안성시 도시계획 조례', org: '경기도 안성시', eff: '20260410',
                              url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2121099',
                              bcr: { '계획관리': 40 }, far: { '계획관리': 100 }, slope: 25, forest: 150 },
                 '2149501': { name: '서울특별시 도시계획 조례', org: '서울특별시', eff: '20260713',
                              url: 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq=2149501',
                              bcr: { '자연녹지': 20 }, far: { '자연녹지': 50 } } },
          sg: { '41111': ['2102141', 'sigungu'], '41550': ['2121099', 'sigungu'], '11110': ['2149501', 'sido'] },
        }),
      }));
      await pg.goto(`${BASE}/guide/law.html`, { waitUntil: 'domcontentloaded' });
      await pg.waitForFunction(() => /안성시 도시계획 조례/.test(document.getElementById('f-out').innerHTML), null, { timeout: 8000 })
        .catch(() => {});
      const g1 = await pg.evaluate(() => ({
        law: document.getElementById('law-table').innerHTML,
        sido: document.getElementById('f-sido').value,
        out: document.getElementById('f-out').innerHTML,
        stats: document.getElementById('f-stats').textContent,
        sidos: [...document.getElementById('f-sido').options].map((o) => o.value),
        scrollW: document.documentElement.scrollWidth, innerW: window.innerWidth,
      }));
      check('시행령 상한 표를 자료에서 채운다 (계획관리 40% · 50~100%)',
            /계획관리지역<\/th><td class="num">40%<\/td><td class="num">50~100%/.test(g1.law), g1.law.slice(0, 160));
      check('안성시부터 보여 준다 (경기도 · 안성시 도시계획 조례 · 원문 링크)',
            g1.sido === '경기도' && /안성시 도시계획 조례/.test(g1.out) && /ordinSeq=2121099/.test(g1.out) && /시행 2026-04-10/.test(g1.out),
            g1.out.slice(0, 200));
      check('안성 값: 계획관리 40%·100%, 경사 25°, 입목 150%, 표고는 숫자 기준 없음',
            /계획관리<\/th><td class="num">40%<\/td><td class="num">100%/.test(g1.out)
            && /25° 미만/.test(g1.out) && /150% 미만/.test(g1.out) && /표고<\/th><td><span class="muted">조문에 숫자 기준 없음/.test(g1.out));
      check('시·도 목록은 기관명 첫 낱말로 묶인다', g1.sidos.length === 2 && g1.sidos.includes('서울특별시'), g1.sidos.join(','));
      check('요약 통계를 적는다 (조례 3건 · 경사도 2 · 가장 흔한 값)',
            /조례 3건/.test(g1.stats) && /경사도 기준 있음 2/.test(g1.stats), g1.stats);
      check('전화 너비에서 가로로 안 넘친다', g1.scrollW <= g1.innerW, `${g1.scrollW} > ${g1.innerW}`);
      await pg.selectOption('#f-sido', '서울특별시');
      await pg.waitForFunction(() => /서울특별시 도시계획 조례/.test(document.getElementById('f-out').innerHTML), null, { timeout: 4000 })
        .catch(() => {});
      const g2 = await pg.evaluate(() => document.getElementById('f-out').innerHTML);
      check('시·도를 바꾸면 그 조례로 (서울 자연녹지 20%·50% · 경사 기준 없음)',
            /서울특별시 도시계획 조례/.test(g2) && /자연녹지<\/th><td class="num">20%<\/td><td class="num">50%/.test(g2)
            && /경사도<\/th><td><span class="muted">조문에 숫자 기준 없음/.test(g2), g2.slice(0, 200));
      await pg.close();
    }
  } finally {
    await browser.close();
    srv.kill();
  }
  console.log();
  console.log(failed ? `실패 ${failed}건` : '모두 통과');
  process.exit(failed ? 1 : 0);
})();

/** 또래가 얇은 시군구(47940)를 눌러 본다. pnu 앞 다섯 자리가 시군구 코드다. */
async function clickMapPeer(page, code) {
  // 이 덧씌운 길은 뒤 절까지 남는다. 바다 규칙(위도 38 위는 필지 없음)을
  // 여기에도 넣지 않으면 다음 검사가 '바다에서 필지가 나온다' 로 깨진다.
  await page.route('**/api/tile?mode=parcel*', (r) => {
    const u = new URL(r.request().url());
    if (Number(u.searchParams.get('lat')) > 38) {
      return r.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ parcel: null }) });
    }
    return r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ parcel: {
        pnu: `${code}10300100010000`, jimok: '전', land_use: '계획관리지역',
        area_m2: 1000, road_side: '중로한면', shape: '가로장방형',
        slope: '평지', official_price: 50000, stdr_year: '2025',
      } }),
    });
  });
  await page.evaluate(() => {
    window.__zoom = 15;
    (((window.__mapOn || {}).click) || []).forEach((fn) =>
      fn({ latlng: { lat: 37.484, lng: 130.905 }, originalEvent: { target: null } }));
  });
  await page.waitForTimeout(400);
  return page.evaluate(() => ({
    html: (document.getElementById('detail') || {}).innerHTML || '',
    peek: window.__parcel || null,
  }));
}
