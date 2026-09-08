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
      // **배율을 바꿀 수 있어야 한다.** 인구를 묶는 단위가 배율에 따라
      // 달라지는데(시도 → 시군 → 구), 7 로 고정해 두면 그 셋 중 하나만
      // 보고 통과라고 말하게 된다. window.__setZoom 으로 흔든다.
      getZoom() { return window.__zoom == null ? 7 : window.__zoom; },
      on(ev, fn) {
        (window.__mapOn = window.__mapOn || {});
        (window.__mapOn[ev] = window.__mapOn[ev] || []).push(fn);
        return this;
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
      m.bindPopup = (html) => { m.__popupHtml = html; return m; };
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
      default_window: 'y3',
      windows: [
        { key: 'y1', label: '최근 1년', kind: 'year', span: 1 },
        { key: 'y3', label: '최근 3년', kind: 'year', span: 3 },
        { key: 'c20', label: '최근 20건', kind: 'count', span: 20 },
      ],
      zone_kinds: { 계획관리: '비도시지역', 농림: '비도시지역', 자연녹지: '도시지역' },
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
        },
        // **도시는 계획관리가 없고 자연녹지만 있다** (사장님 지적,
        // 2026-09-08). 그 상황을 그대로 만들어 둔다 — 자연녹지는 세
        // 시군구에 다 있고 계획관리는 최근 1년에 두 곳뿐이다.
        농림: {
          41111: { y3: [5, 50000, 50000, 2023] },
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
        cells: [
          { nm: '정자동', sg: '41111', sgnm: '수원시 장안구', lat: 37.304, lon: 127.011,
            w: { y1: [8, 130000, 130000, 2025], y3: [9, 120000, 120000, 2023] } },
          // **같은 면의 리 둘.** 면 단계에서는 하나로 묶여야 하고,
          // 리 단계에서는 따로 서야 한다.
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
          traffic: [0, 50, 120, 300, 700, 1500, 3000, 6000, 12000, 25000, 50000] },
        // 시군구 또래가 얇으면(4건) 시도로 물러난다.
        '47940|계획관리': { n: 4, road: [.5, .5, .5, .5, .5, .5],
          land: [.5, .5, .5, .5, .5, .5], price: [1, 2], traffic: [1, 2] },
        '47|계획관리': { n: 900, road: [.1, .2, .3, .4, .5, .6],
          land: [.1, .2, .3, .4, .5, .6],
          price: [1e4, 2e4, 3e4, 4e4, 5e4, 6e4, 7e4, 8e4, 9e4, 10e4, 11e4],
          traffic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10] },
      },
      zone_pct: { 41111: [.02, .1, .2, .35, .6, .88], 47940: [.1, .3, .4, .5, .6, .7] },
    };
    await page.route('**/app/data/parcelstats.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_STATS),
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
        body: JSON.stringify({ parcel: {
          pnu: '4111110300100010000', jimok: '전', land_use: '계획관리지역',
          use_situation: '전', area_m2: 1653, road_side: '중로한면',
          shape: '가로장방형', slope: '평지', official_price: 250000,
          stdr_year: '2025',
        } }),
      });
    });
    await page.route('**/app/data/landprice-umd-*.json*', (r) => {
      const m = r.request().url().match(/landprice-umd-\w+-(\d+)\.json/);
      const p = m ? m[1] : '41';
      lpUmdHits.push(p);
      return r.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(FAKE_LP_UMD[p] || { cells: [] }),
      });
    });
    await page.route('**/app/data/landprice.json*', (r) => r.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(FAKE_LANDPRICE),
    }));
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
    console.log('4-A. 필터를 큰 분류 셋으로 묶었다');
    // 사장님 지시(2026-09-08): "왼쪽 필터를 큰 분류별로 묶어주세요
    // (호갱노노 참조). 실거래 표시 / IC / 실거래 가격 으로 묶어주고,
    // 선택하면 하단에 현재 필터들을 선택할 수 있도록."
    const cats = await page.evaluate(() => ({
      // 왼쪽 레일을 없앴다 — 필터가 지도 옆에 늘 펼쳐져 있으면 지도가
      // 그만큼 좁아지는데 실제로 만지는 것은 한 번에 한 묶음뿐이다.
      rail: !!document.querySelector('.rail'),
      chips: [...document.querySelectorAll('.cat')].map((b) => b.dataset.cat),
      labels: [...document.querySelectorAll('.cat')].map((b) => b.textContent.trim()),
      sheetShut: (document.getElementById('sheet') || {}).hidden,
    }));
    check('왼쪽 레일이 없다 (지도가 그 자리를 쓴다)', !cats.rail);
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
    // 옮기면서 조작부를 흘리면 안 된다. 하나라도 없으면 그 필터는
    // 화면에서 사라진 것이고, 사라진 줄도 모른다.
    const moved = await page.evaluate(() => ({
      trade: ['kind-filters', 'year-from', 'year-to', 'stage-filters',
              'road-filter', 'land-use-filters', 'parcel-only']
        .filter((id) => !document.getElementById(id)),
      ic: ['tg-year', 'tg-vehicle', 'tier-filters', 'band-legend']
        .filter((id) => !document.getElementById(id)),
      price: ['lp-note', 'lp-swap'].filter((id) => !document.getElementById(id)),
      pills: document.querySelectorAll('.sheet .lp-filter').length,
    }));
    check('실거래 표시 묶음에 그 조작부가 다 있다',
          moved.trade.length === 0, moved.trade.join(','));
    check('IC 묶음에 그 조작부가 다 있다', moved.ic.length === 0, moved.ic.join(','));
    check('실거래 가격 묶음에 땅값 칩이 있다',
          moved.price.length === 0 && moved.pills === 2,
          `빠진 것 ${moved.price.join(',')} · 칩 ${moved.pills}개`);

    const oIc = await openCat('ic');
    check('다른 분류를 누르면 그쪽으로 바뀐다',
          !oIc.shut && oIc.paneShown && oIc.title === 'IC' && oIc.others === 0,
          `"${oIc.title}"`);
    const again = await openCat('ic');
    check('같은 분류를 다시 누르면 닫힌다', again.shut && !again.chipOn);

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
    // 사장님 지시(2026-09-08): "왼쪽 스크롤에 있는 문장들은 물음표 원
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
    console.log('4-B. 지도 위 범례를 걷어냈다');
    // 사장님 지시(2026-09-08): "좌측 범례 삭제".
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
    console.log('9. 행정구역 인구 — 배율에 따라 도 → 시·군 → 구');
    /* 사장님 지시(2026-09-07): "지도 화면 축적/크기에 따라 도/광역시
     * 기준, 시(광역시 포함)/군 기준, 구 기준으로 반영이 가능할까요?"
     *
     * 전국을 볼 때 247개 원이 겹쳐 있으면 아무것도 안 읽힌다. 그때
     * 필요한 것은 17개다. 세 배율을 실제로 흔들어 본다 — 하나만 보고
     * 통과라고 말하면 나머지 둘은 안 본 것이다. */
    // 인구는 이제 **꺼진 채로 시작한다** (사장님 지시 2026-09-08).
    // 이 절은 인구 겹 자체를 보는 곳이므로 먼저 켠다.
    await page.evaluate(() => {
      const b = document.getElementById('pop-bg');
      if (b && !b.checked) { b.checked = true; b.dispatchEvent(new Event('change')); }
    });
    const popAt = async (z) => page.evaluate((zoom) => {
      window.__zoom = zoom;
      (((window.__mapOn || {}).zoomend) || []).forEach((fn) => fn());
      const marks = (window.__map.groups || [])
        .flatMap((g) => g._items)
        .filter((m) => m.__opts && m.__opts.pane === 'popPane');
      return {
        peek: window.__pop || {},
        n: marks.length,
        radii: marks.map((m) => m.__opts.radius),
        tips: marks.map((m) => m.__tooltip || ''),
        at: marks.map((m) => m.__latlng),
      };
    }, z);

    const base = await page.evaluate(() => ({
      pane: (window.__map.panes && window.__map.panes.popPane)
        ? Number(window.__map.panes.popPane.style.zIndex) : null,
      switchShown: !(document.getElementById('pop-switch') || {}).hidden,
    }));
    check('인구 스위치가 보인다 (자료가 있을 때만)', base.switchShown);
    check('인구 원을 IC 아래 판에 그린다 (200 < z < 400)',
          base.pane !== null && base.pane > 200 && base.pane < 400,
          `z-index ${base.pane}`);

    // ① 전국이 보이는 배율 — 도·광역시 하나에 원 하나.
    const wide = await popAt(7);
    check('멀리서는 도·광역시로 묶는다',
          wide.n === 3 && wide.peek.level === 'sido',
          `${wide.n}개 · ${wide.peek.level}`);
    check('도 하나가 그 안의 시군구를 합친 값이다',
          wide.tips.some((t) => /경기도/.test(t) && /1,108,000명/.test(t)),
          wide.tips.join(' | ').slice(0, 200));
    check('몇 곳을 합친 것인지 말한다',
          wide.tips.some((t) => /4개 시군구를 합친/.test(t)),
          wide.tips.find((t) => /경기도/.test(t)) || '없음');

    // ② 중간 배율 — 시(광역시 포함)·군.
    const mid = await popAt(10);
    check('가까이 가면 시·군으로 나뉜다',
          mid.n === 5 && mid.peek.level === 'si', `${mid.n}개 · ${mid.peek.level}`);
    check('시 아래 구는 그 시로 묶인다 (수원시 장안구 + 권선구)',
          mid.tips.some((t) => /^수원시 ·/.test(t) && /650,000명/.test(t)),
          mid.tips.join(' | ').slice(0, 200));
    // "시(광역시 포함)" — 서울을 25개 구로 흩어 놓으면 부산·대구와
    // 나란히 못 본다.
    check('광역시는 하나로 묶는다',
          mid.tips.some((t) => /^서울특별시 ·/.test(t) && /687,000명/.test(t))
          && !mid.tips.some((t) => /^종로구/.test(t)),
          mid.tips.join(' | ').slice(0, 200));

    // ③ 가장 가까운 배율 — 자치구까지.
    const near = await popAt(12);
    check('더 가까이 가면 구까지 나뉜다',
          near.n === 7 && near.peek.level === 'gu',
          `${near.n}개 · ${near.peek.level}`);
    check('그때는 종로구·강남구가 따로 선다',
          near.tips.some((t) => /^종로구/.test(t))
          && near.tips.some((t) => /^강남구/.test(t)),
          near.tips.join(' | ').slice(0, 200));

    // 크기는 **네 단**이다. 235가지 크기를 눈으로 가를 수는 없다.
    // 구 단위에서 넷이 다 나오도록 자료를 넣어 두었다.
    const R = [...new Set(near.radii)].sort((a, b) => b - a);
    check('크기가 네 단으로 끊긴다', R.length === 4, near.radii.join(' / '));
    // 단위가 바뀌면 자르는 자리도 바뀐다. 시군구 기준 5만·20만·50만을
    // 시도에 그대로 쓰면 17곳이 전부 맨 위 칸에 들어가 원이 다 같아진다.
    check('묶음 단위가 바뀌면 자르는 자리도 바뀐다',
          new Set(wide.radii).size > 1,
          `시도 반지름 ${wide.radii.join('/')}`);

    // 예전에는 여기서 지도 위 범례가 원 크기와 인구를 짝지어 말하는지
    // 봤다. **그 범례는 없앴다** (사장님 지시 2026-09-08: "좌측 범례
    // 삭제"). 대신 원마다 말풍선이 인구를 숫자로 말하는지 본다 —
    // 크기만 남고 숫자가 없으면 큰 원과 작은 원의 차이를 못 읽는다.
    check('원마다 인구를 숫자로 말한다',
          near.tips.length > 0 && near.tips.every((t) => /명/.test(t)),
          (near.tips[0] || '없음').slice(0, 80));
    check('어느 해 인구인지 말풍선에 적는다',
          !!near.peek.year
          && near.tips.some((t) => t.includes(String(near.peek.year))),
          (near.tips[0] || '없음').slice(0, 80));

    /* ── 원의 중심은 관청 소재지 (2026-09-07 지시) ──
     * "인구 표시 원의 중심은 도청/시청/구청/군청 소재지가 중심이 되도록."
     * 그 전에는 우리 거래 좌표에서 만든 대표점이라, 거래가 없는 동네가
     * 많은 시군구는 그만큼 끌려갔다. */
    const near2 = await popAt(12);
    const jangan = near2.at[near2.tips.findIndex((t) => /^수원시 장안구/.test(t))];
    check('구 단위 원이 그 구청 위에 선다',
          !!jangan && Math.abs(jangan[0] - 37.3040) < 1e-4
          && Math.abs(jangan[1] - 127.0101) < 1e-4,
          JSON.stringify(jangan));
    check('관청 위에 찍혔다고 말한다',
          near2.tips.some((t) => /^수원시 장안구/.test(t)
                                 && /점 위치는 관청 소재지/.test(t)),
          near2.tips.find((t) => /^수원시 장안구/.test(t)) || '없음');
    // 못 받은 곳은 사라지지 않고, 관청 위인 척하지도 않는다.
    check('관청을 못 받은 곳도 원은 그린다',
          near2.tips.some((t) => /^울릉군/.test(t)));
    check('그 원은 대표점이라고 말한다',
          near2.tips.some((t) => /^울릉군/.test(t)
                                 && /인구로 가중한 대표점/.test(t)),
          near2.tips.find((t) => /^울릉군/.test(t)) || '없음');

    // 묶은 단위는 **묶은 단위의 관청**이다. 시군구 관청의 평균을 쓰면
    // 그것은 다시 대표점이다 — 경기도청은 수원에 있지 경기도 한가운데
    // 있지 않다.
    const wide2 = await popAt(7);
    const gg = wide2.at[wide2.tips.findIndex((t) => /^경기도/.test(t))];
    check('시·도 원이 도청 위에 선다',
          !!gg && Math.abs(gg[0] - 37.274975) < 1e-4
          && Math.abs(gg[1] - 127.009235) < 1e-4,
          JSON.stringify(gg));
    const mid2 = await popAt(10);
    const suwon = mid2.at[mid2.tips.findIndex((t) => /^수원시 ·/.test(t))];
    check('시 원이 시청 위에 선다',
          !!suwon && Math.abs(suwon[0] - 37.263434) < 1e-4
          && Math.abs(suwon[1] - 127.028653) < 1e-4,
          JSON.stringify(suwon));

    // 다음 절이 기본 배율을 가정하므로 되돌린다.
    await popAt(7);

    console.log();
    console.log('9-B. 땅값 지도 — 사각형 표찰 · 왼쪽 필터를 따름 · 추이');
    /* 사장님 지시(2026-09-08): "좌측 범례 삭제 / 호갱노노처럼 사각형으로
     * 변경 후 동, 리 이름만 표시 가격 아래로 / 마우스 오버랩시 정보와
     * 실거래가격 트랜드 표시 / 용도지역 선택 시 선택된 용도지역의
     * 중간값으로 가격 변환 (초기는 계획관리, 자연녹지, 생산관리 기준)" */

    // 왼쪽 용도지역 필터를 직접 만진다. **땅값 글자는 이것을 따른다** —
    // 고르는 곳이 두 군데면 둘이 어긋난 채로 보게 되고, 그러면 지도의
    // 점과 글자가 서로 다른 땅을 말한다.
    const lpRail = async (names) => page.evaluate((want) => {
      const box = document.getElementById('land-use-filters');
      box.querySelectorAll('input').forEach((i) => {
        const on = want.some((w) => String(i.dataset.key).indexOf(w) >= 0);
        if (i.checked !== on) i.click();
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
        html: marks.map((m) => (m.options.icon || {}).options.html || ''),
        tips: marks.map((m) => m.__tooltip || ''),
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
        // 왼쪽 필터의 기본값. 사장님이 말씀하신 셋이어야 한다.
        rail: [...document.querySelectorAll('#land-use-filters input')]
          .filter((i) => i.checked).map((i) => i.dataset.key),
      };
    });
    check('땅값 막대가 보인다 (자료가 있을 때만)', lpUi.barShown);
    check('필터가 눌러서 고르는 칩이다 (드롭다운이 아니다)',
          lpUi.selects === 0, `남은 select ${lpUi.selects}개`);
    check('용도지역 칩을 없앴다 (왼쪽 필터 하나로 합쳤다)', !lpUi.groupChip);
    // 사장님 지시: "초기는 계획관리, 자연녹지, 생산관리 기준".
    check('처음 켜진 용도지역이 계획관리·생산관리·자연녹지 셋이다',
          lpUi.rail.length === 3
          && ['계획관리', '생산관리', '자연녹지']
            .every((g) => lpUi.rail.some((n) => n.indexOf(g) >= 0)),
          lpUi.rail.join(','));
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
    check('용도지역을 켜면 지역이 칠해진다', lp1.n === 3 && lp1.peek.on,
          `${lp1.n}곳 · on=${lp1.peek.on}`);
    // **사각형 표찰: 이름 위, 값 아래.** 알약에 나란히 쓰면 이름이 길수록
    // 옆으로 늘어나 서로 겹친다.
    check('사각형 표찰에 이름이 위, 값이 아래다',
          lp1.html.every((h) => /class="lp-card"/.test(h)
                               && /<b>[^<]+<\/b><i>[^<]+<\/i>/.test(h)),
          (lp1.html[0] || '없음').slice(0, 100));
    const lp1Fills = fillsOf(lp1.html);
    check('색이 파란 계열이다 (빨강·노랑이 없다)',
          lp1Fills.length === 3 && lp1Fills.every((c) => {
            const r = parseInt(c.slice(1, 3), 16);
            const bl = parseInt(c.slice(5, 7), 16);
            return bl > r;
          }), lp1Fills.join(' '));
    check('지역이 적어도 값이 다르면 색이 갈린다', new Set(lp1Fills).size === 3,
          lp1Fills.join(' '));
    check('순위로 편 것을 분위수인 척하지 않는다',
          /순위로 색을 폄/.test(lp1.note), lp1.note);
    check('안내문이 지금 보는 용도지역을 말한다',
          /^계획관리 ·/.test(lp1.note), lp1.note);
    check('글자는 평당으로 접어 쓴다',
          lp1.html.some((h) => /33\.1만|33만/.test(h)),
          lp1.html.find((h) => /장안구/.test(h)) || '없음');

    // ── 말풍선: 정보 + 실거래가 추이 ──
    const tipJan = lp1.tips.find((t) => /수원시 장안구/.test(t)) || '';
    check('말풍선이 평당·㎡당·건수·기준을 적는다',
          /평당/.test(tipJan) && /㎡당/.test(tipJan)
          && /거래/.test(tipJan) && /최근 3년/.test(tipJan),
          tipJan.slice(0, 110));
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
          /262,857원/.test(lpMix2.tips.find((t) => /장안구/.test(t)) || ''),
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
    check('기준을 최근 1년으로 좁히면 거래 없는 곳이 빠진다',
          lpY1.n === 2 && !lpY1.tips.some((t) => /울릉군/.test(t)),
          `${lpY1.n}곳`);
    const lpC = await lpPick('c20', null);
    check('건수 기준은 몇 년치를 긁어온 값인지 밝힌다',
          /2009년부터/.test(lpC.tips.find((t) => /울릉군/.test(t)) || ''),
          (lpC.tips.find((t) => /울릉군/.test(t)) || '없음').slice(0, 120));
    const lpMed = await lpPick('y3', 'p50');
    const lpMean = await lpPick('y3', 'avg');
    const val = (t) => (t.match(/평당 ([\d,]+)원/) || [])[1];
    check('평균으로 바꾸면 값이 달라진다',
          val(lpMed.tips.find((t) => /장안구/.test(t)) || '')
          !== val(lpMean.tips.find((t) => /장안구/.test(t)) || ''),
          `중앙값 ${val(lpMed.tips.find((t) => /장안구/.test(t)) || '')}`
          + ` vs 평균 ${val(lpMean.tips.find((t) => /장안구/.test(t)) || '')}`);
    await lpPick('y3', 'p50');

    await page.evaluate(() => { window.__zoom = 7; });
    await lpFire();
    const lpWide = await lpRead();
    check('멀리서는 시·도로 묶인다',
          lpWide.peek.level === 'sido' && lpWide.n === 2,
          `${lpWide.peek.level} · ${lpWide.n}곳`);
    // 경기도 = 장안구(10만, 10건) + 권선구(20만, 20건) → 가중 16.7만.
    check('묶을 때 거래 건수로 가중한다 (합치지 않는다)',
          lpWide.tips.some((t) => /^<div class="lp-tip-h">경기도/.test(t)
                                  && /166,667원/.test(t)),
          (lpWide.tips.find((t) => /경기도/.test(t)) || '없음').slice(0, 140));

    // ── 읍·면·동 → 리·동 ──
    await page.evaluate(() => { window.__bbox = [37.0, 126.5, 37.6, 127.5]; });
    lpUmdHits.length = 0;
    await page.evaluate(() => { window.__zoom = 12; });
    await lpFire();
    await page.waitForTimeout(300);
    await lpFire();
    const lpMyeon = await lpRead();
    check('배율 12 에서 읍·면·동이 뜬다 (군 이름 하나로 안 끝난다)',
          lpMyeon.peek.level === 'umd' && lpMyeon.n === 2,
          `${lpMyeon.peek.level} · ${lpMyeon.n}곳`);
    check('면 단계는 리를 면으로 묶는다',
          lpMyeon.html.some((h) => /<b>백곡면<\/b>/.test(h))
          && !lpMyeon.html.some((h) => /사송리/.test(h)),
          lpMyeon.html.map((h) => (h.match(/<b>([^<]*)/) || [])[1]).join(','));
    check('묶을 때 리 개수와 함께 건수로 가중한다',
          /2개 리·동 합침/.test(lpMyeon.tips.find((t) => /백곡면/.test(t)) || ''),
          (lpMyeon.tips.find((t) => /백곡면/.test(t)) || '없음').slice(0, 140));

    await page.evaluate(() => { window.__zoom = 14; });
    await lpFire();
    const lpRi = await lpRead();
    check('더 당기면 리·동까지 내려간다',
          lpRi.peek.level === 'ri' && lpRi.n === 3,
          `${lpRi.peek.level} · ${lpRi.n}곳`);
    // **표찰에는 리 이름만.** 어느 읍인지는 지도 바탕에 이미 적혀 있다.
    check('표찰에는 리 이름만 쓴다 (앞의 면 이름을 뗀다)',
          lpRi.html.some((h) => /<b>사송리<\/b>/.test(h))
          && !lpRi.html.some((h) => /<b>백곡면 사송리<\/b>/.test(h)),
          lpRi.html.map((h) => (h.match(/<b>([^<]*)/) || [])[1]).join(','));
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
    // 글자만 띄우고 안 되면 더 나쁘다. **왼쪽 필터가 실제로 켜져야 한다.**
    await page.evaluate(() => document.getElementById('lp-swap').click());
    await page.waitForTimeout(200);
    const swapped = await page.evaluate(() => ({
      rail: [...document.querySelectorAll('#land-use-filters input')]
        .filter((i) => i.checked).map((i) => i.dataset.key),
      peek: window.__lp || {},
    }));
    check('누르면 왼쪽 필터가 실제로 켜진다',
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
    console.log('9-C. 필지 진단 — 다섯 축을 또래 안 백분위로');
    /* 사장님 지시(2026-09-08): "해당 필지를 클릭하면 스파이더 차트를 통해
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
    check('레이더를 그린다 (다섯 축)',
          /<svg class="radar"/.test(pc.html)
          && (pc.peek.diag.axes || []).length === 5,
          (pc.peek.diag.axes || []).map((a) => a.key).join(','));

    const byKey = {};
    (pc.peek.diag.axes || []).forEach((a) => { byKey[a.key] = a; });
    // 중로한면 = 등급 4 → 또래 누적 .7
    check('도로 축이 또래 사다리를 탄다',
          Math.abs(byKey.road.pct - 0.7) < 1e-6, String(byKey.road.pct));
    // 공시지가 25만 = 분위 경계의 6번째(0..10) → 0.6
    check('가격 축이 분위 경계를 선형으로 읽는다',
          Math.abs(byKey.price.pct - 0.6) < 1e-6, String(byKey.price.pct));
    // 계획관리 = 사다리 5 → 시군구 zone_pct[5] = .88
    check('개발 여지는 또래가 아니라 시군구 안에서 잰다',
          Math.abs(byKey.zoning.pct - 0.88) < 1e-6, String(byKey.zoning.pct));
    // 가로장방형(4) + 평지(5) → 반올림 5 → land[5] = .95
    check('모양·지세를 한 축으로 묶는다',
          Math.abs(byKey.land.pct - 0.95) < 1e-6, String(byKey.land.pct));
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

    // 바다·도로를 누른 것은 오류가 아니다.
    const sea = await clickMap(38.5, 128.5);
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

    /* ── 거래 연도 · 상세 말풍선 ──
     *
     * 사장님 지시(2026-09-07) 세 가지를 그대로 본다.
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

      // 사장님 지시(2026-09-08): "실거래 연도는 좌/우로 선택해서 범위를
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
      // 전 기간을 기본으로 두면 처음 보는 화면이 늘 성긴 표본이라
      // '거래가 이것뿐인가' 로 읽힌다.
      check('기본은 가장 최근 한 해다',
            sel.from === '2025' && sel.to === '2025' && /2025년/.test(sel.out),
            `${sel.from}~${sel.to} "${sel.out}"`);

      // 거래는 기본이 꺼져 있다(2026-09-04 지시). 켜야 그려진다.
      await page2.evaluate(() => {
        document.querySelectorAll('#kind-filters input').forEach((i) => {
          if (!i.checked) i.click();
        });
      });
      await page2.waitForTimeout(300);

      const styles = await page2.evaluate(() => window.__tradeStyles || []);
      check('고른 해의 거래가 그려진다', styles.length === 5, `${styles.length}개`);
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
      check('말풍선에 평당가가 들어 있다',
            !!land && /평당/.test(land.popup) && /165만원/.test(land.popup),
            land ? (land.popup.match(/평당[^<]*/) || [''])[0] : '없음');
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
      check('안내가 그 해 실제 건수를 말한다', /400,000건/.test(note), note);
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

      /* ── 토지: 개발단계 · 용도지역 (2026-09-07 지시) ── */
      const landUi = await page2.evaluate(() => ({
        hidden: document.getElementById('land-box').hidden,
        stages: [...document.querySelectorAll('#stage-filters label')]
          .map((l) => l.textContent.replace(/\s+/g, ' ').trim()),
        uses: [...document.querySelectorAll('#land-use-filters label')]
          .map((l) => l.textContent.replace(/\s+/g, ' ').trim()),
      }));
      check('토지 필터 묶음이 보인다', landUi.hidden === false);
      check('개발단계 칸이 건수와 함께 선다',
            landUi.stages.some((t) => /개발완료/.test(t) && /1,500,000건/.test(t))
            && landUi.stages.some((t) => /원지/.test(t) && /9,100,000건/.test(t)),
            landUi.stages.join(' | '));
      check('용도지역이 많은 것부터 늘어선다',
            landUi.uses[0].startsWith('계획관리지역')
            && landUi.uses.length === 4,
            landUi.uses.join(' | '));
      // 처음에는 세 지역만 켜져 있어야 한다 (2026-09-07 지시).
      const luOn = await page2.evaluate(() =>
        [...document.querySelectorAll('#land-use-filters input')]
          .filter((i) => i.checked).map((i) => i.dataset.key));
      check('처음에 계획관리·자연녹지만 켜져 있다',
            luOn.includes('계획관리지역') && luOn.includes('자연녹지지역')
            && !luOn.includes('농림지역') && !luOn.includes('제2종일반주거지역'),
            luOn.join(','));

      // 아래 검사들은 토지가 다 보이는 상태를 가정한다. 기본값이
      // 세 지역만이므로 먼저 전체를 켠다.
      await page2.evaluate(() => document.getElementById('lu-all').click());
      await page2.waitForTimeout(300);

      // 원지를 끄면 원지 토지만 빠진다. 공장·창고는 그대로여야 한다 —
      // 토지 칸을 만졌는데 공장이 사라지면 화면을 믿을 수 없다.
      const before = await page2.evaluate(() => (window.__tradeStyles || []).length);
      await page2.evaluate(() => {
        [...document.querySelectorAll('#stage-filters label')]
          .find((l) => /원지/.test(l.textContent))
          .querySelector('input').click();
      });
      await page2.waitForTimeout(300);
      const afterRaw = await page2.evaluate(() => (window.__tradeStyles || []) .slice());
      check('원지를 끄면 원지 토지만 빠진다',
            afterRaw.length === before - 1
            && afterRaw.filter((x) => x.kind === 'factory').length === 3,
            `${before} → ${afterRaw.length}, 공장계 ${afterRaw.filter((x) => x.kind === 'factory').length}`);

      // 되돌리고 용도지역으로 걸러 본다.
      await page2.evaluate(() => {
        [...document.querySelectorAll('#stage-filters label')]
          .find((l) => /원지/.test(l.textContent))
          .querySelector('input').click();
        document.getElementById('lu-none').click();
      });
      await page2.waitForTimeout(300);
      const noLu = await page2.evaluate(() => (window.__tradeStyles || []).slice());
      check('용도지역을 모두 끄면 토지가 사라진다',
            noLu.filter((x) => x.kind === 'land').length === 0
            && noLu.filter((x) => x.kind === 'factory').length === 3,
            `토지 ${noLu.filter((x) => x.kind === 'land').length} · 공장계 ${noLu.filter((x) => x.kind === 'factory').length}`);

      // '분석 대상만' 은 settings.yaml 의 계획관리·생산관리·자연녹지다.
      await page2.evaluate(() => document.getElementById('lu-core').click());
      await page2.waitForTimeout(300);
      const core = await page2.evaluate(() => ({
        on: [...document.querySelectorAll('#land-use-filters input')]
          .filter((i) => i.checked).map((i) => i.dataset.key),
        land: (window.__tradeStyles || []).filter((x) => x.kind === 'land').length,
      }));
      check("'분석 대상만' 이 계획관리·자연녹지를 고른다",
            core.on.includes('계획관리지역') && core.on.includes('자연녹지지역')
            && !core.on.includes('농림지역'),
            core.on.join(','));
      check('그 선택이 지도에 반영된다', core.land === 2, `토지 ${core.land}건`);

      // 말풍선이 개발단계를 적는가.
      const landPop = await page2.evaluate(() =>
        (window.__tradeStyles || []).find((x) => x.kind === 'land'));
      check('말풍선이 지목 옆에 개발단계를 적는다',
            !!landPop && /\(원지\)|\(개발완료\)/.test(landPop.popup),
            landPop ? (landPop.popup.match(/지목[^<]*<[^>]*>[^<]*</) || [''])[0] : '없음');

      await page2.evaluate(() => document.getElementById('lu-all').click());
      await page2.waitForTimeout(300);

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
            roadOk.filter((x) => x.kind === 'land').length === 1
            && roadOk.filter((x) => x.kind === 'factory').length === 3,
            `토지 ${roadOk.filter((x) => x.kind === 'land').length} · `
            + `공장계 ${roadOk.filter((x) => x.kind === 'factory').length}`);
      check('조사 안 된 거래를 차 진입 가능으로 세지 않는다',
            roadOk.filter((x) => x.kind === 'land').length === 1
            && /세로한면\(가\)/.test(roadOk.find((x) => x.kind === 'land').popup),
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
