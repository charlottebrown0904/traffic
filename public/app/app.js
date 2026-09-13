/* IC 스크리닝 — 화면 로직.
   DB 에 직접 붙지 않고 public/app/data/*.json 만 읽는다.
   합성 데이터든 실데이터든 이 파일은 그대로다. */
'use strict';

const QUADRANTS = {
  undervalued: { label: '저평가 후보', color: 'var(--q-under)' },
  rising:      { label: '동반 상승',   color: 'var(--q-rising)' },
  overheated:  { label: '과열 주의',   color: 'var(--q-over)' },
  quiet:       { label: '관망',        color: 'var(--q-quiet)' },
};
const KIND_LABEL = { land: '토지', factory: '공장·창고', house: '단독·다가구', commercial: '상업업무용' };

const TOKEN_KEY = 'redt.token.v1';
const CONFIG = window.REDT_CONFIG || {};
const API = CONFIG.apiBase || '';

const state = {
  meta: null, tollgates: [], trades: [], series: {}, traffic: null, chart: null,
  rank: { year: null, vehicle: 'total', sort: 'volume', q: '', coordsOnly: false },
  trend: { id: null, scale: 'index', base: null, on: new Set(), ready: false },
  activeTiers: new Set([0, 1, 2, 3, 'new', 'none']),
  // 용도지역 배경은 기본으로 켜 둔다 — 요청된 화면이다.
  // 용도지역 색면은 **꺼진 채로 시작한다** (요구사항 2026-09-08).
  // 색면이 깔리면 그 위의 땅값 글자와 거래 점이 묻힌다.
  zoning: false,
  // 필지 경계선 (요구사항 2026-09-10). **기본은 켬** — 땅을 보는
  // 사람에게 경계는 배경이 아니라 본문이다. 껐다 켠 것은 기억한다.
  cadastral: (() => {
    try { return localStorage.getItem('toji.cadastral') !== 'off'; }
    catch (e) { return true; }
  })(),
  tgYear: null,
  // 고른 차종. **여럿 고를 수 있다** (요구사항 2026-09-09).
  // 처음에는 다 켠다 — 예전 '전체 차종' 과 같은 화면으로 시작한다.
  tgVehicles: new Set([1, 2, 3, 4, 5, 6]),
  dealYear: 'all', tradeCache: {}, tradesShown: null,
  activeStages: new Set(), activeLandUse: new Set(),
  hasStageFilter: false, hasLandUseFilter: false,
  // 'all' | 'ok' | 'no'. 기본은 'all' — 필지 특성을 아직 전국의 일부만
  // 훑었으므로, 여기서 걸면 조사 안 된 거래가 통째로 사라진다.
  roadFilter: 'all',
  activeKinds: new Set(),
  parcelOnly: false, selected: null, tiers: null,
  token: null, broker: null, listings: [], scope: 'public', pickMode: false,
  apiAvailable: false, verdicts: null,
  verdictSets: {}, verdictKind: 'land',
  // 인구·영업소는 **꺼진 채로 시작한다** (요구사항 2026-09-08).
  // 땅값이 이 화면의 주인공인데, 인구 원과 영업소 점이 함께 깔리면
  // 처음 여는 사람은 무엇을 봐야 할지 모른다.
  regions: null, popYear: null, showGates: false,
  // 거래 연도 범위 (좌/우 손잡이). yearWide 면 전 기간 표본으로 물러난 것이다.
  yearFrom: null, yearTo: null, yearWide: false,
  // 땅값 분위지도 (2026-09-08 지시)
  landPrice: null, lpStat: 'p50', lpWindow: '',
  // 거래 핀에 무엇을 적을 것인가. 총액이 기본이다 — 땅을 보는
  // 사람이 가장 먼저 묻는 것이 '얼마에 팔렸나' 다.
  pinKind: 'price', tradeLabelled: false,
  // 배경 지도. 기본은 지금 것(OSM) — 브이월드는 고른 사람만 씁니다.
  baseMap: (() => {
    try { return localStorage.getItem('toji.basemap') || 'osm'; }
    catch (e) { return 'osm'; }
  })(),
  // 땅값 글자의 용도지역. 거래 점 필터(activeLandUse)와 **따로 논다**.
  lpGroupSet: new Set(),
};

let map, tollgateLayer, tradeLayer, bandLayer, listingLayer, zoningLayer, lpLayer;
/* 고른 필지의 윤곽. 한 번에 하나만 그린다. */
let parcelLayer = null;
/* 필지 경계선 타일. **용도지역과 따로 논다** (요구사항 2026-09-10).
 *
 * 예전에는 zoningLayer 안에 같이 들어 있었다. 그래서 경계선만 보려면
 * 용도지역 색면까지 켜야 했고, 그 색면이 지도를 덮었다 — "필지를
 * 선택하기 전에 윤곽이 미리 보였으면" 이 안 되던 이유가 이것이다. */
let cadastralLayer = null;
const markers = new Map();

/* ─────────── 유틸 ─────────── */
const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};
const pct = (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%');
const num = (v) => (v == null ? '—' : Math.round(v).toLocaleString('ko-KR'));
const quad = (key) => QUADRANTS[key] || { label: '미산출', color: 'var(--q-quiet)' };
/* 거리 밴드는 순서대로 --band-1..5 를 쓴다. 다섯 개가 전부 같은 브라운이라
   0-1km 와 10-20km 를 눈으로 가릴 수 없던 것을 고친 것이다. 밴드가 다섯 개를
   넘으면 처음부터 다시 돌려 쓴다 — 색이 없어 안 그려지는 것보다 낫다. */
const BAND_COLORS = 5;
const bandColor = (i) => `var(--band-${(i % BAND_COLORS) + 1})`;

/* Leaflet 은 CSS 변수를 못 읽는다. 실제 색 문자열로 풀어서 넘겨야 한다.
   거래 점마다 풀면 2,500번 계산하므로 한 번 푼 값은 담아둔다. 다만 OS 테마가
   바뀌면 값이 달라지므로 그때 캐시를 비우고 다시 그린다. */
const _cssCache = new Map();
function cssVar(name) {
  if (!_cssCache.has(name)) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    _cssCache.set(name, v || '#888');
  }
  return _cssCache.get(name);
}
if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    _cssCache.clear();
    if (typeof refreshMap === 'function') refreshMap();
    if (state.selected) selectTollgate(state.selected);
  });
}

/* ─────────── 부팅 ─────────── */
async function boot() {
  // 탭 배선을 **맨 먼저** 한다. 탭은 정적 HTML 이라 자료가 없어도 있다.
  // 배선을 아래 자료 받기 뒤에 두면, 그 사이에 누른 클릭은 듣는 사람이
  // 없어 그냥 사라진다 — 화면은 멀쩡한데 눌러도 안 넘어간다. 바깥
  // CDN(Leaflet·폰트)이 느리거나 막히면 app.js 실행 자체가 몇 초 밀려서
  // 이 틈이 눈에 띄게 벌어진다.
  wireTabs();
  wireWhy();
  wireSheet();
  try {
    const [meta, tollgates, trades, series] = await Promise.all(
      ['meta', 'tollgates', 'trades', 'series'].map((n) =>
        fetch(`/app/data/${n}.json`).then((r) => {
          if (!r.ok) throw new Error(`data/${n}.json 을 읽지 못했습니다 (${r.status})`);
          return r.json();
        }))
    );
    Object.assign(state, { meta, tollgates, trades, series });
  } catch (err) {
    showFatal(err.message);
    return;
  }

  // 요구사항(2026-09-04): "모든 실거래는 초기 기본설정은 표기 끄는 것."
  // 거래가 2천 점이라 처음 화면이 온통 점으로 덮인다. 필요할 때 켠다.
  state.activeKinds = new Set();
  state.tradesShown = state.trades;

  if (state.meta.is_synthetic) $('#demo-banner').hidden = false;
  $('#meta-stamp').innerHTML =
    `${state.meta.year_min}–${state.meta.year_max} · 영업소 ${state.meta.counts.tollgates}` +
    `<br>거래 ${state.meta.counts.trades_total.toLocaleString('ko-KR')}건`;
  $('#disclaimer').textContent = state.meta.disclaimer;

  if (CONFIG.homeUrl) {
    const home = $('#home-link');
    home.href = CONFIG.homeUrl;
    home.hidden = false;
  }

  // 순위 탭 자료는 없어도 나머지 화면은 살아야 한다. 실패하면 그 탭만 끈다.
  try {
    const r = await fetch('/app/data/traffic.json');
    if (r.ok) state.traffic = await r.json();
  } catch (err) {
    state.traffic = null;
  }
  try {
    const r = await fetch('/app/data/chart.json');
    if (r.ok) state.chart = await r.json();
  } catch (err) {
    state.chart = null;
  }
  // 행정구역. 인구와 관청 좌표가 여기서 온다.
  try {
    const r = await fetch('/app/data/regions.json');
    if (r.ok) state.regions = await r.json();
  } catch (err) {
    state.regions = null;
  }
  // 행정구역별·연도별 땅값. 없으면 그 테마 막대만 숨긴다.
  try {
    const r = await fetch('/app/data/landprice.json');
    if (r.ok) state.landPrice = await r.json();
  } catch (err) {
    state.landPrice = null;
  }
  // 판정은 분석이 한 번이라도 돈 뒤에야 생긴다. 없으면 그 탭만 비운다.
  // 토지와 공장을 따로 낸다 — 한 파일에 덮어쓰면 나중에 돈 쪽만 남아,
  // 공장을 돌렸는데 화면에는 토지가 떠 있는 일이 생긴다.
  state.verdictSets = {};
  await Promise.all([['land', 'verdicts'], ['factory', 'verdicts_factory']]
    .map(async ([k, name]) => {
      try {
        const r = await fetch(`/app/data/${name}.json`);
        if (r.ok) state.verdictSets[k] = await r.json();
      } catch (err) { /* 없으면 그 종류만 안 보인다 */ }
    }));
  state.verdictKind = state.verdictSets.land ? 'land' : 'factory';
  state.verdicts = state.verdictSets[state.verdictKind] || null;

  // 4분위는 지도와 무관하게 미리 잡는다. buildMap 안에서 잡으면 Leaflet 이
  // 없을 때(CDN 차단·오프라인) 계산 자체를 건너뛰고, 범례가 실제 교통량
  // 대신 '하위 25%' 같은 맹탕 문구로 떨어진다.
  // 기준 연도는 자료의 마지막 해. 연도 선택이 이 값에서 시작한다.
  const _ty = (state.traffic || {}).years || [];
  state.tgYear = _ty.length ? _ty[_ty.length - 1] : null;
  state.tiers = buildTiers();

  // 검사가 설정값을 읽을 수 있게 열어 둔다. 밴드 개수를 검사에 박아 두면
  // 밴드를 조정할 때마다 멀쩡한 검사가 빨개진다.
  window.__bands = state.meta.bands_km || [];

  buildFilters();
  // buildFilters 가 기본 연도를 정한다. 그 해 파일을 여기서 받아 둔다 —
  // 안 받으면 처음 화면이 전 기간 표본으로 그려져, 연도 칸이 가리키는
  // 해와 지도에 찍힌 점이 서로 다른 해가 된다.
  if (state.yearFrom != null) await loadTradeYears(state.yearFrom, state.yearTo);
  buildRank();
  buildTrend();
  buildMap();
  wireMapChrome();
  wireBaseMap();
  wireValueButtons();
  wireLandPrice();
  drawLandPrice();
  buildLegend();
  buildMatrix();
  buildBoardTable();
  buildVerdict();
  initListings();
}

function showFatal(message) {
  document.body.innerHTML =
    `<div style="padding:3rem 1.5rem;max-width:34rem;margin:0 auto">
       <h1 style="font-size:1.1rem;margin-bottom:.5rem">데이터를 불러오지 못했습니다</h1>
       <p style="color:#5B6875">${message}</p>
       <p style="color:#5B6875">먼저 <code>make web</code> 를 실행해 <code>public/app/data/</code> 를 생성하세요.
       파일을 직접 열면(<code>file://</code>) 브라우저가 차단하므로 로컬 서버로 열어야 합니다.</p>
     </div>`;
}

/* 물음표 하나에 설명 한 덩이 (요구사항 2026-09-08:
 * "지금은 무슨 책같아서 뭘 봐야할 지 모르겠습니다").
 *
 * 설명이 틀린 것은 아니었다 — 왜 이 셋만 켜 두는지, 도로접이 왜 1.7배인지는
 * 알아야 한다. 다만 **처음 여는 사람이 조작부를 못 찾는다.** 필터가
 * 열두 줄짜리 설명 사이에 파묻혀 있으면, 읽지도 않고 만지지도 못한다.
 *
 * 지우지 않고 접는다. 지우면 '왜 계획관리만 켜져 있나' 를 물을 곳이
 * 없어진다. */
function wireWhy() {
  document.querySelectorAll('.info-dot').forEach((btn) => {
    // 설명은 제목 **다음 형제**다. 그래야 표시가 제목 옆에 붙는다.
    const body = btn.closest('h2, h3').nextElementSibling;
    if (!body || !body.classList.contains('info-pop')) return;
    btn.addEventListener('click', () => {
      const open = body.hidden;
      body.hidden = !open;
      btn.setAttribute('aria-expanded', String(open));
      btn.classList.toggle('is-on', open);
    });
  });
}

/* 큰 분류 셋 — 실거래 표시 / IC / 실거래 가격 (요구사항 2026-09-08).
 *
 * 왼쪽 레일을 통째로 없앴다. 필터가 지도 옆에 늘 펼쳐져 있으면 지도가
 * 그만큼 좁아지는데, 실제로 만지는 것은 한 번에 한 묶음뿐이다. 칩을
 * 누르면 그 묶음만 아래에서 올라온다 (호갱노노가 하는 것이 이것이다). */
const SHEET_TITLE = {
  trade: '실거래 표시', ic: 'IC', price: '실거래 가격',
};

function openSheet(cat) {
  const sheet = document.getElementById('sheet');
  if (!sheet) return;
  const same = sheet.dataset.cat === cat && !sheet.hidden;
  document.querySelectorAll('.cat').forEach((b) => {
    b.classList.toggle('is-on', !same && b.dataset.cat === cat);
  });
  const side = document.getElementById('side');
  if (same) {
    sheet.hidden = true; sheet.dataset.cat = '';
    if (side) side.classList.remove('is-open');
    if (map) setTimeout(() => map.invalidateSize(), 200);
    return;
  }
  if (side) side.classList.add('is-open');
  sheet.hidden = false;
  sheet.dataset.cat = cat;
  const title = document.getElementById('sheet-title');
  if (title) title.textContent = SHEET_TITLE[cat] || '';
  sheet.querySelectorAll('.sheet-pane').forEach((p) => {
    p.hidden = p.dataset.cat !== cat;
  });
  // 왼쪽 칸이 벌어지면 지도 폭이 바뀐다. Leaflet 에 알려주지 않으면
  // 새로 드러난 부분이 회색으로 남는다.
  if (map) setTimeout(() => map.invalidateSize(), 220);
}

function wireSheet() {
  document.querySelectorAll('.cat').forEach((b) => {
    b.addEventListener('click', () => openSheet(b.dataset.cat));
  });
  const close = document.getElementById('sheet-close');
  if (close) {
    close.addEventListener('click', () => {
      const sheet = document.getElementById('sheet');
      if (sheet) { sheet.hidden = true; sheet.dataset.cat = ''; }
      const side = document.getElementById('side');
      if (side) side.classList.remove('is-open');
      document.querySelectorAll('.cat').forEach((b) => b.classList.remove('is-on'));
      if (map) setTimeout(() => map.invalidateSize(), 220);
    });
  }
}

function wireTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => showView(tab.dataset.view));
  });
  showHiddenView();
  window.addEventListener('hashchange', showHiddenView);
}

function showView(key) {
  document.querySelectorAll('.tab').forEach((t) => {
    const on = t.dataset.view === key;
    t.classList.toggle('is-active', on);
    t.setAttribute('aria-selected', String(on));
  });
  document.querySelectorAll('.view').forEach((v) => v.classList.remove('is-active'));
  const view = $(`#view-${key}`);
  if (view) view.classList.add('is-active');
  if (key === 'explore' && map) map.invalidateSize();
}

/* 접어 둔 화면으로 가는 길 (요구사항 2026-09-10).
 *
 * 탭 넷을 숨겼지만 **지운 것이 아니다** — 화면도 코드도 자료도 그대로
 * 있다. 다시 쓸 날이 오면 index.html 의 hidden 한 글자만 떼면 된다.
 *
 * 그때까지도 우리는 그 화면을 봐야 한다(배포가 안 깨졌는지). 주소 끝에
 * #rank · #trend · #board · #verdict 를 붙이면 열린다. 숨긴 탭도 이때는
 * 같이 보여 준다 — 화면만 열고 탭을 감추면 돌아갈 길이 없다. */
function showHiddenView() {
  const key = (location.hash || '').replace('#', '');
  if (!key) return;
  const tab = document.querySelector(`.tab[data-view="${key}"]`);
  if (!tab) return;
  if (tab.hidden) tab.hidden = false;
  showView(key);
}

/* ─────────── 필터 ─────────── */
function buildFilters() {
  const counts = {};
  state.tollgates.forEach((t) => {
    const key = t.quadrant_key || 'none';
    counts[key] = (counts[key] || 0) + 1;
  });

  // ── IC 교통량: 기준 연도 · 차종 ──
  const years = (state.traffic || {}).years || [];
  const ySel = $('#tg-year');
  years.slice().reverse().forEach((y) => {
    const o = el('option', null, `${y}년`);
    o.value = String(y);
    ySel.append(o);
  });
  ySel.value = String(state.tgYear);
  ySel.addEventListener('change', () => {
    state.tgYear = Number(ySel.value);
    recolorTollgates();
  });

  buildVehiclePicker();

  // 구간 필터 — 예전 '분면 필터'(저평가·과열 등) 자리다. 분면은 평가라
  // 오해를 부르고, 지도 색과 뜻이 달라 혼란스러웠다. 지도 색과 필터가
  // 같은 것을 가리키는 편이 낫다.
  const tierBox = $('#tier-filters');
  trafficLabels(TRAFFIC_CUTS).forEach((label, i) => {
    const btn = el('button', 'quad-btn');
    btn.type = 'button';
    btn.dataset.tier = String(i);
    btn.style.setProperty('--c', `var(--tg-${i + 1})`);
    btn.setAttribute('aria-pressed', 'true');
    btn.append(el('span', 'dot'), el('span', null, label),
               el('span', 'n', '0'));
    btn.addEventListener('click', () => {
      const on = btn.getAttribute('aria-pressed') === 'true';
      btn.setAttribute('aria-pressed', String(!on));
      on ? state.activeTiers.delete(i) : state.activeTiers.add(i);
      refreshMap();
    });
    tierBox.append(btn);
  });
  // 신설 — 그 해에 처음 교통량이 잡힌 영업소
  const newBtn = el('button', 'quad-btn');
  newBtn.type = 'button';
  newBtn.dataset.tier = 'new';
  newBtn.style.setProperty('--c', 'var(--tg-new)');
  newBtn.setAttribute('aria-pressed', 'true');
  newBtn.append(el('span', 'dot'), el('span', null, '신설'),
                el('span', 'n', '0'));
  newBtn.addEventListener('click', () => {
    const on = newBtn.getAttribute('aria-pressed') === 'true';
    newBtn.setAttribute('aria-pressed', String(!on));
    on ? state.activeTiers.delete('new') : state.activeTiers.add('new');
    refreshMap();
  });
  tierBox.append(newBtn);

  // 통행량 미공개 — 켜 두는 것이 기본이다. 마도처럼 실재하는 IC 가
  // 지도에서 사라지는 것이 지금까지의 문제였다.
  const noneBtn = el('button', 'quad-btn is-hollow');
  noneBtn.type = 'button';
  noneBtn.dataset.tier = 'none';
  noneBtn.style.setProperty('--c', 'var(--tg-none)');
  noneBtn.setAttribute('aria-pressed', 'true');
  noneBtn.title = '민자 운영사가 요금을 직접 걷는 노선. 도로공사 TCS 공공데이터에 통행량이 없습니다.';
  noneBtn.append(el('span', 'dot'), el('span', null, '통행량 미공개'),
                 el('span', 'n', '0'));
  noneBtn.addEventListener('click', () => {
    const on = noneBtn.getAttribute('aria-pressed') === 'true';
    noneBtn.setAttribute('aria-pressed', String(!on));
    on ? state.activeTiers.delete('none') : state.activeTiers.add('none');
    refreshMap();
  });
  tierBox.append(noneBtn);

  const kinds = $('#kind-filters');
  // 공장과 창고를 갈라 보여준다. 국토부 15126470 은 '공장 및 창고 등'
  // 자료라 창고가 처음부터 같이 들어와 있었는데, 한 칸에 담아 두어
  // 가릴 수가 없었다. (2026-09-07 지시)
  //
  // 칸을 자료에서 만든다. 갈리지 않은 것이 있으면 그 칸도 만들어 몇
  // 건인지 적는다 — 안 보여주면 그만큼이 조용히 사라진다.
  const mix = state.meta.usage_mix || {};
  const options = [];
  (state.meta.kinds || []).forEach((kind) => {
    if (kind !== 'factory') {
      options.push({ key: kind, label: KIND_LABEL[kind] || kind });
      return;
    }
    // 건물주용도를 **그대로** 늘어놓는다. 처음에는 공장/창고/기타 셋으로
    // 줄였는데, 실제 자료(run 33)에서 그 '기타' 41,588건이 축사·온실
    // (동물 및 식물 관련시설), 정비소(자동차 관련시설), 주유소(위험물
    // 저장 및 처리시설)로 **또렷이 갈려 있었다.** 모르는 것이 아니라
    // 아는 것들을 한 칸에 뭉쳐 놓고 '미상' 이라고 부르고 있었던 셈이다.
    // 값이 7종뿐이라 뭉갤 이유가 없다.
    Object.keys(mix)
      .sort((a, b) => (mix[b] || 0) - (mix[a] || 0))
      .forEach((name) => {
        if (!mix[name]) return;
        options.push({ key: `factory:${name}`, label: name, n: mix[name] });
      });
  });
  options.forEach(({ key, label: text, n, title }) => {
    const label = el('label', 'check');
    if (title) label.title = title;
    const input = el('input');
    input.type = 'checkbox';
    // 처음에는 꺼 둔다 (state.activeKinds 가 비어 있는 것과 짝이 맞아야 한다).
    input.checked = state.activeKinds.has(key);
    // 토지 하위 필터가 이 칸을 찾아 켤 수 있어야 한다 (ensureLandOn).
    input.dataset.key = key;
    input.addEventListener('change', () => {
      input.checked ? state.activeKinds.add(key) : state.activeKinds.delete(key);
      refreshMap();
    });
    const suffix = (typeof n === 'number')
      ? ` <span class="n">${n.toLocaleString('ko-KR')}건</span>` : '';
    const span = el('span');
    span.innerHTML = text + suffix;
    label.append(input, span);
    kinds.append(label);
  });

  /* **토지 하위 필터를 만지면 토지를 켠다.**
   *
   * 보고된 문제(2026-09-08): "제2종일반주거지역 처럼 일부 용도지역 클릭 시
   * 지도에 표기되지 않습니다."
   *
   * 고장이 아니라 덫이었다. 용도지역·개발단계·도로접은 **토지에만 거는
   * 조건**인데, 물건 종류에서 '토지' 가 꺼져 있으면(처음이 그렇다) 아무리
   * 켜도 걸러낼 토지가 없다. 화면은 아무 말도 안 하고 비어 있다.
   *
   * 조건을 켠 사람은 그것을 보고 싶은 것이다. 토지를 같이 켠다. */
  function ensureLandOn() {
    if (state.activeKinds.has('land')) return;
    state.activeKinds.add('land');
    const box = document.getElementById('kind-filters');
    if (box) {
      box.querySelectorAll('input').forEach((i) => {
        if (i.dataset.key === 'land') i.checked = true;
      });
    }
  }

  /* ── 토지: 개발단계 · 용도지역 ──
   *
   * 요구사항(2026-09-07). 토지 표본의 78% 가 전·답·임야인데, 그
   * 값은 개발 가능 여부·도로접·모양이 정한다. 실거래 자료는 그 셋을
   * 하나도 안 준다(scripts/land_shape_probe.py 가 확인 중). 우리가 쥔
   * 유일한 단서가 지목이라, 지목으로 개발단계를 갈라 놓고 고르게 한다.
   *
   * 칸은 자료에서 만든다. 없는 것은 칸도 안 생긴다. */
  const landBox = document.getElementById('land-box');
  const stageMix = state.meta.stage_mix || {};
  const luMix = state.meta.land_use_mix || {};
  // 토지가 아예 없으면 이 묶음을 통째로 숨긴다.
  //
  // **둘 다 비었을 때만 숨긴다.** 예전에는 stage_mix 만 봤는데, 개발단계
  // 칸을 뺀 지금(2026-09-09) 그 하나에 매달아 두면 개발단계 자료가
  // 없다는 이유로 도로접함·용도지역까지 통째로 사라진다.
  if (landBox) {
    landBox.hidden = !Object.keys(stageMix).length
                     && !Object.keys(luMix).length;
  }

  const nfmt = (v) => v.toLocaleString('ko-KR');

  // 개발단계 칸은 뺐다 (요구사항 2026-09-09: "토지-개발단계는 선택
  // 제외"). state.hasStageFilter 가 false 로 남으므로 visibleTrades 가
  // 이 조건을 통째로 건너뛴다 — **필터가 없는 것**이지 전부 끈 것이
  // 아니다. 그 둘은 다르고, 그 구분을 검사가 이미 못 박아 두었다.
  state.hasStageFilter = false;

  /* 도로 접함 — 요구사항(2026-09-07): "도로를 접하는 가가 제일
   * 중요합니다." 실측이 크기까지 확인했다: 차가 들어가느냐가 단가를
   * 남이천 +66%, 안성 +67% 가른다. 두 표본에서 같은 크기다.
   *
   * 칸 이름 옆에 건수를 적는다. 지금은 '조사 안 됨' 이 압도적인데,
   * 그것을 안 보여 주면 '차 진입 가능' 을 골랐을 때 지도가 텅 비는
   * 이유를 알 수가 없다. */
  const rsel = $('#road-filter');
  if (rsel) {
    const roadMix = state.meta.road_mix || {};
    const cnt = (k) => (typeof roadMix[k] === 'number'
      ? ` (${nfmt(roadMix[k])}건)` : '');
    const known = (roadMix['차 진입 가능'] || 0) + (roadMix['진입 어려움'] || 0);
    rsel.innerHTML =
      `<option value="all">전체${known ? '' : ' — 아직 조사 전'}</option>`
      + `<option value="ok">차 진입 가능${cnt('차 진입 가능')}</option>`
      + `<option value="no">진입 어려움 · 맹지${cnt('진입 어려움')}</option>`;
    rsel.value = state.roadFilter;
    // 조사된 것이 하나도 없으면 고를 수 있게 두지 않는다 — 골라 봐야
    // 지도가 비고, 왜 비는지는 안 보인다.
    rsel.disabled = !known;
    rsel.addEventListener('change', () => {
      state.roadFilter = rsel.value;
      // 도로 접함도 토지에만 거는 조건이다 (ensureLandOn 참조).
      if (rsel.value !== 'all') ensureLandOn();
      refreshMap();
    });
  }

  // 용도지역 칸은 뺐다 (요구사항 2026-09-10: "실거래 표시에서 용지역은
  // 삭제합니다. 항상 전체 표기 함").
  //
  // 스물다섯 종이 세로로 늘어서 왼쪽 칸의 절반을 먹었고, 처음에 셋만
  // 켜져 있어서 나머지 스물둘이 지도에서 빠진 채로 시작했다.
  //
  // **개발단계 때와 같은 방식으로 뺀다** — hasLandUseFilter 를 false 로
  // 두면 visibleTrades 가 이 조건을 통째로 건너뛴다. 집합을 비우는
  // 것과는 다르다. 비우면 '전부 끈 것' 이 되어 토지가 하나도 안 보인다.
  state.hasLandUseFilter = false;
  state.activeLandUse.clear();
  // 여전히 뒤에서 쓴다 — 땅값 글자의 용도지역 고르기(lp-groups)는
  // 그대로다. 그쪽은 지도에 적히는 중앙값을 정하는 것이라 성격이
  // 다르고, 분석 표본의 기준(CORE_LAND_USE)도 손대지 않는다.

  // ── 실거래 연도 — 좌/우 손잡이로 범위 ──
  //
  // 요구사항(2026-09-08): "실거래 연도는 좌/우로 선택해서 범위를 정할
  // 수 있도록 (호갱노노 참조)".
  //
  // **범위는 공짜가 아니다.** 해마다 파일이 따로 있고 한 해가 약 950KB 다.
  // 넓게 잡으면 그만큼 받는다. 그래서 MAX_YEAR_FILES 까지만 받고, 그보다
  // 넓히면 전 기간 표본으로 물러난다 — 어느 쪽인지 아래 줄이 말한다.
  const dealYears = (state.meta.trade_years || []).map((r) => r.year);
  if (dealYears.length) {
    const from = $('#year-from');
    const to = $('#year-to');
    const lo = dealYears[0];
    const hi = dealYears[dealYears.length - 1];
    [from, to].forEach((el) => { el.min = String(lo); el.max = String(hi); el.step = '1'; });
    // 기본은 **최근 두 해** (요구사항 2026-09-09: "거래 연도는
    // 2024~2025년 기본 세팅").
    //
    // 한 해로 두면 처음 보는 화면이 성겨서 '거래가 이것뿐인가' 로
    // 읽히고, 전 기간으로 두면 파일을 다섯 개씩 받는다. 두 해가
    // 그 사이다 — 자료가 한 해뿐이면 자연히 한 해로 줄어든다.
    const lo2 = Math.max(lo, hi - 1);
    from.value = String(lo2);
    to.value = String(hi);
    state.yearFrom = lo2;
    state.yearTo = hi;

    const paint = () => {
      const span = (hi - lo) || 1;
      const fill = document.getElementById('yr-fill');
      if (fill) {
        fill.style.left = `${((state.yearFrom - lo) / span) * 100}%`;
        fill.style.right = `${((hi - state.yearTo) / span) * 100}%`;
      }
      const out = document.getElementById('year-out');
      if (out) {
        out.textContent = state.yearFrom === state.yearTo
          ? `${state.yearFrom}년`
          : `${state.yearFrom} ~ ${state.yearTo}년`;
      }
    };

    const pull = async () => {
      // 두 손잡이가 엇갈리면 서로 밀어낸다. 안 그러면 '2020~2015' 같은
      // 뒤집힌 범위가 만들어지고 아무것도 안 보인다.
      let f = Number(from.value);
      let t = Number(to.value);
      if (f > t) { const m = f; f = t; t = m; }
      state.yearFrom = f;
      state.yearTo = t;
      paint();
      await loadTradeYears(f, t);
      refreshMap();
    };
    from.addEventListener('input', pull);
    to.addEventListener('input', pull);
    paint();
  }

  $('#parcel-only').addEventListener('change', (e) => {
    state.parcelOnly = e.target.checked;
    refreshMap();
  });

  // 처음 그릴 때도 개수를 채운다. 안 하면 전부 0 으로 보인다.
  updateTierCounts();
}

/* 거리 밴드 범례만 남긴다 (왼쪽 필터 안).
 *
 * 요구사항(2026-09-08): "좌측 범례 삭제". 지도 위 왼쪽 아래에 있던
 * 12줄짜리 범례를 없앤다. 지도를 키워 놓고 그 위를 범례로 다시 덮으면
 * 뜻이 없고, 담고 있던 것(거래 색·영업소 단·밴드)은 왼쪽 필터와
 * 말풍선에 이미 있다. */
function buildLegend() {
  const box = $('#band-legend');
  if (!box) return;
  box.innerHTML = shownBands()
    .map(([lo, hi], i) =>
      `<div class="row" style="--c:${bandColor(i)}">` +
      `<span class="ring"></span>${lo}–${hi} km</div>`)
    .join('');
}

/* ─────────── 교통량 순위 (지시4) ───────────
   traffic.json 하나만 읽는다. 구조는 자리를 아끼려고 접혀 있다.

     years  [2018 … 2025]
     types  [1 … 6]                       ← 차종 코드
     rows[].v[연도인덱스][차종인덱스]      ← 일평균 통행량 (대/일)

   값이 **일평균**인 것이 중요하다. 연 합계로 순위를 매기면 연중 개통한
   영업소가 다른 곳의 몇 분의 일로 찍혀 순위표가 통째로 틀어진다.        */

function trafficDisabled(message) {
  const tab = document.querySelector('.tab[data-view="rank"]');
  if (tab) tab.hidden = true;
  const note = $('#rank-note');
  if (note) { note.textContent = message; note.hidden = false; }
}

function buildRank() {
  const data = state.traffic;
  if (!data || !data.rows || !data.rows.length) {
    trafficDisabled('교통량 자료가 없습니다.');
    return;
  }

  const yearSel = $('#rank-year');
  yearSel.innerHTML = data.years
    .map((y) => `<option value="${y}">${y}년</option>`).join('');
  yearSel.value = String(data.years[data.years.length - 1]);
  state.rank.year = Number(yearSel.value);

  // 묶음(전체·화물·승용·중형)을 먼저, 그 다음 개별 차종.
  const groups = data.vehicle_groups || [];
  const types = data.vehicle_types || [];
  $('#rank-vehicle').innerHTML =
    `<optgroup label="묶음">${groups
      .map((g) => `<option value="g:${g.key}">${g.label}</option>`).join('')}</optgroup>` +
    `<optgroup label="개별 차종">${types
      .map((t) => `<option value="t:${t.code}">${t.label}</option>`).join('')}</optgroup>`;
  $('#rank-vehicle').value = 'g:total';

  const rerender = () => {
    state.rank.year = Number($('#rank-year').value);
    state.rank.vehicle = $('#rank-vehicle').value;
    state.rank.sort = $('#rank-sort').value;
    state.rank.q = $('#rank-search').value.trim();
    state.rank.coordsOnly = $('#rank-coords-only').checked;
    renderRank();
  };
  ['#rank-year', '#rank-vehicle', '#rank-sort', '#rank-coords-only']
    .forEach((sel) => $(sel).addEventListener('change', rerender));
  $('#rank-search').addEventListener('input', rerender);

  renderVehicleTables();
  buildRankIndex();
  // '지가 추이' 단추 — 행마다 리스너를 붙이지 않고 표 하나에서 받는다.
  $('#rank-table tbody').addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-trend');
    if (btn && !btn.disabled) openTrendPopup(btn.dataset.tg);
  });
  state.rank.vehicle = 'g:total';
  renderRank();
}

/* 검색 색인 (지시 2026-09-13). 영업소 이름과 지역(시·도, 시·군·구)을 목록으로
   내려 준다 — 적어도 되고 목록에서 골라도 된다. 검색은 여전히 부분 일치라
   '경기도' 를 고르면 경기도 영업소가 전부 남는다. */
function buildRankIndex() {
  const list = $('#rank-index');
  if (!list) return;
  const rows = (state.traffic || {}).rows || [];
  const names = [...new Set(rows.map((r) => r.name).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'ko'));
  const regions = new Set();
  rows.forEach((r) => {
    if (r.sido) regions.add(r.sido);
    if (r.sido && r.sigungu) regions.add(`${r.sido} ${r.sigungu}`);
  });
  const regionList = [...regions].sort((a, b) => a.localeCompare(b, 'ko'));
  list.innerHTML =
    names.map((n) => `<option value="${escapeHtml(n)}" label="영업소">`).join('') +
    regionList.map((n) => `<option value="${escapeHtml(n)}" label="지역">`).join('');
}

/* 최근 5년의 전년 대비 증감률 (지시 2026-09-13: '전년 대비' 한 칸 대신
   '최근 5년 YoY'). 왼쪽이 오래된 해. 값이 없는 해는 null 로 둔다 — 0 이 아니다. */
function rankYoy(row, yearIdx, codes, typeIdx, years) {
  const out = [];
  for (let k = 4; k >= 0; k -= 1) {
    const yi = yearIdx - k;
    const cur = yi >= 0 ? rankValue(row, yi, codes, typeIdx) : null;
    const prev = yi - 1 >= 0 ? rankValue(row, yi - 1, codes, typeIdx) : null;
    out.push({
      year: years[yi],
      v: cur != null && prev != null && prev > 0 && cur > 0 ? cur / prev - 1 : null,
    });
  }
  return out;
}

/* 다섯 막대 하나로. 위로 뻗으면 증가, 아래면 감소. ±15% 에서 자른다 —
   한 해의 개통 효과(수백 %)가 나머지 넷을 납작하게 만들지 않게. */
function yoyBars(yoy) {
  const W = 46; const H = 20; const mid = H / 2; const bw = 6; const gap = 4; const cap = 0.15;
  const bars = yoy.map((p, i) => {
    const x = i * (bw + gap) + 1;
    if (p.v == null) return `<circle cx="${x + bw / 2}" cy="${mid}" r="1.2" class="none"/>`;
    const h = Math.max(1, Math.min(Math.abs(p.v), cap) / cap * (mid - 1));
    const y = p.v >= 0 ? mid - h : mid;
    return `<rect x="${x}" y="${y.toFixed(1)}" width="${bw}" height="${h.toFixed(1)}" class="${p.v >= 0 ? 'up' : 'down'}"/>`;
  }).join('');
  const title = yoy.map((p) => `${p.year || '?'}년 ${p.v == null ? '—' : (p.v >= 0 ? '+' : '') + (p.v * 100).toFixed(1) + '%'}`).join(' · ');
  const last = yoy[yoy.length - 1];
  const lastTxt = last && last.v != null
    ? `<span class="delta ${last.v >= 0 ? 'up' : 'down'} last">${last.v >= 0 ? '+' : ''}${(last.v * 100).toFixed(1)}%</span>`
    : '<span class="hint last">—</span>';
  return `<span class="yoy" title="${escapeHtml(title)}"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-label="${escapeHtml(title)}">`
    + `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" class="base"/>${bars}</svg>${lastTxt}</span>`;
}

/* ── 차종 고르기 (요구사항 2026-09-09) ──────────────────────────
 *
 * "차종 선택을 여러개를 선택 할 수 있게 펼쳐 주시고 (용도지역처럼)
 *  1종, 2종 등 차종에 따른 이미지 및 간략 설명 넣어주세요."
 *
 * 드롭다운이라 **하나만** 고를 수 있었습니다. 그런데 이 제품이 보는
 * 것은 화물(2·3·4·5종)이라, 그것을 보려면 네 번 나눠 보고 머릿속에서
 * 더해야 했습니다. 펼쳐 놓고 여럿 고르게 합니다.
 *
 * ## 그림은 장식이 아닙니다
 *
 * 한국도로공사 차종은 **축 수와 크기**로 갈립니다(유료도로법 시행령
 * 별표1). '4종 대형화물' 이라는 이름만으로는 그것이 3축 10~20톤이라는
 * 것을 알 수 없습니다. 그래서 축 수와 덩치를 그대로 그립니다 — 그림이
 * 곧 그 차종의 정의입니다.
 *
 *   6종 경차      작은 몸통 · 2축
 *   1종 승용      승용차 · 2축
 *   2종 중형      조금 큼 · 2축
 *   3종 대형      큼 · 2축
 *   4종 대형화물  길고 · **3축**
 *   5종 특수화물  가장 길고 · **4축**
 */
const VEHICLE_ART = {
  6: { w: 26, h: 11, axles: 2, box: false },
  1: { w: 30, h: 11, axles: 2, box: false },
  2: { w: 34, h: 14, axles: 2, box: true },
  3: { w: 38, h: 16, axles: 2, box: true },
  4: { w: 44, h: 17, axles: 3, box: true },
  5: { w: 50, h: 18, axles: 4, box: true },
};

/* 옆에서 본 차 한 대. 축은 바퀴 수로 보인다. */
function vehicleIcon(code) {
  const a = VEHICLE_ART[code] || VEHICLE_ART[1];
  const W = 54; const H = 22;
  const x0 = (W - a.w) / 2;
  const baseY = H - 4;
  const bodyTop = baseY - a.h;
  const parts = [];
  if (a.box) {
    // 화물·승합 — 앞칸(운전실)과 짐칸.
    const cab = Math.max(9, a.w * 0.26);
    parts.push(`<rect x="${x0}" y="${bodyTop + a.h * 0.28}" width="${cab}"`
      + ` height="${a.h * 0.72}" rx="2"/>`);
    parts.push(`<rect x="${x0 + cab + 1}" y="${bodyTop}"`
      + ` width="${a.w - cab - 1}" height="${a.h}" rx="1.5"/>`);
  } else {
    // 승용 — 지붕이 얹힌 한 덩이.
    parts.push(`<rect x="${x0}" y="${bodyTop + a.h * 0.42}" width="${a.w}"`
      + ` height="${a.h * 0.58}" rx="3"/>`);
    parts.push(`<rect x="${x0 + a.w * 0.22}" y="${bodyTop}"`
      + ` width="${a.w * 0.48}" height="${a.h * 0.5}" rx="2.5"/>`);
  }
  // 바퀴 — **축 수가 이 차종의 정의다.** 앞 하나, 뒤에 나머지.
  const r = 2.6;
  const wheels = [x0 + a.w * 0.18];
  for (let i = 0; i < a.axles - 1; i += 1) {
    wheels.push(x0 + a.w * (0.62 + i * 0.15));
  }
  wheels.forEach((cx) => {
    parts.push(`<circle cx="${cx.toFixed(1)}" cy="${baseY}" r="${r}"/>`);
  });
  return `<svg class="veh-art" viewBox="0 0 ${W} ${H}" width="${W}"`
    + ` height="${H}" aria-hidden="true">${parts.join('')}</svg>`;
}

function vehicleCodes() {
  const all = ((state.traffic || {}).vehicle_types || []).map((v) => v.code);
  const on = all.filter((c) => state.tgVehicles.has(c));
  // 하나도 안 고르면 전체로 읽는다. 빈 지도를 보여 주는 것보다 낫다 —
  // 아래 안내가 '전체' 라고 말한다.
  return on.length ? on : all;
}

function buildVehiclePicker() {
  const box = document.getElementById('tg-vehicle');
  if (!box) return;
  const types = (state.traffic || {}).vehicle_types || [];
  box.innerHTML = '';
  types.forEach((v) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'veh-opt';
    b.dataset.code = String(v.code);
    b.title = v.desc || '';
    b.setAttribute('aria-pressed', String(state.tgVehicles.has(v.code)));
    b.innerHTML = vehicleIcon(v.code)
      + `<b>${escapeHtml(v.label)}</b>`
      + `<s>${escapeHtml(vehicleShort(v))}</s>`;
    b.addEventListener('click', () => {
      if (state.tgVehicles.has(v.code)) state.tgVehicles.delete(v.code);
      else state.tgVehicles.add(v.code);
      syncVehiclePicker();
      recolorTollgates();
    });
    box.appendChild(b);
  });
  const all = document.getElementById('veh-all');
  if (all) {
    all.addEventListener('click', () => {
      const every = types.every((v) => state.tgVehicles.has(v.code));
      state.tgVehicles.clear();
      if (!every) types.forEach((v) => state.tgVehicles.add(v.code));
      syncVehiclePicker();
      recolorTollgates();
    });
  }
  syncVehiclePicker();
}

/* 칸에 적을 한 줄. 자료의 desc 는 두세 문장이라 칸에 안 들어간다 —
   **첫 마디만** 적고 나머지는 마우스를 올렸을 때 보인다. */
function vehicleShort(v) {
  const d = String(v.desc || '');
  const cut = d.split('.')[0];
  return cut.length > 22 ? `${cut.slice(0, 22)}…` : cut;
}

function syncVehiclePicker() {
  const types = (state.traffic || {}).vehicle_types || [];
  document.querySelectorAll('.veh-opt').forEach((b) => {
    b.setAttribute('aria-pressed',
      String(state.tgVehicles.has(Number(b.dataset.code))));
  });
  const all = document.getElementById('veh-all');
  if (all) {
    all.textContent = types.every((v) => state.tgVehicles.has(v.code))
      ? '해제' : '전체';
  }
  window.__veh = [...state.tgVehicles].sort((a, b) => a - b);
}

/* 선택한 차종(또는 묶음)의 합계를 낸다. 값이 하나도 없으면 0 이 아니라 null 을
   돌려준다 — '통행량이 0' 과 '그 해 자료가 없음' 은 다른 말이라 순위표에서
   섞이면 안 된다. */
function rankValue(row, yearIdx, codes, typeIdx) {
  const grid = row.v[yearIdx];
  if (!grid) return null;
  let sum = 0;
  let seen = false;
  codes.forEach((code) => {
    const i = typeIdx.get(code);
    if (i == null) return;
    const v = grid[i];
    if (v == null) return;
    sum += v;
    seen = true;
  });
  return seen ? sum : null;
}

function renderRank() {
  const data = state.traffic;
  const yearIdx = data.years.indexOf(state.rank.year);
  const prevIdx = yearIdx - 1;
  const typeIdx = new Map(data.types.map((c, i) => [c, i]));

  const [scope, key] = state.rank.vehicle.split(':');
  const group = (data.vehicle_groups || []).find((g) => g.key === key);
  const codes = scope === 'g'
    ? (group ? group.types : data.types)
    : [Number(key)];
  const label = scope === 'g'
    ? (group ? group.label : '전체')
    : ((data.vehicle_types || []).find((t) => String(t.code) === key) || {}).label || key;

  const q = state.rank.q.toLowerCase();
  const rows = [];
  data.rows.forEach((r) => {
    if (state.rank.coordsOnly && (r.lat == null || r.lon == null)) return;
    if (q && !`${r.name} ${r.sido || ''} ${r.sigungu || ''}`.toLowerCase().includes(q)) return;
    const value = rankValue(r, yearIdx, codes, typeIdx);
    if (value == null || value <= 0) return;
    const prev = prevIdx >= 0 ? rankValue(r, prevIdx, codes, typeIdx) : null;
    // '전체' 를 고르면 비중은 언제나 100% 라 칸만 차지한다.
    const isAll = codes.length === data.types.length;
    const all = isAll ? null : rankValue(r, yearIdx, data.types, typeIdx);
    rows.push({
      ...r,
      value,
      growth: prev && prev > 0 ? value / prev - 1 : null,
      share: all && all > 0 ? value / all : null,
      yoy: rankYoy(r, yearIdx, codes, typeIdx, data.years),
      hasTrend: !!(state.chart && state.chart.rows && state.chart.rows[r.id]),
    });
  });

  const sorters = {
    volume: (a, b) => b.value - a.value,
    growth: (a, b) => (b.growth ?? -Infinity) - (a.growth ?? -Infinity),
    share: (a, b) => (b.share ?? -Infinity) - (a.share ?? -Infinity),
  };
  rows.sort(sorters[state.rank.sort] || sorters.volume);

  const max = rows.length ? Math.max(...rows.map((r) => r.value)) : 1;
  const body = $('#rank-table tbody');
  body.innerHTML = rows.map((r, i) => {
    const width = Math.max(2, (r.value / max) * 100);
    const trendBtn = r.hasTrend
      ? `<button type="button" class="btn-trend" data-tg="${escapeHtml(r.id)}">지가 추이</button>`
      : '<button type="button" class="btn-trend" disabled title="이 영업소는 추이 자료가 없습니다">지가 추이</button>';
    const region = [r.sido, r.sigungu].filter(Boolean).join(' ') ||
                   '<span class="hint">미상</span>';
    return `<tr>
      <td class="rank">${i + 1}</td>
      <td>${escapeHtml(r.name)}</td>
      <td>${region}</td>
      <td class="num bar"><span style="width:${width}%"></span><b>${num(r.value)}</b></td>
      <td class="act">${trendBtn}</td>
      <td class="num">${yoyBars(r.yoy)}</td>
      <td class="num">${r.share == null ? '—' : (r.share * 100).toFixed(1) + '%'}</td>
    </tr>`;
  }).join('');

  // 부가 설명은 뺐다 (지시 2026-09-13). 한 줄 요약은 표 제목 옆 툴팁으로만 남긴다.
  const missing = data.rows.length - rows.length;
  const h2 = document.querySelector('#view-rank h2');
  if (h2) {
    h2.title = `${state.rank.year}년 · ${label} — ${data.unit || '일평균 통행량 (대/일)'}. 영업소 ${rows.length}개` +
      (missing > 0 ? ` (그해 자료가 없는 ${missing}개 제외)` : '');
  }
  const note = $('#rank-note');
  if (note) { note.hidden = true; note.textContent = ''; }
}

function renderVehicleTables() {
  const data = state.traffic;
  $('#vt-table tbody').innerHTML = (data.vehicle_types || []).map((t) =>
    `<tr><th>${escapeHtml(t.label)}</th><td>${escapeHtml(t.desc)}</td></tr>`).join('');
  $('#vg-table tbody').innerHTML = (data.vehicle_groups || []).map((g) =>
    `<tr><th>${escapeHtml(g.label)}</th><td>${escapeHtml(g.desc)}</td></tr>`).join('');
}

/* ─────────── 추이 비교 (교통량 × 지가 × 공시지가 × 반경) ───────────

   단위가 제각각이다. 교통량은 대/일(십만 단위), 지가는 원/㎡(백만 단위).
   그대로 한 축에 겹치면 지가 선이 화면 꼭대기에 붙고 교통량은 바닥에
   깔린 직선이 된다. 그래서 기본은 **지수**다 — 각 계열의 기준연도를
   100으로 두고 그린다. 주식 비교차트가 하는 것과 같다.

   '원값' 을 고르면 축이 하나뿐이라 비교가 깨진다는 것을 화면에 적어 둔다.
   숨기지 않고 고를 수 있게 두되, 무슨 일이 벌어지는지는 말해 준다.       */

const TREND_KIND_LABEL = { land: '토지', factory: '공장·창고' };

function trendDisabled(message) {
  const tab = document.querySelector('.tab[data-view="trend"]');
  if (tab) tab.hidden = true;
  const note = $('#trend-note');
  if (note) note.textContent = message;
}

/* 그릴 수 있는 계열을 모두 모은다. 각 계열은 {key,label,group,color,dash,points}.
   points 는 {연도: 값}. 값이 없는 해는 아예 넣지 않는다 — 0 으로 채우면
   '거래가 없던 해' 가 '값이 0 인 해' 로 둔갑한다. */
function trendSeriesFor(id) {
  const out = [];
  const chart = state.chart || {};
  const row = (chart.rows || {})[id] || {};

  // 1) 교통량 — traffic.json 을 그대로 쓴다 (같은 숫자를 두 번 담지 않는다)
  const tr = state.traffic;
  if (tr) {
    const t = (tr.rows || []).find((r) => r.id === id);
    if (t) {
      const typeIdx = new Map(tr.types.map((c, i) => [c, i]));
      (tr.vehicle_groups || []).forEach((g, gi) => {
        const pts = {};
        tr.years.forEach((y, yi) => {
          const v = rankValue(t, yi, g.types, typeIdx);
          if (v != null && v > 0) pts[y] = v;
        });
        if (Object.keys(pts).length >= 2) {
          out.push({
            key: `traffic:${g.key}`, label: `교통량 · ${g.label}`, group: '교통량',
            color: TRAFFIC_COLORS[gi % TRAFFIC_COLORS.length], dash: false, thick: true,
            unit: '대/일', points: pts,
          });
        }
      });
    }
  }

  // 2) 지가 — 반경(밴드)별
  const bands = chart.bands || [];
  Object.entries(row.band || {}).forEach(([band, pts]) => {
    const i = Math.max(0, bands.indexOf(band));
    // 대조 밴드는 점선으로 끊는다. 두 가지 이유가 겹친다.
    //   뜻   영향범위 바깥의 기준선이라 '자료 계열' 과 성격이 다르다.
    //   색약 중립 회색과 승용(자홍)이 적록색약에서 ΔE 5.9 로 붙는다.
    //        색만으로는 구별이 안 되므로 모양이 그 몫을 대신한다.
    // **지가 계열은 전부 점선.** 교통량 계열은 실선이다.
    //
    // 한 그래프에 교통량 4계열 + 지가 3밴드까지 들어가는데, 일곱 색이
    // 서로 다 구별되게 만드는 것은 색상환 안에서 불가능하다. 선 모양으로
    // 무리를 갈라두면 색은 무리 안에서만 달라도 된다. 지도에서 밴드가
    // 점선인 것과도 말이 맞는다.
    out.push({
      key: `band:${band}`,
      label: `지가 · ${band} km`,
      group: '지가 (반경별)',
      color: bandColor(i), dash: true, unit: '원/㎡', points: pts,
    });
  });

  // 3) 지가 — 용도지역별 (영향범위 안에서만)
  Object.entries(row.land_use || {}).forEach(([use, pts], i) => {
    out.push({
      key: `use:${use}`, label: `지가 · ${use}`, group: '지가 (용도지역별)',
      color: USE_COLORS[i % USE_COLORS.length], dash: true, unit: '원/㎡', points: pts,
    });
  });

  // 4) 지가 — 물건 종류별
  Object.entries(row.kind || {}).forEach(([kind, pts]) => {
    out.push({
      key: `kind:${kind}`, label: `지가 · ${TREND_KIND_LABEL[kind] || kind}`,
      group: '지가 (물건 종류)',
      color: `var(--kind-${kind === 'factory' ? 'factory' : 'land'})`,
      dash: true, unit: '원/㎡', points: pts,
    });
  });

  // 5) 공시지가
  const lp = (chart.landprice || {});
  const lpPts = (lp.rows || {})[id];
  if (lpPts) {
    out.push({
      key: 'landprice', label: '공시지가', group: '공시지가',
      color: 'var(--accent)', dash: false, unit: '원/㎡', points: lpPts,
    });
  }
  return out;
}

// 밴드색과 겹치지 않는 색만 쓴다. --q-under 를 쓰다가 지가 5-10km(--band-4)와
// 똑같은 파랑이 나와 한 그래프에서 두 선을 구별할 수 없었다.
const TRAFFIC_COLORS = ['var(--traffic-1)', 'var(--traffic-2)',
                        'var(--traffic-3)', 'var(--traffic-4)'];
const USE_COLORS = ['var(--band-3)', 'var(--band-5)', 'var(--q-over)', 'var(--band-2)'];

function trendCandidates() {
  const chart = state.chart;
  if (!chart || !chart.rows) return [];
  const named = new Map(state.tollgates.map((t) => [t.tollgate_id, t]));
  const fromTraffic = new Map(((state.traffic || {}).rows || []).map((r) => [r.id, r]));
  return Object.keys(chart.rows).map((id) => {
    const t = named.get(id) || fromTraffic.get(id) || {};
    return {
      id,
      name: t.name || `영업소 ${id}`,
      region: [t.sido, t.sigungu].filter(Boolean).join(' '),
    };
  }).sort((a, b) => a.name.localeCompare(b.name, 'ko'));
}

function buildTrend() {
  const chart = state.chart;
  if (!chart || !chart.rows || !Object.keys(chart.rows).length) {
    trendDisabled((chart && chart.note) || '추이 자료가 없습니다.');
    return;
  }
  const list = trendCandidates();
  if (!list.length) { trendDisabled('그릴 영업소가 없습니다.'); return; }

  $('#trend-list').innerHTML = list
    .map((c) => `<option value="${escapeHtml(c.name)}${c.region ? ' · ' + escapeHtml(c.region) : ''}">`)
    .join('');

  document.querySelectorAll('#trend-scale .seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#trend-scale .seg-btn')
        .forEach((b) => b.classList.toggle('is-on', b === btn));
      state.trend.scale = btn.dataset.scale;
      renderTrend();
    });
  });
  $('#trend-base').addEventListener('change', () => {
    state.trend.base = Number($('#trend-base').value);
    renderTrend();
  });
  $('#trend-search').addEventListener('input', () => {
    const q = $('#trend-search').value.trim().split(' · ')[0].toLowerCase();
    const hit = list.find((c) => c.name.toLowerCase() === q)
             || list.find((c) => c.name.toLowerCase().includes(q) && q.length >= 2);
    if (hit && hit.id !== state.trend.id) selectTrend(hit.id);
  });

  selectTrend(list[0].id);
  state.trend.ready = true;
  initTrendDialog();
}

/* ── 추이 비교 팝업 (지시 2026-09-13, 슬라이드 3) ──
   IC 교통량 표의 '지가 추이' 단추가 연다. #view-trend 의 내용물(.trend-wrap)을
   <dialog> 안으로 옮겨 띄우고 닫으면 제자리로 돌려 놓는다 — 화면을 복제하지
   않으므로 리스너·상태가 하나다. <dialog> 를 모르는 브라우저에서는 예전처럼
   #trend 화면으로 간다. */
function initTrendDialog() {
  const dlg = $('#trend-dialog');
  if (!dlg) return;
  const putBack = () => {
    const wrap = dlg.querySelector('.trend-wrap');
    const home = $('#view-trend');
    if (wrap && home) home.appendChild(wrap);
  };
  $('#trend-dialog-close').addEventListener('click', () => dlg.close());
  dlg.addEventListener('close', putBack);
  // 바깥(배경)을 누르면 닫힌다. 안쪽 클릭은 target 이 dialog 자신이 아니다.
  dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
}

function openTrendPopup(id) {
  const dlg = $('#trend-dialog');
  const wrap = document.querySelector('#view-trend .trend-wrap');
  if (!state.trend.ready) return;
  if (!dlg || !wrap || typeof dlg.showModal !== 'function') {
    location.hash = 'trend';
    showHiddenView();
    selectTrend(id);
    return;
  }
  $('#trend-dialog-body').appendChild(wrap);
  if (!dlg.open) dlg.showModal();
  selectTrend(id);
  const info = trendCandidates().find((c) => c.id === id);
  $('#trend-dialog-title').textContent =
    `추이 비교 — ${info ? info.name : id}${info && info.region ? ' · ' + info.region : ''}`;
}

/* 영업소를 바꾸면 계열 구성이 달라진다. 켜둔 계열 중 남아 있는 것은 유지하고,
   처음 고른 영업소에서는 기본 조합(교통량 전체 + 영향범위 대표 지가)을 켠다. */
function selectTrend(id) {
  const first = state.trend.id == null;
  state.trend.id = id;
  const all = trendSeriesFor(id);
  const keys = new Set(all.map((s) => s.key));

  if (first) {
    const band = state.meta.band;
    ['traffic:total', 'traffic:freight', `band:${band}`]
      .forEach((k) => { if (keys.has(k)) state.trend.on.add(k); });
    if (![...state.trend.on].some((k) => k.startsWith('band:'))) {
      const anyBand = all.find((s) => s.key.startsWith('band:'));
      if (anyBand) state.trend.on.add(anyBand.key);
    }
  }
  // 이 영업소에 없는 계열은 켜둔 채로 두어도 무해하다 (다시 고르면 살아난다)

  const years = trendYears(all);
  const base = $('#trend-base');
  base.innerHTML = years.map((y) => `<option value="${y}">${y}년</option>`).join('');
  if (!years.includes(state.trend.base)) state.trend.base = years[0];
  base.value = String(state.trend.base);

  const info = trendCandidates().find((c) => c.id === id) || {};
  $('#trend-sub').textContent =
    `${info.name || id}${info.region ? ' · ' + info.region : ''}` +
    ` — 영업소 코드 ${id}`;
  if ($('#trend-search') !== document.activeElement) {
    $('#trend-search').value = info.name || '';
  }

  renderTrendPicker(all);
  renderTrend();
}

function trendYears(all) {
  const set = new Set();
  all.forEach((s) => Object.keys(s.points).forEach((y) => set.add(Number(y))));
  return [...set].sort((a, b) => a - b);
}

function renderTrendPicker(all) {
  const box = $('#trend-series');
  const groups = [];
  all.forEach((s) => {
    let g = groups.find((x) => x.name === s.group);
    if (!g) { g = { name: s.group, items: [] }; groups.push(g); }
    g.items.push(s);
  });

  const lp = (state.chart || {}).landprice || {};
  let html = groups.map((g) => `
    <div>
      <h3>${escapeHtml(g.name)}</h3>
      <div class="opts">${g.items.map((s) => `
        <label class="series-opt${state.trend.on.has(s.key) ? '' : ' is-off'}">
          <input type="checkbox" data-key="${escapeHtml(s.key)}"
                 ${state.trend.on.has(s.key) ? 'checked' : ''}>
          <span class="sw${s.dash ? ' dashed' : ''}${s.thick ? ' thick' : ''}" style="--c:${s.color}"></span>
          <span>${escapeHtml(s.label)}</span>
          <span class="why">${Object.keys(s.points).length}년</span>
        </label>`).join('')}</div>
    </div>`).join('');

  // 공시지가가 없으면 '선이 안 보이는 것' 과 '자료가 없는 것' 을 구분해 준다.
  if (!lp.available) {
    html += `<div><h3>공시지가</h3><p class="hint">${
      escapeHtml(lp.reason || '아직 확보하지 못했습니다.')}</p></div>`;
  }
  box.innerHTML = html;

  box.querySelectorAll('input[type=checkbox]').forEach((el) => {
    el.addEventListener('change', () => {
      el.checked ? state.trend.on.add(el.dataset.key) : state.trend.on.delete(el.dataset.key);
      el.closest('.series-opt').classList.toggle('is-off', !el.checked);
      renderTrend();
    });
  });
}

function renderTrend() {
  const svg = $('#trend-chart');
  const all = trendSeriesFor(state.trend.id);
  const picked = all.filter((s) => state.trend.on.has(s.key));
  const legend = $('#trend-legend');

  if (!picked.length) {
    svg.innerHTML = '';
    legend.innerHTML = '';
    $('#trend-note').textContent = '오른쪽에서 계열을 하나 이상 고르세요.';
    return;
  }

  const years = trendYears(picked);
  if (years.length < 2) {
    svg.innerHTML = '';
    legend.innerHTML = '';
    $('#trend-note').textContent = '고른 계열에 그릴 만한 연도가 부족합니다.';
    return;
  }

  const indexed = state.trend.scale === 'index';
  const base = years.includes(state.trend.base) ? state.trend.base : years[0];

  // 지수화: 기준연도 값이 없는 계열은 **그 계열이 가진 가장 이른 해**를 쓰고,
  // 그 사실을 범례에 적는다. 조용히 다른 기준을 쓰면 비교가 거짓말이 된다.
  const prepared = picked.map((s) => {
    const has = Object.keys(s.points).map(Number).sort((a, b) => a - b);
    const anchor = s.points[base] != null ? base : has[0];
    const div = s.points[anchor];
    const vals = years.map((y) => {
      const raw = s.points[y];
      if (raw == null) return null;
      return indexed ? (div ? (raw / div) * 100 : null) : raw;
    });
    return { ...s, vals, anchor, rebased: anchor !== base };
  });

  const flat = prepared.flatMap((s) => s.vals).filter((v) => v != null);
  let lo = Math.min(...flat), hi = Math.max(...flat);
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.12;
  lo -= pad; hi += pad;
  if (indexed) { lo = Math.min(lo, 95); hi = Math.max(hi, 105); }

  const W = 720, H = 300, L = 52, R = 14, T = 14, B = 30;
  const sx = (y) => L + ((y - years[0]) / Math.max(1, years[years.length - 1] - years[0]))
                        * (W - L - R);
  const sy = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  const ticks = 5;
  let grid = '';
  for (let i = 0; i <= ticks; i++) {
    const v = lo + ((hi - lo) * i) / ticks;
    const y = sy(v);
    grid += `<line class="grid" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    grid += `<text class="axis" x="${L - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end">${
      indexed ? Math.round(v) : compact(v)}</text>`;
  }
  if (indexed && lo < 100 && hi > 100) {
    grid += `<line class="baseline" x1="${L}" y1="${sy(100).toFixed(1)}" x2="${W - R}" y2="${sy(100).toFixed(1)}"/>`;
  }
  years.forEach((y) => {
    grid += `<text class="axis" x="${sx(y).toFixed(1)}" y="${H - B + 16}" text-anchor="middle">${y}</text>`;
  });

  // 결측 해는 선을 끊는다. 이어 버리면 없는 관측을 있는 것처럼 그리게 된다.
  const paths = prepared.map((s) => {
    let d = '', open = false, dots = '';
    s.vals.forEach((v, i) => {
      if (v == null) { open = false; return; }
      const x = sx(years[i]).toFixed(1), y = sy(v).toFixed(1);
      d += `${open ? 'L' : 'M'}${x} ${y}`;
      open = true;
      dots += `<circle class="dot" cx="${x}" cy="${y}" r="2.6" fill="${s.color}"/>`;
    });
    const cls = `series${s.dash ? ' dashed' : ''}${s.thick ? ' thick' : ''}`;
    return `<path class="${cls}" d="${d}" stroke="${s.color}"/>${dots}`;
  }).join('');

  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = grid + paths +
    `<line class="lead" id="trend-lead" x1="0" y1="${T}" x2="0" y2="${H - B}" style="display:none"/>`;

  legend.innerHTML = prepared.map((s) =>
    `<span class="item"><span class="sw${s.dash ? ' dashed' : ''}${s.thick ? ' thick' : ''}" style="--c:${s.color}"></span>${
      escapeHtml(s.label)}${s.rebased ? ` <em>(기준 ${s.anchor})</em>` : ''}</span>`).join('');

  $('#trend-note').innerHTML = indexed
    ? `<strong>${base}년 = 100</strong> 인 지수입니다. 단위가 다른 계열을 겹쳐 보려면` +
      ' 이 방법뿐입니다. 선이 위로 벌어질수록 그 계열이 기준연도보다 많이 오른 것입니다.' +
      (prepared.some((s) => s.rebased)
        ? ' 일부 계열은 기준연도 값이 없어 <strong>자기 첫 해</strong>를 기준으로 삼았습니다(범례 표시).'
        : '')
    : '<strong>원값</strong>입니다. 축이 하나뿐이라 단위가 큰 계열이 화면을 차지합니다 —' +
      ' 값을 확인할 때만 쓰고, 비교는 지수로 하세요.';

  wireTrendHover(svg, prepared, years, sx, indexed);
}

const compact = (v) => {
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(1) + '억';
  if (a >= 1e4) return Math.round(v / 1e4).toLocaleString('ko-KR') + '만';
  return Math.round(v).toLocaleString('ko-KR');
};

function wireTrendHover(svg, prepared, years, sx, indexed) {
  const readout = $('#trend-readout');
  const lead = svg.querySelector('#trend-lead');
  const move = (ev) => {
    const box = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    const x = ((ev.clientX - box.left) / box.width) * vb.width;
    let best = years[0], bd = Infinity;
    years.forEach((y) => { const d = Math.abs(sx(y) - x); if (d < bd) { bd = d; best = y; } });
    const i = years.indexOf(best);
    lead.setAttribute('x1', sx(best).toFixed(1));
    lead.setAttribute('x2', sx(best).toFixed(1));
    lead.style.display = '';
    readout.hidden = false;
    readout.innerHTML = `<div class="yr">${best}년</div>` + prepared.map((s) => {
      const v = s.vals[i];
      const raw = s.points[best];
      const shown = v == null ? '—'
        : indexed ? `${v.toFixed(1)} <span class="hint">(${compact(raw)})</span>`
                  : compact(raw);
      return `<div class="row"><span class="sw" style="--c:${s.color}"></span>` +
             `<span class="nm">${escapeHtml(s.label)}</span><b>${shown}</b></div>`;
    }).join('');
  };
  svg.addEventListener('mousemove', move);
  svg.addEventListener('touchmove', (e) => { move(e.touches[0]); }, { passive: true });
  svg.addEventListener('mouseleave', () => {
    readout.hidden = true;
    if (lead) lead.style.display = 'none';
  });
}

/* ─────────── 영업소 교통량 4분위 ─────────── */
/* 지도의 영업소 색은 **교통량이 많은 순서**다. 잘한 곳/못한 곳을 매기는
 * 것이 아니다. 예전에는 분면(저평가·과열 등) 색을 썼는데, 그것은 평가라
 * 오해를 부르고 무엇보다 442곳 중 83곳만 값이 있어 나머지가 전부 같은
 * 색으로 찍혔다.
 *
 * 교통량은 traffic.json 에 484곳이 다 있다. 4분위는 순서형이므로 한 색상의
 * 명도 단계로 그린다 — 진할수록 교통량이 많다. */
/* 영업소 교통량 구간 — **고정 경계**다.
 *
 * 4분위(전국 상위 25%)로 나눴더니 수도권을 확대하면 거의 전부가 최상위로
 * 떨어졌다. 전국 기준 분위는 수도권 안에서 아무것도 안 가른다.
 * 1만대 단위 고정 경계로 바꾸면 같은 화면에서 네 단계가 다 나온다.
 *
 *   ~1만    232곳      1~2만  106곳
 *   2~3만    53곳      3만+    84곳
 */
const TRAFFIC_CUTS = [10000, 20000, 30000];
const TRAFFIC_TIERS = TRAFFIC_CUTS.length + 1;

/* **차종을 골라 보면 경계가 따라 내려간다** (요구사항 2026-09-10).
 *
 * 보고: "차량 종류 선택 시 일평균 통행량이 줄어드는데 기준이 최소
 * 1만대라서 분별이 안됩니다."
 *
 * 맞습니다. 5종만 켜면 대부분 영업소가 수백~수천 대라 1만대 경계
 * 아래로 다 몰려 **지도가 한 색**이 됩니다. 고정 경계는 '전체' 를
 * 볼 때만 뜻이 있습니다.
 *
 * 그래서 전체를 볼 때는 지금 경계를 그대로 두고, 일부만 골랐을 때는
 * **그 선택에서 가장 많은 곳**을 기준으로 네 단계를 새로 끊습니다.
 * 해마다·차종마다 경계가 달라지므로 범례에 숫자를 적어 둡니다 —
 * 안 적으면 어제 본 색과 오늘 본 색이 다른 뜻이 됩니다.
 */
function niceStep(v) {
  // 1·2·5 × 10^n 으로 올린다. 사람이 읽는 눈금이다.
  // 백 단위 아래로는 안 내려간다 — 요구사항의 "최소 백단위".
  if (!(v > 0)) return 100;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const head = v / pow;
  const nice = head <= 1 ? 1 : head <= 2 ? 2 : head <= 5 ? 5 : 10;
  return Math.max(100, nice * pow);
}

/** 몇 대인지 사람 말로. 만 단위가 넘으면 '만' 으로 적는다. */
function volWord(v) {
  if (v >= 10000) {
    const man = v / 10000;
    return `${Number.isInteger(man) ? man : man.toFixed(1)}만대`;
  }
  return `${v.toLocaleString('ko-KR')}대`;
}

function trafficLabels(cuts) {
  return cuts.map((c, i) => (i === 0
    ? `${volWord(c)} 미만`
    : `${volWord(cuts[i - 1])}~${volWord(c)}`))
    .concat(`${volWord(cuts[cuts.length - 1])} 이상`);
}

/** 지금 고른 차종에 맞는 경계. 전체면 고정, 일부면 최대값 기준. */
function trafficCuts(vol) {
  const all = ((state.traffic || {}).vehicle_types || []).map((v) => v.code);
  const picked = vehicleCodes();
  if (!all.length || picked.length >= all.length) return TRAFFIC_CUTS;
  let max = 0;
  vol.forEach((v) => { if (v > max) max = v; });
  // 네 단계로 나누므로 한 칸은 최대값의 1/4 이다. 그것을 사람이 읽는
  // 눈금으로 올린다. 최대값이 1만을 넘으면 고정 경계가 이미 맞는다.
  const step = niceStep(max / 4);
  if (step * 3 >= TRAFFIC_CUTS[2]) return TRAFFIC_CUTS;
  return [step, step * 2, step * 3];
}

/* 선택한 연도·차종의 영업소별 교통량. 둘 다 사용자가 고른다 —
 * 2003년 화물만 보고 싶을 수도 있고, 올해 전체를 보고 싶을 수도 있다. */
function tollgateVolumes(year, vehicle) {
  const tr = state.traffic || {};
  const years = tr.years || [];
  const types = tr.types || [];
  const yi = years.indexOf(year);
  if (yi < 0) return new Map();
  // 고른 차종의 **합**이다. 예전에는 하나만 골랐지만 이제 여럿이다.
  const idx = (Array.isArray(vehicle) ? vehicle : [vehicle])
    .map((c) => types.indexOf(Number(c))).filter((i) => i >= 0);
  const out = new Map();
  (tr.rows || []).forEach((r) => {
    const yv = (r.v || [])[yi];
    if (!Array.isArray(yv)) return;
    const total = idx.reduce((a, i) => a + (Number(yv[i]) || 0), 0);
    if (total > 0) out.set(String(r.id), total);
  });
  return out;
}

/* 그 해에 **처음** 교통량이 잡힌 영업소 = 신설.
 *
 * 이전 해에 값이 없다가 그 해에 생겼다는 뜻이다. 개통 효과를 보는
 * 이 제품에서 신설 IC 는 가장 중요한 관측 대상이라, 교통량 구간에
 * 섞지 않고 따로 표시한다 — 신설은 '교통량이 적은 곳' 이 아니라
 * '이제 막 생긴 곳' 이다. */
function newTollgates(year) {
  const tr = state.traffic || {};
  const years = tr.years || [];
  const yi = years.indexOf(year);
  const out = new Set();
  if (yi <= 0) return out;          // 첫 해는 비교 대상이 없다
  (tr.rows || []).forEach((r) => {
    const v = r.v || [];
    const now = Array.isArray(v[yi])
      ? v[yi].reduce((a, b) => a + (Number(b) || 0), 0) : 0;
    if (now <= 0) return;
    const before = v.slice(0, yi).some(
      (yv) => Array.isArray(yv) && yv.reduce((a, b) => a + (Number(b) || 0), 0) > 0);
    if (!before) out.add(String(r.id));
  });
  return out;
}

/* 값 → 0..3. 경계는 고정이라 해마다 흔들리지 않는다 — 작년과 올해 지도를
 * 나란히 놓고 비교할 수 있다는 뜻이다. */
function buildTiers() {
  const year = state.tgYear;
  const vol = tollgateVolumes(year, vehicleCodes());
  const fresh = newTollgates(year);
  const cuts = trafficCuts(vol);
  const tier = new Map();
  vol.forEach((v, id) => {
    if (fresh.has(id)) { tier.set(id, 'new'); return; }
    let q = 0;
    while (q < cuts.length && v >= cuts[q]) q++;
    tier.set(id, q);
  });
  // 통행량 미공개 — 도로공사 TCS 에 한 해도 값이 없는 영업소. 민자
  // 운영사가 요금을 직접 걷는 노선이라 도로공사가 자료를 갖고 있지
  // 않다(마도 등). 0 으로 두면 '가장 한산한 IC' 로 줄을 서서 정반대의
  // 결론이 나오므로, 구간이 아니라 별도 상태로 둔다.
  (state.tollgates || []).forEach((t) => {
    if (t.no_traffic) tier.set(String(t.tollgate_id), 'none');
  });
  return { rank: tier, vol, cut: cuts, fresh };
}

/* 연도·차종을 바꾸면 마커 색·크기를 다시 칠한다. 지도를 새로 만들지
 * 않는다 — 442개를 다시 그리면 화면이 한 번 껌뻑인다. */
function recolorTollgates() {
  state.tiers = buildTiers();
  const { rank, vol } = state.tiers;
  state.tollgates.forEach((t) => {
    const m = markers.get(t.tollgate_id);
    if (!m) return;
    styleTollgate(m, t, rank.get(String(t.tollgate_id)),
                  vol.get(String(t.tollgate_id)));
  });
  updateTierCounts();
  refreshMap();
  // 인구도 같은 해를 본다. 교통량은 2026년인데 인구는 2025년이면
  // 화면 두 곳이 다른 해를 말하게 된다.
  drawLandPrice();
  buildLegend();
}

function updateTierCounts() {
  const counts = {};
  (state.tiers ? state.tiers.rank : new Map()).forEach((q) => {
    counts[q] = (counts[q] || 0) + 1;
  });
  // **글자도 같이 간다.** 차종을 고르면 경계가 내려가는데 범례가
  // '1만대 미만' 인 채로 있으면 같은 색이 어제와 다른 뜻이 된다.
  const labels = trafficLabels(((state.tiers || {}).cut) || TRAFFIC_CUTS);
  document.querySelectorAll('#tier-filters .quad-btn').forEach((btn) => {
    const t = btn.dataset.tier;
    const key = (t === 'new' || t === 'none') ? t : Number(t);
    btn.querySelector('.n').textContent = String(counts[key] || 0);
    if (key !== 'new' && key !== 'none' && labels[key]) {
      const span = btn.querySelectorAll('span')[1];
      if (span) span.textContent = labels[key];
    }
  });
}

/* 마커 한 개의 색·크기·툴팁. 지도를 만들 때와 연도·차종을 바꿀 때
 * 같은 함수를 쓴다 — 두 군데에 따로 쓰면 한쪽만 고치게 된다. */
const LABEL_ZOOM = 10;

/* 화면에 그리는 밴드는 **영향범위까지**다.
 *
 * 가장 바깥(5-10km)은 위약 대조 밴드로, 분석이 '여기서도 효과가 나오면
 * IC 때문이 아니다' 를 판정하는 데 쓴다. 그것은 통계 절차이지 사용자가
 * 볼 것이 아니다 — 화면에 '위약 대조' 라고 적어두면 무슨 말인지 모르는
 * 채로 지도만 복잡해진다. 분석에서는 그대로 쓴다.
 */
const shownBands = () => (state.meta.bands_km || []).slice(0, -1);      // 이 배율부터 이름을 띄운다

function styleTollgate(marker, t, tier, vol) {
  const known = tier !== undefined && tier !== null;
  const isNew = tier === 'new';
  const isNone = tier === 'none';
  const q = (isNew || isNone) ? 0 : tier;
  marker.setStyle({
    // 미공개는 **가장 작게** 그린다. 크게 그리면 눈이 먼저 가는데,
    // 이것은 값이 큰 곳이 아니라 값을 모르는 곳이다. 크기는 교통량을
    // 말하는 자리라 '모른다' 가 그 자리를 차지하면 안 된다.
    // 1만대 이하(q=0)와 같은 4.5 를 쓴다.
    radius: isNew ? 7 : isNone ? 4.5 : (known ? 4.5 + q * 1.4 : 3.5),
    // 신설은 링이 굵고 거의 검정이다. 네 구간은 흰 링이라 **테두리
    // 색만 봐도** 갈린다 — 채움 색이 비슷해 보이는 작은 배율에서도.
    // 미공개는 **속이 비어 있다** — 색을 하나 더 만들지 않은 이유는,
    // 색 구간에 끼워 넣는 순간 '통행량이 이만큼' 으로 읽히기 때문이다.
    weight: isNew ? 3 : isNone ? 2.2 : 1.6,
    color: isNew ? cssVar('--tg-new-ring')
      : isNone ? cssVar('--tg-none') : '#fff',
    fillColor: isNew ? cssVar('--tg-new')
      : isNone ? cssVar('--surface')
      : (known ? cssVar(`--tg-${q + 1}`) : cssVar('--faint')),
    fillOpacity: isNone ? .95 : known ? .92 : .45,
    opacity: known ? .95 : .5,
  });
  const name = t.name || t.tollgate_id;
  marker.bindTooltip(
    name + (isNew ? ` · ${state.tgYear}년 신설 (하루 ${num(vol)}대)`
      : isNone ? ' · 통행량 미공개 (민자 운영 — 도로공사 자료에 없음)'
      : known ? ` · 하루 ${num(vol)}대` : ' · 교통량 자료 없음'),
    { direction: 'top' });
  marker._tgName = name;
}

/* 확대 배율에 따라 이름표를 켜고 끈다. */
function syncTollgateLabels() {
  if (!map) return;
  const on = map.getZoom() >= LABEL_ZOOM;
  markers.forEach((m) => {
    if (on && !m._nameOn) {
      m.bindTooltip(m._tgName, {
        permanent: true, direction: 'right', offset: [6, 0],
        className: 'tg-label',
      }).openTooltip();
      m._nameOn = true;
    } else if (!on && m._nameOn) {
      m.unbindTooltip();
      m.bindTooltip(m._tgName, { direction: 'top' });
      m._nameOn = false;
    }
  });
}

/* ─────────── 지도 ─────────── */
function buildMap() {
  // CDN 이 막히거나 오프라인이면 Leaflet 이 없다. 지도만 포기하고 나머지는 살린다.
  if (typeof L === 'undefined') {
    $('#map').innerHTML =
      '<div class="map-fallback">' +
      '<p><strong>지도를 불러오지 못했습니다.</strong></p>' +
      '<p>Leaflet CDN 에 연결할 수 없습니다. 네트워크를 확인하세요.</p>' +
      '<p class="hint">스코어보드와 매물 탭은 정상 동작합니다.</p></div>';
    return;
  }
  const withCoords = state.tollgates.filter((t) => t.lat && t.lon);
  // **+/- 는 오른쪽 아래다** (요구사항 2026-09-10).
  //
  // Leaflet 의 기본 자리는 왼쪽 위인데, 그 자리를 지역 검색칸에
  // 내줬다. 검색은 지도 조작이지 페이지 요소가 아니라서 지도 위에
  // 얹었고(머리띠에서 65px 이 돌아왔다), 두 개를 같은 자리에 놓을
  // 수는 없다. 오른쪽 아래는 폰에서 엄지가 닿는 자리이기도 하다.
  // **캔버스를 안 쓴다.** 보고된 문제(2026-09-10): "IC/영업소 하나
  // 클릭 후 지자체 태그에 마우스 올리면 팝업 정보가 안 나와요."
  //
  // preferCanvas 를 켜면 Leaflet 이 원(circleMarker·circle)을 그리려고
  // **지도 전체를 덮는 <canvas> 한 장**을 overlayPane(z 400)에 깝니다.
  // 그 캔버스는 자기 위에서 일어난 마우스 사건을 전부 받아 스스로
  // 판정하고, 못 맞히면 그냥 버립니다 — 아래로 안 흘려보냅니다.
  //
  // 땅값 글자는 lpPane(375), 거래 핀은 tradePane(380) 이라 **둘 다
  // 그 캔버스 아래**입니다. 그래서 캔버스가 생기는 순간(=원이 하나라도
  // 그려지는 순간, 즉 IC·영업소를 켜거나 밴드를 그린 뒤) 글자에 마우스가
  // 안 닿습니다. 켜기 전에는 캔버스가 없어서 되던 것이 이것 때문입니다.
  //
  // SVG 로 그리면 **그려진 선만** 사건을 받습니다(leaflet.css 가
  // path 에 pointer-events:none 을 걸고 .leaflet-interactive 에만
  // auto 를 줍니다). 층 순서는 그대로 두고 가로채기만 없앱니다.
  // 값은 원 561개 + 밴드 몇 개뿐이고, 이것들은 화면을 옮겨도 다시
  // 그리지 않습니다 — SVG 로 감당이 됩니다.
  map = L.map('map', { zoomControl: false, preferCanvas: false })
    .setView([36.5, 127.8], 7);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  // 보이는 영역만 그리므로, 움직이면 다시 그려야 한다. moveend 는
  // 확대·축소 뒤에도 온다.
  // 누름과 끌기를 가른다. 순서는 pointerdown → dragstart → click 이라,
  // 누를 때 지우고 끌면 세우면 click 시점에 답이 나와 있다.
  const holder = map.getContainer();
  const clearDrag = () => { lpDragged = false; };
  ['pointerdown', 'mousedown', 'touchstart'].forEach((ev) => {
    try { holder.addEventListener(ev, clearDrag, { capture: true, passive: true }); }
    catch (e) { holder.addEventListener(ev, clearDrag, true); }
  });
  map.on('dragstart', () => { lpDragged = true; });

  map.on('moveend', () => {
    drawTrades();
    // 경계선은 칸 단위라 움직일 때마다 새 칸만 부른다. 말풍선이
    // 열려 있어도 상관없다 — 이 층은 말풍선을 안 건드린다.
    drawCadastral();
    // 땅값 글자는 **보이는 곳만** 그린다. 움직이면 다시 그려야 하고,
    // 색도 다시 끊어야 한다 — 화면 안에서의 5분위이기 때문이다.
    // 조회수는 drawLandPrice 가 '지금 화면에 있는 태그' 를 넘겨 준다.
    //
    // 말풍선이 열려 있으면 헛일을 안 한다. **진짜 잠금은 여기가 아니라
    // drawLandPrice 안에 있다** — 부르는 자리가 열여섯 곳이다.
    if (lpOpenPk != null) return;
    drawLandPrice();
  });
  // 닫으면 그때 다시 그린다 — 열려 있는 동안 밀린 갱신을 여기서 갚는다.
  map.on('popupclose', (e) => {
    const cls = ((e.popup || {}).options || {}).className;
    if (cls !== 'lp-pop') return;
    lpOpenPk = null;
    // 다시 그리는 도중에 닫힌 것이면 여기서 또 그리면 안 된다 —
    // clearLayers 가 popupclose 를 부르므로 끝없이 돈다.
    if (!lpDrawing) drawLandPrice();
  });
  // 배율이 바뀌면 인구를 묶는 단위가 바뀐다 (시도 → 시군 → 구).
  // 다시 그리지 않으면 확대해 들어가도 전국 원 17개가 그대로 남는다.
  map.on('zoomend', () => {
    drawLandPrice();
    // 범례의 원 크기와 '몇 만 이하' 도 단위에 맞춰 다시 그린다.
    // 자료가 오기 전이면 그릴 것이 없다.
    if (state.meta) buildLegend();
  });
  // 거래·매물은 **영업소 아래**에 깐다.
  //
  // Leaflet 은 divIcon 마커를 markerPane(z-index 600)에, 원(circleMarker)을
  // overlayPane(400)에 그린다. 그래서 무리를 어떤 순서로 지도에 붙이든
  // 거래 네모가 영업소 원을 덮었다 — 거래가 2천 개, 영업소가 4백 개라
  // 화면이 온통 초록 네모가 됐다. 순서로는 못 고치고 **판을 따로 파야**
  // 한다. 380 은 배경 타일(200)보다 위, 밴드·영업소(400)보다 아래다.
  map.createPane('tradePane').style.zIndex = 380;
  // 배경 지도는 물러나야 한다. OSM 기본 타일은 도로가 노랑·주황, 녹지가
  // 초록, 물이 파랑이라 그 위에 얹은 밴드 색과 경쟁한다 — 밴드 파랑이
  // 강물 파랑과 겹치면 색을 아무리 잘 골라도 안 보인다.
  //
  // 무채색 타일 서비스(CARTO·Stadia 등)는 이제 API 키를 요구한다. 키를
  // 하나 더 늘리는 대신 **CSS 로 채도를 낮춘다**(style.css 의
  // .leaflet-tile-pane). 키도 계정도 없이 같은 결과를 얻고, 남의 서비스
  // 정책이 바뀌어도 지도가 안 깨진다.
  // 배경 지도는 **wireBaseMap() 이 깐다.** 여기서도 깔면 층이 둘이
  // 되는데, 겹쳐 놓으면 눈에는 안 보이고 타일만 두 번 받는다.
  addZoningLayer();

  // 필지 경계선. 배경 타일(200) 바로 위, 용도지역 색면보다 아래에 둔다.
  // **판을 따로 파는 이유는 색이다** — 배경 타일 판에는 이미 채도를
  // 낮추는 손질이 걸려 있어서(.leaflet-tile-pane), 같은 판에 두면 그
  // 손질이 경계선에도 겹쳐 걸린다.
  map.createPane('cadastralPane').style.zIndex = 250;
  addCadastralLayer();

  // 고른 필지의 윤곽 (요구사항 2026-09-10 — 부동산플래닛처럼).
  // 용도지역 색면(타일 200)보다 위, 땅값 글자(375)보다 아래에 둔다 —
  // 윤곽이 글자를 덮으면 값을 못 읽는다.
  map.createPane('parcelPane').style.zIndex = 370;
  parcelLayer = L.layerGroup().addTo(map);

  // 땅값 분위지도. 배경 타일(200)보다 위, 거래(380)보다 아래.
  map.createPane('lpPane').style.zIndex = 375;
  lpLayer = L.layerGroup().addTo(map);
  bandLayer = L.layerGroup().addTo(map);
  tradeLayer = L.layerGroup().addTo(map);
  tollgateLayer = L.layerGroup().addTo(map);

  // 색은 교통량 4분위다. 값이 없는 곳은 회색 테두리만 남겨 '모른다' 를
  // 색으로 말한다 — 값이 있는 것처럼 아무 색이나 칠하면 안 된다.
  const { rank, vol } = state.tiers || buildTiers();
  withCoords.forEach((t) => {
    const marker = L.circleMarker([t.lat, t.lon], { radius: 5, weight: 1.6 });
    styleTollgate(marker, t, rank.get(String(t.tollgate_id)),
                  vol.get(String(t.tollgate_id)));
    marker.on('click', () => selectTollgate(t.tollgate_id));
    markers.set(t.tollgate_id, marker);
  });

  // 확대하면 이름을 띄운다. 축소 상태에서 442개 이름을 다 띄우면
  // 글자가 서로 덮여 아무것도 못 읽는다.
  map.on('zoomend', syncTollgateLabels);

  map.on('click', (e) => {
    if (state.pickMode) { endPick(e.latlng); return; }
    // 영업소·거래 점을 누른 것이면 그쪽이 할 일을 한다. Leaflet 은 레이어
    // 클릭을 지도까지 올려보내므로, 막지 않으면 영업소를 누를 때마다
    // 상세 패널과 용도지역 말풍선이 함께 뜬다.
    const t = e.originalEvent && e.originalEvent.target;
    if (t && t.closest && t.closest('.leaflet-interactive')) return;
    // 용도지역을 켜 놓았을 때만. 꺼 놓았으면 색면이 없으니 누를 이유도
    // 없고, 누를 때마다 브이월드를 부르는 것은 한도를 태우는 일이다.
    // 필지 진단(레이더)을 연다. 배율이 낮으면 어느 필지를 누른 것인지
    // 알 수 없으므로 그때는 예전처럼 용도지역만 말한다.
    if (map.getZoom() >= ZONING_MIN_ZOOM) askParcel(e.latlng);
    else if (state.zoning) askZoning(e.latlng);
  });

  if (withCoords.length) {
    map.fitBounds(L.latLngBounds(withCoords.map((t) => [t.lat, t.lon])).pad(0.15));
  }
  refreshMap();
}

/* 밴드 하나. 선 + 옅은 음영으로 그린다.
 *
 * 선만 그으면 '어디까지가 그 밴드인지' 를 눈으로 채워 넣어야 한다. 음영이
 * 있으면 면적이 바로 읽힌다. 다만 원이 겹쳐 쌓이므로 아주 옅게 깔고,
 * **큰 원부터 그려** 작은 원이 위에 오게 한다. 순서를 뒤집으면 가까운
 * 밴드가 먼 밴드에 덮여 안 보인다.
 */
function bandRing(lat, lon, hi, i, isControl, faint) {
  const color = cssVar(`--band-${(i % BAND_COLORS) + 1}`);
  return L.circle([lat, lon], {
    radius: hi * 1000,
    color,
    weight: faint ? 1.2 : (isControl ? 2 : 2.5),
    opacity: faint ? .55 : (isControl ? .85 : 1),
    // **모든 밴드를 점선으로** 긋는다(2026-09-03 지시). 실선은 행정경계나
    // 도로처럼 보여 배경 지도의 선과 섞인다. 점선은 '우리가 그은 선' 이라고
    // 말한다. 대조 밴드만 더 성기게 끊어 성격이 다르다는 것을 보탠다.
    dashArray: isControl ? '2 8' : '7 5',
    // 대조 밴드는 채우지 않는다. 영향범위 바깥이라 면적을 강조할 이유가
    // 없고, 가장 큰 원이라 채우면 화면 전체가 물든다.
    // 면을 채우지 않는다. 넓은 색면은 한국 토지이용계획도의 용도지역
    // (주거 노랑·상업 빨강·공업 보라·녹지 초록)처럼 읽힌다 — 우리 밴드는
    // 용도와 아무 상관이 없는데 그렇게 오해된다. 점선만 남긴다.
    fill: false,
    // 밴드는 **누를 수 없어야 한다.** 보고된 문제(2026-09-04):
    // "IC 선택 후 범위가 표시되면 범위 내로 들어가는 인근 IC가 클릭 불가."
    //
    // fill:false 로 그려도 소용없다. 지도가 canvas 방식이라(preferCanvas)
    // Leaflet 은 원을 누를 수 있는지 판정할 때 **중심에서의 거리만** 본다
    // (Circle._containsPoint: 거리 ≤ 반지름). 채웠는지 안 채웠는지는 안
    // 본다. 그래서 5km 밴드는 속이 빈 것처럼 보여도 그 원판 전체가
    // 누름을 가로챈다.
    //
    // 게다가 캔버스는 겹칠 때 **나중에 그린 것**을 누른 것으로 친다.
    // 영업소는 처음 한 번 그리고 밴드는 IC 를 고를 때마다 다시 그리므로,
    // 밴드가 항상 나중이 된다 — 즉 밴드가 늘 이긴다. 그리는 순서로는
    // 못 고치고, 판정 대상에서 빼야 한다. 밴드에 붙은 동작은 없다.
    interactive: false,
  });
}


/* 고른 해의 거래를 받아 온다. 한 번 받은 해는 다시 안 받는다.
 *
 * 실패해도 화면은 살려 둔다 — 거래가 안 보이는 것과 화면이 죽는 것은
 * 사용자에게 전혀 다른 일이다. */
/* 한 해가 약 950KB 다. 이보다 넓게 잡으면 전 기간 표본으로 물러난다 —
 * 20년치를 다 받으면 19MB 이고, 그 중 화면에 그리는 것은 수천 점뿐이다. */
const MAX_YEAR_FILES = 5;

async function loadTradeYear(year) {
  if (year === 'all') { state.tradesShown = state.trades; return; }
  if (state.tradeCache[year]) { state.tradesShown = state.tradeCache[year]; return; }
  try {
    const r = await fetch(`/app/data/trades-${year}.json`);
    if (!r.ok) throw new Error(String(r.status));
    state.tradeCache[year] = await r.json();
  } catch (err) {
    state.tradeCache[year] = [];
  }
  state.tradesShown = state.tradeCache[year];
}

/* 범위만큼 받아서 잇는다. 받은 해는 다시 안 받는다(브라우저 캐시와
 * 별개로 우리도 들고 있는다) — 손잡이를 조금씩 미는 동안 같은 파일을
 * 몇 번씩 받으면 그게 더 느리다. */
async function loadTradeYears(from, to) {
  const years = [];
  for (let y = from; y <= to; y += 1) years.push(y);
  state.yearWide = years.length > MAX_YEAR_FILES;
  if (state.yearWide) {
    // **넓게 잡으면 전 기간 표본으로 물러난다.** 그 표본은 20년에
    // 흩어져 있어 성기다. 그것을 안 밝히면 '2015~2025 거래가 이것뿐' 으로
    // 읽힌다 — updateYearNote 가 말한다.
    state.tradesShown = state.trades.filter(
      (t) => t.deal_year >= from && t.deal_year <= to);
    return;
  }
  await Promise.all(years.map((y) => loadTradeYear(y)));
  const out = [];
  years.forEach((y) => { (state.tradeCache[y] || []).forEach((t) => out.push(t)); });
  state.tradesShown = out;
}

/* 표본이라는 사실을 화면에 적는다.
 *
 * 이 한 줄이 없으면 '2019년 계획관리 거래는 이 열 점이 전부' 로 읽힌다.
 * 스크리닝 도구에서 그 오해는 곧바로 투자 판단으로 이어진다. */
function updateYearNote() {
  const node = document.getElementById('deal-year-note');
  if (!node) return;
  const n = (v) => v.toLocaleString('ko-KR');
  const held = visibleTrades().length;
  const rows = (state.meta.trade_years || []).filter(
    (r) => r.year >= state.yearFrom && r.year <= state.yearTo);
  const total = rows.length
    ? rows.reduce((a, r) => a + r.total, 0)
    : ((state.meta.counts || {}).trades_mapped || 0);
  const label = state.yearFrom === state.yearTo
    ? `${state.yearFrom}년` : `${state.yearFrom}~${state.yearTo}년`;

  let text = `${label} 좌표 있는 거래 <strong>${n(total)}건</strong>`;
  if (held < total) text += ` 중 무작위 표본 ${n(held)}건을 받았습니다`;
  else text += ` 전부를 받았습니다`;
  // **넓게 잡으면 성긴 표본으로 물러난다.** 그것을 안 밝히면 범위를
  // 넓혔는데 점이 줄어드는 것을 고장으로 읽는다.
  if (state.yearWide) {
    text += ` <em>(${MAX_YEAR_FILES}년이 넘어 전 기간 표본에서 골랐습니다 —`
      + ` 좁히면 그 해 자료를 통째로 받습니다)</em>`;
  }
  // 화면에 실제로 몇 개가 그려졌는지. 잘렸으면 반드시 말한다.
  if (typeof state.tradeInView === 'number') {
    text += ` · 지금 보이는 영역 ${n(state.tradeInView)}건`;
    if (state.tradeDrawn < state.tradeInView) {
      // **핀일 때는 '확대하면 다 보인다' 가 거짓이다.** 핀은 더 당겨도
      // 60개에서 끊긴다. 왜 끊었고 무엇을 남겼는지를 그대로 적는다 —
      // 안 적으면 '이 동네 거래는 이것뿐' 으로 읽힌다.
      text += state.tradeLabelled
        ? ` <em>(핀은 겹치지 않게 ${n(state.tradeDrawn)}건만 —`
          + ' 최근 거래부터입니다)</em>'
        : ` <em>(그중 ${n(state.tradeDrawn)}건만 표시 — 확대하면 다 보입니다)</em>`;
    }
    if (!state.tradeLabelled) {
      text += ' <em>(더 당기면 핀에 값이 적힙니다)</em>';
    }
  }
  node.innerHTML = text + '.';
}

/* 필터 칸의 열쇠. 공장 자료는 공장·창고·그 밖으로 갈린다.
 *
 * usage 가 비어 있는(가를 칸이 없던) 거래도 '그 밖' 으로 보낸다 —
 * 어디에도 안 넣으면 켜 놓은 칸이 하나도 그것을 안 집어서 지도에서
 * 통째로 사라지고, 사라진 줄도 모른다. */
function tradeFilterKey(t) {
  if (t.kind !== 'factory') return t.kind;
  return `factory:${t.usage || '구분 없음'}`;
}

function visibleTrades() {
  const rows = state.tradesShown || state.trades || [];
  // 연도는 파일을 고를 때 이미 갈렸다. 여기서 또 자르지 않는다.
  return rows.filter((t) => {
    if (!state.activeKinds.has(tradeFilterKey(t))) return false;
    if (state.parcelOnly && t.geocode_level !== 'parcel') return false;
    // 개발단계·용도지역은 **토지에만** 건다. 공장·창고에 걸면
    // 토지 칸을 만질 때마다 공장이 같이 사라진다.
    //
    // 그리고 **칸이 만들어졌을 때만** 건다. meta 에 stage_mix 가 없으면
    // (수집이 아직 새 코드로 안 돈 상태) 집합이 비는데, 그것을 그대로
    // 거르면 토지가 통째로 사라진다. 필터가 없는 것과 전부 끈 것은
    // 다른 상황이다 — 검사가 이것을 잡았다.
    if (t.kind === 'land') {
      if (state.hasStageFilter
          && !state.activeStages.has(t.stage || '지목 미상')) return false;
      if (state.hasLandUseFilter
          && !state.activeLandUse.has(t.land_use || '용도 미상')) return false;
      // 도로 접함. car_ok 는 파이썬이 판정해서 실어 준다 — 여기서
      // 문자열을 다시 뜯지 않는다('세로한면(가)' 와 '(불)' 은 한 글자
      // 차이라 갈라 두면 언젠가 어긋난다).
      //
      // **조사 안 된 것은 어느 쪽도 아니다.** 'ok' 를 골랐을 때 빈 값을
      // 남기면 맹지가 섞이고, 'no' 에 남기면 아직 모르는 땅이 맹지로
      // 몰린다. 그래서 둘 다에서 뺀다 — 고르는 순간 표본이 '조사된 것'
      // 으로 좁아진다는 뜻이고, 그 숫자는 아래 안내가 말해 준다.
      if (state.roadFilter === 'ok' && t.car_ok !== 'Y') return false;
      if (state.roadFilter === 'no' && t.car_ok !== 'N') return false;
    }
    return true;
  });
}

/* 지금 보이는 영역의 거래만 그린다.
 *
 * 표식 하나가 DOM 요소 하나라 휴대폰에서는 수천 개를 못 버틴다. 그렇다고
 * 표본을 줄이면 **확대해 들어갔을 때** 그 동네 거래가 몇 점 안 남는다 —
 * 스크리닝 도구에서 정작 들여다볼 때 비는 셈이다.
 *
 * 그래서 받아 두는 것은 넉넉히, 그리는 것은 보이는 영역만. 전국을 볼 때는
 * 자연히 성기고, 시군구 하나로 확대하면 그 안이 촘촘해진다. */
const TRADE_DRAW_CAP = 1500;

function drawTrades() {
  if (!map || !tradeLayer) return;
  tradeLayer.clearLayers();
  const rows = visibleTrades();
  const bounds = map.getBounds();
  const inView = rows.filter((t) => bounds.contains([t.lat, t.lon]));
  // 한 화면에 1,500개가 넘으면 앞에서 자른다. 자를 때는 반드시 말한다 —
  // 말 안 하면 '이 동네 거래는 이것뿐' 으로 읽힌다.
  state.tradeInView = inView.length;
  // **당겨 보면 글자를 단다** (요구사항 2026-09-09 — 눌러야만 알 수
  // 있는 것을 고친다). 멀리서는 점 그대로다: 전국에 1,500개 글자를 달면
  // 서로 덮여 하나도 못 읽는다.
  const labelled = map.getZoom() >= TRADE_LABEL_ZOOM;
  let rowsToDraw = inView;
  if (labelled && inView.length > TRADE_LABEL_CAP) {
    // 자를 때는 **최근 거래부터** 남긴다. 앞에서 그냥 자르면 파일에
    // 실린 순서가 곧 '보여줄 거래' 가 되는데, 그것은 아무 뜻도 없다.
    rowsToDraw = inView.slice().sort(
      (a, b) => (b.deal_year - a.deal_year)
                || ((b.deal_month || 0) - (a.deal_month || 0)));
  }
  state.tradeLabelled = labelled;
  state.tradeDrawn = Math.min(
    rowsToDraw.length, labelled ? TRADE_LABEL_CAP : TRADE_DRAW_CAP);
  for (let i = 0; i < state.tradeDrawn; i++) {
    tradeLayer.addLayer(tradeMarker(rowsToDraw[i], labelled));
  }
  // **여기서 내놓는다.** 예전에는 refreshMap() 이 내놓았는데, 핀 유형만
  // 바꿀 때는 refreshMap 을 안 거치므로 들여다보기 창이 옛 그림을
  // 가리켰다 — 검사가 초록인데 화면은 바뀌어 있는 상태가 된다.
  // 검사용 들여다보기 창. window.__bands 와 같은 취지다 — 지도는 CDN
  // 의 Leaflet 이 있어야 그려져서, 그리는 값 자체를 밖에서 볼 길이
  // 없으면 '색이 안 보인다' 같은 지적을 검사로 못 옮긴다.
  window.__tradeStyles = tradeLayer.getLayers
    ? tradeLayer.getLayers().map((l) => ({
        kind: l.options.kind,
        geocodeLevel: l.options.geocodeLevel,
        // 어느 판에 그렸는가. 판이 곧 위아래 순서다 — 영업소를 덮는지
        // 아닌지가 여기서 갈린다.
        pane: l.options.pane,
        // 모양과 색은 CSS 클래스가 정한다. 무엇이 붙었는지를 그대로
        // 내보내야 검사가 '네모인가 마름모인가' 를 볼 수 있다.
        html: (l.options.icon && l.options.icon.options
               && l.options.icon.options.html) || '',
        // 누를 수 있는지와, 눌렀을 때 무엇이 뜨는지. 이 둘이 없으면
        // '눌러도 아무것도 안 나온다' 를 검사로 옮길 수 없다.
        interactive: l.options.interactive === true,
        popup: (l.getPopup && l.getPopup() && l.getPopup().getContent
                && l.getPopup().getContent()) || l.__popupHtml || '',
      }))
    : undefined;
  window.__pins = { kind: state.pinKind, labelled, drawn: state.tradeDrawn,
                    inView: state.tradeInView };
  updateYearNote();
}

function refreshMap() {
  // 지도가 없어도(CDN 차단) 개수 안내는 갱신한다. 그 한 줄이 표본이라는
  // 사실을 말하는 유일한 자리다.
  updateYearNote();
  if (!map) return;
  tollgateLayer.clearLayers();
  const rank = (state.tiers || {}).rank || new Map();
  // 영업소를 끄면 점도 이름도 안 그린다 (기본 꺼짐).
  if (!state.showGates) { syncTollgateLabels(); }
  state.tollgates.forEach((t) => {
    if (!state.showGates) return;
    const marker = markers.get(t.tollgate_id);
    if (!marker) return;
    const tier = rank.get(String(t.tollgate_id));
    // 교통량을 모르는 영업소는 필터와 무관하게 늘 보여준다 — 걸러버리면
    // '그 자리에 영업소가 없다' 로 읽힌다.
    if (tier === undefined || state.activeTiers.has(tier)) {
      tollgateLayer.addLayer(marker);
    }
  });
  syncTollgateLabels();

  drawTrades();
  // **땅값 글자는 여기서 다시 그리지 않는다.** 거래 점 필터와 따로 놀기로
  // 했다(요구사항 2026-09-08) — 점을 걸러 볼 때마다 바탕의 중앙값이
  // 함께 흔들리면 견줄 수가 없다. 배율·이동과 자기 칸에서만 다시 그린다.
}

/* 용도지역 폴리곤 배경 — 네이버 지적편집도의 그 화면.
 *
 * 한국 **법정** 용도지역(계획관리·생산관리·자연녹지…)은 OSM 에 없다.
 * 국토교통부 자료이고 브이월드에서만 온다.
 *
 * **인증키를 여기 적지 않는다.** 우리 서버(api/tile.js)가 대신 받아온다.
 * 그 키는 실거래 지오코딩에 쓰는 하루 3만 건짜리 자원이고, 이 프로젝트에서
 * 가장 자주 병목이 되는 것이다 — 오늘도 그것 때문에 수집이 한 번 멈췄다.
 * 페이지에 적어두면 누가 대신 써버릴 수 있고, 그러면 수집이 선다.
 *
 * 배율이 낮을 때는 켜지 않는다. 전국이 보이는 배율에서 용도지역을 깔면
 * 색면이 지도를 통째로 덮어 거래 점도 영업소도 안 보인다 — 지적편집도는
 * 원래 필지를 들여다볼 때 쓰는 것이다.
 */
const ZONING_MIN_ZOOM = 12;
// 필지 경계선은 더 깊이 들어가야 뜻이 있다. 12배율에서 필지선을 깔면
// 실선 뭉치가 되어 용도지역 색을 오히려 가린다.
//
// 벡터로 받으므로 브이월드의 z18 문턱에 안 묶인다. 대신 다른 벽이
// 있다 — 얕을수록 한 화면에 든 필지가 기하급수로 는다. 실측(안성,
// 폰 화면 하나 기준, 속성 버리고 좌표 여섯 자리):
//
//   z14~16  1,000개 상한에 걸림   390~420KB
//   z17       378개              166KB
//
// z16 이 상한에 걸리는 것은 **화면 통째로 부를 때** 다. 칸으로 나눠
// 부르면 한 칸이 그 1/8 이라 z16 도 선다. 그보다 얕으면 칸마다 상한에
// 걸려 선이 군데군데 빠진다 — 빠진 선은 없는 선보다 나쁘다.
const CADASTRAL_MIN_ZOOM = 16;

/* ── 배경 지도 (요구사항 2026-09-09) ────────────────────────────
 *
 * "배경 지도를 시인성 좋은 카카오맵이나 네이버맵을 받아올 수 있나요?"
 * → "현재 것, 브이월드, 위성, 일반 등 선택할 수 있도록 해두면 좋을 것
 *    같으나, 캐쉬 여유가 되는 지 확인하고 진행해 주세요."
 *
 * 카카오·네이버는 **타일이 아니라 자바스크립트 지도 SDK** 라 Leaflet 에
 * 못 꽂힙니다. 타일 주소를 뜯어 쓰는 것은 양쪽 약관이 금지하고, 상업적
 * 이용이 전제인 서비스에서 갈 길이 아닙니다.
 *
 * 브이월드는 래스터 타일이라 그대로 꽂힙니다. 재보고 넷을 남겼습니다
 * (점검 6-C: gray 만 그림 대신 XML 이 왔습니다).
 *
 * **기본은 지금 것(OSM)** 입니다. 이유가 둘입니다.
 *
 *   · OSM 은 브라우저가 직접 받아 우리 함수를 안 거칩니다. 브이월드는
 *     거칩니다 — 배경은 화면마다 스무 장씩이라 그 차이가 큽니다.
 *   · 고른 사람만 그 값을 쓰면 됩니다. 다들 쓰게 만들 이유가 없습니다.
 *
 * 같은 타일은 CDN 이 이레(s-maxage=604800) 붙들어 둡니다 — 점검에서
 * 두 번째 호출이 x-vercel-cache: HIT 로 왔습니다. 그래서 실제 함수 호출은
 * 그 동네를 **처음 여는 사람** 몫뿐입니다.
 */
/**
 * 브이월드 배경 타일 주소.
 *
 * 기본은 우리 서버(/api/tile)를 거친다. 그런데 그 함수 호출이 곧 비용이다
 * — Vercel Hobby 는 월 100만 회이고, 배경 타일은 한 번 움직임에 열 장 남짓
 * 나간다. config.js 에 **지도 전용** 브이월드 키(`vworldMapKey`)를 두면
 * 브라우저가 브이월드를 바로 부르고 우리 함수는 한 번도 안 돈다.
 *
 * 그 키는 페이지에 그대로 실린다. 그래서 **지오코딩에 쓰는 키와 다른
 * 키**여야 한다 — 새는 것은 지도 키의 하루 한도뿐이고, 수집은 안 선다.
 * 브이월드 키는 서비스 주소(toji.fyi)에 묶여 Referer 를 본다.
 */
const VWORLD_WMTS = { base: ['Base', 'png'], satellite: ['Satellite', 'jpeg'],
                      hybrid: ['Hybrid', 'png'], midnight: ['midnight', 'png'] };
function vworldTileUrl(key) {
  const mk = CONFIG.vworldMapKey;
  if (mk && VWORLD_WMTS[key]) {
    const [name, ext] = VWORLD_WMTS[key];
    return `https://api.vworld.kr/req/wmts/1.0.0/${mk}/${name}/{z}/{y}/{x}.${ext}`;
  }
  return `/api/tile?layer=${key}&z={z}&y={y}&x={x}`;
}
const BASEMAPS = [
  { key: 'osm', label: '기본',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap' },
  { key: 'base', label: '브이월드',
    url: vworldTileUrl('base'),
    attribution: '배경지도 © 국토교통부 브이월드' },
  { key: 'satellite', label: '위성',
    url: vworldTileUrl('satellite'),
    attribution: '위성영상 © 국토교통부 브이월드' },
  { key: 'hybrid', label: '위성+지명',
    url: vworldTileUrl('hybrid'),
    attribution: '배경지도 © 국토교통부 브이월드' },
  { key: 'midnight', label: '야간',
    url: vworldTileUrl('midnight'),
    attribution: '배경지도 © 국토교통부 브이월드' },
];

/**
 * 우리 서버를 거치는 타일 층의 공통 옵션 — 요청 수를 줄인다.
 *
 *   updateWhenZooming: false  손가락으로 배율을 바꾸는 동안 Leaflet 은
 *                             정수 배율마다 타일을 새로 받는다 (z10→16 이면
 *                             여섯 벌). 끝난 뒤 한 벌만 받게 한다.
 *   updateWhenIdle: true      움직이는 동안이 아니라 멈춘 뒤에 받는다.
 *   keepBuffer: 4             화면 밖 네 줄까지 들고 있어 되돌아오면 안 받는다.
 */
const TILE_OPTS = { updateWhenZooming: false, updateWhenIdle: true, keepBuffer: 4 };

let baseLayer = null;

function setBaseMap(key, first) {
  const spec = BASEMAPS.find((b) => b.key === key) || BASEMAPS[0];
  state.baseMap = spec.key;
  if (map) {
    if (baseLayer) map.removeLayer(baseLayer);
    baseLayer = L.tileLayer(spec.url, {
      maxZoom: 19, attribution: spec.attribution,
      // OSM 은 남의 서버라 그대로 두고, 브이월드는 우리 함수를 아낀다.
      ...(spec.key === 'osm' ? {} : TILE_OPTS),
    }).addTo(map);
    // **맨 아래로 내린다.** 갈아 끼운 층은 나중에 붙은 것이라 위에
    // 얹히는데, 그러면 용도지역 색면과 거래 점을 덮는다.
    if (baseLayer.bringToBack) baseLayer.bringToBack();
  }
  // 위성 위에서는 흰 글자가, 일반 지도 위에서는 검은 글자가 읽힌다.
  // 그 판단을 CSS 에 맡기려고 몸통에 표를 남긴다.
  document.body.dataset.basemap = spec.key;
  document.querySelectorAll('#basemap-pick button').forEach((b) => {
    b.classList.toggle('is-on', b.dataset.key === spec.key);
    b.setAttribute('aria-pressed', String(b.dataset.key === spec.key));
  });
  // 고른 것은 그 사람 브라우저에만 남긴다. 다음에 열 때 다시 고르게
  // 하면 매번 같은 수고를 시킨다. 못 써도(사생활 보호 창 등) 그만이다.
  if (!first) { try { localStorage.setItem('toji.basemap', spec.key); } catch (e) { /* 무시 */ } }
  window.__basemap = spec.key;
}

/* 지도 위 작은 단추 둘 (요구사항 2026-09-10).
 *
 * 폰에서 지도가 쓰는 높이를 재 보면 위에 255px, 아래에 120px 이
 * 붙어 있었다. 지도가 쓸 수 있는 것이 절반뿐이었다는 뜻이다.
 *
 *   ⓘ   면책 문구와 가이드. 지도 아래에 상주하던 120px 을 단추
 *        하나로 줄인다. 늘 읽는 글이 아니라 한 번 확인하는 글이다.
 *   ⛶   지도만 보기. 머리띠·탭·필터·상세가 접힌다.
 *
 * **빠져나갈 길을 둘 준다** — 같은 단추를 다시 누르는 것과 Esc.
 * 전체화면에서 나가는 법을 못 찾으면 그것은 갇힌 것이다. */
function wireMapChrome() {
  const note = $('#map-note');
  const noteBtn = $('#map-note-btn');
  if (note && noteBtn) {
    const setNote = (on) => {
      note.hidden = !on;
      noteBtn.setAttribute('aria-expanded', on ? 'true' : 'false');
    };
    noteBtn.addEventListener('click', () => setNote(note.hidden));
    // 바깥을 누르면 닫는다. 지도 위에 뜬 것이라 안 닫히면 지도를 가린다.
    document.addEventListener('click', (e) => {
      if (note.hidden) return;
      if (note.contains(e.target) || noteBtn.contains(e.target)) return;
      setNote(false);
    });
  }

  const full = $('#map-full');
  if (full) {
    // 뒤로 가기가 앱을 떠나 버렸다 (보고된 문제 2026-09-10:
    // "전체 화면 전환 후 뒤로 가기 누르면 로그인 화면으로 갑니다").
    //
    // 전체화면은 주소를 안 바꾸므로 방문 기록에 아무것도 안 남았다.
    // 그래서 안드로이드 뒤로 가기가 **그 앞 기록** — 관문(/account) —
    // 으로 갔다. 사용자에게는 지도를 크게 켠 것이 '화면 하나' 이므로,
    // 켤 때 기록을 한 칸 넣고 뒤로 가기로 그것만 닫는다.
    let pushed = false;
    const paint = (on) => {
      document.body.classList.toggle('is-mapmax', on);
      full.setAttribute('aria-pressed', on ? 'true' : 'false');
      full.title = on ? '원래대로' : '지도만 보기';
      full.textContent = on ? '✕' : '⛶';
      // **크기가 바뀐 것을 Leaflet 에 알려야 한다.** 안 알리면 타일이
      // 예전 크기 그대로 남아 오른쪽·아래가 회색으로 빈다.
      if (map) setTimeout(() => map.invalidateSize(), 60);
    };
    // fromPop: 뒤로 가기가 부른 것. 그때 다시 history 를 건드리면
    // 한 번 더 뒤로 가서 앱을 떠난다.
    const setFull = (on, fromPop) => {
      paint(on);
      if (on && !fromPop) {
        try { history.pushState({ tojiFull: true }, ''); pushed = true; }
        catch (e) { pushed = false; }
      } else if (!on && !fromPop && pushed) {
        pushed = false;
        history.back();
      }
    };
    full.addEventListener('click', () => {
      setFull(!document.body.classList.contains('is-mapmax'));
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && document.body.classList.contains('is-mapmax')) {
        setFull(false);
      }
    });
    window.addEventListener('popstate', () => {
      if (!document.body.classList.contains('is-mapmax')) return;
      pushed = false;
      setFull(false, true);
    });
    // 검사가 안에서 부를 수 있게 내놓는다.
    window.__mapFull = setFull;
  }
}

function wireBaseMap() {
  const box = document.getElementById('basemap-pick');
  if (!box) return;
  box.innerHTML = '';
  BASEMAPS.forEach((b) => {
    const el2 = document.createElement('button');
    el2.type = 'button';
    el2.dataset.key = b.key;
    el2.textContent = b.label;
    el2.setAttribute('aria-pressed', 'false');
    el2.addEventListener('click', () => setBaseMap(b.key));
    box.appendChild(el2);
  });
  setBaseMap(state.baseMap, true);
}

function addZoningLayer() {
  zoningLayer = L.layerGroup();
  // 색면 — 용도지역 네 장을 서버가 한 요청에 겹쳐 받아온다
  // (api/tile.js 의 LAYERS.zoning). 브이월드 공식 색이라 지적편집도를
  // 읽어온 분들에게는 설명이 필요 없다.
  L.tileLayer('/api/tile?layer=zoning&z={z}&y={y}&x={x}', {
    ...TILE_OPTS,
    maxZoom: 19,
    minZoom: ZONING_MIN_ZOOM,
    // 위에 거래 점과 영업소가 얹히므로 반투명해야 한다. 불투명하면
    // 배경 지도의 도로까지 같이 가린다.
    opacity: .42,
    attribution: '용도지역 © 국토교통부 브이월드',
  }).addTo(zoningLayer);
  // **필지 경계선은 여기 없다.** addCadastralLayer 가 따로 깐다.
  if (state.zoning) zoningLayer.addTo(map);
}

/* 필지 경계선 — 지적편집도의 그 선.
 *
 * **그림이 아니라 도형으로 받는다.** 처음에는 브이월드 WMS 타일을
 * 깔았는데, 라이브에서 재 보니 z14~17 이 전부 '완전히 투명' 한 PNG
 * 였다 (2026-09-10, scripts/cadastral_tile_probe.py):
 *
 *   z=16  1:6,812  칠해진 화소 0개
 *   z=17  1:3,406  칠해진 화소 0개
 *   z=18  1:1,703  칠해진 화소 65,536개 (100%)
 *
 * 문턱이 z18 이고, 그리기 시작하면 화면을 100% 덮는다 — 선이 아니라
 * 면이다. 배경으로 쓸 수가 없다.
 *
 * 그래서 같은 자료를 WFS 로 받아 여기서 선으로 그린다. 얕은 배율에서
 * 나오고, 색도 CSS 필터 꼼수 없이 그대로 정한다.
 *
 * **칸을 나눠 받는다.** 화면을 통째로 부르면 조금만 움직여도 다시
 * 받는다. 타일 격자로 자르면 겹치는 칸은 엣지 캐시가 받아내고 새 칸만
 * 나간다. 받은 칸은 여기서도 들고 있어 되돌아올 때 다시 안 부른다.
 */
const cadTiles = new Map();      // 'z/x/y' → L.GeoJSON (그린 것)
const cadAsked = new Set();      // 부르는 중인 칸
const cadFailed = new Map();     // 'z/x/y' → 실패 시각. 잠시 뒤 다시 묻는다.
const CAD_RETRY_MS = 30_000;
// **동시에** 이보다 많은 칸은 안 부른다. 화면이 넓어도 폰이 버티게.
//
// 한 칸이 오면 다음 칸을 부른다 (fetchCadTile 의 finally). 전에는 한 번
// 부르고 끝이라 **넓은 화면의 오른쪽 절반이 비었다** — PC 에서 z16 은
// 칸이 서른 개 남짓인데 열두 개만 받고 다음 movend 까지 멈춰 있었다.
// 폰은 열두 개 안이라 안 보였다 (2026-09-11 지시).
const CAD_MAX_TILES = 12;
// 화면 하나가 이보다 많은 칸이면 아예 안 그린다 — 창이 아직 안 잡혔거나
// 지도가 세계 전체를 내놓는 순간을 걸러내는 값이다. 큰 모니터(2560px)
// 의 z16 이 일흔 칸쯤이라 그 위로 잡는다.
const CAD_MAX_VIEW = 120;

function addCadastralLayer() {
  cadastralLayer = L.layerGroup();
  if (state.cadastral) cadastralLayer.addTo(map);
  drawCadastral();
}

/** 지금 화면을 덮는 칸들의 좌표. 배율은 경계선용으로 따로 잡는다. */
function cadTileList() {
  const z = Math.min(Math.round(map.getZoom()), 19);
  const b = map.getBounds();
  const n = 2 ** z;
  const xOf = (lon) => Math.floor(((lon + 180) / 360) * n);
  const yOf = (lat0) => {
    const lat = Math.max(-85.05, Math.min(85.05, lat0));
    const r = (lat * Math.PI) / 180;
    return Math.floor(
      ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n);
  };
  const x1 = xOf(b.getWest()); const x2 = xOf(b.getEast());
  const y1 = yOf(b.getNorth()); const y2 = yOf(b.getSouth());
  // **넓으면 통째로 그만둔다.** 화면 하나는 배율과 무관하게 칸 몇 개다.
  // 그보다 넓은 경계가 오면(창이 아직 안 잡혔거나 지도가 세계 전체를
  // 내놓는 순간) 두 겹 반복이 수십억 바퀴를 돈다 — 화면이 멎는다.
  if ((x2 - x1 + 1) * (y2 - y1 + 1) > CAD_MAX_VIEW) return [];
  const out = [];
  for (let x = x1; x <= x2; x += 1) {
    for (let y = y1; y <= y2; y += 1) {
      if (x < 0 || y < 0 || x >= n || y >= n) continue;
      out.push([z, x, y]);
    }
  }
  // 가운데부터. 열두 개씩 받으므로 왼쪽 위부터 채우면 사람이 보는
  // 한복판이 마지막에 온다.
  const cx = (x1 + x2) / 2; const cy = (y1 + y2) / 2;
  out.sort((a, b) => (Math.abs(a[1] - cx) + Math.abs(a[2] - cy))
                   - (Math.abs(b[1] - cx) + Math.abs(b[2] - cy)));
  return out;
}

function drawCadastral() {
  if (!map || !cadastralLayer) return;
  // 꺼져 있거나 너무 멀면 걷어낸다. 들고 있던 칸도 버린다 — 배율이
  // 바뀌면 칸 좌표 자체가 달라져 쓸 수 없다.
  if (!state.cadastral || map.getZoom() < CADASTRAL_MIN_ZOOM) {
    cadastralLayer.clearLayers();
    cadTiles.clear();
    return;
  }
  const want = cadTileList();
  const keep = new Set(want.map(([z, x, y]) => `${z}/${x}/${y}`));
  for (const [key, layer] of cadTiles) {
    if (!keep.has(key)) { cadastralLayer.removeLayer(layer); cadTiles.delete(key); }
  }
  const now = Date.now();
  for (const [z, x, y] of want) {
    const key = `${z}/${x}/${y}`;
    if (cadTiles.has(key) || cadAsked.has(key)) continue;
    if (now - (cadFailed.get(key) || 0) < CAD_RETRY_MS) continue;
    if (cadAsked.size >= CAD_MAX_TILES) break;
    cadAsked.add(key);
    fetchCadTile(z, x, y, key);
  }
}

// 서버가 '너무 잦다' 고 하면 잠시 쉰다. 계속 두드리면 창이 안 비어
// 더 오래 막힌다. 지도를 움직이는 것 자체는 그대로 된다 — 선만 잠깐
// 안 깔린다.
let cadPausedUntil = 0;
let cadResumeTimer = null;

function fetchCadTile(z, x, y, key) {
  if (Date.now() < cadPausedUntil) {
    // 쉬는 동안은 '부르는 중' 으로 남기지 않는다 — 남기면 그 칸은 배율을
    // 바꾸기 전까지 영영 안 온다. 쉬는 시간이 끝나면 한 번 다시 돈다.
    cadAsked.delete(key);
    if (!cadResumeTimer) {
      cadResumeTimer = setTimeout(() => { cadResumeTimer = null; drawCadastral(); },
                                  Math.max(0, cadPausedUntil - Date.now()) + 50);
    }
    return;
  }
  let ok = false;
  fetch(`/api/tile?mode=parcels&z=${z}&x=${x}&y=${y}`)
    .then((r) => {
      if (r.status === 429) {
        const wait = Number(r.headers.get('retry-after')) || 60;
        cadPausedUntil = Date.now() + wait * 1000;
        return null;
      }
      if (r.ok) ok = true;
      return r.ok ? r.json() : null;
    })
    .then((d) => {
      // 도중에 꺼졌거나 배율이 바뀌었으면 그리지 않는다.
      if (!d || !state.cadastral || !cadastralLayer) return;
      if (map.getZoom() < CADASTRAL_MIN_ZOOM) return;
      if (!cadTileList().some(([a, b, c]) => `${a}/${b}/${c}` === key)) return;
      const geoms = d.geoms || [];
      if (!geoms.length) { cadTiles.set(key, L.layerGroup()); return; }
      const layer = L.geoJSON(
        { type: 'FeatureCollection',
          features: geoms.map((g) => ({ type: 'Feature', properties: {}, geometry: g })) },
        {
          pane: 'cadastralPane',
          // 누름을 가로채면 안 된다 — 필지를 눌러 카드를 여는 것은
          // 지도 자신의 click 이 받는다.
          interactive: false,
          // 색은 CSS 가 정한다(.cad-line). 배경 지도에 따라 달라야
          // 하는데, 그 판단을 여기 흩어 놓으면 배경을 바꿀 때마다
          // 다시 그려야 한다.
          className: 'cad-line',
          style: { weight: 1, fill: false },
        });
      cadastralLayer.addLayer(layer);
      cadTiles.set(key, layer);
    })
    .catch(() => { /* 한 칸이 안 와도 나머지는 그린다. */ })
    .finally(() => {
      cadAsked.delete(key);
      if (!ok) cadFailed.set(key, Date.now());
      // 자리가 났다 — 남은 칸을 이어서 부른다. 이것이 없으면 열두 칸
      // 뒤가 다음 움직임까지 빈다.
      if (state.cadastral && cadastralLayer) drawCadastral();
    });
}

function toggleCadastral(on) {
  state.cadastral = on;
  try { localStorage.setItem('toji.cadastral', on ? 'on' : 'off'); }
  catch (e) { /* 사생활 보호 창에서는 못 적는다. 화면은 그대로 돈다. */ }
  if (!map || !cadastralLayer) return;
  if (!on) { cadastralLayer.remove(); cadastralLayer.clearLayers(); cadTiles.clear(); return; }
  cadastralLayer.addTo(map);
  drawCadastral();
}

/* 눌러서 이름을 본다.
 *
 * 색면만 깔면 지적편집도가 아니라 색칠이다. 색이 스무 가지인데 그것을
 * 외우게 하는 것보다, 궁금한 자리를 눌러 이름을 보여주는 편이 낫다 —
 * 특히 휴대폰에서는 범례를 띄우면 지도를 가린다.
 *
 * 이름은 서버가 브이월드에 물어서 준다(api/tile.js 의 mode=info).
 * 브라우저가 직접 부르면 인증키를 페이지에 적어야 한다.
 */
async function askZoning(latlng) {
  const lat = latlng.lat.toFixed(6);
  const lon = latlng.lng.toFixed(6);
  const popup = L.popup({ maxWidth: 260 })
    .setLatLng(latlng)
    .setContent('<div class="zone-pop">용도지역을 확인하는 중…</div>')
    .openOn(map);

  let body;
  try {
    const resp = await fetch(`/api/tile?layer=zoning&mode=info&lat=${lat}&lon=${lon}`);
    body = await resp.json();
  } catch (err) {
    popup.setContent('<div class="zone-pop">확인하지 못했습니다.</div>');
    return;
  }
  // 사람이 그 사이 다른 곳을 눌렀으면 덮어쓰지 않는다.
  if (!map.hasLayer(popup)) return;

  if (body && body.tileError) {
    popup.setContent('<div class="zone-pop">확인하지 못했습니다 — '
      + escapeHtml(body.tileError) + '</div>');
    return;
  }
  const z = body && body.zoning;
  if (!z) {
    popup.setContent('<div class="zone-pop"><b>용도지역 미지정</b><br>'
      + '<span class="muted">이 자리에는 지정된 용도지역이 없습니다.</span></div>');
    return;
  }
  const where = [z.sido_name, z.sigg_name].filter(Boolean).join(' ');
  const jibun = z.bon_bun
    ? String(Number(z.bon_bun)) + (Number(z.bu_bun) ? '-' + Number(z.bu_bun) : '')
    : '';
  popup.setContent(
    '<div class="zone-pop"><b>' + escapeHtml(z.uname) + '</b>'
    + (where ? '<br><span class="muted">' + escapeHtml(where)
               + (jibun ? ' ' + escapeHtml(jibun) : '') + '</span>' : '')
    + (z.ucode ? '<br><span class="muted">코드 ' + escapeHtml(z.ucode) + '</span>' : '')
    + '</div>');
}

/* 끌 수 있어야 한다. 용도지역을 깔면 지도가 확 복잡해지는데, 거래 점
 * 위치만 보고 싶은 순간이 있다. */
function toggleZoning(on) {
  state.zoning = on;
  if (!map || !zoningLayer) return;
  on ? zoningLayer.addTo(map) : zoningLayer.remove();
}

/* 거래 표식 — 영업소와 **모양으로** 가른다.
 *
 * 예전에는 거래도 원이었고 색을 용도지역별로 다섯 가지 썼다. 화면에는
 * 영업소 6색 + 밴드 3색이 이미 있어서, 전국을 보면 열 몇 가지 색의
 * 원이 뒤덮여 어느 것이 IC 이고 어느 것이 거래인지 구분이 안 됐다
 * (2026-09-04 지적).
 *
 * 색을 더 늘려 푸는 문제가 아니다. **모양이 먼저 종류를 말해야 한다.**
 *
 *   영업소   원
 *   토지     네모   초록  #00A63E
 *   공장     마름모 진파랑 #1414CC
 *
 * 두 색은 눈으로 고르지 않고 쟀다. 영업소 6색·밴드 3색·배경 5색
 * 전부와 최소 ΔE 16.0, 둘끼리 44.8 이다 (scripts/test_palette.js 3절).
 *
 * 용도지역은 이제 색이 아니라 **배경 색면과 눌러서 뜨는 이름**으로
 * 본다(askZoning). 같은 것을 두 군데서 말하면 화면만 복잡해진다.
 */
const TRADE_PX = 9;              // 표식 한 변(px). 원 반경 3.6 과 비슷한 무게.

const PYEONG_M2 = 3.305785;          // 1평

/* 원 단위를 사람이 읽는 꼴로. 3.7억 · 8,500만원 · 940만원 */
function won(v) {
  if (!(typeof v === 'number' && isFinite(v)) || v <= 0) return null;
  if (v >= 1e8) {
    const eok = v / 1e8;
    return `${eok >= 10 ? Math.round(eok) : eok.toFixed(1)}억원`;
  }
  return `${Math.round(v / 1e4).toLocaleString('ko-KR')}만원`;
}

// 위쪽 num() 은 없으면 '—' 을 준다. 말풍선에서는 없는 칸을 아예 빼야
// 하므로 null 을 주는 것이 따로 필요하다.
const popNum = (v, digits = 0) =>
  (typeof v === 'number' && isFinite(v))
    ? v.toLocaleString('ko-KR', { maximumFractionDigits: digits }) : null;

/* 거래 한 건의 상세. 요구사항(2026-09-07): "클릭 시 주요 거래 정보를
 * 상세히." 지도에 점만 있으면 얼마에 팔렸는지를 알 수 없어 스크리닝에
 * 쓸 수가 없다.
 *
 * 평(坪)을 함께 적는다. 토지·공장 거래를 실제로 하는 자리에서는 ㎡ 보다
 * 평으로 값을 셈한다. */
function tradePopup(t) {
  const factory = t.kind === 'factory';
  const addr = [t.sido, t.sigungu, t.umd, t.jibun].filter(Boolean).join(' ');
  const rows = [];
  const add = (k, v) => { if (v) rows.push(`<tr><th>${k}</th><td>${v}</td></tr>`); };

  const when = t.deal_month
    ? `${t.deal_year}년 ${t.deal_month}월` : `${t.deal_year}년`;
  add('거래', when);
  add('거래금액', won(t.price_krw));

  const m2 = popNum(t.area_m2, 0);
  const py = popNum(t.area_m2 / PYEONG_M2, 0);
  if (m2) add(factory ? '대지면적' : '거래면적', `${m2}㎡ <span class="mut">(${py}평)</span>`);

  const per = won(t.price_per_m2);
  const perPy = won(t.price_per_m2 * PYEONG_M2);
  // won() 이 이미 '원' 을 붙여 준다 ('165만원'). 여기서 또 붙이면
  // '165만원원/평' 이 된다.
  if (per) add('단가', `${perPy}/평 <span class="mut">· ${per}/㎡</span>`);

  // 지번·지목·용도지역·거래유형은 자료에서 그대로 온다. HTML 에
  // 넣기 전에 막는다.
  // 지목 옆에 개발단계를 적는다. '답' 이라는 두 글자만으로는 그 땅이
  // 왜 싼지가 안 보인다.
  add('지목', t.jimok && (escapeHtml(t.jimok)
      + (t.stage ? ` <span class="mut">(${escapeHtml(t.stage)})</span>` : '')));
  add('용도지역', t.land_use && escapeHtml(t.land_use));

  /* ── 필지 특성 ──
   * 실거래 API 에는 없는 값이다. 브이월드 토지특성(dt_d194)에서 따로
   * 받아 점-다각형으로 맞춰 붙였다. 요구사항(2026-09-07):
   * "실거래 내용에 도로접하거나 토지의 모양등을 알 수 있는 지". */
  if (t.road_side) {
    const ok = t.car_ok === 'Y';
    add('도로접', escapeHtml(t.road_side)
        + ` <span class="road-tag ${ok ? 'is-ok' : 'is-no'}">`
        + `${ok ? '차 진입 가능' : '진입 어려움'}</span>`);
  }
  // 형상은 등급이 아니다. 요구사항(2026-09-07): "부정형이 무조건
  // 좋지 않은 건 아닙니다." 그래서 좋고 나쁨을 붙이지 않고 그대로 적는다.
  add('형상', t.parcel_shape && escapeHtml(t.parcel_shape));
  add('지세', t.parcel_slope && escapeHtml(t.parcel_slope));
  if (t.official_price) {
    // 공시지가 대비 배수. 스크리닝에서 '비싸게 샀나' 를 가장 빨리
    // 가늠하는 값이라 함께 적는다.
    const mult = t.price_per_m2 ? t.price_per_m2 / t.official_price : null;
    add('공시지가', `${won(t.official_price)}/㎡`
        + (mult && isFinite(mult)
           ? ` <span class="mut">(실거래가 ${mult.toFixed(1)}배)</span>` : ''));
  }
  // 토지인데 필지 특성이 하나도 없으면 그 사실을 말한다. 비어 있는
  // 것과 '맹지·부정형' 인 것은 전혀 다른데, 아무 말도 없으면 읽는
  // 사람은 둘을 못 가른다.
  const noParcel = !factory && !t.road_side && !t.parcel_shape;

  if (t.building_area_m2) {
    add('건물면적', `${popNum(t.building_area_m2, 0)}㎡ ` +
        `<span class="mut">(${popNum(t.building_area_m2 / PYEONG_M2, 0)}평)</span>`);
  }
  if (t.build_year) {
    const age = t.deal_year - t.build_year;
    add('건축연도', `${t.build_year}년` +
        (age >= 0 ? ` <span class="mut">(거래 시점 ${age}년차)</span>` : ''));
  }
  add('거래유형', t.deal_type && escapeHtml(t.deal_type));

  // **좌표가 지번 좌표가 아니면 반드시 말한다.**
  // 법정동 중심점은 오차가 ±1~2km 다. 지번을 적어 놓고 점을 그 자리에
  // 찍어 두면, 보는 사람은 그 점이 그 필지라고 읽는다. 땅을 보러 가는
  // 사람에게 2km 는 다른 동네다.
  const coarse = t.geocode_level !== 'parcel';
  const warn = coarse
    ? '<p class="pop-warn">이 점은 <strong>법정동 중심점</strong>입니다 —'
      + ' 실제 필지 위치가 아닙니다 (오차 ±1~2km).</p>'
    : '';

  // 말풍선 머리말은 건물주용도를 그대로 적는다. '공장·창고' 로 뭉치면
  // 축사인지 주유소인지가 사라진다.
  const shape = tradeShape(t);
  const head = !factory ? { cls: 'is-land', text: '토지' }
    : { cls: shape === 'trade-warehouse' ? 'is-warehouse'
           : shape === 'trade-factory' ? 'is-factory' : 'is-etc',
        text: escapeHtml(t.usage || '공장·창고 (구분 없음)') };
  const nochar = noParcel
    ? '<p class="pop-note">도로접·형상은 <strong>아직 조사 전</strong>입니다'
      + ' (전국을 나눠 받는 중입니다). 맹지라는 뜻이 아닙니다.</p>'
    : '';
  return `<div class="trade-pop">`
    + `<p class="pop-kind ${head.cls}">${head.text}</p>`
    + (addr ? `<p class="pop-addr">${escapeHtml(addr)}</p>` : '')
    + `<table class="pop-table">${rows.join('')}</table>`
    + nochar + warn + `</div>`;
}

/* 색은 셋으로 묶는다 — 공장 계열 / 창고 계열 / 그 밖.
 *
 * 필터는 7종을 다 갈라 놓지만 색까지 7가지로 나누면 지도에서 서로
 * 구별이 안 된다. 사람 눈이 점 색을 대여섯 개까지밖에 못 가른다. */
/* ── 거래 핀에 글자를 얹는다 (요구사항 2026-09-09) ────────────
 *
 * "우리는 매물을 클릭했을 때 나와서 무슨 물건인지 모릅니다."
 *
 * 맞습니다. 지금 거래는 **9px 짜리 점**입니다. 색으로 종류만 겨우 갈리고,
 * 얼마에 팔렸는지·언제인지·얼마나 큰지는 하나하나 눌러 봐야 압니다.
 * 스무 건을 견주려면 스무 번 눌러야 하는데, 그러면 지도를 쓰는 뜻이
 * 없습니다 — 지도는 **한눈에 견주라고** 있는 것입니다.
 *
 * 부동산플래닛(map.bdsplanet.com)을 보고 그 방식을 가져옵니다.
 *
 *     ┌─────────┐
 *     │ 토지    │   종류
 *     │ 2.2억   │   고른 유형의 값
 *     │ 2020·202평│ 보조
 *     └────┬────┘
 *          ▼        꼬리가 **실제 좌표**를 가리킨다
 *
 * 그리고 그 값을 무엇으로 볼지 고르게 합니다. 사는 사람마다 먼저 보는
 * 것이 다릅니다 — 총액을 보는 사람, 평단가를 보는 사람, 언제 거래인지를
 * 보는 사람.
 *
 * **없는 칸은 고르게 두지 않습니다.** 부동산플래닛에는 건물단가·준공연도·
 * 세대수도 있지만 우리 토지 자료에는 그 칸이 없습니다. 목록에 올려 두고
 * 눌렀을 때 비면, 그것은 자료가 없다는 말이 아니라 고장으로 읽힙니다. */
const PIN_KINDS = [
  { key: 'price', label: '거래금액', of: (t) => pinMoney(t.price_krw) },
  { key: 'unit', label: '평단가',
    of: (t) => pinMoney(t.price_per_m2 * PYEONG_M2) },
  { key: 'year', label: '거래연도',
    of: (t) => (t.deal_year ? `${t.deal_year}년` : null) },
  { key: 'area', label: '토지면적', of: (t) => pinPyeong(t.area_m2) },
  { key: 'jimok', label: '지목', of: (t) => t.jimok || null },
  { key: 'zone', label: '용도지역', of: (t) => pinZone(t.land_use) },
];

/* 핀에 글자를 붙이는 배율.
 *
 * **낮은 배율에서 붙이면 안 됩니다.** 전국을 보면서 1,500개에 글자를
 * 달면 서로 덮여 하나도 못 읽고, 그리는 데도 한참 걸립니다. 지금 점을
 * 그대로 두는 배율과 글자를 다는 배율을 가릅니다 — 부동산플래닛도
 * 필지가 보일 만큼 당겨야 핀이 뜹니다. */
const TRADE_LABEL_ZOOM = 15;
/* 그 배율에서도 한 화면에 몇 개까지. 넘으면 최근 거래부터 남깁니다. */
const TRADE_LABEL_CAP = 60;

/* won() 은 '2.2억원' 을 줍니다. 핀은 좁아서 '원' 을 뗍니다 — 억/만이
 * 이미 돈이라고 말하고 있습니다. */
function pinMoney(v) {
  const got = won(v);
  return got ? got.replace(/원$/, '') : null;
}

function pinPyeong(m2) {
  if (!(typeof m2 === 'number' && isFinite(m2) && m2 > 0)) return null;
  return `${Math.round(m2 / PYEONG_M2).toLocaleString('ko-KR')}평`;
}

/* '제1종일반주거지역' → '제1종일반주거'. 핀 너비가 이름 길이를 못 견딥니다.
 * **자르지 않고 꼬리말만 뗍니다** — 가운데를 자르면 다른 용도지역과
 * 구별이 안 됩니다. */
function pinZone(name) {
  const v = String(name || '').trim();
  if (!v) return null;
  return v.replace(/지역$/, '');
}

function pinKind() {
  return PIN_KINDS.find((k) => k.key === state.pinKind) || PIN_KINDS[0];
}

/* 핀 머리의 '무엇인가'. 색만으로는 공장과 창고가 안 갈립니다. */
function pinTitle(t) {
  if (t.kind !== 'factory') return '토지';
  const u = t.usage || '';
  if (u.includes('창고')) return '창고';
  if (u.includes('공장')) return '공장';
  return '공장·창고';
}

/* 셋째 줄. **고른 유형과 겹치는 것은 뺍니다** — 같은 값을 두 번 적으면
 * 그 줄이 아무 말도 안 하게 됩니다. */
function pinSub(t) {
  const now = state.pinKind;
  const bits = [];
  if (now !== 'year' && t.deal_year) bits.push(`${t.deal_year}`);
  if (now !== 'area') { const py = pinPyeong(t.area_m2); if (py) bits.push(py); }
  if (now === 'year' || now === 'area') {
    const per = pinMoney(t.price_per_m2 * PYEONG_M2);
    if (per) bits.push(`${per}/평`);
  }
  return bits.join(' · ');
}

function tradeShape(t) {
  if (t.kind !== 'factory') return 'trade-land';
  const u = t.usage || '';
  if (u.includes('창고')) return 'trade-warehouse';
  if (u.includes('공장')) return 'trade-factory';
  return 'trade-etc';
}

function tradeMarker(t, labelled) {
  const factory = t.kind === 'factory';
  const coarse = t.geocode_level !== 'parcel';
  if (labelled) return tradePin(t, coarse);
  return L.marker([t.lat, t.lon], {
    // divIcon 을 쓰는 이유는 하나다 — Leaflet 의 circleMarker 는 원밖에
    // 못 그린다. 모양으로 가르려면 이 길뿐이다.
    icon: L.divIcon({
      className: 'trade-icon',
      html: '<i class="trade-mark ' + tradeShape(t)
            + (coarse ? ' trade-coarse' : '') + '"></i>',
      iconSize: [TRADE_PX, TRADE_PX],
      iconAnchor: [TRADE_PX / 2, TRADE_PX / 2],
    }),
    pane: 'tradePane',
    // 전에는 interactive:false 였다. 표식을 눌러도 밑의 용도지역
    // 말풍선이 뜨게 하려던 것인데, 그러면 **거래 자체는 눌러도 아무
    // 것도 안 나온다.** 지시(2026-09-07)에 따라 거래 상세를 띄우고,
    // 용도지역은 그 말풍선 안에 같이 적어 잃는 것이 없게 했다.
    interactive: true,
    keyboard: false,
    // 검사와 화면 양쪽이 같은 값을 본다.
    kind: t.kind,
    geocodeLevel: t.geocode_level || '',
  }).bindPopup(tradePopup(t), { className: 'trade-popup', maxWidth: 320 });
}

/* 글자를 단 핀. 점과 **같은 자리**를 가리켜야 한다 — 꼬리 끝이 좌표다.
 *
 * iconAnchor 를 카드 아래 꼭짓점에 둔다. 가운데에 두면 카드가 점 위에
 * 얹혀, 정작 어느 필지인지 가린다. */
function tradePin(t, coarse) {
  const k = pinKind();
  const val = k.of(t);
  const sub = pinSub(t);
  return L.marker([t.lat, t.lon], {
    icon: L.divIcon({
      className: 'trade-pin-wrap',
      html: `<span class="trade-pin ${tradeShape(t)}`
        // 좌표가 필지가 아니라 법정동 중심점인 거래. 점일 때는 테두리를
        // 흐리게 해서 말했는데, 핀에서도 같은 말을 해야 한다 — 값은
        // 정확한데 **자리가 ±1~2km** 라는 것은 큰 차이다.
        + (coarse ? ' is-coarse' : '') + '">'
        + `<b>${escapeHtml(pinTitle(t))}</b>`
        + `<i>${escapeHtml(val || '—')}</i>`
        + (sub ? `<s>${escapeHtml(sub)}</s>` : '')
        // 꼬리는 **카드 안**에 둔다. 밖에 두면 카드의 색을 못 물려받아
        // (currentColor) 검은 세모가 된다.
        + '<u class="trade-pin-tail"></u></span>',
      iconSize: null,
      iconAnchor: [0, 0],
    }),
    pane: 'tradePane',
    interactive: true,
    keyboard: false,
    kind: t.kind,
    geocodeLevel: t.geocode_level || '',
  }).bindPopup(tradePopup(t), { className: 'trade-popup', maxWidth: 320 });
}

function selectTollgate(id) {
  const t = state.tollgates.find((x) => x.tollgate_id === id);
  if (!t) return;
  state.selected = id;
  renderDetail(t);
  if (!map) return;

  markers.forEach((m, key) => m.setStyle({ weight: key === id ? 4 : 2 }));
  bandLayer.clearLayers();
  const bands = shownBands();
  // 큰 원부터 그린다 — 작은 원이 위에 오게.
  for (let i = bands.length - 1; i >= 0; i--) {
    bandLayer.addLayer(bandRing(t.lat, t.lon, bands[i][1], i, false));
  }
  map.panTo([t.lat, t.lon]);
}

/* ─────────── 상세 패널 ─────────── */
function renderDetail(t) {
  const info = quad(t.quadrant_key);
  const rows = (state.series[t.tollgate_id] || [])
    .filter((r) => r.band === state.meta.band);
  const byYear = new Map();
  rows.forEach((r) => {
    const cur = byYear.get(r.year) || { year: r.year, price: [], volume: r[state.meta.volume_col], n: 0 };
    if (r.price_per_m2 != null) cur.price.push(r.price_per_m2);
    cur.n += r.n_trades || 0;
    cur.volume = r[state.meta.volume_col] ?? cur.volume;
    byYear.set(r.year, cur);
  });
  const seq = [...byYear.values()].sort((a, b) => a.year - b.year).map((d) => ({
    year: d.year, n: d.n, volume: d.volume,
    price: d.price.length ? d.price.reduce((a, b) => a + b, 0) / d.price.length : null,
  }));

  const box = $('#detail');
  showDetail(true);
  box.innerHTML = '';
  box.append(detailClose());
  box.append(el('h2', null, t.name || t.tollgate_id));
  box.append(el('div', 'sub',
    [t.sido, t.sigungu, t.route_no ? `노선 ${t.route_no}` : null].filter(Boolean).join(' · ')));

  // **사분면 배지와 통계 카드 넷은 뺐다** (요구사항 2026-09-09:
  // "IC 근처 분석내용은 이제 필지 선택 시 스파이더 차트 형태로 제공될
  //  예정이라 내용 삭제").
  //
  // '동반 상승 · 교통량 증가율 0.0% · 신뢰도 보통' 은 IC 하나를 통째로
  // 한 낱말로 요약한 것이다. 그 자리를 필지 레이더가 대신한다 — 요약은
  // 필지마다 달라야 쓸모가 있다.

  // **여기 가격이 지도 필터와 다르다는 것을 밝힌다** (요구사항).
  // 지도의 땅값 글자는 켜 놓은 용도지역을 따르지만, 이 추이는
  // 분석용 세 지역으로 고정돼 있다(config/settings.yaml 의
  // land_use_filter). 같은 화면에 두 값이 있는데 기준이 다르면,
  // 안 밝히는 순간 둘 중 하나는 틀린 값으로 읽힌다.
  const coreUses = ((state.meta || {}).land_use_filter || []);
  if (coreUses.length) {
    box.append(el('p', 'hint',
      `아래 가격은 ${coreUses.join('·')} 거래만 모은 값입니다`
      + ' — 지도에서 켠 용도지역과 무관합니다.'));
  }

  box.append(sparkline('가격 추이 (㎡당 원)', seq.map((d) => [d.year, d.price])));
  box.append(sparkline('교통량 추이 (일평균)', seq.map((d) => [d.year, d.volume])));

  if (seq.length) {
    const table = el('table');
    table.innerHTML =
      '<thead><tr><th>연도</th><th class="num">㎡당</th><th class="num">교통량</th><th class="num">거래</th></tr></thead>' +
      '<tbody>' + seq.map((d) =>
        `<tr><td>${d.year}</td><td class="num">${num(d.price)}</td>` +
        `<td class="num">${num(d.volume)}</td><td class="num">${d.n || 0}</td></tr>`).join('') +
      '</tbody>';
    box.append(table);
  }
}

/* 상세 패널은 **고를 때만** 연다 (요구사항 2026-09-09).
 *
 * "IC 주변 분석내용은 IC를 선택 시 활성화. 기본 세팅은 나타나 있지 않음
 *  (지도 영역 최대화)"
 *
 * 빈 칸이 휴대폰 화면의 4분의 1을 먹고 있었다. 아무것도 안 알려주면서
 * 자리만 차지하는 칸이다. 여닫는 자리를 한 곳으로 모아 둔다 — 여는 곳과
 * 닫는 곳이 흩어지면 한쪽만 고쳐 놓고 '왜 안 닫히지' 를 하게 된다. */
/* 오른쪽 칸의 닫기 단추 (요구사항 2026-09-09).
 *
 * "필지 자료 창 닫기 버튼 추가해 주세요."
 *
 * 한 번 열면 닫을 길이 없었습니다. 휴대폰에서는 이 칸이 화면의 3분의
 * 1을 먹는데, 지도로 돌아가려면 다른 필지를 눌러 내용을 바꾸는 수밖에
 * 없었습니다.
 *
 * **내용을 넣을 때마다 다시 붙입니다.** 이 칸은 innerHTML 을 통째로
 * 갈아 끼우는 자리라, 한 번 심어 두면 다음 내용에 지워집니다. */
function detailClose() {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'detail-close';
  b.setAttribute('aria-label', '닫기');
  b.title = '닫기';
  b.textContent = '×';
  b.addEventListener('click', () => showDetail(false));
  return b;
}

/* 오른쪽 칸에 내용을 넣는다. 닫기 단추가 늘 따라붙는다. */
function detailBody(html) {
  const box = document.getElementById('detail');
  if (!box) return null;
  box.innerHTML = html;
  box.prepend(detailClose());
  return box;
}

function showDetail(on) {
  const box = document.getElementById('detail');
  if (!box) return;
  box.hidden = !on;
  if (!on) {
    box.innerHTML = '';
    // 칸을 닫으면 윤곽도 지운다. 카드가 없는데 파란 테두리만 남아
    // 있으면 무엇을 고른 것인지 알 길이 없다.
    drawParcelShape(null);
  }
  // 지도가 넓어졌다 좁아졌다 하므로 Leaflet 에 알려야 한다. 안 알리면
  // 타일이 회색으로 남고 클릭 좌표가 어긋난다.
  if (map) setTimeout(() => map.invalidateSize(), 0);
  window.__detail = { on: !!on };
}

function statCard(key, value, signed) {
  const card = el('div', 'stat');
  card.append(el('div', 'k', key));
  const v = el('div', 'v', value);
  if (typeof signed === 'number') v.classList.add(signed >= 0 ? 'up' : 'down');
  card.append(v);
  return card;
}

/* 인라인 SVG 스파크라인. 값이 하나뿐이면 선이 안 그려지므로 점으로 표시한다. */
function sparkline(title, pairs) {
  const wrap = el('div', 'chart');
  wrap.append(el('h3', null, title));
  const data = pairs.filter(([, v]) => v != null && isFinite(v));
  if (data.length === 0) {
    wrap.append(el('p', 'hint', '표시할 값이 없습니다'));
    return wrap;
  }
  const W = 300, H = 70, PAD = 4;
  const xs = data.map(([x]) => x), ys = data.map(([, y]) => y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x) => (x1 === x0 ? W / 2 : PAD + ((x - x0) / (x1 - x0)) * (W - PAD * 2));
  const sy = (y) => (y1 === y0 ? H / 2 : H - PAD - ((y - y0) / (y1 - y0)) * (H - PAD * 2));

  const path = data.map(([x, y], i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join('');
  const last = data[data.length - 1];
  const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${title}">
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${sx(last[0]).toFixed(1)}" cy="${sy(last[1]).toFixed(1)}" r="3" fill="var(--accent)"/>
    <text class="axis" x="0" y="${H + 10}">${x0}</text>
    <text class="axis" x="${W}" y="${H + 10}" text-anchor="end">${x1}</text>
  </svg>`;
  wrap.insertAdjacentHTML('beforeend', svg);
  return wrap;
}

/* ─────────── 2×2 매트릭스 ─────────── */
function buildMatrix() {
  const pts = state.tollgates.filter((t) => t.traffic_score != null && t.price_score != null);
  const W = 420, H = 420, PAD = 34;
  const sx = (v) => PAD + (v / 100) * (W - PAD * 2);
  const sy = (v) => H - PAD - (v / 100) * (H - PAD * 2);

  const dots = pts.map((t) =>
    `<circle cx="${sx(t.traffic_score).toFixed(1)}" cy="${sy(t.price_score).toFixed(1)}" r="4"
       fill="${quad(t.quadrant_key).color}" fill-opacity=".8"
       data-id="${t.tollgate_id}"><title>${t.name || t.tollgate_id} · ${quad(t.quadrant_key).label}</title></circle>`).join('');

  $('#matrix').innerHTML = `<svg viewBox="0 0 ${W} ${H + 14}" role="img"
      aria-label="교통량 모멘텀과 가격 모멘텀 산점도">
    <rect x="${PAD}" y="${PAD}" width="${W - PAD * 2}" height="${H - PAD * 2}"
          fill="none" stroke="var(--border)"/>
    <line x1="${sx(50)}" y1="${PAD}" x2="${sx(50)}" y2="${H - PAD}" stroke="var(--border-strong)" stroke-dasharray="3 3"/>
    <line x1="${PAD}" y1="${sy(50)}" x2="${W - PAD}" y2="${sy(50)}" stroke="var(--border-strong)" stroke-dasharray="3 3"/>
    <text x="${sx(75)}" y="${sy(96)}" text-anchor="middle" font-size="11" fill="var(--q-rising)">동반 상승</text>
    <text x="${sx(25)}" y="${sy(96)}" text-anchor="middle" font-size="11" fill="var(--q-over)">과열 주의</text>
    <text x="${sx(75)}" y="${sy(2)}" text-anchor="middle" font-size="11" fill="var(--q-under)" font-weight="600">저평가 후보</text>
    <text x="${sx(25)}" y="${sy(2)}" text-anchor="middle" font-size="11" fill="var(--q-quiet)">관망</text>
    ${dots}
    <text x="${W / 2}" y="${H + 8}" text-anchor="middle" font-size="11" fill="var(--faint)">교통량 모멘텀 →</text>
    <text x="10" y="${H / 2}" font-size="11" fill="var(--faint)"
          transform="rotate(-90 10 ${H / 2})" text-anchor="middle">가격 모멘텀 →</text>
  </svg>`;

  $('#matrix').addEventListener('click', (e) => {
    const id = e.target.dataset && e.target.dataset.id;
    if (id) focusOnMap(id);
  });
}

/* ─────────── 순위 표 ─────────── */
function buildBoardTable() {
  const body = $('#board-table tbody');
  const render = (query = '') => {
    const rows = state.tollgates
      .filter((t) => t.traffic_score != null)
      .filter((t) => !query || (t.name || t.tollgate_id).includes(query))
      .sort((a, b) => b.traffic_score - a.traffic_score);
    body.innerHTML = rows.map((t) => {
      const info = quad(t.quadrant_key);
      return `<tr data-id="${t.tollgate_id}">
        <td>${t.name || t.tollgate_id}</td>
        <td><span class="q-tag" style="--c:${info.color}">${info.label}</span></td>
        <td class="num">${pct(t.traffic_cagr)}</td>
        <td class="num">${pct(t.price_cagr)}</td>
        <td class="num">${num(t.n_trades)}</td>
        <td>${t.confidence || '—'}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="empty">해당 영업소가 없습니다</td></tr>';
  };
  render();
  $('#board-search').addEventListener('input', (e) => render(e.target.value.trim()));
  body.addEventListener('click', (e) => {
    const row = e.target.closest('tr[data-id]');
    if (row) focusOnMap(row.dataset.id);
  });
}


/* ─────────── 행정구역 인구 ─────────── */
/* 시군구 대표점에 인구만큼 원을 그린다.
 *
 * 크기는 **넓이에 비례**시킨다(반지름은 √인구). 반지름을 인구에 그대로
 * 비례시키면 인구가 4배인 곳이 넓이로는 16배로 보여, 큰 도시가 화면을
 * 통째로 덮고 작은 군은 점이 된다. 사람은 원을 넓이로 읽는다.
 *
 * 대표점은 행정구역의 기하학적 중심이 아니다 — 우리가 이미 가진 법정동
 * 중심점의 중앙값이다(webexport._regions). 몇 km 어긋날 수 있어서
 * 말풍선에도 그렇게 적는다.
 */
/* 크기를 **네 단**으로 끊는다 (2026-09-04 요구사항: "간단하게").
 *
 * 원 넓이를 인구에 그대로 비례시키면 크기가 235가지가 된다. 그러면 두 원을
 * 나란히 놓고도 어느 쪽이 큰지 눈으로 못 가른다 — 크기는 순서를 말할 때는
 * 좋지만 값을 읽는 데는 나쁘다. 몇 단이면 한눈에 갈린다.
 *
 * **단은 묶음 단위마다 다르다.** 시군구 기준으로 잡은 5만·20만·50만을
 * 시도에 그대로 쓰면 17곳이 전부 맨 위 칸에 들어가 원이 다 같아진다
 * (가장 작은 세종이 39만, 가장 큰 경기가 1,360만이다). 단위가 바뀌면
 * 자르는 자리도 같이 바뀌어야 한다. */
const POP_LEVELS = [
  { key: 'sido', label: '시·도', minZoom: 0,
    hint: '도 · 광역시 단위',
    tiers: [
      { max: 1000000, r: 9, label: '100만 이하' },
      { max: 3000000, r: 14, label: '300만 이하' },
      { max: 6000000, r: 19, label: '600만 이하' },
      { max: Infinity, r: 25, label: '600만 초과' },
    ] },
  { key: 'si', label: '시·군', minZoom: 9,
    hint: '시(광역시 포함) · 군 단위',
    tiers: [
      { max: 100000, r: 7, label: '10만 이하' },
      { max: 300000, r: 12, label: '30만 이하' },
      { max: 1000000, r: 17, label: '100만 이하' },
      { max: Infinity, r: 23, label: '100만 초과' },
    ] },
  { key: 'gu', label: '구·시·군', minZoom: 11,
    hint: '자치구까지 나눈 단위',
    tiers: [
      { max: 50000, r: 6, label: '5만 이하' },
      { max: 200000, r: 11, label: '20만 이하' },
      { max: 500000, r: 16, label: '50만 이하' },
      { max: Infinity, r: 22, label: '50만 초과' },
    ] },
];

/* 지금 배율에서 어느 단위로 묶을 것인가.
 *
 * 요구사항(2026-09-07): "지도 화면 축적/크기에 따라 도/광역시 기준,
 * 시(광역시 포함)/군 기준, 구 기준으로." 전국을 볼 때 247개 원이 서로
 * 겹쳐 있으면 아무것도 안 읽힌다 — 그때 필요한 것은 17개다. */
function popLevel(zoom) {
  let out = POP_LEVELS[0];
  POP_LEVELS.forEach((lv) => { if (zoom >= lv.minZoom) out = lv; });
  return out;
}

/* 특별시·광역시·특별자치시. '시·군' 단위에서 이들은 **하나로 묶는다** —
 * 요구사항의 "시(광역시 포함)" 가 그 뜻이다. 서울을 25개 구로 흩어
 * 놓으면 부산·대구와 나란히 못 본다. */
const METRO = /(특별시|광역시|특별자치시)$/;

/* 화면에 적을 이름. */
function popGroupName(r, levelKey) {
  if (levelKey === 'sido') return r.sido || r.parent || r.name;
  if (levelKey === 'si') {
    if (METRO.test(r.sido || '')) return r.sido;
    // '수원시 장안구' 는 '수원시' 로. 내보내기가 parent 에 넣어 준다.
    return r.parent || r.name;
  }
  return r.name;
}

/* 묶는 열쇠. **이름만으로는 안 된다.**
 *
 * 보고된 문제(2026-09-09): "서울 강서구가 안성에 있습니다."
 *
 * 그랬습니다. 열쇠가 이름뿐이라 서울 강서구(11500)와 부산 강서구(26440)가
 * 한 칸으로 묶였고, 대표점이 둘의 인구가중 평균 —
 *
 *   서울 37.5647,126.8182 (55만) + 부산 35.1304,128.8863 (15만)
 *   → 37.0420, 127.2622   ← 안성·평택 언저리
 *
 * 인구도 70만으로 합쳐졌습니다. 지도 한복판에 있지도 않은 구가 하나
 * 생긴 셈입니다.
 *
 * 겹치는 이름이 일곱, 걸린 구·군이 스물다섯입니다.
 *
 *   동구 5 · 중구 4 · 서구 4 · 남구 4 · 북구 4 · 강서구 2 · 고성군 2
 *
 * 시·도를 앞에 붙여 가릅니다. 이미 조회수 열쇠(placeKey)는 그렇게 하고
 * 있었는데 — "'고성군' 은 강원과 경남에 둘이고, '중구' 는 여섯이다" —
 * 정작 **묶는 열쇠에는 그 규칙이 안 들어가 있었습니다.**
 *
 * 시·군 단계도 같습니다. 광역시의 구는 시·도로 묶이니 무사한데, 도
 * 아래의 고성군 둘은 여기서도 겹칩니다. */
function popGroupKey(r, levelKey) {
  const name = popGroupName(r, levelKey);
  if (levelKey === 'sido') return name;          // 시·도 이름은 안 겹친다
  return `${r.sido || ''}|${name}`;
}

function popYear() {
  if (!Array.isArray(state.regions) || !state.regions.length) return null;
  const years = new Set();
  state.regions.forEach((r) => Object.keys(r.pop || {}).forEach((y) => years.add(y)));
  if (!years.size) return null;
  const sorted = [...years].sort();
  // 교통량 화면이 보고 있는 해와 맞춘다. 그 해 인구가 없으면 가장 최근 해.
  const want = String(state.popYear || state.tgYear || '');
  return years.has(want) ? want : sorted[sorted.length - 1];
}

/* 묶은 단위 하나의 중심 — 그 단위의 **관청**.
 *
 * 요구사항(2026-09-07): "인구 표시 원의 중심은 도청/시청/구청/군청
 * 소재지가 중심이 되도록." 브이월드 장소검색에서 받아 두었다
 * (redt.cli offices → office 표).
 *
 *   구 단위   regions.json 의 각 행이 office_lat/office_lon 을 들고 온다
 *   시·시도   meta.region_offices[단위][이름] = [lat, lon]
 *
 * 못 받은 곳은 **인구로 가중한 평균**으로 물러난다. 시군구 대표점을
 * 그냥 평균내면 인구 3만인 군과 60만인 시가 같은 무게로 잡아당겨, 도의
 * 중심이 사람이 안 사는 산으로 간다. 물러났다는 사실은 말풍선이 적는다 —
 * 관청 위에 찍힌 원과 그렇지 않은 원이 화면에서 같아 보이면 안 된다. */
function popCenter(group, levelKey, year) {
  const members = group.members;
  // ① 묶은 단위 자체의 관청 (시·도, 시·군)
  const table = (state.meta.region_offices || {})[levelKey] || {};
  const hit = table[group.name];
  if (Array.isArray(hit) && hit.length === 2) return { at: hit, office: true };
  // ② 안 묶였으면 그 시군구 자신의 관청
  if (members.length === 1) {
    const r = members[0];
    if (r.office_lat && r.office_lon) {
      return { at: [r.office_lat, r.office_lon], office: true };
    }
  }
  // ③ 물러남 — 인구로 가중한 대표점
  let wsum = 0, lat = 0, lon = 0;
  members.forEach((r) => {
    const w = (r.pop || {})[year] || 1;
    wsum += w; lat += r.lat * w; lon += r.lon * w;
  });
  return {
    at: wsum ? [lat / wsum, lon / wsum] : [members[0].lat, members[0].lon],
    office: false,
  };
}

/* 인구 원은 사라졌다 (요구사항 2026-09-08).

   "화면 상단 인구 및 IC범위 체크는 삭제합니다."

   원을 지우면서 인구를 버리지는 않는다 — **땅값 글자 옆으로 옮겼다**
   (lpItemsRegion 의 pop). 원은 크기가 곧 값이라 서로 겹쳐 가렸고,
   정작 옆에 적힌 땅값과 견주려면 눈이 두 번 오갔다. 같은 자리에
   나란히 적으면 한 번에 읽힌다. */

/* ─────────── 땅값 지도 ─────────── */
/* 요구사항(2026-09-08, 넷째 묶음):
 *   "좌측 범례 삭제 / 호갱노노처럼 사각형으로 변경 후 동, 리 이름만 표시
 *    가격 아래로 / 마우스 오버랩시 정보와 실거래가격 트랜드 표시 /
 *    용도지역 선택 시 선택된 용도지역의 중간값으로 가격 변환"
 *
 * 마지막 것이 구조를 바꾼다. **용도지역 고르기가 두 군데 있었다** —
 * 왼쪽 필터(거래 점용)와 이 막대의 칩(땅값용). 같은 것을 두 번 고르게
 * 하면 둘이 어긋난 채로 보게 되고, 그러면 지도의 점과 글자가 서로 다른
 * 땅을 말한다. 그래서 칩을 없애고 **왼쪽 필터 하나를 따른다.**
 * 그 기본값이 이미 계획관리·생산관리·자연녹지 셋이다. */

/* 파란 계열 다섯 칸 (요구사항). 밝을수록 싸고 짙을수록 비싸다. */
const LP_COLORS = ['#7FB3E0', '#5B93D6', '#3B73C4', '#2454A6', '#123B7A'];
const LP_LABELS = ['가장 싼 20%', '', '가운데', '', '가장 비싼 20%'];
/* 거래가 없는 지자체. **파란 칸에 안 넣는다** — 값이 없는 것을 '가장 싼
 * 20%' 로 칠하면 그 지역이 싸다고 말하는 것이 된다. 회색은 '모른다' 다.
 *
 * 옅게 두는 것도 뜻이 있다. 값이 있는 칸과 같은 무게로 칠하면 빈 칸이
 * 지도를 덮어, 정작 읽을 숫자가 그 사이에 묻힌다. 없는 것은 물러나야
 * 한다. 대신 바탕이 옅으므로 글자는 어둡게 쓴다(.lp-card.is-none). */
const LP_NONE_COLOR = '#E4E8ED';

/*   11 이하   시·도 / 시·군 / 구
 *   12        읍·면·동  — 리를 면으로 묶는다 ('백곡면')
 *   13 이상    리·동     — 그대로 ('백곡면 사송리')
 * 도시의 법정동은 애초에 한 마디('정자동')라 두 단계가 같아진다. */
const LP_UMD_ZOOM = 12;
const LP_RI_ZOOM = 13;
/* 한 화면에 글자를 몇 개까지. 넘으면 거래가 많은 곳부터 남긴다. */
const LP_MAX_LABELS = 90;
/* 내보내기(webexport.LANDPRICE_MIN_N)와 같은 값. 안내문에 쓴다. */
const LP_MIN_LABEL = 5;

let lpUmdCache = {};      // "용도지역|시도두자리" → cells
const lpUmdPending = new Set();

/* 전국 법정동 명부 조각. 땅값 조각과 달리 **용도지역이 없다** — 거래와
 * 무관한 원부라 시·도 하나에 파일 하나다. 열쇠는 시도 두 자리. */
let lpRosterCache = {};
const lpRosterPending = new Set();

/* 지금 열려 있는 말풍선의 태그 열쇠. 없으면 null.
 *
 * 보고된 문제(2026-09-10): "태그 클릭 시 정보가 나오는데 너무 민감한
 * 것 같습니다. 조심히 누르지 않거나 가장자리 태그 클릭 시 지도가
 * 옮겨지면서 계속 사라집니다."
 *
 * 손가락이 조금 미끄러지거나 가장자리 태그에서 지도가 스스로 밀리면
 * (autoPan) moveend 가 오고, 그때 태그를 **전부 지우고 다시 만듭니다**
 * (drawLandPrice 의 clearLayers). 방금 열린 말풍선은 그 마커에 붙어
 * 있었으므로 함께 사라집니다. 즉 말풍선을 보여주려고 켠 autoPan 이
 * 그 말풍선을 스스로 죽이고 있었습니다.
 *
 * 그래서 **말풍선이 열려 있는 동안에는 화면을 옮겨도 태그를 다시
 * 그리지 않습니다.** 읽는 중인 사람에게 태그 갱신은 필요 없고, 닫으면
 * 그때 한 번 다시 그립니다. */
let lpOpenPk = null;
let lpDrawing = false;
/* 손가락을 끌었는가. 끌었다면 그 끝의 '누름' 은 누른 것이 아니다.
 *
 * Leaflet 은 마커 위에서 시작한 끌기를 **누름으로도** 셉니다 —
 * 마커가 지도와 함께 움직여서 손가락이 계속 그 위에 있기 때문입니다.
 * 그래서 지도를 옮기려고 태그 위에서 끌면 말풍선이 딸려 열립니다.
 * 끌기가 있었으면 열지 않습니다. */
let lpDragged = false;
/* 말풍선이 열려 있는 동안 미뤄 둔 다시 그리기가 있는가. */
let lpPending = false;

/* ㎡ 단가를 **평당**으로 바꿔 짧게 쓴다. ㎡당 30만원은 감이 안 오지만
 * 평당 100만원은 바로 온다. */
/* ─── 값을 적는 규칙 ───────────────────────────────────────────────
 *
 * 보고된 문제(2026-09-09): "값의 단위가 화면마다 다릅니다. 지도 카드는
 * 86.9만/평, 말풍선은 592,441원/평, 필지 카드는 250,000원/㎡."
 *
 * 규칙은 둘이고, 여기서만 정한다.
 *
 *   훑는 자리(지도 카드·요약·눈금)   → 평당, 만/억으로 줄여서   lpMoney()
 *   짚는 자리(말풍선·상세)           → 평당 원 그대로, ㎡ 는 아랫줄
 *                                      perPy() / perM2()
 *
 * **㎡ 를 먼저 적지 않는다.** 토지·공장을 실제로 사고파는 자리에서는
 * 평으로 값을 셈한다. ㎡ 는 공부(公簿)의 단위라 확인용으로 뒤에 붙인다.
 */
const perPy = (perM2) => Math.round(perM2 * PYEONG_M2).toLocaleString('ko-KR');
const perM2Str = (perM2) => Math.round(perM2).toLocaleString('ko-KR');

function lpMoney(perM2) {
  const py = perM2 * PYEONG_M2;
  if (py >= 100000000) return `${(py / 100000000).toFixed(py >= 1000000000 ? 0 : 1)}억`;
  if (py >= 10000) {
    const man = py / 10000;
    return `${man >= 1000 ? Math.round(man) : man.toFixed(man >= 100 ? 0 : 1)}만`;
  }
  return `${Math.round(py).toLocaleString('ko-KR')}원`;
}

function lpWindows() {
  return (state.landPrice && state.landPrice.windows) || [];
}
function lpWindow() {
  const ws = lpWindows();
  return ws.find((w) => w.key === state.lpWindow) || ws[0] || null;
}

/* **땅값 글자의 용도지역은 거래 점 필터와 따로 논다.**
 *
 * 요구사항(2026-09-08): "실거래 표시에 용도지역과 실거래 가격의
 * 용도지역을 구분하여, 지도에 표시된 중앙값은 실거래 표시와 무관하게
 * 나타낼 수 있도록 수정해주세요."
 *
 * 앞서 하나로 합쳤던 것을 다시 가른다. 합쳐 두면 거래 점을 걸러 볼
 * 때마다 지도의 중앙값이 함께 흔들린다 — **바탕이 움직이면 견줄 수가
 * 없다.** 점은 찾는 도구이고 중앙값은 자로 삼는 것이라, 자가 손을
 * 따라 움직이면 안 된다. */
/* 용도지역 범례 — 색과 무늬.
 *
 * 요구사항(2026-09-08): "용도 지역 선택하면 체크가 아니라 용도 지역
 * 범례 표시 (색상과 패턴)이 들어 가도록 해주세요."
 *
 * 체크상자 스물다섯 개는 목록이지 범례가 아니다. 무엇을 켰는지는
 * 알려주지만 **그것이 무슨 땅인지**는 안 알려준다. 색을 칸에 직접
 * 칠하면 목록이 곧 범례가 된다.
 *
 * 색만으로는 모자란 이유가 둘이다.
 *   · 주거 다섯, 상업 넷, 공업 셋은 같은 계열이라 색만으로 못 가른다.
 *     한 계열 안에서 진하기로 서열을 주고, **무늬로 갈래를 표시**한다.
 *   · 남성 스무 명 중 한 명은 적록색약이다. 초록 계열 여섯이 색상만
 *     다르면 그 사람에게는 전부 같은 칸이다. 무늬는 색을 안 탄다.
 *
 * 무늬는 셋만 쓴다 — 없음 / 사선 / 점. 넷을 넘기면 12px 칸에서 서로
 * 구별이 안 되어 무늬가 오히려 잡음이 된다.
 *
 * **브이월드 지적편집도와 같은 색이 아니다.** 색면은 브이월드가 서버에서
 * 칠해 보내주므로 우리에게 팔레트가 없다. 여기 색은 우리 것이고,
 * 국토계획법 관례(주거 노랑·상업 분홍·공업 보라·녹지 초록)만 따른다.
 */
const ZONE_STYLE = {
  // 비도시지역 — 흙빛·연녹
  '계획관리':       { c: '#E4D9A6', p: '' },
  '생산관리':       { c: '#CBDFA4', p: 'd' },
  '보전관리':       { c: '#A6C888', p: 'o' },
  '농림':           { c: '#BCD79C', p: '' },
  '자연환경보전':   { c: '#8AC3B2', p: 'o' },
  '관리(미세분)':   { c: '#D9D0AC', p: 'd' },
  // 도시지역 · 녹지
  '자연녹지':       { c: '#A3CE8A', p: '' },
  '생산녹지':       { c: '#BBDA9C', p: 'd' },
  '보전녹지':       { c: '#7FB06C', p: 'o' },
  // 도시지역 · 주거 (노랑, 종이 올라갈수록 진하게)
  '제1종전용주거':  { c: '#FFF1BC', p: 'o' },
  '제2종전용주거':  { c: '#FFE79C', p: 'o' },
  '제1종일반주거':  { c: '#FFDF8C', p: '' },
  '제2종일반주거':  { c: '#FFCE62', p: '' },
  '제3종일반주거':  { c: '#FFB937', p: '' },
  '준주거':         { c: '#FFAB7C', p: '' },
  '전용주거(미세분)': { c: '#FFF3CC', p: 'd' },
  '일반주거(미세분)': { c: '#FFDCA2', p: 'd' },
  // 도시지역 · 상업 (분홍)
  '중심상업':       { c: '#EF5F92', p: '' },
  '일반상업':       { c: '#F48EB0', p: '' },
  '근린상업':       { c: '#F9BCD0', p: '' },
  '유통상업':       { c: '#E0A8C6', p: 'd' },
  // 도시지역 · 공업 (보라)
  '전용공업':       { c: '#9A79C2', p: '' },
  '일반공업':       { c: '#B69AD4', p: '' },
  '준공업':         { c: '#D1BCE6', p: '' },
  // 용도구역
  '개발제한구역':   { c: '#9DB7A5', p: 'd' },
};

const ZONE_FALLBACK = { c: '#C9CDD4', p: '' };

/* 칸 하나의 배경. 무늬는 색 위에 얹는 겹배경으로 그린다 —
   따로 요소를 두면 12px 칸 안에서 자리가 안 나온다. */
function zoneSwatch(g) {
  const st = ZONE_STYLE[g] || ZONE_FALLBACK;
  if (st.p === 'd') {
    return `repeating-linear-gradient(45deg,`
      + `rgba(0,0,0,.22) 0 1.5px, transparent 1.5px 4.5px), ${st.c}`;
  }
  if (st.p === 'o') {
    return `radial-gradient(rgba(0,0,0,.28) 1px, transparent 1.2px)`
      + ` 0 0/4px 4px, ${st.c}`;
  }
  return st.c;
}

/* 인구를 **만명** 단위로 (요구사항 2026-09-08).

   "이름 옆에 인구를 아주 작게 표시해 주세요. (XX만) 단위는 만명"

   10만 위는 소수점을 뗀다 — '136.0만' 의 .0 은 자리만 먹고 알려주는
   것이 없다. 10만 아래는 한 자리를 남긴다. 안 남기면 안성(19만)과
   울릉(0.9만)이 둘 다 '0만' 이 된다. */
function popMan(v) {
  if (!(typeof v === 'number' && v > 0)) return '';
  const man = v / 10000;
  return (man >= 10 ? Math.round(man) : man.toFixed(1)) + '만';
}

function lpGroups() {
  const have = Object.keys((state.landPrice || {}).groups || {});
  return have.filter((g) => state.lpGroupSet.has(g));
}

/* 한 칸의 창 값. [건수, 중앙값, 평균, 시작연도]. */
function lpOne(cell) {
  const w = cell && cell[state.lpWindow];
  if (!w) return null;
  const v = state.lpStat === 'avg' ? w[2] : w[1];
  if (!(typeof v === 'number' && v > 0)) return null;
  return { v, n: w[0], from: w[3], s: cell.s || null };
}

/* **여러 용도지역을 하나로 섞는다.** 거래 건수로 가중한다.
 *
 * 평균끼리 섞으면 그 결과는 정확한 전체 평균이다. 중앙값끼리 섞는 것은
 * 근사다 — 진짜 합동 중앙값이 아니다. 두 용도지역의 분포가 많이 다르면
 * 조금 어긋난다. 그래서 **여럿을 섞었을 때는 말풍선에 그렇게 적는다.** */
function lpMix(cells) {
  let wsum = 0; let vsum = 0; let n = 0; let from = Infinity;
  const parts = [];
  const years = new Map();
  cells.forEach(({ group, cell }) => {
    const got = lpOne(cell);
    if (!got) return;
    wsum += got.n; vsum += got.v * got.n; n += got.n;
    from = Math.min(from, got.from);
    parts.push({ group, v: got.v, n: got.n });
    (got.s || []).forEach(([y, cnt, p50]) => {
      const cur = years.get(y) || { w: 0, v: 0 };
      cur.w += cnt; cur.v += p50 * cnt;
      years.set(y, cur);
    });
  });
  if (!wsum) return null;
  const trend = [...years.entries()].sort((x, y) => x[0] - y[0])
    .map(([y, o]) => [y, o.w, o.v / o.w]);
  return { v: vsum / wsum, n, from, parts, trend };
}

/* 지금 화면에 걸치는 조각들 (용도지역 하나에 대해). */
function lpUmdChunks(group) {
  const idx = ((state.landPrice || {}).umd_index || {})[group] || [];
  if (!map) return idx;
  const b = map.getBounds();
  const sw = b.getSouthWest ? b.getSouthWest() : null;
  const ne = b.getNorthEast ? b.getNorthEast() : null;
  if (!sw || !ne) return idx;
  return idx.filter((c) => !(c.bbox[2] < sw.lat || c.bbox[0] > ne.lat
                             || c.bbox[3] < sw.lng || c.bbox[1] > ne.lng));
}

function lpUmdReady() {
  return lpGroups().some((g) =>
    lpUmdChunks(g).some((c) => lpUmdCache[`${g}|${c.p}`]));
}

/* 지금 화면에 걸치는 명부 조각들. 색인은 landprice.json 의 umd_roster. */
function lpRosterChunks() {
  const idx = (state.landPrice || {}).umd_roster || [];
  if (!map || !idx.length) return idx;
  const b = map.getBounds();
  const sw = b.getSouthWest ? b.getSouthWest() : null;
  const ne = b.getNorthEast ? b.getNorthEast() : null;
  if (!sw || !ne) return idx;
  return idx.filter((c) => !(c.bbox[2] < sw.lat || c.bbox[0] > ne.lat
                             || c.bbox[3] < sw.lng || c.bbox[1] > ne.lng));
}

/* 화면에 걸치는 명부 조각을 받아 둔다. */
async function lpLoadRoster() {
  const want = lpRosterChunks().filter(
    (c) => !lpRosterCache[c.p] && !lpRosterPending.has(c.p));
  if (!want.length) return;
  want.forEach((c) => lpRosterPending.add(c.p));
  await Promise.all(want.map(async (c) => {
    try {
      const r = await fetch(`/app/data/${c.f}`, { cache: 'no-cache' });
      if (r.ok) lpRosterCache[c.p] = await r.json();
    } catch (e) {
      // 못 받아도 지도는 거래 있는 곳만으로 계속 돈다.
    } finally {
      lpRosterPending.delete(c.p);
    }
  }));
  drawLandPrice();
}

/* 아직 오는 중이면 시군구로 물러난다 — 빈 화면을 보여주느니 덜 자세한
 * 것이 낫다. 사용자는 '고장' 과 '로딩 중' 을 구별하지 못한다. */
function lpLevel(zoom) {
  if (zoom >= LP_UMD_ZOOM && lpUmdReady()) {
    return zoom >= LP_RI_ZOOM
      ? { key: 'ri', label: '리·동' }
      : { key: 'umd', label: '읍·면·동' };
  }
  return popLevel(zoom);
}

/* 화면 안에 드는 것만, 거래가 많은 순으로 잘라서. */
function lpVisible(items) {
  if (!map) return items;
  const b = map.getBounds();
  const inside = items.filter((it) => b.contains(it.at));
  if (inside.length <= LP_MAX_LABELS) return inside;
  return inside.slice().sort((a, b2) => b2.n - a.n).slice(0, LP_MAX_LABELS);
}

/* 시도·시군·구 — regions.json 의 좌표를 타고 묶는다. */
function lpItemsRegion(levelKey) {
  const groups = lpGroups();
  const src = (state.landPrice || {}).groups || {};
  const bag = new Map();
  (state.regions || []).forEach((r) => {
    const cd = String(r.sigungu_cd);
    const cells = groups.map((g) => ({ group: g, cell: (src[g] || {})[cd] }))
      .filter((x) => x.cell);
    const got = lpMix(cells);
    const key = popGroupKey(r, levelKey);
    if (!bag.has(key)) {
      // **열쇠와 이름은 다르다.** 열쇠에는 시·도가 붙어 있다.
      bag.set(key, { name: popGroupName(r, levelKey), key,
                     members: [], wsum: 0, vsum: 0, n: 0, few: 0,
                     from: Infinity, years: new Map(), parts: new Map() });
    }
    const g = bag.get(key);
    // **값이 없어도 지자체는 담는다** (요구사항 2026-09-09).
    //
    // 예전에는 여기서 그냥 돌아섰다. 그러면 그 용도지역 거래가 없는
    // 지자체는 지도에서 **통째로 사라졌다** — 대전에서 유성구와 대덕구만
    // 남고 동구·중구·서구가 안 보인 것이 그것이었다. 지도에 지자체가
    // 없으면 사람은 '자료가 없다' 가 아니라 '이 지도가 고장났다' 로
    // 읽는다. 이름은 늘 있고, 값이 없다는 사실을 값 자리에 적는다.
    g.members.push(r);
    if (!got) {
      // 왜 값이 없는지는 둘로 갈린다. 거래가 0건인 곳과, 있었지만
      // 다섯 건이 안 돼 값으로 안 쓴 곳. 뒤엣것에 '0' 을 적으면 거짓이
      // 되므로 건수를 세어 둔다.
      cells.forEach(({ cell }) => {
        g.few += ((cell && cell.few) || {})[state.lpWindow] || 0;
      });
      return;
    }
    g.wsum += got.n; g.vsum += got.v * got.n; g.n += got.n;
    g.from = Math.min(g.from, got.from);
    got.parts.forEach((pt) => {
      const cur = g.parts.get(pt.group) || { w: 0, v: 0 };
      cur.w += pt.n; cur.v += pt.v * pt.n;
      g.parts.set(pt.group, cur);
    });
    got.trend.forEach(([y, cnt, p50]) => {
      const cur = g.years.get(y) || { w: 0, v: 0 };
      cur.w += cnt; cur.v += p50 * cnt;
      g.years.set(y, cur);
    });
  });
  const year = String(popYear() || '');
  // 인구 원이 사라진 자리를 이 숫자가 대신한다 (요구사항 2026-09-08).
  //
  // **거래가 있는 시군구만 더하면 안 된다.** g.members 에는 켠 용도지역의
  // 값이 있는 시군구만 들어 있다. 경기도는 47곳인데 계획관리 거래가 있는
  // 곳만 세면 도시 쪽 구가 통째로 빠진다 — 검사 fixture 에서 경기도가
  // 110만이 아니라 65만으로 나온 것이 그것이었다. 인구는 행정구역의
  // 인구지 '거래가 있는 곳의 인구' 가 아니다. 그러니 **묶음 열쇠가 같은
  // 시군구를 전부** 더한다.
  const popByKey = new Map();
  (state.regions || []).forEach((r) => {
    const v = (r.pop || {})[year];
    if (!(typeof v === 'number' && v > 0)) return;
    const k = popGroupKey(r, levelKey);
    popByKey.set(k, (popByKey.get(k) || 0) + v);
  });
  return [...bag.values()].map((g) => ({
    name: g.name,
    // 거래가 없으면 값도 없다. 0 을 넣으면 '평당 0원' 이라는 뜻이 되고
    // 분위 눈금까지 그쪽으로 끌린다. **없는 것은 null 이다.**
    few: g.few,
    // 조회수를 셀 열쇠. **이름만으로는 안 된다** — '고성군' 은 강원과
    // 경남에 둘이고, '중구' 는 여섯이다. 시·도 자리를 함께 적는다.
    pk: placeKey(levelKey, g.members[0], g.name),
    sg: String((g.members[0] || {}).sigungu_cd || ''),
    // **열쇠로 찾는다.** 이름으로 찾으면 안 된다 — 열쇠에는 시·도가
    // 붙어 있어서('경기도|용인시') 이름과 다르다. 강서구를 가르면서
    // 열쇠를 바꿔 놓고 이 줄을 안 고쳐, 시·군·구 태그의 인구가 통째로
    // 사라졌다 (보고된 문제 2026-09-09 — "인구 표시가 안됩니다").
    pop: popByKey.get(g.key) || 0,
    v: g.wsum ? g.vsum / g.wsum : null,
    n: g.n,
    from: Number.isFinite(g.from) ? g.from : null,
    parts: g.members.length,
    at: popCenter(g, levelKey, year).at,
    byGroup: [...g.parts.entries()].map(([k, o]) => ({ group: k, v: o.v / o.w, n: o.w })),
    trend: [...g.years.entries()].sort((a, b2) => a[0] - b2[0])
      .map(([y, o]) => [y, o.w, o.v / o.w]),
  }));
}

/* 읍·면·동 / 리·동. 리 단계는 그대로, 면 단계는 첫 마디로 묶는다. */
function lpItemsUmd(levelKey) {
  const groups = lpGroups();
  // 같은 칸(시군구+법정동)에 여러 용도지역이 있으므로 먼저 모은다.
  const byCell = new Map();
  groups.forEach((g) => {
    lpUmdChunks(g).forEach((c) => {
      const chunk = lpUmdCache[`${g}|${c.p}`];
      if (!chunk) return;
      const heads = chunk.headPop || {};
      chunk.forEach((x) => {
        const key = `${x.sg}|${x.nm}`;
        if (!byCell.has(key)) {
          // 면 인구는 조각이 따로 실어 준다 — 리 값을 합친 것이 아니다.
          const head = String(x.nm).split(' ')[0];
          byCell.set(key, { info: { ...x, headPop: heads[`${x.sg}|${head}`] || 0 },
                            cells: [] });
        }
        byCell.get(key).cells.push({ group: g, cell: x.w });
      });
    });
  });
  const out = [];
  const bag = new Map();
  byCell.forEach(({ info, cells }) => {
    const got = lpMix(cells);
    if (!got) return;
    if (levelKey === 'ri') {
      out.push({
        name: info.nm, sub: info.sgnm, full: info.nm,
        pk: `u:${info.sg}:${info.nm}`, sg: String(info.sg),
        // 읍·면·동 인구 (요구사항 2026-09-09). **없으면 안 적는다** —
        // KOSIS 는 행정동이고 우리는 법정동이라 이름이 안 맞는 곳이
        // 있다. 그 자리에 시군구 인구를 넣으면 리 하나가 20만이 된다.
        pop: info.pop || 0,
        v: got.v, n: got.n, from: got.from, parts: 1,
        at: [info.lat, info.lon],
        byGroup: got.parts, trend: got.trend,
      });
      return;
    }
    const myeon = String(info.nm).split(' ')[0];
    const key = `${info.sg}|${myeon}`;
    if (!bag.has(key)) {
      bag.set(key, { name: myeon, sub: info.sgnm, wsum: 0, vsum: 0, n: 0,
                     from: got.from, lat: 0, lon: 0, parts: 0, pop: 0,
                     years: new Map(), byGroup: new Map() });
    }
    const g = bag.get(key);
    g.wsum += got.n; g.vsum += got.v * got.n; g.n += got.n;
    g.from = Math.min(g.from, got.from);
    g.lat += info.lat; g.lon += info.lon; g.parts += 1;
    // **리 인구를 합치는 것이 아니다.** 우리는 리 인구를 갖고 있지
    // 않다 — KOSIS 가 주는 것은 면·동 단위다. 그래서 면 하나의 값을
    // 그대로 쓴다 (조각이 head_pop 에 실어 준다). 리 값을 합치면
    // 인구가 붙은 리만 더해져 면 인구가 실제보다 작아진다.
    if (!g.pop) g.pop = info.headPop || 0;
    got.parts.forEach((pt) => {
      const cur = g.byGroup.get(pt.group) || { w: 0, v: 0 };
      cur.w += pt.n; cur.v += pt.v * pt.n;
      g.byGroup.set(pt.group, cur);
    });
    got.trend.forEach(([y, cnt, p50]) => {
      const cur = g.years.get(y) || { w: 0, v: 0 };
      cur.w += cnt; cur.v += p50 * cnt;
      g.years.set(y, cur);
    });
  });
  bag.forEach((g, key) => out.push({
    name: g.name, sub: g.sub, full: g.name,
    // byCell 의 열쇠는 '41220|안중읍' 이다. 조회수 열쇠는 콜론으로 쓴다.
    pk: `u:${key.replace('|', ':')}`, sg: key.split('|')[0],
    pop: g.pop || 0,
    v: g.vsum / g.wsum, n: g.n, from: g.from, parts: g.parts,
    at: [g.lat / g.parts, g.lon / g.parts],
    byGroup: [...g.byGroup.entries()].map(([k, o]) => ({ group: k, v: o.v / o.w, n: o.w })),
    trend: [...g.years.entries()].sort((a, b2) => a[0] - b2[0])
      .map(([y, o]) => [y, o.w, o.v / o.w]),
  }));
  return out.concat(lpEmptyUmd(levelKey, out));
}

/* 거래가 없는 읍·면·동도 이름은 남긴다 (요구사항 2026-09-09).
 *
 * "거래가 없는 동 이름이 다 안나오네요. 모두 나오도록 해주세요."
 *
 * 왜 안 나왔나. 읍·면·동 태그는 **땅값 조각(landprice-umd-*.json)에서만**
 * 만들어집니다. 그 조각에는 거래가 다섯 건 넘는 칸만 실려 있습니다
 * (webexport.UMD_MIN_TRADES). 그러니 고른 용도지역에 거래가 없는 동은
 * 애초에 재료가 없어 그려질 수가 없었습니다 — 서울에서 여덟 개만 뜬
 * 것이 그것입니다.
 *
 * 첫 손질은 검색 색인(places.json)으로 메우는 것이었습니다. 그런데 그
 * 색인도 **거래에서 나온 목록**이라(거래 세 건 넘은 곳 17,430) 거래가
 * 한 번도 없던 법정동은 여전히 빠졌습니다. 시골의 리가 그렇습니다.
 *
 * 이제는 **명부**를 씁니다 — 행정표준코드에서 받아 좌표를 붙인
 * region_umd 를, 시·도 조각(umd-roster-NN.json)으로 내보낸 것입니다.
 * 거래와 무관한 원부라 빠지는 곳이 없습니다.
 *
 * 명부가 아직 안 실린 배포에서는 예전처럼 검색 색인으로 물러납니다 —
 * 덜 채워지는 것과 아무것도 안 나오는 것은 다른 일입니다. */
function lpEmptyUmd(levelKey, have) {
  if (!map) return [];
  const seen = new Set(have.map((it) => it.pk));
  const b = map.getBounds();
  const bag = new Map();
  const add = (nm, sg, sub, lat, lon, pop) => {
    const name = levelKey === 'ri' ? nm : nm.split(' ')[0];
    const pk = `u:${sg}:${name}`;
    if (seen.has(pk)) return;
    if (!bag.has(pk)) {
      bag.set(pk, { name, sg: String(sg), sub: sub || '',
                    lat: 0, lon: 0, n: 0, pop: 0 });
    }
    const g = bag.get(pk);
    g.lat += lat; g.lon += lon; g.n += 1;
    // 리 여럿이 한 면으로 접힐 때 인구를 더하면 안 된다 — 실려 오는
    // 값은 이미 '면 하나의 인구' 이지 리들의 합이 아니다.
    if (!g.pop && pop) g.pop = pop;
  };

  const chunks = lpRosterChunks()
    .map((c) => lpRosterCache[c.p]).filter(Boolean);
  if (chunks.length) {
    chunks.forEach((chunk) => {
      const sgnm = chunk.sgnm || {};
      const headPop = chunk.head_pop || {};
      (chunk.rows || []).forEach((row) => {
        const [nm, sg, lat, lon, pop] = row;
        if (!b.contains([lat, lon])) return;
        // 면 단계에서는 면 인구를, 리 단계에서는 그 리의 인구만.
        // 리 자리에 면 인구를 넣으면 리 하나가 면 전체 인구가 된다.
        const head = String(nm).split(' ')[0];
        const use = levelKey === 'ri'
          ? pop : (headPop[`${sg}|${head}`] || pop);
        add(String(nm), sg, sgnm[sg], lat, lon, use);
      });
    });
  } else if (findIndex) {
    findIndex.forEach((x) => {
      if (x.k !== 'umd' || !x.sg) return;
      if (!b.contains([x.lat, x.lon])) return;
      add(String(x.n), String(x.sg), x.p, x.lat, x.lon, x.pop);
    });
  } else {
    return [];
  }

  return [...bag.values()].map((g) => ({
    name: g.name, sub: g.sub, full: g.name,
    pk: `u:${g.sg}:${g.name}`, sg: g.sg,
    pop: g.pop || 0,
    // 값이 없다. few 도 모른다 — 조각에 없는 칸이라 건수를 셀 자료가
    // 없다. 말풍선은 '거래 5건 미만' 이라고만 말한다.
    v: null, few: 0, n: 0, from: null, parts: g.n,
    at: [g.lat / g.n, g.lon / g.n],
    byGroup: [], trend: [],
  }));
}

/* 값 → 색. **지역이 적을 때가 함정이다.** 분위수로 끊으면 다섯 곳
 * 미만일 때 경계가 안 만들어져 모두 '가장 싼 20%' 색을 뒤집어쓴다.
 * 그래서 적으면 순위로 편다. 한 곳뿐이면 가운데 색이다. */
function lpScale(values) {
  const v = values.slice().sort((a, b) => a - b);
  if (v.length >= 5) {
    const breaks = [0.2, 0.4, 0.6, 0.8].map((q) => v[Math.floor(v.length * q)]);
    return { kind: 'quantile', breaks, sorted: v };
  }
  return { kind: 'rank', breaks: [], sorted: v };
}

function lpColor(val, scale) {
  if (val == null) return LP_NONE_COLOR;
  if (scale.kind === 'quantile') {
    let i = 0;
    while (i < scale.breaks.length && val >= scale.breaks[i]) i += 1;
    return LP_COLORS[Math.min(i, LP_COLORS.length - 1)];
  }
  const v = scale.sorted;
  if (v.length <= 1) return LP_COLORS[2];        // 비교 대상이 없다
  const rank = v.indexOf(val);
  return LP_COLORS[Math.round((rank / (v.length - 1)) * (LP_COLORS.length - 1))];
}

/* 화면에 걸치는 읍면동 조각을 받아 둔다. 고른 용도지역마다 따로 받는다. */
async function lpLoadUmd() {
  const want = [];
  lpGroups().forEach((g) => {
    lpUmdChunks(g).forEach((c) => {
      const key = `${g}|${c.p}`;
      if (!lpUmdCache[key] && !lpUmdPending.has(key)) want.push({ key, f: c.f });
    });
  });
  if (!want.length) return;
  want.forEach((w) => lpUmdPending.add(w.key));
  await Promise.all(want.map(async (w) => {
    try {
      // **절대 경로여야 한다.** 상대 경로는 …/app 에서 404 가 나고,
      // 그러면 조각이 영영 안 와서 지도가 조용히 시·군으로 물러난다.
      const r = await fetch(`/app/data/${w.f}`, { cache: 'no-cache' });
      if (r.ok) {
        const payload = await r.json();
        // **면 인구는 칸 목록과 따로 온다** (head_pop). 리 값을 합친
        // 것이 아니라 면 하나의 값이다 — 우리는 리 인구를 갖고 있지
        // 않다. 배열만 저장하던 것을 통째로 담게 바꾼다.
        const cells = payload.cells || [];
        cells.headPop = payload.head_pop || {};
        lpUmdCache[w.key] = cells;
      }
    } catch (e) {
      // 못 받아도 지도는 시군구로 계속 돈다.
    } finally {
      lpUmdPending.delete(w.key);
    }
  }));
  drawLandPrice();
}

/* 최근 추이 꺾은선. 말풍선 안에 들어가는 작은 그림이다.
 *
 * 값 하나만 보면 그것이 오르는 중인지 내리는 중인지 알 수 없다. 같은
 * 평당 80만원이라도 3년째 오르는 80만과 꺾여 내려온 80만은 다른
 * 물건이다. 거래가 세 건 미만인 해는 내보내기에서 이미 빠져 있다. */
function lpSpark(trend) {
  if (!trend || trend.length < 2) return '';
  const W = 132; const H = 34; const P = 3;
  const vs = trend.map((t) => t[2]);
  const lo = Math.min(...vs); const hi = Math.max(...vs);
  const span = hi - lo || 1;
  const x = (i) => P + (i / (trend.length - 1)) * (W - P * 2);
  const y = (v) => H - P - ((v - lo) / span) * (H - P * 2);
  const pts = trend.map((t, i) => `${x(i).toFixed(1)},${y(t[2]).toFixed(1)}`);
  const first = trend[0]; const last = trend[trend.length - 1];
  const chg = (last[2] / first[2] - 1);
  return `<span class="lp-spark"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">`
    + `<polyline points="${pts.join(' ')}" fill="none" stroke="#2454A6" stroke-width="1.8"/>`
    + `<circle cx="${x(trend.length - 1).toFixed(1)}" cy="${y(last[2]).toFixed(1)}" r="2.6" fill="#123B7A"/>`
    + `</svg><em>${first[0]}→${last[0]} ${chg >= 0 ? '+' : ''}${(chg * 100).toFixed(0)}%</em></span>`;
}

/* 값이 없는 칸은 **이름만 남긴다.**
 *
 * 요구사항이 세 번에 걸쳐 여기로 왔다.
 *
 *   1차  "거래 0만/평으로 표기하고 지자체는 보이도록"
 *   2차  "5건 미만이라 표시가 안되는 곳은 -만/평으로"
 *   3차  "없는 곳은 지명만 나오고 거래 있는 곳은 색상으로 구분"
 *
 * 3차가 맞다. 0 이든 줄표든 **값 자리를 채우면 값처럼 읽힌다.** 값이
 * 없다는 것은 값 자리를 비워서 말하는 편이 정확하고, 그 자리에 아무것도
 * 없으면 태그가 짧아져 거래가 있는 곳이 눈에 먼저 든다 — 그것이 지도를
 * 훑는 목적이다.
 *
 * 0건과 '적다' 의 구별은 없앤 것이 아니라 **말풍선으로 옮겼다.** 태그는
 * 훑는 자리고 말풍선은 짚는 자리다. */
function lpNoneText() {
  return '';
}

function lpTip(it, level, w) {
  if (it.v == null) {
    // 요구사항(2026-09-09): "그냥 간단하게 표시합니다. - 거래 5건 미만-"
    //
    // 앞서 '이 용도지역 거래가 없습니다' 라는 문장을 넣었는데, 말풍선이
    // 세로로 길게 늘어졌습니다(실사용 화면). 값이 없는 칸에 설명을 길게
    // 붙일 이유가 없습니다 — 왜 비었는지는 **한 마디면 됩니다.**
    //
    // 0건과 1~4건을 굳이 가르지 않습니다. 둘 다 '다섯 건이 안 된다' 가
    // 참이고, 그것이 값을 안 쓰는 이유 전부입니다.
    return `<div class="lp-tip-h">${escapeHtml(it.full || it.name)}</div>`
      + `<div class="lp-tip-m">${escapeHtml(w ? w.label : '')}`
      + ` · ${escapeHtml(lpGroups().join('·'))}`
      + ` · 거래 ${LP_MIN_LABEL}건 미만</div>`;
  }
  const per = perM2Str(it.v);
  const py = perPy(it.v);
  const stat = state.lpStat === 'avg' ? '평균' : '중앙값';
  let html = `<div class="lp-tip-h">${escapeHtml(it.full || it.name)}`
    + `${it.sub ? ` <em>${escapeHtml(it.sub)}</em>` : ''}</div>`
    // 요구사항(2026-09-08): "xx원/평, xx원/㎡ 으로 수정해 주시고
    // 미터당 가격은 평단가 아랫줄로 내려주세요."
    //
    // '평당 592,441원 ㎡당 179,213원' 처럼 한 줄에 두 값을 이어 놓으면
    // 어느 숫자가 어느 단위인지 눈이 못 잡는다. 값과 단위를 붙여 쓰고
    // 줄을 나눈다.
    + `<div class="lp-tip-v"><b>${py}원/평</b></div>`
    + `<div class="lp-tip-v2">${per}원/㎡ · ${stat}</div>`
    + `<div class="lp-tip-m">${escapeHtml(w ? w.label : '')}`
    + ` · 거래 ${it.n.toLocaleString('ko-KR')}건`
    // 건수 기준은 시점이 지역마다 다르다. 몇 년치인지 안 밝히면
    // '최근' 이라는 말이 거짓이 된다.
    + (w && w.kind === 'count' ? ` · ${it.from}년부터` : '')
    + (it.parts > 1
       ? ` · ${it.parts}개 ${level.key === 'umd' ? '리·동' : '시군구'} 합침` : '')
    + '</div>';
  html += lpSpark(it.trend);
  // 어떤 용도지역을 섞었는지. 중앙값끼리 섞은 것은 근사라서 밝힌다.
  if ((it.byGroup || []).length) {
    html += '<div class="lp-tip-g">'
      + it.byGroup.slice().sort((a, b2) => b2.n - a.n)
        .map((g) => `<span>${escapeHtml(g.group)} ${lpMoney(g.v)}원/평`
          + ` <em>${g.n.toLocaleString('ko-KR')}건</em></span>`).join('')
      + '</div>';
    if (it.byGroup.length > 1 && state.lpStat !== 'avg') {
      html += '<div class="lp-tip-n">여러 용도지역의 중앙값을 건수로 가중해'
        + ' 섞은 값입니다 (합동 중앙값의 근사).</div>';
    }
  }
  return html;
}

function drawLandPrice() {
  const bar = document.getElementById('lp-bar');
  const have = !!(state.landPrice && (state.landPrice.windows || []).length);
  if (bar) bar.hidden = !have;
  if (!map || !lpLayer) return;
  /* **잠금은 여기 있어야 한다.** 부르는 자리를 세어 보면 열여섯 곳이고,
   * 그중에는 우리가 부르지 않은 것들이 섞여 있다 —
   *
   *   · 조회수 RPC(bump_place_view) 응답
   *   · 실시간 접속(presence) 알림
   *   · 읍면동·명부 조각이 도착했을 때
   *   · 필터·배율·연도 변경
   *
   * 자리마다 막으면 하나는 반드시 빠뜨린다. 실제로 두 번 빠뜨렸다 —
   * moveend 만 막았더니 조회수 RPC 응답이 말풍선을 죽였다. 진짜
   * Leaflet 으로 재현해서 확인한 순서가 이것이다:
   *
   *   click → popupopen → moveend(건너뜀) → 조회수 RPC → draw() → 사망
   *
   * 다시 그리면 clearLayers 가 마커를 지우고, 말풍선은 그 마커에
   * 붙어 있으므로 함께 닫힌다. 그래서 **열려 있으면 안 그린다.**
   * 미룬 것은 잊지 않고, 닫을 때 갚는다(map 의 popupclose). */
  if (lpOpenPk != null) { lpPending = true; return; }
  lpPending = false;
  lpDrawing = true;
  try {
    drawLandPriceInner(have);
  } finally {
    lpDrawing = false;
  }
}

// 검사가 '우리가 부르지 않은 자리' 를 흉내낼 수 있게 내놓는다. 조회수
// RPC 응답도 presence 알림도 밖에서는 이 함수 하나로 보인다.
window.__drawLandPrice = () => drawLandPrice();
// 경계선은 화면을 움직여야 도는데, 검사에서는 그것을 흉내내기가
// 번거롭다. 부를 구멍을 하나 낸다.
window.__drawCadastral = () => drawCadastral();
window.__cadTileList = () => cadTileList();
// 조회 배지·별표 검사가 안을 들여다볼 구멍.
window.__viewersPeek = () => ({ star: viewers.star, open: lpOpenPk, pending: lpPending,
  stat: [...viewers.stat].map(([k, v]) => [k, v.n24]) });
// 차종을 바꾸면 경계가 따라 내려가는지 검사가 볼 수 있게. 화면에서는
// 차종 칸을 눌러 도는 길과 같은 함수다.
window.state = state;
window.__rebuildTiers = () => { recolorTollgates(); updateTierCounts(); };

function drawLandPriceInner(have) {
  lpLayer.clearLayers();
  const groups = lpGroups();
  window.__lp = { on: false, n: 0, groups, level: null };
  if (!have || !groups.length) { updateLpNote(null); return; }

  const zoom = map.getZoom();
  if (zoom >= LP_UMD_ZOOM) {
    lpLoadUmd();
    // 거래가 없는 동의 이름은 **명부 조각**에서 온다. 보이는 시·도만
    // 받으므로 100KB 안팎이다.
    if (((state.landPrice || {}).umd_roster || []).length) {
      lpLoadRoster();
    } else if (!findIndex && !findLoading) {
      // 명부가 아직 안 실린 배포에서는 예전대로 검색 색인으로 메운다.
      // 2MB 라 첫 화면에 얹지 않고 **여기서 처음 받는다**.
      findLoad().then(() => drawLandPrice());
    }
  }
  const level = lpLevel(zoom);
  const all = (level.key === 'umd' || level.key === 'ri')
    ? lpItemsUmd(level.key) : lpItemsRegion(level.key);
  if (!all.length) { updateLpNote({ n: 0, level: level.label }); return; }

  // **색은 화면에 보이는 것끼리 끊는다.** 전국 분위로 칠하면 경기도만
  // 봐도 전부 짙은 파랑이 되어 그 안에서 어디가 비싼지 안 보인다.
  const shown = lpVisible(all);
  // **값이 없는 칸은 눈금에서 뺀다.** 넣으면 '가장 싼 20%' 칸이 거래
  // 없는 곳으로 채워져, 실제로 싼 곳이 가운데 칸으로 밀린다.
  const withValue = shown.filter((it) => it.v != null);
  const scale = lpScale(withValue.map((it) => it.v));
  const w = lpWindow();

  shown.forEach((it) => {
    const fill = lpColor(it.v, scale);
    // **이름만 위에, 값은 아래에** (요구사항). 리 단계에서는 앞의
    // 면 이름을 뗀다 — '목천읍 신계리' 가 아니라 '신계리'. 어느 읍인지는
    // 지도 바탕에 이미 적혀 있고, 말풍선이 전체 이름을 말한다.
    const short = level.key === 'ri'
      ? String(it.name).split(' ').pop() : it.name;
    const marker = L.marker(it.at, {
      pane: 'lpPane',
      keyboard: false,
      icon: L.divIcon({
        className: 'lp-card-wrap',
        html: `<span class="lp-card${it.v == null ? ' is-none' : ''}"`
          + ` style="background:${fill}">`
          // 주간 1등 별표는 **시·군 안에서** 뽑는다 (요구사항:
          // 전국 제외). 이름 앞에 붙는다.
          + `<b>${viewerStar(it)}${escapeHtml(short)}`
          // 읍·면·동과 리에는 인구가 **없다**. 우리가 가진 인구는 KOSIS
          // 시군구 단위가 전부다. 그 자리에 시군구 인구를 적으면 리 하나가
          // 20만인 것처럼 읽히므로, 없으면 아무것도 안 적는다.
          + (it.pop ? `<em>${popMan(it.pop)}</em>` : '')
          + `</b>`
          // 값이 없으면 이 줄 자체가 없다 (요구사항 2026-09-09 3차).
          + (it.v == null ? ''
            : `<i>${escapeHtml(lpMoney(it.v))}<u>/평</u></i>`)
          // 셋째 줄 — 지금 보는 사람 / 오늘 본 사람 (요구사항
          // 2026-09-09 2차). 둘 다 0이면 줄 자체가 없다.
          + viewerLine(it.pk)
          + '</span>',
        iconSize: null,
      }),
    });
    // 마우스를 올리면(PC) 그리고 **눌러도**(폰) 나온다.
    //
    // 보고된 문제(2026-09-10): "모바일에서는 이 팝업 정보를 볼 수가
    // 없어요." 터치 화면에는 hover 가 없으므로 말풍선만으로는 영영
    // 못 봅니다. 같은 내용을 누름에도 답니다.
    //
    // **화면 가운데가 아니라 그 태그 자리에** 띄웁니다. 가운데로
    // 옮기면 어느 동네 값인지가 끊깁니다. 대신 autoPan 을 켜서, 태그가
    // 화면 끝에 있으면 지도가 스스로 밀려 말풍선이 다 보이게 합니다.
    const tip = lpTip(it, level, w);
    marker.bindTooltip(tip,
      { direction: 'top', className: 'lp-tip', opacity: 1 });
    marker.bindPopup(tip, {
      className: 'lp-pop', maxWidth: 260, autoPan: true,
      autoPanPadding: [12, 12], closeButton: true,
    });
    // 누르면 말풍선이 뜨는데 그 위에 hover 말풍선이 겹치면 두 겹이 된다.
    marker.on('popupopen', () => {
      // 지도를 끌다가 손을 뗀 것이면 누른 것이 아니다. 열지 않는다.
      if (lpDragged) { marker.closePopup(); return; }
      marker.closeTooltip();
      lpOpenPk = it.pk;
    });
    lpLayer.addLayer(marker);
  });

  window.__lp = {
    on: true, n: shown.length, withValue: withValue.length, total: all.length,
    groups, level: level.key, window: state.lpWindow, scale: scale.kind,
    // 검사용 — 지금 화면이 어느 조각을 원하고 무엇을 들고 있는지.
    // 이것이 없으면 '안 받았다' 와 '받을 것이 없다' 를 밖에서 못 가른다.
    chunks: groups.flatMap((g) => lpUmdChunks(g).map((c) => `${g}|${c.p}`)),
    cached: Object.keys(lpUmdCache),
    // 조회수 열쇠도 내놓는다. 이것이 없으면 '별표가 시·군 안에서
    // 뽑혔는가' 를 밖에서 셀 수가 없다.
    items: shown.map((it) => ({ pk: it.pk, sg: it.sg, name: it.name })),
  };
  updateLpNote({ n: shown.length, withValue: withValue.length,
                 total: all.length, level: level.label, scale, w });
  // 조회수는 **그린 뒤에** 챙긴다. 무엇이 화면에 있는지는 여기서만 안다.
  viewersOnMove(shown);
}

/* 5분위 눈금 (요구사항 2026-09-09, 2번).
 *
 * "왜 이 색인가 가 지도에 안 적혀 있습니다. 경기도를 보다 충북으로
 *  넘어가면 같은 평당 80만원이 짙은 파랑에서 옅은 파랑으로 바뀝니다."
 *
 * 맞다. 색은 **화면 안에서** 끊는다 — 그래야 그 지역 안에서 어디가 비싼지
 * 보인다. 전국 분위로 칠하면 경기도만 봤을 때 전부 짙은 파랑이 된다.
 * 다만 그 설계를 화면이 말하지 않으면 고장으로 읽힌다. 끊는 자리를
 * 숫자로 적고, **'이 화면 안에서' 라는 말을 함께 적는다.**
 *
 * 곳이 다섯도 안 되면 분위를 못 낸다. 그때는 순위로 색을 펴는데, 그것도
 * 그렇다고 말한다 — 눈금 없이 색만 있으면 없는 정밀도를 있는 것처럼
 * 보이게 한다. */
function drawLpScale(info) {
  const el = document.getElementById('lp-scale');
  if (!el) return;
  const groups = lpGroups();
  if (!info || !info.n || !groups.length || !info.scale) {
    el.hidden = true;
    window.__lpScale = null;
    return;
  }
  // 값이 있는 칸이 하나도 없으면 끊을 것이 없다. 그때 '0곳뿐이라
  // 5분위를 못 냅니다' 를 띄우면 눈금 자리가 오류처럼 보인다.
  if (info.withValue === 0) { el.hidden = true; window.__lpScale = null; return; }
  const sc = info.scale;
  if (sc.kind !== 'quantile') {
    el.hidden = false;
    el.innerHTML = '<div class="lps-h">이 화면 안에서 순위로 색을 폅니다</div>'
      + `<div class="lps-note">비교할 곳이 ${sc.sorted.length}곳뿐이라`
      + ' 5분위를 못 냅니다.</div>';
    window.__lpScale = { kind: 'rank', n: sc.sorted.length };
    return;
  }
  // 칸 다섯의 경계. 맨 아래와 맨 위는 실제 최소·최대를 적는다 —
  // '0원부터' 라고 적으면 없는 칸을 있는 것처럼 보이게 한다.
  const lo = sc.sorted[0];
  const hi = sc.sorted[sc.sorted.length - 1];
  const edges = [lo, ...sc.breaks, hi];
  el.hidden = false;
  el.innerHTML = '<div class="lps-h">이 화면 안에서 5분위 · 평당</div>'
    + '<div class="lps-bar">'
    + LP_COLORS.map((c, i) =>
      `<span class="lps-cell" style="background:${c}" title="${
        escapeHtml(lpMoney(edges[i]))}~${escapeHtml(lpMoney(edges[i + 1]))}"></span>`)
      .join('') + '</div>'
    + '<div class="lps-ticks">'
    + edges.map((v, i) => `<span${i === 0 ? ' class="is-first"' : ''}${
      i === edges.length - 1 ? ' class="is-last"' : ''}>${
      escapeHtml(lpMoney(v))}</span>`).join('')
    + '</div>'
    + '<div class="lps-note">지역을 옮기면 끊는 자리도 함께 바뀝니다.</div>';
  window.__lpScale = { kind: 'quantile', edges };
}

function updateLpNote(info) {
  drawLpScale(info);
  const el = document.getElementById('lp-note');
  if (!el) return;
  const groups = lpGroups();
  if (!info || !groups.length) {
    el.textContent = '용도지역을 켜면 그 땅의 최근 실거래 단가를 지역마다 적습니다.';
    lpSuggest(null);
    return;
  }
  // 값이 있는 칸을 센다. 태그 수가 아니다 — 이제 거래가 없는 지자체도
  // 태그를 갖기 때문에, 태그 수로 세면 '거래가 있다' 고 말하게 된다.
  const got = info.withValue == null ? info.n : info.withValue;
  if (!got) {
    el.textContent = `이 화면에는 ${groups.join('·')} 거래가 없습니다`
      + ` (한 곳에 ${LP_MIN_LABEL}건은 있어야 값으로 씁니다).`
      + (info.n ? ` 지자체 ${info.n}곳은 이름만 적었습니다.` : '');
    lpSuggest(info);
    return;
  }
  const stat = state.lpStat === 'avg' ? '평균' : '중앙값';
  const how = info.scale.kind === 'quantile'
    ? '화면 안에서 5분위로 색을 나눔'
    : `비교 대상이 ${info.scale.sorted.length}곳뿐이라 순위로 색을 폄`;
  const cut = info.total > info.n
    ? ` · 화면 안 ${info.total}곳 중 거래 많은 ${info.n}곳만 표시` : '';
  const none = info.n - got;
  el.textContent = `${groups.join('·')} · ${info.level} 단위 · ${got}곳`
    + ` · 평당 ${stat} · ${how}${cut}`
    + (none > 0 ? ` · 거래 없는 곳 ${none}곳은 회색` : '');
  lpSuggest(info);
}

/* **이 화면에서 용도지역마다 몇 곳이 잡히는가.**
 *
 * 도시는 계획관리가 없다 — 인구 15만에서 자연녹지 비중이 6%→65% 로
 * 뒤집힌다(docs 7장 실측). 계획관리로 서울을 보면 지도가 텅 비는데,
 * 화면이 '자료가 없다' 와 '그런 땅이 여기 없다' 를 구별해 주지 않으면
 * 사람은 빈 화면을 고장으로 읽는다.
 *
 * 시군구 칸으로만 센다 — 늘 받아 둔 자료라 공짜다. */
function lpCoverage() {
  const lp = state.landPrice || {};
  const b = map && map.getBounds();
  const near = new Set();
  (state.regions || []).forEach((r) => {
    const at = (r.office_lat != null) ? [r.office_lat, r.office_lon] : [r.lat, r.lon];
    if (!b || b.contains(at)) near.add(String(r.sigungu_cd));
  });
  const out = [];
  Object.keys(lp.groups || {}).forEach((g) => {
    let n = 0;
    Object.keys(lp.groups[g]).forEach((cd) => {
      if (near.has(cd) && lp.groups[g][cd][state.lpWindow]) n += 1;
    });
    out.push({ group: g, n, kind: (lp.zone_kinds || {})[g] || '' });
  });
  out.sort((a, b2) => b2.n - a.n);
  return out;
}

/* 이 화면에 더 잘 맞는 용도지역이 있으면 왼쪽 필터를 대신 켜 준다. */
function lpSuggest(info) {
  const btn = document.getElementById('lp-swap');
  if (!btn) return;
  const on = lpGroups();
  if (!state.landPrice) { btn.hidden = true; return; }
  const cov = lpCoverage();
  const mine = cov.filter((c) => on.indexOf(c.group) >= 0)
    .reduce((a, c) => a + c.n, 0);
  const best = cov.find((c) => on.indexOf(c.group) < 0);
  // 비어 있으면 무조건 길을 알려준다. 값이 이미 나오는 중이면 두 배는
  // 벌어져야 권한다 — 12곳과 14곳 사이에서 권하면 잔소리가 된다.
  const enough = best && best.n
    && (mine === 0 ? best.n >= 1 : best.n >= Math.max(3, mine * 2));
  if (!enough) { btn.hidden = true; return; }
  btn.hidden = false;
  btn.textContent = `이 화면엔 ${on.join('·') || '고른 것'} ${mine}곳 —`
    + ` ${best.group}(${best.kind})를 켜면 ${best.n}곳`;
  btn.dataset.group = best.group;
}

/* 칩 세 개가 같은 뼈대를 쓴다. 앞의 둘은 땅값 글자용이고 'pin' 은
 * 거래 핀용이다 — 생김새와 조작이 같아야 사용자가 두 번 배우지 않는다. */
const LP_FILTER_STATE = {
  window: () => state.lpWindow,
  stat: () => state.lpStat,
  pin: () => state.pinKind,
};

function lpMenuItems(kind) {
  if (kind === 'window') {
    return lpWindows().map((w) => ({ value: w.key, label: w.label }));
  }
  if (kind === 'pin') {
    return PIN_KINDS.map((k) => ({ value: k.key, label: k.label }));
  }
  return [{ value: 'p50', label: '중앙값' }, { value: 'avg', label: '평균' }];
}

function lpPickFilter(kind, value) {
  if (kind === 'window') state.lpWindow = value;
  else if (kind === 'pin') state.pinKind = value;
  else state.lpStat = value;
  lpSyncChips();
  // 핀은 거래 층이다. 땅값 글자를 다시 그릴 이유가 없다 — 그 둘은
  // 일부러 따로 논다(2026-09-08 지시).
  if (kind === 'pin') { drawTrades(); return; }
  drawLandPrice();
}

function lpSyncChips() {
  document.querySelectorAll('.lp-filter').forEach((box) => {
    const kind = box.dataset.filter;
    if (!LP_FILTER_STATE[kind]) return;
    const now = LP_FILTER_STATE[kind]();
    const picked = lpMenuItems(kind).find((i) => i.value === now);
    const val = box.querySelector('.lp-pill-val');
    if (val) val.textContent = picked ? picked.label : '';
    box.querySelectorAll('.lp-opt').forEach((b) => {
      b.classList.toggle('is-on', b.dataset.value === now);
    });
  });
}

function lpCloseMenus(except) {
  document.querySelectorAll('.lp-filter').forEach((box) => {
    if (box === except) return;
    box.querySelector('.lp-menu').hidden = true;
    box.querySelector('.lp-pill').setAttribute('aria-expanded', 'false');
  });
}

function wireLandPrice() {
  const lp = state.landPrice;
  state.lpWindow = (lp && lp.default_window) || (lpWindows()[0] || {}).key || '';

  document.querySelectorAll('.lp-filter').forEach((box) => {
    const kind = box.dataset.filter;
    const menu = box.querySelector('.lp-menu');
    const pill = box.querySelector('.lp-pill');
    menu.innerHTML = '';
    lpMenuItems(kind).forEach((item) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'lp-opt';
      b.dataset.value = item.value;
      b.textContent = item.label;
      b.addEventListener('click', () => {
        lpPickFilter(kind, item.value);
        menu.hidden = true;
        pill.setAttribute('aria-expanded', 'false');
      });
      menu.appendChild(b);
    });
    pill.addEventListener('click', () => {
      const open = menu.hidden;
      lpCloseMenus(box);
      menu.hidden = !open;
      pill.setAttribute('aria-expanded', String(open));
    });
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.lp-filter')) lpCloseMenus(null);
  });

  // 땅값 글자의 용도지역 칸. **거래 점 필터와 따로 놓는다.**
  //
  // 분류는 **내보내기가 준 나무를 그대로 그린다** (zone_tree).
  // 요구사항(2026-09-09): "분류는 법령기준으로 정확히 합니다."
  //
  //   국토계획법 §36①  도시지역 / 관리지역 / 농림지역 / 자연환경보전지역
  //   시행령 §30①      주거·상업·공업·녹지의 세분
  //   같은 법 §38       개발제한구역은 용도구역 (용도지역이 아니다)
  //
  // 여기서 다시 분류하지 않는다. 두 곳에 적어 두면 언젠가 어긋나고,
  // 그때 어느 쪽이 맞는지 아무도 모른다.
  const gbox = document.getElementById('lp-groups');
  if (gbox) {
    const have = Object.keys((lp && lp.groups) || {});
    const notes = (lp && lp.zone_notes) || {};
    const tree = (lp && lp.zone_tree) || [];
    // 처음에는 분석이 쓰는 셋. 요구사항도 처음부터 그 셋이었다.
    ['계획관리', '생산관리', '자연녹지'].forEach((g) => {
      if (have.includes(g)) state.lpGroupSet.add(g);
    });

    let lastMajor = '';
    tree.forEach((node) => {
      const names = (node.names || []).filter((n) => have.includes(n));
      if (!names.length) return;
      if (node.major !== lastMajor) {
        const h = document.createElement('div');
        h.className = 'zone-major';
        h.textContent = node.major;
        gbox.appendChild(h);
        lastMajor = node.major;
      }
      if (node.middle) {
        const h2 = document.createElement('div');
        h2.className = 'zone-middle';
        h2.textContent = node.middle;
        gbox.appendChild(h2);
      }
      const row = document.createElement('div');
      row.className = 'zone-row';
      names.forEach((g) => {
        // 체크상자가 아니라 **범례 칸**이다 (요구사항 2026-09-08).
        // aria-pressed 로 눌림을 알린다 — 색만으로는 화면낭독기가 못
        // 읽고, 색약인 사람에게는 켠 것과 끈 것이 같아 보인다.
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'zone-opt';
        btn.dataset.group = g;
        const on = state.lpGroupSet.has(g);
        btn.setAttribute('aria-pressed', String(on));
        // 왜 이 칸에 있는지. '기타' 는 사유를 밝혀야 한다 —
        // 요구사항: "정말 분류 못하는 것은 기타로하고 사유 표기".
        if (notes[g]) btn.title = notes[g];
        btn.innerHTML = `<i class="zone-sw" style="background:${zoneSwatch(g)}"></i>`
          + `<span>${escapeHtml(g)}</span>`
          + (notes[g] ? '<b class="zone-why" aria-hidden="true">?</b>' : '');
        btn.addEventListener('click', () => {
          const now = !(btn.getAttribute('aria-pressed') === 'true');
          btn.setAttribute('aria-pressed', String(now));
          now ? state.lpGroupSet.add(g) : state.lpGroupSet.delete(g);
          drawLandPrice();
        });
        row.appendChild(btn);
      });
      gbox.appendChild(row);
    });
    // 사유를 눌러 읽을 수 있게. title 은 휴대폰에서 안 뜬다.
    gbox.addEventListener('click', (e) => {
      const why = e.target.closest('.zone-why');
      if (!why) return;
      e.stopPropagation();
      const g = why.closest('.zone-opt').dataset.group;
      const box = document.getElementById('zone-note');
      if (!box) return;
      box.textContent = `${g} — ${notes[g] || ''}`;
      box.hidden = false;
    });
  }

  const swap = document.getElementById('lp-swap');
  if (swap) {
    swap.addEventListener('click', () => {
      const g = swap.dataset.group;
      if (!g) return;
      // 여기서 켜는 것은 **땅값 글자의 용도지역**이다. 거래 점은 안 건드린다.
      state.lpGroupSet.add(g);
      const box = document.getElementById('lp-groups');
      if (box) {
        box.querySelectorAll('.zone-opt').forEach((b) => {
          if (b.dataset.group === g) b.setAttribute('aria-pressed', 'true');
        });
      }
      drawLandPrice();
    });
  }
  lpSyncChips();
}


/* ─────────── 필지 진단 (레이더) ─────────── */
/* 요구사항(2026-09-08):
 *   "해당 필지를 클릭하면 스파이더 차트를 통해 여러가지 인자들을 분석하여
 *    어떤 방향이 좋을 지 판단할 수 있도록 보여주는 방향으로 변경하겠습니다.
 *    (어떤 토지이든 나쁜 토지는 없다. 어떤 방향으로 개발할 지가 문제다)"
 *
 * **점수를 만들지 않는다.** 땅에 0~100 점 하나를 매기면 가짜 정밀도가
 * 된다 — 같은 필지가 물류창고에는 A급이고 전원주택에는 C급인데, 하나의
 * 숫자로 뭉개면 그 사실이 사라진다. 레이더는 "무엇이 강하고 무엇이
 * 약한가" 만 말한다.
 *
 * 그래서 축을 전부 **또래 안의 백분위**로 통일한다 (다섯, 주변 이용이 검증되면 여섯). 단위가 같아지고
 * (전부 %), 넓이를 점수로 안 쓰므로 축 순서도 해롭지 않다. 또래는
 * 같은 시군구·같은 용도지역에서 실제로 거래된 땅이다 — 전국 대비로 재면
 * 시골 땅은 전부 찌그러진 별이 되어 아무것도 못 읽는다. */

/* 두 점 사이 거리(km). 교통 축이 이것으로 중력을 계산한다.
 * 내보내기 쪽은 조인 표의 distance_km 를 쓰는데, 그것도 같은 하버사인
 * 으로 만든 값이다 (transform/link). 두 자가 달라지면 백분위가 딴 것을
 * 가리킨다. */
function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371.0088;
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

let parcelStats = null;
let parcelStatsTried = false;

async function loadParcelStats() {
  if (parcelStats || parcelStatsTried) return parcelStats;
  parcelStatsTried = true;
  try {
    const r = await fetch('/app/data/parcelstats.json', { cache: 'no-cache' });
    if (r.ok) parcelStats = await r.json();
  } catch (e) { /* 없으면 진단만 못 보여준다. 지도는 그대로 돈다. */ }
  return parcelStats;
}

/* 값 → 또래 안 백분위. 분위 경계 사이를 선형으로 읽는다. */
function pctFromQuantiles(v, breaks) {
  if (!Array.isArray(breaks) || breaks.length < 2 || !(v >= 0)) return null;
  if (v <= breaks[0]) return 0;
  const last = breaks.length - 1;
  if (v >= breaks[last]) return 1;
  for (let i = 0; i < last; i += 1) {
    if (v <= breaks[i + 1]) {
      const span = breaks[i + 1] - breaks[i];
      const frac = span > 0 ? (v - breaks[i]) / span : 0;
      return (i + frac) / last;
    }
  }
  return 1;
}

/* 우리 다섯 묶음 중 이 용도지역이 어디에 드는가. */
function parcelGroup(landUse) {
  const groups = Object.keys(((state.landPrice || {}).groups) || {});
  return groups.find((g) => String(landUse || '').indexOf(g) >= 0) || null;
}

/* 또래를 고른다. 시군구 → 시도 → 전국으로 물러나고, **어디까지
 * 물러났는지 함께 돌려준다** — 그것을 안 밝히면 '전국 상위 10%' 를
 * '우리 동네 상위 10%' 로 읽는다. */
/* 추세만 따로 물러난다 (요구사항 2026-09-10).
 *
 * 또래는 도로·형상 분포가 두터운 단계에서 고릅니다. 그런데 그 단계에
 * **추세가 없을 수 있습니다** — 거래가 해마다 다섯 건은 있어야 그 해를
 * 쓰는데, 시군구 단위에서 그것이 안 서는 조합이 있습니다.
 *
 * 실측(2026-09-10): 화면이 고르는 또래에 추세가 있는 조합이 95.2%
 * (6,794/7,140). 없는 346 조합은 **전부** 위 단계에 값이 있었습니다.
 * 그래서 추세만 따로 물러나면 100% 가 됩니다.
 *
 * 다만 **어디서 온 값인지 말합니다.** 시·도 값을 그 동네 값인 척
 * 적으면, 읽는 사람은 옆 동네와 견주는 데 그것을 씁니다.
 */
function pickTrend(sigunguCd, group) {
  const st = parcelStats;
  if (!st || !group) return null;
  const tries = [
    { key: `${sigunguCd}|${group}`, level: null },
    { key: `${String(sigunguCd).slice(0, 2)}|${group}`, level: '시·도 기준' },
    { key: `*|${group}`, level: '전국 기준' },
  ];
  for (const t of tries) {
    const p = st.peers[t.key];
    if (p && typeof p.trend === 'number') {
      return { trend: p.trend, span: p.trend_span || null, from: t.level };
    }
  }
  return null;
}

/* 지목군 — 또래 열쇠의 앞 단 (요구사항 2026-09-10). 평가서는 같은
 * 용도지역 안에서도 임야·농지·대지의 표준지를 따로 고른다. 규칙은
 * valuation.use_group 과 같아야 한다 — 어긋나면 화면이 딴 또래를 찾는다. */
function useGroupOf(jimok, use) {
  const j = String(jimok || '').trim();
  if (j === '임야') return '임야';
  if (['전', '답', '과수원', '목장용지'].includes(j)) return '전·답';
  if (j === '대') return '대';
  if (['공장용지', '도로', '잡종지', '창고용지', '주차장'].includes(j)) return '공장·도로';
  const t = String(use || '') + ' ' + j;
  const table = [
    ['임야', ['임야', '자연림', '토지임야', '임']],
    ['전·답', ['전', '답', '과수', '묵', '농', '목장']],
    ['대', ['대', '주거', '주택', '나지', '상업']],
    ['공장·도로', ['공장', '공업', '도로', '잡종', '창고', '주차']],
  ];
  const hit = table.find(([, keys]) => keys.some((k) => t.indexOf(k) >= 0));
  return hit ? hit[0] : null;
}

function pickPeer(sigunguCd, group, ug) {
  const st = parcelStats;
  if (!st || !group) return null;
  const min = st.min_peer || 30;
  const sido = String(sigunguCd).slice(0, 2);
  // 지목군 단이 앞이다: 시군구|용도|지목군 → 시도|… → 전국|… → 시군구|용도 → …
  const tries = ug ? [
    { key: `${sigunguCd}|${group}|${ug}`, level: `같은 시군구 · ${ug}` },
    { key: `${sido}|${group}|${ug}`, level: `같은 시·도 · ${ug}` },
    { key: `*|${group}|${ug}`, level: `전국 · ${ug}` },
  ] : [];
  tries.push(
    { key: `${sigunguCd}|${group}`, level: '같은 시군구' },
    { key: `${sido}|${group}`, level: '같은 시·도' },
    { key: `*|${group}`, level: '전국' },
  );
  for (const t of tries) {
    const p = st.peers[t.key];
    if (p && p.n >= min) return { ...p, level: t.level, group };
  }
  const last = st.peers[`*|${group}`];
  return last ? { ...last, level: '전국', group } : null;
}

/* 교통 축 — 10km 안 영업소의 화물 통행량을 거리 제곱으로 나눠 더한다.
 * 김진유(2011)의 대도시접근성지수와 같은 꼴(질량/거리)이고, 우리는
 * 인구 대신 **실제로 지나가는 화물 대수**를 쓴다.
 *
 * 내보내기(parcelscore.build)와 **같은 식·같은 반경**이어야 한다.
 * 어긋나면 백분위가 딴 자를 대는 셈이 된다. */
function trafficGravity(lat, lon) {
  const cfg = (parcelStats || {}).traffic || { radius_km: 10, min_km: 0.5 };
  let sum = 0;
  let near = null;
  (state.tollgates || []).forEach((t) => {
    if (!t.lat || !t.freight) return;
    const d = haversine(lat, lon, t.lat, t.lon);
    if (d > cfg.radius_km) return;
    sum += t.freight / Math.pow(Math.max(d, cfg.min_km), 2);
    if (!near || d < near.km) near = { km: d, name: t.name, freight: t.freight };
  });
  return { grav: sum, near };
}

/* 필지 하나 → 축들. 값이 없는 축은 **비워 둔다** (0 이 아니다) —
 * 조사가 안 된 것과 나쁜 것은 다르다. */
function parcelAxes(parcel, at, zones) {
  const st = parcelStats;
  if (!st) return null;
  const code = String(parcel.pnu || '').slice(0, 5);
  const group = parcelGroup(parcel.land_use);
  const ug = useGroupOf(parcel.jimok, parcel.use_situation);
  const peer = pickPeer(code, group, ug);
  const zoneNames = (zones || []).map((z) => String((z && z.label) || z || ''));
  const out = { peer, group, ug, axes: [] };

  const grade = (table, text) => {
    if (!text) return null;
    const hit = Object.keys(table).find((k) => String(text).indexOf(k) >= 0);
    return hit === undefined ? null : table[hit];
  };

  // 1) 도로
  const rg = roadGradeOf(parcel.road_side);
  out.axes.push({
    key: 'road', label: '도로',
    pct: (peer && rg !== null) ? peer.road[rg] : null,
    raw: parcel.road_side || '조사 안 됨',
  });

  // 2) 교통
  const tg = trafficGravity(at[0], at[1]);
  out.axes.push({
    key: 'traffic', label: '물류 교통',
    pct: peer ? pctFromQuantiles(tg.grav, peer.traffic) : null,
    raw: tg.near
      ? `${tg.near.name} ${tg.near.km.toFixed(1)}km · 화물 ${Math.round(tg.near.freight).toLocaleString('ko-KR')}대/일`
      : '10km 안에 영업소 없음',
  });

  // 3) 개발 여지 — **또래가 아니라 시군구 안에서** 잰다. 또래는 용도지역
  //    으로 묶여 있어서 그 안에서 재면 늘 같은 값이 나온다.
  let zg = grade(st.zone_ladder, parcel.land_use);
  // 농업진흥구역·개발제한구역이 겹치면 한 단 아래 (요구사항 2026-09-10,
  // docs/radar-and-current-value.md §2-5). 평가서도 표준지를 그 구역
  // 안에서 따로 고른다. 사다리의 분모(시군구 거래)는 용도지역만 알아서
  // 이 한 단은 대상 필지에만 적용된다 — 그 사실을 raw 에 적는다.
  const tight = ['농업진흥구역', '개발제한구역'].find((n) =>
    zoneNames.some((z) => z.indexOf(n) >= 0)
    || String(parcel.land_use2 || '').indexOf(n) >= 0);
  if (zg !== null && zg > 0 && tight) zg -= 1;
  const zp = (st.zone_pct || {})[code];
  out.axes.push({
    key: 'zoning', label: '개발 여지',
    pct: (zp && zg !== null) ? zp[zg] : null,
    raw: (parcel.land_use || '용도 미상') + (tight ? ` · ${tight} (한 단 아래)` : ''),
  });

  // 4) 가격 추세 (요구사항 2026-09-10 — '가격 수준' 을 바꿉니다).
  //
  // 지금 비싼 땅이 좋은 땅은 아닙니다. 토지에서는 **오르는 중인지**가
  // 사는 사람에게 더 쓸모 있는 정보입니다.
  //
  // 필지 하나에는 올해 공시지가 한 값뿐이라 그 땅만으로는 추세를 못
  // 냅니다. 그 땅이 속한 **동네·용도지역의 실거래 단가**가 최근 몇 해
  // 어떻게 움직였는지를 씁니다. 견주는 상대도 달라집니다 — 같은 또래
  // 안에서 재면 모두 같은 값이 되므로, **전국의 다른 동네·용도들**과
  // 견줍니다.
  // 이름을 tg 로 두면 위의 교통 축(trafficGravity)과 부딪힌다.
  const mo = pickTrend(code, group);
  const moNote = [mo && mo.span ? `최근 ${mo.span}년` : null,
                  mo && mo.from ? mo.from : null].filter(Boolean).join(' · ');
  out.axes.push({
    key: 'price', label: '시장 동향',
    pct: (mo && (st.trend_q || []).length)
      ? pctFromQuantiles(mo.trend, st.trend_q) : null,
    raw: mo
      ? `연 ${mo.trend >= 0 ? '+' : ''}${(mo.trend * 100).toFixed(1)}%`
        + (moNote ? ` (${moNote})` : '')
      : '거래가 얇아 추세를 못 냅니다',
  });

  // 5) 모양·지세
  // 임야는 지세만 (parcelscore.land_grade 와 같은 규칙) — 평가서의
  // 임야지대 항목표에 형상이 없다.
  const sg = ug === '임야' ? null : grade(st.shape_grade, parcel.shape);
  const lg = grade(st.slope_grade, parcel.slope);
  const got = [sg, lg].filter((g) => g !== null);
  const land = got.length ? Math.round(got.reduce((a, b) => a + b, 0) / got.length) : null;
  out.axes.push({
    key: 'land', label: '모양·지세',
    pct: (peer && land !== null) ? peer.land[land] : null,
    raw: (ug === '임야' ? [parcel.slope, '임야는 지세만'] : [parcel.shape, parcel.slope])
      .filter(Boolean).join(' · ') || '조사 안 됨',
  });

  // 6) 주변 이용 — **검증을 통과했을 때만** 내보내기가 st.urban 을 싣는다
  //    (analyze/urban.py). 없으면 다섯 축이다. 값은 법정동리(PNU 앞
  //    10자리)의 도시용지 면적 비율이고, 같은 시군 안 동리들의 분위로
  //    읽는다 — 토지적성평가가 하는 방식 그대로다.
  if (st.urban && st.urban.umd) {
    const umd = String(parcel.pnu || '').slice(0, 10);
    const v = st.urban.umd[umd];
    const q = (st.urban.q || {})[code] || (st.urban.q_sido || {})[code.slice(0, 2)] || null;
    const from = (st.urban.q || {})[code] ? null : '시·도 기준';
    out.axes.push({
      key: 'urban', label: '주변 이용',
      pct: (typeof v === 'number' && q) ? pctFromQuantiles(v, q) : null,
      raw: typeof v === 'number'
        ? `도시용지 ${Math.round(v * 100)}% (법정동리${from ? ` · ${from}` : ''})`
        : '동리 자료 없음',
    });
  }
  return out;
}

/* 도로접 사다리. usage.road_grade 와 **같은 규칙**이다 — 둘이 어긋나면
 * 화면과 분석이 다른 땅을 말한다. */
function roadGradeOf(text) {
  if (!text || typeof text !== 'string') return null;
  const t = text.trim();
  if (!t || t.indexOf('지정되지') >= 0 || t.indexOf('미상') >= 0) return null;
  if (t.indexOf('맹지') >= 0) return 0;
  if (t.indexOf('광대') >= 0) return 5;
  if (t.indexOf('중로') >= 0) return 4;
  if (t.indexOf('소로') >= 0) return 3;
  if (t.indexOf('세로') >= 0 || t.indexOf('세각') >= 0) {
    return t.indexOf('불') >= 0 ? 1 : 2;
  }
  return null;
}

/* 레이더 그림. **넓이를 점수로 쓰지 않는다** — 축 순서만 바꿔도 넓이가
 * 달라지므로 그것을 값처럼 읽게 두면 안 된다. 그래서 색을 옅게 깔고
 * 축마다 백분위 숫자를 따로 적는다. */
function radarSvg(axes) {
  const R = 62; const CX = 84; const CY = 78;
  const n = axes.length;
  const ang = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const at = (i, r) => [CX + Math.cos(ang(i)) * r, CY + Math.sin(ang(i)) * r];
  const rings = [0.25, 0.5, 0.75, 1].map((f) =>
    `<polygon points="${axes.map((_, i) => at(i, R * f).map((v) => v.toFixed(1)).join(',')).join(' ')}"
      fill="none" stroke="var(--border)" stroke-width="1"/>`).join('');
  const spokes = axes.map((_, i) =>
    `<line x1="${CX}" y1="${CY}" x2="${at(i, R)[0].toFixed(1)}" y2="${at(i, R)[1].toFixed(1)}"
      stroke="var(--border)" stroke-width="1"/>`).join('');
  // 값이 없는 축은 가운데로 끌어당기지 않는다. 그러면 '나쁜 땅' 으로
  // 보이는데 실제로는 **조사가 안 된 것**이다. 점선으로 끊어 둔다.
  const known = axes.filter((a) => a.pct !== null && a.pct !== undefined);
  const poly = known.length >= 3
    ? `<polygon points="${axes.map((a, i) =>
        at(i, R * (a.pct == null ? 0 : a.pct)).map((v) => v.toFixed(1)).join(',')).join(' ')}"
        fill="rgba(59,115,196,.22)" stroke="#2454A6" stroke-width="2"
        stroke-linejoin="round"/>` : '';
  const dots = axes.map((a, i) => (a.pct == null ? '' :
    `<circle cx="${at(i, R * a.pct)[0].toFixed(1)}" cy="${at(i, R * a.pct)[1].toFixed(1)}"
      r="2.6" fill="#123B7A"/>`)).join('');
  const labels = axes.map((a, i) => {
    const [x, y] = at(i, R + 14);
    const anchor = Math.abs(x - CX) < 6 ? 'middle' : (x > CX ? 'start' : 'end');
    return `<text x="${x.toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="${anchor}"
      font-size="10.5" fill="var(--muted)">${escapeHtml(a.label)}</text>`;
  }).join('');
  return `<svg class="radar" viewBox="0 0 168 160" width="168" height="160"
    role="img" aria-label="필지 진단 레이더">${rings}${spokes}${poly}${dots}${labels}</svg>`;
}

/* 필지의 기본 정보를 표로 (요구사항 2026-09-10 — 부동산플래닛 참조).
 *
 * **없는 칸은 아예 안 세운다.** 빈 줄이 늘어서면 '조회가 반쯤
 * 실패했다' 로 읽힌다. 값이 있는 것만 적고, 우리가 못 주는 것
 * (소유·토지이동사유·지역지구 전체)은 아래 토지이음 단추로 넘긴다.
 *
 * '지정되지않음' 은 값이 아니라 빈칸이다. 브이월드가 그렇게 적어
 * 보내는데, 그대로 두면 사람이 무슨 뜻인지 되묻게 된다.
 */
function parcelFacts(parcel, zones) {
  const won = (v) => Math.round(v).toLocaleString('ko-KR');
  const py = parcel.area_m2 ? (parcel.area_m2 / PYEONG_M2) : null;
  const blank = (v) => !v || /^지정되지\s*않음$/.test(String(v).trim());
  const zone = [parcel.land_use, parcel.land_use2]
    .filter((v) => !blank(v)).join(' · ');
  const price = parcel.official_price
    ? `${won(parcel.official_price)}원/㎡`
      + (parcel.stdr_year
         ? ` <em>(${escapeHtml(parcel.stdr_year)}년 기준)</em>` : '')
    : null;
  const facts = [
    ['지목', parcel.jimok],
    ['면적', parcel.area_m2
      ? `${won(parcel.area_m2)}㎡ <em>(${won(py)}평)</em>` : null],
    ['이용상황', parcel.use_situation],
    ['용도지역', zone],
    ['지세(고저)', parcel.slope],
    ['형상', parcel.shape],
    ['도로조건', parcel.road_side],
    ['공시지가', price],
    // 임야대장은 지번 앞에 '산' 이 붙는 땅이다. 대장이 다르면 등본을
    // 뗄 곳도 다르므로 적어 준다.
    ['대장', parcel.register === '2' ? '임야대장'
      : parcel.register === '1' ? '토지대장' : null],
    // 요구사항(2026-09-10): "하단 토지정보 리스트에 지구, 구역에
    // 대해 자세히 표시". 세부 이름까지 적습니다 — '가축사육제한구역'
    // 만으로는 '절대제한(전 축종)' 인지 '일부 축종' 인지 모릅니다.
    ['지구·구역', (zones || []).length
      ? zones.map((z) => escapeHtml(z.label)
          + (z.detail ? ` <em>${escapeHtml(String(z.detail))}</em>` : ''))
        .join('<br>')
      : null],
  ].filter(([, v]) => !blank(v));
  if (!facts.length) return '';
  return '<table class="pc-facts"><tbody>'
    + facts.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join('')
    + '</tbody></table>';
}

/* 개발 한도 (docs/dev-constraints-and-costs.md §6 (1) · C2·C4).
 *
 * '토지 정보' 바로 아래. 용도지역·지목·구역이 바로 위에 있고 이 표는
 * 그것들의 **결과**다. 값 옆에 근거(조례·조문)를 적어 '왜 40%냐' 를
 * 화면이 답하게 한다.
 *
 * 두 층이다. 법(시행령)은 상한 **범위**, 조례는 그 안의 **값**. 조례 값이
 * 있으면 그것을 크게, 없으면 시행령 상한을 '≤' 로 적고 조례 미확인이라
 * 말한다. 경사·표고·임목은 조례의 **문턱**만 적는다 — 필지의 경사·표고는
 * 아직 못 잰다(DEM 없음). 문턱만 있고 잰 값이 없으면 '통과' 라고 쓰지
 * 않는다. */
function parcelLimits(parcel, Z) {
  if (!Z || !Z.law) return '';
  const e = escapeHtml;
  const won = (v) => Math.round(v).toLocaleString('ko-KR');
  const code = String(parcel.pnu || '').slice(0, 5);
  const ref = (Z.sg || {})[code];
  const ord = ref ? (Z.ord || {})[ref[0]] : null;
  const zone = String(parcel.land_use || '').replace(/지역$/, '');
  const law = Z.law[zone];
  const bcr = ord && ord.bcr && ord.bcr[zone] != null ? ord.bcr[zone] : null;
  const far = ord && ord.far && ord.far[zone] != null ? ord.far[zone] : null;
  const rows = [];
  if (law) {
    const bcrV = bcr != null ? bcr : law.bcr_max;
    const farV = far != null ? far : law.far_max;
    rows.push(['건폐율', bcr != null
      ? `<b>${bcr}%</b> <em>조례</em>`
      : `≤ <b>${law.bcr_max}%</b> <em>시행령 상한 · 조례 값 미확인</em>`]);
    rows.push(['용적률', far != null
      ? `<b>${far}%</b> <em>조례</em>`
      : `<b>${law.far_min}~${law.far_max}%</b> <em>시행령 범위 · 조례 값 미확인</em>`]);
    if (parcel.area_m2) {
      rows.push(['최대 규모', `바닥 ${won(parcel.area_m2 * bcrV / 100)}㎡ · 연면적 ${won(parcel.area_m2 * farV / 100)}㎡`
        + ` <em>(${won(parcel.area_m2)}㎡ × ${bcrV}% · ${farV}%)</em>`]);
    }
  } else if (zone) {
    rows.push(['건폐율·용적률', `<em>${e(zone)} 은 용도지역별 상한 표에 없습니다</em>`]);
  }
  if (ord) {
    rows.push(['경사도', ord.slope != null
      ? `허가 기준 <b>${ord.slope}° 미만</b> <em>필지 경사는 아직 못 잼 (DEM 없음)</em>`
      : '<em>조례에 숫자 기준 없음</em>']);
    rows.push(['표고', ord.elev != null
      ? `기준 지반고 위 <b>${ord.elev} m 미만</b> <em>필지 표고는 아직 못 잼</em>`
      : '<em>조례에 숫자 기준 없음</em>']);
    rows.push(['입목축적', ord.forest != null
      ? `시군 평균의 <b>${ord.forest}% 미만</b> <em>임상도 오기 전 · 확정은 현장 조사</em>`
      : '<em>조례에 숫자 기준 없음</em>']);
  }
  if (!rows.length) return '';
  const basis = ord
    ? `<a href="${e(ord.url)}" target="_blank" rel="noopener">${e(ord.name)}</a>`
      + (ord.eff ? ` <em>(시행 ${e(String(ord.eff).replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3'))})</em>` : '')
      + (ref[1] === 'sido' ? ' <em>· 자치구·행정시는 광역시·도 조례를 따릅니다</em>' : '')
    : '<em>이 시군구 조례는 아직 못 받았습니다 — 시행령 상한만 적었습니다</em>';
  // 건축 제한처럼 **늘 펼쳐 둔다** (지시 2026-09-11). 접어 두면 있는 줄 모른다.
  return '<section class="pc-limits"><h4 class="pc-sub">개발 한도 <em>건폐율·용적률·개발행위 문턱</em></h4>'
    + '<table class="pc-facts"><tbody>'
    + rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join('')
    + '</tbody></table>'
    + `<p class="pc-limits-src">근거: ${basis}</p>`
    + '<p class="pc-limits-note">조례의 첫 값입니다. 완화·강화 단서(성장관리계획구역·기존 공장 등)는 '
    + '원문 조문에 있고, 지구·구역이 걸리면 그쪽이 먼저입니다. '
    + '<a href="/guide/law" target="_blank" rel="noopener">누가 정하나 · 내 시·군 조례 →</a></p>'
    + '</section>';
}

/* 카드 머리의 주소 (요구사항 2026-09-10).
 *
 * **지번이 주인공이다.** 도로명주소는 건물이 있는 곳에만 붙는데,
 * 이 화면이 다루는 것은 대개 빈 땅이다 — 실측한 두 곳 모두
 * 도로명이 없었다(광주 지월리 답, 안성 승두리 대). 없는 것을
 * '조회 실패' 로 보여주면 고장으로 읽히므로, 있을 때만 덧붙인다.
 */
function parcelAddr(addr, parcel) {
  const a = addr || {};
  const jibun = a.jibun
    || [a.sido, a.sigungu, a.umd, a.ri].filter(Boolean).join(' ')
    || null;
  if (!jibun && !a.road) return '';
  return '<div class="pc-addr">'
    + (jibun ? `<b>${escapeHtml(jibun)}</b>` : '')
    + (a.road ? `<span>${escapeHtml(a.road)}</span>` : '')
    + '</div>';
}

/* 겹친 지구·구역 (요구사항 2026-09-10).
 *
 * 보고: "단순히 용도 지역으로만 토지를 평가하니 오류가 발생됩니다."
 * 무엇을 지을 수 있는지는 용도지역 위에 겹친 것들이 정합니다.
 *
 * **레이더는 안 건드립니다.** 규제의 무게를 숫자 하나로 환산하면
 * 그 환산율 자체가 근거 없는 점수가 됩니다. 대신 아래에 따로,
 * 무엇이 걸렸고 그것이 무엇을 막는지 글로 적습니다.
 *
 * **이것이 전부가 아니라고 적습니다.** 준보전산지·접도구역은
 * 브이월드에 아예 없습니다(목록을 훑어 확인). 다 보여준 척하는 것이
 * 안 보여주는 것보다 위험합니다.
 */
function parcelZones(zones) {
  const list = (zones || []).filter((z) => z && z.label);
  const rows = list.map((z) => '<li><b>' + escapeHtml(z.label) + '</b>'
    + (z.detail ? ` <em>${escapeHtml(String(z.detail))}</em>` : '')
    + `<span>${escapeHtml(z.note || '')}</span></li>`).join('');
  return '<h4 class="pc-sub">건축 제한</h4>'
    + (rows
       ? `<ul class="pc-zones">${rows}</ul>`
       : '<p class="pc-zone-none">확인한 구역 중에서는 걸린 것이 '
         + '없습니다.</p>')
    + '<p class="pc-zone-note">여기 적힌 것이 전부가 아닙니다 — '
    + '<strong>준보전산지·접도구역</strong> 등은 우리가 받는 자료에 '
    + '없습니다. 실제 건축 전에는 토지이음에서 확인하세요.</p>';
}

/* 축이 각각 무엇을 재는지 (요구사항 2026-09-10).
 *
 * "5개 항목이 어떤 의미인지 간략하게 도표 아래에 주석으로 표기".
 * 축 이름만으로는 '개발 여지' 가 무엇을 견준 것인지 알 수 없습니다.
 * 무엇과 견줬고 무엇이 높은 쪽인지를 한 줄씩 적습니다.
 *
 * '가격 수준' 만 방향을 따로 적습니다 — 나머지 넷은 높을수록 좋지만
 * 가격은 높다고 좋은 것도 낮다고 좋은 것도 아닙니다. 그것을 안 적으면
 * 다섯 축을 같은 방향으로 읽게 됩니다.
 */
/* 축 설명 — **무엇을 재는지만** 적는다 (2026-09-12 지시).
 *
 * 예전에는 재는 방법을 그대로 적어 두었습니다 — 몇 km 안의 어느 차종을
 * 어떻게 거리로 나눠 더하는지, 또래를 무슨 열쇠로 묶고 얇으면 어디로
 * 물러나는지까지. 그 문장이 곧 이 서비스의 만드는 법이라, 화면에 두면
 * 누구나 베낄 수 있습니다. 뜻과 주의만 남기고 방법은 뺍니다.
 */
const AXIS_NOTES = {
  road: ['도로', '차가 들어올 수 있는가. <strong>지적상 접면</strong>이라 현황 진입로와 다를 수 있습니다.'],
  traffic: ['물류 교통', '주변 고속도로의 화물 통행이 얼마나 되는가. 물류·공장 적성이지, 그래서 오른다는 뜻이 아닙니다.'],
  zoning: ['개발 여지', '용도지역이 허용하는 개발 강도. 겹치는 보전규제를 함께 봅니다.'],
  price: ['시장 동향', '이 동네·용도의 실거래 단가가 <strong>오르는 중인지</strong>입니다. 지금 비싼지가 아닙니다.'],
  land: ['모양·지세', '필지 형상과 경사입니다. 반듯하고 평평할수록 높습니다.'],
  urban: ['주변 이용', '주변이 얼마나 개발되어 있는가. <strong>좋고 나쁨의 방향이 없습니다.</strong>'],
};

function axisNotes(axes) {
  const keys = (axes || []).map((a) => a.key).filter((k) => AXIS_NOTES[k]);
  const n = keys.length === 6 ? '여섯' : '다섯';
  return `<details class="pc-axis-help"><summary>${n} 축이 무엇을 재는가</summary>`
    + '<dl>' + keys.map((k) => `<dt>${AXIS_NOTES[k][0]}</dt><dd>${AXIS_NOTES[k][1]}</dd>`).join('')
    + '</dl>'
    + '<p>모두 <strong>비슷한 조건의 거래</strong>와 견준 자리입니다.</p></details>';
}

/* 현재 가치 · 미래 가치 (요구사항 2026-09-10).
 *
 * 레이더 아래 단추 둘. **지금은 이름과 '곧 공개' 뿐입니다.**
 *
 * 처음에는 무엇을 근거로 값을 내는지까지 적어 두었는데, 걷어냈습니다.
 * 그 설명이 곧 유료 전환의 열쇠라서, 정작 값이 없는 지금 미리 풀어
 * 놓으면 두 번 손해입니다 — 살 이유를 먼저 소비해 버리고, 그때 가서
 * 근거가 조금이라도 달라지면 앞말과 어긋납니다. 근거를 실제로 손에
 * 쥔 뒤에 정확히 적습니다.
 *
 *   현재 가치  감정평가서에서 배운 배율을 이 필지에 대입 → 지금 얼마인가
 *   미래 가치  주변 개발 사건의 전후 상승폭을 얹음      → 그 뒤에 얼마가 되는가
 *
 * 미래는 현재 위에 서므로 순서가 있습니다. */
const VALUE_SERVICES = {
  now: { label: '현재 가치' },
  future: { label: '미래 가치' },
};

/* 현재 가치·미래 가치는 **프리미엄**이다 (2026-09-11 지시). 등급은
 * public/lib/access.js 가 판단하고, 프로필은 관문(gate.js)이 window.ME 에
 * 둔다. 여기서 가리는 것은 편의다 — 자물쇠는 데이터베이스 쪽
 * (supabase/migrations/0003_grade.sql) 이고, 숫자 원천을 API 뒤로 옮기는
 * 일이 남아 있다 (docs/membership-grades.md). */
function myAccess() {
  const me = window.ME;
  /* 손님 = **로그인 없이 들어온 사람** (2026-09-12 지시). 지금은 가입이
     필수라 이 자리가 비지만, 나중에 로그인 없이 들어올 수 있게 풀면 그
     사람이 여기로 온다. 이름도 그때 '손님' 으로 서야 한다. */
  const guest = !(me && me.user);
  const prof = me && me.profile;
  const base = (typeof window.accessOf === 'function')
    ? window.accessOf(prof)
    : { grade: 'C', label: '손님', premium: false, expired: false, admin: false };
  return { ...base, guest, label: guest ? '손님' : base.label };
}

function valueButtons() {
  const acc = myAccess();
  const tag = '회원 전용';          // 둘 다 회원에게만 엽니다 (2026-09-12 지시)
  return `<div class="pc-val-row${acc.premium ? '' : ' is-locked'}">`
    + Object.entries(VALUE_SERVICES).map(([k, s]) =>
      `<button type="button" class="pc-val" data-val="${k}" aria-expanded="false">`
      + `<b>${s.label}</b><span class="pcv-tag${acc.premium ? '' : ' pcv-lock'}">${tag}</span></button>`).join('')
    + '</div><div class="pc-val-box" id="pc-val-box" hidden></div>';
}

/* 잠긴 단추를 눌렀을 때. 두 경우를 가른다 (2026-09-12 지시).
 *
 *   손님(로그인 안 한 사람)  → 가입을 권한다. 값이 있다는 것만 보인다.
 *   등급이 모자란 회원        → 등급 안내. 결제 문구는 아직 확정이 아니다.
 */
function premiumNotice(key, acc) {
  const s = VALUE_SERVICES[key] || { label: '' };
  const head = `<h4>${s.label} <span class="pcv-sub">회원 전용</span></h4>`;
  if (acc.guest) {
    return head
      + `<p class="pcv-lock-msg">이 필지의 ${s.label}는 회원에게 보여 드립니다.</p>`
      + '<p class="pcv-lock-msg"><a class="pcv-cta" href="/account?next=%2Fapp">무료 회원 가입</a></p>'
      + '<p class="pcv-lock-msg">구글·카카오 계정으로 가입하시면 됩니다.</p>';
  }
  /* 2026-09-12 방향 전환으로 등급 문턱이 없어졌다. 로그인한 사람이 여기
     오는 경우는 **아직 승인 전**이거나(가입 직후), 나중에 다시 잠갔을
     때뿐이다. 그러니 '등급을 올려 달라' 가 아니라 승인을 말해야 한다. */
  if (!acc.approved) {
    return head
      + `<p class="pcv-lock-msg">가입 승인을 기다리고 있습니다. 승인되면 ${s.label}가 바로 열립니다.</p>`
      + '<p class="pcv-lock-msg">승인은 무료이고 등급을 따지지 않습니다 — '
      + '<a href="/account">내 계정</a>에서 상태를 볼 수 있습니다.</p>';
  }
  const why = acc.expired
    ? `이용 기간이 끝났습니다${acc.until ? ` (${acc.until.toLocaleDateString('ko-KR')}까지)` : ''}.`
    : `${s.label}는 지금 열려 있지 않습니다.`;
  return head
    + `<p class="pcv-lock-msg">${why} 지금 등급은 <b>${escapeHtml(acc.label)}</b> 입니다.</p>`
    + '<p class="pcv-lock-msg">등급은 관리자가 올려 드립니다 — '
    + '<a href="/account">내 계정</a>에서 문의해 주세요.</p>';
}

/* 미래 가치는 **판단**이다 (2026-09-12 회의). 현재 가치는 규칙이 정한
 * 순서를 따라가는 계산이지만, 미래 가치는 '이 땅이 앞으로 오를 것인가' 를
 * 우리가 판단해 내놓는 숫자다. 그 숫자를 보고 산 사람이 손해를 보면 책임을
 * 묻는 일이 생긴다. 그래서 값을 내기 전에 면책을 붙여 둔다 — 값이 나온
 * 뒤에 붙이면 앞말과 어긋난다. */
const FUTURE_DISCLAIMER =
  '<p class="pcv-legal"><b>미래 가치는 예측이 아니라 참고 지표입니다.</b> '
  + '과거 실거래·교통량·개발 사건 자료로 만든 통계이며, 앞으로의 가격을 '
  + '약속하거나 보장하지 않습니다. 투자 판단과 그 결과는 이용자 본인의 '
  + '것이고, 저희는 그 결과에 책임지지 않습니다. 감정평가·투자자문이 '
  + '아닙니다.</p>';

function valuePanel(key) {
  const s = VALUE_SERVICES[key];
  if (!s) return '';
  return `<h4>${s.label}</h4>`
    + '<p class="pcv-soon">곧 공개합니다.</p>'
    + (key === 'future' ? FUTURE_DISCLAIMER : '');
}

/* ─────────── 현재 가치 — 공시지가기준법 2판 (표준지 방식) ───────────
 *
 * 감정평가에 관한 규칙 §14 의 순서 그대로다 (docs/radar-and-current-value.md):
 *
 *   토지단가 = 표준지공시지가 × 시점수정 × 지역요인 × 개별요인 × 그 밖의 요인
 *
 * 숫자는 여기 없다. 격차율 표·그 밖의 요인·특례는 valuation.json 이고
 * 그 원본은 src/redt/valuation.py 다 — 표가 두 곳에 있으면 어긋난다.
 * 여기는 산식과 표준지 고르기만 옮겼다.
 *
 * 표준지는 시군구 조각(stdland-NNNNN.json)으로 받는다. 조각이 없으면
 * (아직 적재 전) 예전처럼 '곧 공개합니다' 만 보인다 — 값이 없는데
 * 있는 척하지 않는다. 마디가 하나라도 비면 산출을 **보류**한다. */
let valuationTables = null;
const stdlandCache = {};
let zoningLimits = null;

/* 개발 한도 표 (C1). 시행령 상한(법) + 시군구 조례 값. 원본은
 * config/zoning_limits.yaml (python -m redt.cli zoning-limits 가 만든다).
 * 없으면 카드는 그 칸을 건너뛴다 — 값이 없는데 있는 척하지 않는다. */
async function loadZoningLimits() {
  if (zoningLimits) return zoningLimits;
  try {
    const r = await fetch('/app/data/zoning-limits.json', { cache: 'no-cache' });
    if (r.ok) zoningLimits = await r.json();
  } catch (e) { /* 없으면 개발 한도 칸이 안 선다. 나머지는 그대로. */ }
  return zoningLimits;
}

/* 실패는 **기억하지 않는다.** 처음 누를 때 조각이 없었다고 그 세션 내내
 * '곧 공개' 로 굳으면, 잠깐의 망 오류가 기능 하나를 통째로 끈다.
 * 404 는 싸다. 성공만 담아 둔다. */
/* 프리미엄 자료 (격차율 표 · 표준지 조각) — Supabase 비공개 버킷 'premium' 에서
 * 로그인 토큰으로 받는다. 버킷 정책이 premium_ok() 를 묻는다 — 이것이 자물쇠다.
 * 로그인 클라이언트가 없을 때(로컬 개발·검사)만 같은 자리의 파일로 물러난다.
 * 실패는 기억하지 않는다 — 잠깐의 망 오류가 세션 내내 기능을 끄면 안 된다. */
async function premiumFetch(name) {
  const sb = window.SB;
  if (sb && sb.storage && typeof sb.storage.from === 'function') {
    try {
      const { data, error } = await sb.storage.from('premium').download(name);
      if (error || !data) return null;
      return JSON.parse(await data.text());
    } catch (e) { return null; }
  }
  try {
    const r = await fetch(`/app/data/${name}`, { cache: 'no-cache' });
    return r.ok ? await r.json() : null;
  } catch (e) { return null; }
}

async function loadValuationTables() {
  if (valuationTables) return valuationTables;
  const t = await premiumFetch('valuation.json');
  if (t) valuationTables = t;
  return valuationTables;
}

/* 표준지 조각도 프리미엄 버킷에서. (2026-09-11 낮에 잠깐 CDN 을 썼다 — 배포
 * 크기 때문이었는데, 공개 CDN 은 자물쇠가 아니라서 버킷으로 옮겼다.) */
async function loadStdland(code) {
  if (stdlandCache[code]) return stdlandCache[code];
  const chunk = await premiumFetch(`stdland-${code}.json`);
  if (chunk) stdlandCache[code] = chunk;
  return stdlandCache[code] || null;
}

function zoneGroupOf(lu, T) {
  const t = String(lu || '');
  const hit = (T.zone_groups || []).find(([, keys]) => keys.some((k) => t.indexOf(k) >= 0));
  return hit ? hit[0] : null;
}

function zoneKindOf(lu, jimok, use, T) {
  const zg = zoneGroupOf(lu, T);
  const ug = useGroupOf(jimok, use);
  if (zg === '상업' && (ug === '대' || !ug)) return '상업지대';
  if (zg === '공업' && (ug === '대' || ug === '공장·도로' || !ug)) return '공업지대';
  const byUse = { '임야': '임야지대', '전·답': '농경지대', '대': '주택지대', '공장·도로': '공업지대' };
  return byUse[ug] || (['관리', '녹지', '농림'].includes(zg) ? '농경지대' : '주택지대');
}

function idxOf(text, table) {
  const t = String(text || '');
  if (!t) return null;
  const hit = (table || []).find(([k]) => t.indexOf(k) >= 0);
  return hit ? hit[1] : null;
}

function roadIndexOf(text, T) {
  if (!text) return null;
  const t = String(text);
  if (t.indexOf('지정되지') >= 0 || t.indexOf('미상') >= 0) return null;
  let v = idxOf(t, T.road_index);
  if (v === null && (t.indexOf('차선') >= 0 || t.indexOf('포장') >= 0)) v = 1.0;
  if (v !== null && t.indexOf('각지') >= 0 && t.indexOf('맹지') < 0) v += T.road_corner_bonus || 0;
  return v;
}

/* 표준지 조각의 짧은 열 이름을 필지와 같은 이름으로 편다. */
function stdAsParcel(r) {
  return { pnu: r.pnu, ld: r.ld, ld_name: r.nm, jibun: r.jb, year: r.y, price: r.pr,
           jimok: r.jm, area_m2: r.ar, land_use: r.lu, land_use2: r.lu2, district: r.dz,
           use_situation: r.us, road_side: r.rs, shape: r.sh, slope: r.sl,
           lon: r.lon, lat: r.lat };
}

function zoneNamesOf(p, T) {
  const keys = (T.must_match || []).concat(Object.keys(T.special || {}));
  const texts = [p.land_use, p.land_use2, p.district]
    .concat((p.zones || []).map((z) => (z && z.label) || z || ''))
    .map((x) => String(x || '')).filter((x) => x && x.indexOf('지정되지') < 0);
  const out = [];
  texts.forEach((t) => keys.forEach((k) => { if (t.indexOf(k) >= 0 && !out.includes(k)) out.push(k); }));
  return out;
}

function ratioOf(a, b) { return (a === null || b === null || a === undefined || b === undefined || !b) ? null : a / b; }

function individualFactor(subject, std, T) {
  const kind = zoneKindOf(subject.land_use, subject.jimok, subject.use_situation, T);
  const items = [];
  const warnings = [];
  const add = (cond, mine, theirs, ratio, why) =>
    items.push({ cond, subject: mine, std: theirs, ratio: ratio === null ? null : Math.round(ratio * 1000) / 1000, why });
  const useTxt = String(subject.use_situation || '');
  if (useTxt.indexOf('도로') >= 0 && (useTxt.indexOf('현황') >= 0 || subject.jimok === '도로')) {
    const [r, why] = T.special['현황도로'];
    add('기타(특례)', useTxt, std.use_situation, r, why);
    return { kind, items, factor: r, warnings, special: '현황도로' };
  }
  let r = ratioOf(roadIndexOf(subject.road_side, T), roadIndexOf(std.road_side, T));
  add('가로·접근 (도로접면)', subject.road_side, std.road_side, r, r === null ? '도로접면을 한쪽이라도 모른다' : null);
  if (r === null) warnings.push('도로접면 미상 — 격차율에서 뺐다');
  if (kind !== '임야지대') {
    r = ratioOf(idxOf(subject.shape, T.shape_index), idxOf(std.shape, T.shape_index));
    add('획지 (형상)', subject.shape, std.shape, r, r === null ? '형상을 한쪽이라도 모른다' : null);
  }
  const slopeTable = T.slope_index[kind] || T.slope_index['*'];
  r = ratioOf(idxOf(subject.slope, slopeTable), idxOf(std.slope, slopeTable));
  add('자연·획지 (지세)', subject.slope, std.slope, r, r === null ? '지세를 한쪽이라도 모른다' : null);
  if (r === null) warnings.push('지세 미상 — 격차율에서 뺐다');
  const rules = T.area_rules[kind];
  if (rules && subject.area_m2 && std.area_m2) {
    const q = Number(subject.area_m2) / Number(std.area_m2);
    const rule = rules.find(([lo, hi]) => q >= lo && (hi === null || q < hi));
    if (rule) add('획지 (면적)', `${Math.round(subject.area_m2).toLocaleString('ko-KR')}㎡`,
                  `${Math.round(std.area_m2).toLocaleString('ko-KR')}㎡`, rule[2], rule[3] || '표준지의 0.5~3배 안');
  }
  const ugS = useGroupOf(subject.jimok, subject.use_situation);
  const ugD = useGroupOf(std.jimok, std.use_situation);
  if (ugS && ugD && ugS !== ugD) {
    const m = T.use_mismatch[`${ugS}|${ugD}`];
    add('행정·기타 (지목·이용상황)', ugS, ugD, m ? m[0] : null, m ? m[1] : '지목군이 다르다 — 표준지를 다시 고를 것');
    if (!m) warnings.push(`지목군 불일치 ${ugS}/${ugD} — 표준지 재선정 권고`);
  }
  const zs = zoneNamesOf(subject, T);
  const zd = zoneNamesOf(std, T);
  (T.must_match || []).forEach((n) => {
    if (zs.includes(n) === zd.includes(n)) return;
    if ((T.std_known || []).includes(n)) warnings.push(`${n}이(가) 대상·표준지 한쪽에만 있다 — 표준지를 같은 구역에서 다시 고를 것`);
    else if (zs.includes(n)) warnings.push(`대상이 ${n} 안인데 표준지 자료에는 그 구역 정보가 없어 같은지 확인하지 못했다`);
  });
  Object.entries(T.special || {}).forEach(([name, [ratio, why]]) => {
    if (name === '현황도로') return;
    if (zs.includes(name) && !zd.includes(name)) add('행정 (지구·구역)', name, '—', ratio, why);
    else if (zd.includes(name) && !zs.includes(name) && name === '자연취락지구') add('행정 (지구·구역)', '—', name, 0.95, '표준지가 자연취락지구 (평가서 0.95)');
  });
  let factor = 1;
  items.forEach((it) => { if (it.ratio !== null) factor *= it.ratio; });
  return { kind, items, factor: Math.round(factor * 1000) / 1000, warnings, special: null };
}

/* 비교표준지 — 실무기준의 순서. 용도지역(세분까지)·구역은 거르고, 나머지는
 * 벌점(거리 km 로 환산)이다. 좌표는 아직 없어 같은 법정동리(PNU 앞 10자리)
 * 가 거리를 대신한다.
 * 가격 수준: 표준지 공시지가 ÷ 대상 개별공시지가 가 0.7~1.4 밖이면 로그
 * 배율 × 3 을 벌점으로 (두 배 벗어나면 다른 읍면동만큼). 원장 376건에서
 * 평가사가 고른 표준지는 중앙 1.05 · 78% 가 띠 안. 좌표 없이 위치 차이를
 * 잡는 자리다 — 3.6배짜리 표준지가 '조건 일치'로 뽑히던 것을 막는다. */
const PRICE_BAND = [0.7, 1.4];
const PRICE_PEN_PER_LOG = 3.0;
function priceLevelPenalty(subjectPrice, stdPrice) {
  const a = Number(subjectPrice); const b = Number(stdPrice);
  if (!(a > 0) || !(b > 0)) return [0, null];
  const k = b / a;
  if (k >= PRICE_BAND[0] && k <= PRICE_BAND[1]) return [0, k];
  const edge = k > PRICE_BAND[1] ? PRICE_BAND[1] : PRICE_BAND[0];
  return [PRICE_PEN_PER_LOG * Math.abs(Math.log(k / edge)), k];
}
function pickStandard(subject, cands, T, top) {
  const zg = zoneGroupOf(subject.land_use, T);
  const ug = useGroupOf(subject.jimok, subject.use_situation);
  const zs = zoneNamesOf(subject, T);
  const umd = String(subject.pnu || '').slice(0, 10);
  const rows = [];
  cands.forEach((c) => {
    if (zg && zoneGroupOf(c.land_use, T) !== zg) return;
    if (subject.land_use && c.land_use && String(subject.land_use).slice(0, 4) !== String(c.land_use).slice(0, 4)) return;
    const zc = zoneNamesOf(c, T);
    if ((T.std_known || []).some((n) => zs.includes(n) !== zc.includes(n))) return;
    let pen = 0; const why = [];
    if (ug && useGroupOf(c.jimok, c.use_situation) !== ug) { pen += 0.5; why.push('지목군 다름'); }
    const g1 = roadGradeOf(subject.road_side); const g2 = roadGradeOf(c.road_side);
    if (g1 !== null && g2 !== null && g1 !== g2) { pen += 0.3 * Math.abs(g1 - g2); why.push(`도로접면 ${Math.abs(g1 - g2)}단 차`); }
    if (subject.shape && c.shape && idxOf(subject.shape, T.shape_index) !== idxOf(c.shape, T.shape_index)) { pen += 0.2; why.push('형상 다름'); }
    const s1 = idxOf(subject.slope, T.slope_index['*']); const s2 = idxOf(c.slope, T.slope_index['*']);
    if (s1 !== null && s2 !== null && s1 !== s2) { pen += 0.3; why.push('지세 다름'); }
    if (umd && String(c.ld || c.pnu || '').slice(0, 10) !== umd) { pen += 1.0; why.push('다른 읍면동'); }
    const [ppen, k] = priceLevelPenalty(subject.official_price, c.price);
    if (ppen) { pen += ppen; why.push(`공시지가 수준 ${k.toFixed(1)}배`); }
    let dist = null;
    if (subject.lat != null && c.lat != null) dist = haversine(subject.lat, subject.lon, c.lat, c.lon);
    rows.push({ ...c, distance_km: dist === null ? null : Math.round(dist * 1000) / 1000,
                price_ratio: k === null ? null : Math.round(k * 100) / 100,
                penalty: Math.round(pen * 100) / 100, score: Math.round(((dist || 0) + pen) * 1000) / 1000,
                why: why.join(', ') || '조건 일치' });
  });
  rows.sort((a, b) => a.score - b.score);
  return rows.slice(0, top || 3);
}

/* 시점수정 — 표준지 공시기준일(그해 1월 1일) → 오늘. 지가변동률이 아직
 * 없어 또래 실거래 추세로 대신하고 평가서 관측 범위(0.98~1.03)로 누른다.
 * 추세도 없으면 비운다 — 1.00 이 아니다. */
function timeFactorOf(stdYear, trend, T) {
  if (!stdYear) return { factor: null, source: '표준지 연도 미상' };
  const base = new Date(stdYear, 0, 1); const now = new Date();
  const months = Math.max(0, (now - base) / (30.44 * 24 * 3600 * 1000));
  if (typeof trend !== 'number') return { factor: null, months, source: '자료 없음' };
  const [lo, hi] = T.time_clamp || [0.98, 1.03];
  const f = Math.min(hi, Math.max(lo, Math.pow(1 + trend, months / 12)));
  return { factor: Math.round(f * 100000) / 100000, months: Math.round(months * 10) / 10,
           source: '또래 실거래 추세로 대신함 (지가변동률 자료 없음)' };
}

/* 그 밖의 요인 — 두 갈래를 합친다 (src/redt/valuation.py decide_other 와 같은 규칙).
 *
 *   평가선례  T.other['용도지역군|지목군'][시도 코드 | '*']   (비공개 원장의 집계)
 *   거래사례  T.trade['시군구|용도지역군|지목군' | '…|*']     (실거래 ÷ 개별공시지가, 3년)
 *
 * 칸의 지목군은 **표준지의** 지목군이다 (2026-09-11 안성 검증의 교훈: 구거 대상에
 * 대 표준지를 골라 놓고 전·답 배율을 곱하면 틀린다 — 배율은 표준지에 곱하는
 * 것이므로 표준지가 무엇인지가 칸을 정한다). 표준지 칸이 없으면 대상의 지목군,
 * 그다음 지목군 합친 칸.
 *
 * 둘 다 있으면 건수로 가중한 기하평균(건수는 30에서 자른다) — 거래사례가 수십 건이면
 * 그쪽이 이기고 평가선례 셋뿐이면 거의 안 움직인다. 범위는 있는 쪽의 사분위 중
 * 넓은 쪽. */
function otherFactorOf(subject, std, T) {
  const zg = zoneGroupOf(subject.land_use, T);
  if (!zg) return { factor: null, basis: '자료 없음 (용도지역군 없음)', sources: [] };
  const stdUg = useGroupOf(std.jimok, std.use_situation);
  const subjUg = useGroupOf(subject.jimok, subject.use_situation);
  const sido = String(subject.pnu || '').slice(0, 2);
  const code = String(subject.pnu || '').slice(0, 5);
  const ugs = [...new Set([stdUg, subjUg].filter(Boolean))];
  let ledger = null;
  for (const ug of ugs) {
    const cell = (T.other || {})[`${zg}|${ug}`];
    const o = cell && (cell[sido] || cell['*']);
    if (o && o.median) { ledger = { ...o, ug }; break; }
  }
  let trade = null;
  for (const key of [...ugs.map((ug) => `${code}|${zg}|${ug}`), `${code}|${zg}|*`]) {
    const o = (T.trade || {})[key];
    if (o && o.median) { trade = o; break; }
  }
  const have = [ledger, trade].filter(Boolean);
  if (!have.length) return { factor: null, basis: '자료 없음', sources: [] };
  if (have.length === 1) {
    const o = have[0];
    return { factor: o.median, q1: o.q1, q3: o.q3, n: o.n, sources: have,
             basis: `${o.source} 기준 (n=${o.n}, ${o.level})` };
  }
  const w = have.map((o) => Math.min(Number(o.n), 30));
  const lg = have.reduce((acc, o, i) => acc + w[i] * Math.log(o.median), 0) / w.reduce((a, b) => a + b, 0);
  const f = Math.round(Math.exp(lg) * 100) / 100;
  const q1 = Math.min(...have.map((o) => o.q1 || f));
  const q3 = Math.max(...have.map((o) => o.q3 || f));
  return { factor: f, q1: Math.round(q1 * 100) / 100, q3: Math.round(q3 * 100) / 100,
           n: have.reduce((a, o) => a + Number(o.n), 0), sources: have,
           basis: have.map((o) => `${o.source} ${Number(o.median).toFixed(2)} (n=${o.n})`).join(' · ') + ' → 건수 가중 기하평균' };
}
window.__otherFactorOf = otherFactorOf;      // 검사(test_map.js)가 부른다

function roundDecided(x) {
  const unit = x < 10000 ? 100 : (x < 1000000 ? 1000 : 10000);
  return Math.round(x / unit) * unit;
}

function appraiseNow(subject, std, T, trend) {
  const t = timeFactorOf(std.year, trend, T);
  const ind = individualFactor(subject, std, T);
  const other = otherFactorOf(subject, std, T);
  const parts = { '표준지공시지가': std.price || null, '시점수정': t.factor, '지역요인': 1.0,
                  '개별요인': ind.factor, '그 밖의 요인': other.factor };
  const missing = Object.entries(parts).filter(([, v]) => v === null || v === undefined).map(([k]) => k);
  let unit = null; let decided = null; let range = null; let total = null;
  if (!missing.length) {
    unit = std.price * t.factor * 1.0 * ind.factor * other.factor;
    decided = roundDecided(unit);
    if (subject.area_m2) total = decided * Number(subject.area_m2);
    if (other.q1 && other.q3) range = [roundDecided(std.price * t.factor * ind.factor * other.q1),
                                       roundDecided(std.price * t.factor * ind.factor * other.q3)];
  }
  return { subject, std, time: t, individual: ind, other, parts, missing,
           unit_calc: unit, unit_decided: decided,
           range, total_krw: total, warnings: ind.warnings };
}

/* 산출표 — 감정평가서의 '감정평가액의 산출근거 및 결정의견' 을 본뜬다
 * (2026-09-12 지시 "감정평가사가 작성한 것처럼 보이게 자세히").
 *
 * 감정평가에 관한 규칙 §14 의 순서를 그대로 따른다. 평가서를 본 사람이
 * 어디를 봐야 하는지 바로 알도록 이름도 평가서의 말(비교표준지 선정 ·
 * 시점수정 · 지역요인 비교 · 개별요인 비교 · 그 밖의 요인 보정 · 산출단가 ·
 * 결정단가)을 쓴다.
 *
 * 개별요인은 평가서의 격차율 표처럼 **조건 · 대상 · 비교표준지 · 격차율**
 * 네 칸으로 낸다. 어느 조건에서 얼마를 깎였는지가 그 표의 요점이다.
 *
 * '다른 표준지를 쓰면' 은 빼 두었다 (2026-09-12 지시). 평가서는 표준지를
 * 하나 고르고 그 근거를 적는다 — 여러 안을 나란히 두는 것은 평가서의
 * 모양이 아니다.
 */
function renderValuation(res) {
  const won = (v) => (v == null ? '—' : Math.round(v).toLocaleString('ko-KR'));
  const e = escapeHtml;
  const s = res.std;
  const sub = res.subject || {};
  const f3 = (v) => (v == null ? '—' : Number(v).toFixed(3));
  const desc = (o) => [o.land_use, o.jimok || o.use_situation, o.road_side, o.shape, o.slope]
    .filter(Boolean).join(' · ');
  // 동리 이름에 지번이 이미 붙어 오는 자료가 있다 — 그대로 이으면
  // '상삼리 888-7 888-7' 이 된다.
  const ldn = String(s.ld_name || '').trim();
  const jb = String(s.jibun || '').trim();
  const stdLabel = (ldn && jb && (ldn === jb || ldn.endsWith(' ' + jb)) ? ldn
    : [ldn, jb].filter(Boolean).join(' '))
    || `표준지 ${String(s.pnu || '').slice(0, 10)}`;
  const a = sub.addr || {};
  const subLabel = a.jibun
    || [a.sido, a.sigungu, a.umd, a.ri].filter(Boolean).join(' ')
    || [sub.ld_name, sub.jibun].filter(Boolean).join(' ')
    || '대상 필지';
  const today = new Date().toLocaleDateString('ko-KR');

  const rows = [];
  rows.push(['기준시점', `<b>${e(today)}</b> <span>가격조사 완료일 기준</span>`]);
  rows.push(['대상 토지', `${e(subLabel)}${sub.area_m2 ? ` · ${won(sub.area_m2)}㎡` : ''}`
    + `<span class="pcv-desc">${e(desc(sub))}</span>`]);
  rows.push(['비교표준지 선정', `${e(stdLabel)}<span class="pcv-desc">${e(desc(s))}</span>`
    + `<span class="pcv-desc">공시지가 <b>${won(s.price)}원/㎡</b>${s.year ? ` (${s.year}. 1. 1.)` : ''}`
    + (s.distance_km != null ? ` · 대상과 ${s.distance_km}km` : '')
    + (s.why ? ` · ${e(s.why)}` : '') + '</span>']);
  rows.push(['시점수정', res.time.factor == null
    ? '<em>자료 없음</em>'
    : `<b>${f3(res.time.factor)}</b><span class="pcv-desc">${e(res.time.source)}`
      + `${res.time.months ? ` · ${res.time.months}개월` : ''}</span>`]);
  rows.push(['지역요인 비교', '<b>1.000</b><span class="pcv-desc">대상과 비교표준지가 '
    + '같은 인근지역에 있어 지역요인은 대등합니다</span>']);

  /* 격차율은 평가서처럼 조건마다 '대상 / 비교표준지 × 격차율' 을 적는다.
     네 칸 표로 그렸더니 상세 칸(23rem)보다 넓어져 글자가 옆으로 넘쳤다
     (2026-09-12 보고). 조건마다 두 줄로 접어 칸 안에 들어오게 한다. */
  const ind = res.individual;
  const itemRows = ind.items.map((it) =>
    '<li><span class="pcv-i-cond">' + e(it.cond) + '</span>'
    + `<b class="pcv-i-ratio">${f3(it.ratio)}</b>`
    + `<span class="pcv-i-vs">${e(String(it.subject || '—'))} <em>/</em> ${e(String(it.std || '—'))}</span>`
    + (it.why ? `<span class="pcv-i-why">${e(it.why)}</span>` : '')
    + '</li>').join('');
  rows.push(['개별요인 비교', `<b>${f3(ind.factor)}</b><span class="pcv-desc">[${e(ind.kind)}] 조건별 격차율의 곱`
    + ' — 대상 / 비교표준지</span>'
    + '<ul class="pcv-items">' + itemRows + '</ul>']);
  rows.push(['그 밖의 요인 보정', res.other.factor == null
    ? '<em>자료 없음</em>'
    : `<b>${res.other.factor}</b><span class="pcv-desc">${e(res.other.basis)}</span>`]);

  let bottom;
  if (res.missing.length) {
    bottom = `<p class="pcv-hold">산출 보류 — 비어 있는 마디: ${e(res.missing.join(', '))}. `
      + '1.00 으로 메우지 않습니다.</p>';
  } else {
    const p = res.parts;
    bottom = '<div class="pcv-sum">'
      + `<p class="pcv-calc">산출단가 ${won(p['표준지공시지가'])} × ${f3(p['시점수정'])}`
      + ` × 1.000 × ${f3(p['개별요인'])} × ${p['그 밖의 요인']} = ${won(res.unit_calc)}원/㎡</p>`
      + `<p class="pcv-decided">결정단가 <b>${won(res.unit_decided)}원/㎡</b>`
      + (res.range ? ` <span>(인근 지가수준 ${won(res.range[0])}~${won(res.range[1])})</span>` : '') + '</p>'
      + (res.total_krw
        ? `<p class="pcv-total">평가액(추정) 약 <b>${won(res.total_krw)}원</b>`
          + (sub.area_m2 ? ` <span>${won(sub.area_m2)}㎡ × ${won(res.unit_decided)}원/㎡</span>` : '') + '</p>'
        : '') + '</div>';
  }
  const warn = res.warnings.length
    ? '<div class="pcv-warnbox"><b>참고사항</b><ul class="pcv-warn">'
      + res.warnings.map((w) => `<li>${e(w)}</li>`).join('') + '</ul></div>'
    : '';
  return '<table class="pcv-table"><tbody>'
    + rows.map(([k, v]) => `<tr><th>${e(k)}</th><td>${v}</td></tr>`).join('')
    + '</tbody></table>' + bottom + warn
    /* 이 두 줄은 법이 걸리는 자리다 (docs/legal-notes.md §2).
     * '감정평가가 아닙니다' 는 이름을, '담보·소송·과세·보상 목적으로 쓸 수
     * 없습니다' 는 용도를 좁힌다. 감정평가사협회가 프롭테크 시세 산정을
     * 걸고 넘어진 지점이 '감정평가서처럼 보이는 것' 이어서, 스스로 용도를
     * 좁혀 놓은 문장이 실제 사건에서 가장 잘 먹힌다. **지우지 말 것.** */
    + '<p class="pcv-note">공시지가기준법의 다섯 마디를 데이터베이스로 산출한 <strong>예상값</strong>입니다. '
    + '감정평가가 아니며, 담보·소송·과세·보상 목적으로 쓸 수 없습니다. '
    + '<a href="/guide/law">산출 방법</a></p>';
}

/* 단추를 누르면 여기로 온다. 조각이 없으면 예전 글(곧 공개)로 둔다.
   산출은 nowResults() 한 곳에서 한다 — 검사(test_map.js)도 같은 것을 불러
   다섯 마디를 견준다. 화면은 값만 내지만 마디가 틀리면 검사가 잡는다. */
async function nowResults() {
  const ctx = window.__parcel;
  if (!ctx || !ctx.parcel) return null;
  const parcel = ctx.parcel;
  const code = String(parcel.pnu || '').slice(0, 5);
  const [T, chunk] = await Promise.all([loadValuationTables(), loadStdland(code)]);
  if (!T || !chunk || !chunk.rows || !chunk.rows.length) return null;
  // 주소는 필지 자료가 아니라 따로 온다 (ctx.addr). 산출표 첫 줄에 적는다.
  const subject = { ...parcel, zones: ctx.zones || [], addr: ctx.addr || null };
  const cands = chunk.rows.map(stdAsParcel);
  const picked = pickStandard(subject, cands, T, 3);
  if (!picked.length) return { picked: [], results: [] };
  const mo = pickTrend(code, parcelGroup(parcel.land_use));
  return { picked, results: picked.map((std) => appraiseNow(subject, std, T, mo ? mo.trend : null)) };
}
window.__nowResults = () => nowResults();
window.__renderValuation = (res) => renderValuation(res);  // 좁은 칸 확인용

async function fillNowValue(box) {
  const got = await nowResults();
  if (!got) return;
  if (box.dataset.open !== 'now') return;
  if (!got.results.length) {
    box.innerHTML = `<h4>${VALUE_SERVICES.now.label}</h4>`
      + '<p class="pcv-hold">견줄 자료가 모자라 이 필지는 값을 내지 못했습니다.</p>';
    return;
  }
  box.innerHTML = `<h4>${VALUE_SERVICES.now.label}</h4>` + renderValuation(got.results[0]);
}

/* 카드는 누를 때마다 통째로 다시 그려진다. 그래서 단추에 직접 듣지
 * 않고 문서에 한 번만 건다 — 안 그러면 두 번째 필지부터 안 눌린다. */
function wireValueButtons() {
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('.pc-val');
    if (!btn) return;
    const box = document.getElementById('pc-val-box');
    if (!box) return;
    const key = btn.dataset.val;
    const same = box.dataset.open === key && !box.hidden;
    document.querySelectorAll('.pc-val').forEach((b) => {
      b.classList.toggle('is-on', !same && b.dataset.val === key);
      b.setAttribute('aria-expanded', String(!same && b.dataset.val === key));
    });
    if (same) { box.hidden = true; box.dataset.open = ''; return; }
    box.dataset.open = key;
    box.hidden = false;
    const acc = myAccess();
    if (!acc.premium) {
      box.innerHTML = premiumNotice(key, acc);
      return;
    }
    box.innerHTML = valuePanel(key);
    if (key === 'now') fillNowValue(box);
  });
}

function parcelCard(parcel, diag, at, addr, zones, limits) {
  const won = (v) => Math.round(v).toLocaleString('ko-KR');
  const py = parcel.area_m2 ? (parcel.area_m2 / PYEONG_M2) : null;
  /* 백분위를 '상위 N%' 로 적는다. 백분위가 100 이면 N 이 0 이 되어
     **'상위 0%'** 가 찍혔다 — 뜻은 '또래 전부보다 낫다' 인데 읽는 사람에게는
     고장처럼 보인다. 그 칸만 말로 적는다. */
  const pctText = (pct) => {
    if (pct == null) return '<em>조사 안 됨</em>';
    const top = 100 - pct;
    if (top <= 0) return '최상위';
    return `상위 ${top}%`;
  };
  const rows = (diag ? diag.axes : []).map((a) => {
    const pct = a.pct == null ? null : Math.round(a.pct * 100);
    return `<tr><th>${escapeHtml(a.label)}</th>`
      + `<td>${pctText(pct)}</td>`
      + `<td class="raw">${escapeHtml(a.raw)}</td></tr>`;
  }).join('');
  const peer = diag && diag.peer;
  return '<div class="parcel-card">'
    + `<div class="pc-head"><b>${escapeHtml(parcel.land_use || '용도 미상')}</b>`
    + `<span>${escapeHtml(parcel.jimok || '')}</span></div>`
    + parcelAddr(addr, parcel)
    + `<div class="pc-size">${parcel.area_m2 ? `${won(parcel.area_m2)}㎡` : '면적 미상'}`
    + (py ? ` <em>(${won(py)}평)</em>` : '') + '</div>'
    + (diag ? radarSvg(diag.axes) : '')
    + (rows ? `<table class="pc-axes"><tbody>${rows}</tbody></table>` : '')
    + (diag ? axisNotes(diag.axes) : '')
    + valueButtons()
    + '<h4 class="pc-sub">토지 정보</h4>'
    + parcelFacts(parcel, zones)
    + parcelLimits(parcel, limits || zoningLimits)
    + parcelZones(zones)
    + (peer
       ? `<p class="pc-peer">${escapeHtml(peer.level)}의 `
         + `${escapeHtml(peer.group)} 거래 ${peer.n.toLocaleString('ko-KR')}건과 견줬습니다.</p>`
       : '<p class="pc-peer">견줄 또래를 못 찾았습니다.</p>')
    // **합산하지 않는다**는 것을 화면에도 적는다. 이것이 이 제품이
    // 땅박사와 갈리는 지점이고, 적어 두지 않으면 사람은 넓이를 점수로
    // 읽는다.
    + '<p class="pc-note">축을 더해 하나의 점수로 만들지 않습니다. '
    + '같은 땅이 창고에는 좋고 주택에는 나쁠 수 있어서, 그 차이가 '
    + '점수 하나로 뭉개지면 사라집니다.</p>'
    + eumLink(parcel)
    + '</div>';
}

/* 토지이음으로 넘기는 단추 (요구사항 2026-09-10).
 *
 * 우리가 못 주는 것 — 소유 정보, 토지이동(변동) 사유, 지역지구 지정여부
 * 전체 — 은 여기서 봅니다. 브이월드 WFS 응답에 없는 칸들입니다.
 *
 * ## 왜 '열람' 을 한 번 더 눌러야 하는가
 *
 * 주소 세 가지를 실제로 눌러 보고 고른 것입니다 (2026-09-10).
 *
 *   luLandDet.jsp?pnu=            검색칸이 그 필지로 채워진다.
 *                                 '열람' 을 눌러야 표가 나온다.      ← 이것
 *   luLandDetR.jsp?pnu=           시스템 에러 안내
 *   luLandDet.jsp?mode=search&…   표가 바로 나오는데 **값이 섞인다**
 *
 * 마지막 것이 겉보기에는 가장 좋았습니다. 그런데 실측 화면에서 검색칸은
 * 우리 필지(경기 안성시 봉산동 31-3)인데 소재지는 경남 거제시 연초면
 * 송정리 887, 지목·면적도 남의 것이었습니다. 공시지가와 용도지역만
 * 우리 것과 같았습니다 — 앞서 열람한 기록이 섞여 나온 것으로 보입니다.
 *
 * **값이 섞여 나오는 링크는 없느니만 못합니다.** 안성 땅을 보러 들어가서
 * 거제 임야를 읽게 됩니다. 한 번 더 누르는 대신 맞는 것을 보여 줍니다.
 * 그 한 번을 단추 글에 미리 적어 두어, 빈 표를 보고 고장으로 읽지
 * 않게 합니다. */
const EUM_BASE = 'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp';
function eumLink(parcel) {
  const pnu = String((parcel || {}).pnu || '');
  if (!/^\d{19}$/.test(pnu)) return '';
  return `<a class="pc-eum" href="${EUM_BASE}?pnu=${pnu}"`
    + ' target="_blank" rel="noopener noreferrer">'
    + '토지이음에서 더 보기'
    + '<em>소유·지역지구·토지이동 — 열람 단추를 한 번 누르세요</em></a>';
}

/* 고른 필지의 윤곽을 그린다 (요구사항 2026-09-10).
 *
 * **한 번에 하나만.** 누를 때마다 쌓이면 지도가 파란 그물이 된다.
 *
 * 채우기를 옅게 두는 이유. 이 화면의 주인공은 값(땅값 글자·거래 핀)
 * 이고, 윤곽은 '어디까지가 이 땅인가' 만 말하면 된다. 진하게 채우면
 * 그 위의 글자를 덮어 값을 못 읽는다.
 *
 * 도형이 없으면 지우기만 한다 — 바다를 눌렀을 때 앞에 고른 필지가
 * 그대로 남아 있으면 그것을 고른 줄로 읽는다. */
function drawParcelShape(geom) {
  if (!parcelLayer) return;
  parcelLayer.clearLayers();
  window.__parcelShape = null;
  if (!geom) return;
  const shape = L.geoJSON(geom, {
    pane: 'parcelPane',
    // 누름을 가로채면 안 된다. 윤곽 위를 다시 눌러 옆 필지로 가는 것이
    // 막히고, 그 위에 걸친 땅값 글자도 안 눌린다.
    interactive: false,
    style: {
      color: '#1B4F9C', weight: 2.5, opacity: .95,
      fillColor: '#3B73C4', fillOpacity: .18,
    },
  });
  parcelLayer.addLayer(shape);
  window.__parcelShape = geom;
}

/* 지도를 눌렀을 때. 용도지역 말풍선 대신 **오른쪽에 필지 카드**를 연다. */
async function askParcel(latlng) {
  const box = document.getElementById('detail');
  if (!box) return;
  const lat = latlng.lat.toFixed(6);
  const lon = latlng.lng.toFixed(6);
  showDetail(true);
  detailBody('<div class="detail-empty"><p>필지를 확인하는 중…</p></div>');
  const [stats, res, limits] = await Promise.all([
    loadParcelStats(),
    fetch(`/api/tile?mode=parcel&lat=${lat}&lon=${lon}`)
      .then((r) => (r.status === 429
        ? { tooMany: Number(r.headers.get('retry-after')) || 60 }
        : r.json()))
      .catch(() => null),
    loadZoningLimits(),
  ]);
  // **막힌 것과 자료가 없는 것을 구분해 적는다.** 둘을 같은 글로
  // 보여주면 '이 땅은 정보가 없다' 로 읽히는데, 사실은 잠시 뒤 다시
  // 누르면 나온다.
  if (res && res.tooMany) {
    drawParcelShape(null);
    detailBody('<div class="detail-empty"><p>잠깐만요 — 요청이 너무 잦습니다.</p>'
      + `<p class="hint">${res.tooMany}초쯤 뒤에 다시 눌러 주세요. `
      + '자료가 없는 것이 아닙니다.</p></div>');
    window.__parcel = null;
    return;
  }
  const parcel = res && res.parcel;
  if (!parcel) {
    drawParcelShape(null);
    detailBody('<div class="detail-empty"><p>여기서는 필지 자료를 '
      + '못 받았습니다.</p><p class="hint">바다·도로처럼 지적이 없는 곳이거나, '
      + '브이월드가 잠시 응답하지 않은 것입니다.</p></div>');
    window.__parcel = null;
    return;
  }
  drawParcelShape(res.geom);
  const diag = stats ? parcelAxes(parcel, [latlng.lat, latlng.lng], res.zones || []) : null;
  detailBody(parcelCard(parcel, diag, [latlng.lat, latlng.lng],
                        res.addr, res.zones || [], limits));
  window.__parcel = { parcel, diag, geom: res.geom || null,
                      addr: res.addr || null, zones: res.zones || [] };
}

/* ─────────── 세 가설 판정 ─────────── */
/* 이 화면은 숫자를 하나 더 보여주는 곳이 아니다. **그 숫자로 무엇을 주장할
   수 있는가** 를 적는 곳이다. 계수가 유의해도 위약 밴드가 같이 유의하면
   IC 효과가 아니고, 표본이 모자라면 '효과 없음' 이 아니라 '아직 모름' 이다.
   이 구분이 화면에서 사라지면 사람은 스스로 결론을 채워 넣는다. */
const VERDICT_TONE = {
  '지지': 'ok',
  '기각': 'no',
};
function verdictTone(v) {
  const t = String(v || '');
  if (VERDICT_TONE[t]) return VERDICT_TONE[t];
  // '관계 있음 (상관 · 인과 아님)' — 있는 것은 맞지만 인과가 아니다.
  // '지지' 와 같은 초록을 주면 읽는 사람이 구별할 방법이 없다.
  if (t.startsWith('관계 있음')) return 'corr';
  return t.startsWith('교란') ? 'warn' : 'unknown';
}

const fixed = (v, d = 3) => (v == null ? '—' : Number(v).toFixed(d));

function buildVerdict() {
  const cards = $('#verdict-cards');
  const flags = $('#verdict-flags');
  const stamp = $('#verdict-stamp');
  if (!cards) return;
  const data = state.verdicts;
  if (!data || !Array.isArray(data.hypotheses) || !data.hypotheses.length) {
    flags.innerHTML = '';
    stamp.textContent = '';
    const empty = $('#verdict-kind');
    if (empty) empty.hidden = true;
    cards.innerHTML =
      '<p class="empty">아직 판정이 계산되지 않았습니다. ' +
      '분석이 한 번 돌면 여기에 표가 생깁니다.</p>';
    return;
  }

  // 종류 전환. 있는 것만 보여준다 — 눌러도 아무 일 없는 단추는 고장으로 읽힌다.
  const picker = $('#verdict-kind');
  if (picker) {
    const have = Object.keys(state.verdictSets || {});
    picker.hidden = have.length < 2;
    if (!picker.dataset.wired) {
      picker.dataset.wired = '1';
      picker.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-kind]');
        if (!btn) return;
        state.verdictKind = btn.dataset.kind;
        state.verdicts = state.verdictSets[state.verdictKind] || null;
        buildVerdict();
      });
    }
    picker.querySelectorAll('button[data-kind]').forEach((b) => {
      b.hidden = !state.verdictSets[b.dataset.kind];
      b.classList.toggle('is-on', b.dataset.kind === state.verdictKind);
    });
  }

  stamp.textContent =
    `${data.kind === 'factory' ? '공장·창고' : '토지'} · ` +
    `${data.volume_col === 'volume_freight' ? '화물 교통량' : '전체 교통량'} · ` +
    (data.generated_at || '').slice(0, 10) +
    (data.primary === false ? ' · 탐색(참고용)' : '');

  // 경고를 카드 위에 둔다. 표를 먼저 읽고 나서 '사실은 통제가 없었습니다'
  // 를 만나면 이미 늦다 — 사람은 먼저 본 숫자를 기억한다.
  const notes = [];
  // 계수를 여럿 던지면 그중 몇은 우연히 유의하다. 그래서 판정은 미리 정한
  // 한 조합에서만 하고, 나머지는 참고로만 본다. 화면이 이 구분을 안 보이면
  // 탐색에서 우연히 나온 것을 결론으로 읽게 된다.
  if (data.primary === false) {
    notes.push(['warn',
      '<b>이 표는 탐색입니다 — 판정이 아닙니다.</b> 판정은 ' +
      `${data.primary_kind === 'factory' ? '공장' : '토지'}·` +
      `${data.primary_volume === 'volume_freight' ? '화물' : '전체'} 교통량` +
      ' 조합에서만 합니다. 계수를 여럿 던지면 그중 몇은 우연히 유의합니다.']);
  }
  if (data.synthetic) {
    notes.push(['no',
      '<b>합성(연습용) 자료로 돌린 결과입니다.</b> 판정이 아닙니다.']);
  }
  if (!data.controlled) {
    notes.push(['warn',
      '<b>H3 통제 변수가 하나도 없습니다.</b> 아래 계수는 인구·산단 같은 ' +
      '교란을 빼지 않은 값이라, 유의하게 나와도 ‘IC 효과’ 라고 부를 수 없습니다.']);
  } else {
    notes.push(['ok', `H3 통제: ${data.controls.map(escapeHtml).join(', ')}`]);
  }
  if (data.pre_trend_ok === false) {
    notes.push(['no',
      '<b>평행추세가 깨졌습니다.</b> 개통 전부터 이미 다르게 움직이고 있었다는 ' +
      '뜻이라, H1 계수는 개통 효과로 읽을 수 없습니다.']);
  }
  flags.innerHTML = notes
    .map(([tone, html]) => `<p class="verdict-flag is-${tone}">${html}</p>`)
    .join('');

  cards.innerHTML = data.hypotheses.map((h) => {
    const tone = verdictTone(h.verdict);
    const rows = (h.rows || []).map((r) => {
      // 95% 구간이 0 을 품으면 '말할 수 없다' 이다. 계수 부호만 보고
      // 읽지 않도록 그 사실을 글자로 적는다.
      const has = r.ci_lo != null;
      const crosses = has && r.ci_lo <= 0 && r.ci_hi >= 0;
      const ci = has
        ? `<span class="${crosses ? 'ci-null' : 'ci-away'}">` +
          `${r.ci_lo >= 0 ? '+' : ''}${fixed(r.ci_lo)} ~ ` +
          `${r.ci_hi >= 0 ? '+' : ''}${fixed(r.ci_hi)}</span>`
        : '—';
      // 최소 탐지 가능 효과. 계수가 0 근처일 때 '효과가 없다' 와
      // '작아서 못 봤다' 를 가르는 유일한 단서다.
      const weak = r.mde != null && r.beta != null
        && Math.abs(r.beta) < r.mde;
      return `<tr>
        <td>${escapeHtml(r.label)}${r.note
          ? ` <em class="hint">${escapeHtml(r.note)}</em>` : ''}</td>
        <td class="num">${r.n == null ? '—' : r.n.toLocaleString('ko-KR')}</td>
        <td class="num">${r.clusters == null ? '—' : r.clusters}</td>
        <td class="num">${fixed(r.beta)}</td>
        <td class="num">${fixed(r.p)}</td>
        <td>${ci}</td>
        <td class="num${weak ? ' mde-weak' : ''}">${fixed(r.mde)}</td></tr>`;
    }).join('');

    return `<article class="verdict-card is-${tone}">
      <header>
        <span class="verdict-badge is-${tone}">${escapeHtml(h.verdict)}</span>
        <b>${escapeHtml(h.name)}</b>
      </header>
      <p class="claim">${escapeHtml(h.claim)}</p>
      <p class="why">${escapeHtml(h.why)}</p>
      ${rows ? `<div class="scroller"><table class="vt-table">
        <thead><tr><th>항</th><th class="num">n</th><th class="num">영업소</th>
          <th class="num">β</th><th class="num">p</th><th>95% 구간</th>
          <th class="num" title="이 표본으로 잡을 수 있는 최소 효과">잡을 수 있는 최소</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : ''}
    </article>`;
  }).join('');

  // 검사가 화면과 같은 것을 보게 열어 둔다.
  window.__verdicts = data.hypotheses.map((h) => ({
    key: h.key, verdict: h.verdict, tone: verdictTone(h.verdict),
    rows: (h.rows || []).length,
  }));
}

function focusOnMap(id) {
  document.querySelector('.tab[data-view="explore"]').click();
  selectTollgate(id);
  const marker = map && markers.get(id);
  if (marker) map.setView(marker.getLatLng(), 11);
}

/* ─────────── 매물 (서버 연동) ─────────── */
async function api(path, { method = 'GET', body, auth = false } = {}) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(API + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && auth) { setSession(null, null); }
  if (!res.ok) {
    let detail = `요청 실패 (${res.status})`;
    try {
      const payload = await res.json();
      if (typeof payload.detail === 'string') detail = payload.detail;
      // pydantic 검증 오류는 배열로 온다 — 첫 항목의 사람이 읽을 메시지를 쓴다
      else if (Array.isArray(payload.detail) && payload.detail.length) {
        const first = payload.detail[0];
        detail = `${(first.loc || []).slice(-1)[0] || ''} ${first.msg || ''}`.trim();
      }
    } catch { /* 본문이 JSON 이 아니면 기본 메시지 */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function setSession(token, broker) {
  state.token = token;
  state.broker = broker;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch { /* 저장이 막힌 환경에서도 세션은 메모리에서 동작 */ }
  renderAuth();
}

function renderAuth() {
  const authed = Boolean(state.broker);
  $('#auth-box').hidden = authed;
  $('#broker-box').hidden = !authed;
  if (authed) {
    const b = state.broker;
    $('#broker-office').textContent = b.office_name;
    $('#broker-detail').textContent =
      `${b.agent_name} · 등록번호 ${b.license_no} · ${b.phone} · ${b.office_address}`;
  }
  document.querySelectorAll('#listing-scope .seg-btn').forEach((btn) => {
    btn.hidden = btn.dataset.scope === 'mine' && !authed;
  });
  if (!authed && state.scope === 'mine') setScope('public');
}

function showError(sel, message) {
  const node = $(sel);
  node.textContent = message || '';
  node.hidden = !message;
}

async function initListings() {
  // 정적 배포에는 매물 API 가 없다. 있는지부터 확인하고, 없으면 안내로 대체한다.
  if (API) {
    try {
      const fee = await api('/fees');
      state.apiAvailable = true;
      $('#fee-note').innerHTML =
        `등록 수수료 <strong>${fee.listing_fee_krw.toLocaleString('ko-KR')}원</strong>` +
        ` / ${fee.listing_days}일` +
        (fee.payment_connected ? '' : ` <span class="hint">— ${fee.notice}</span>`);
    } catch { state.apiAvailable = false; }
  }
  if (!state.apiAvailable) {
    $('#listings-offline').hidden = false;
    $('#listings-grid').hidden = true;
    return;
  }

  try { state.token = localStorage.getItem(TOKEN_KEY); } catch { state.token = null; }
  if (state.token) {
    try { state.broker = await api('/me', { auth: true }); }
    catch { setSession(null, null); }
  }
  renderAuth();

  document.querySelectorAll('[data-auth]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.auth;
      document.querySelectorAll('[data-auth]').forEach((b) =>
        b.classList.toggle('is-on', b === btn));
      $('#login-form').hidden = mode !== 'login';
      $('#signup-form').hidden = mode !== 'signup';
      showError('#auth-error', '');
    });
  });

  $('#login-form').addEventListener('submit', (e) => submitAuth(e, '/auth/login'));
  $('#signup-form').addEventListener('submit', (e) => submitAuth(e, '/brokers'));

  $('#logout-btn').addEventListener('click', async () => {
    try { await api('/auth/logout', { method: 'POST', auth: true }); } catch { /* 이미 만료 */ }
    setSession(null, null);
    loadListings();
  });

  $('#listing-form').addEventListener('submit', submitListing);
  $('#pick-btn').addEventListener('click', startPick);

  document.querySelectorAll('#listing-scope .seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => setScope(btn.dataset.scope));
  });

  $('#listing-list').addEventListener('click', onListingAction);
  loadListings();
}

async function submitAuth(event, path) {
  event.preventDefault();
  showError('#auth-error', '');
  const body = Object.fromEntries(new FormData(event.target).entries());
  try {
    const res = await api(path, { method: 'POST', body });
    setSession(res.token, res.broker);
    event.target.reset();
    loadListings();
  } catch (err) {
    showError('#auth-error', err.message);
  }
}

async function submitListing(event) {
  event.preventDefault();
  showError('#listing-error', '');
  const raw = Object.fromEntries(new FormData(event.target).entries());
  const body = {
    kind: raw.kind, deal_type: raw.deal_type, address: raw.address.trim(),
    area_m2: Number(raw.area_m2), price_manwon: Number(raw.price_manwon),
    contact_phone: raw.contact_phone.trim(),
    memo: raw.memo ? raw.memo.trim() : null,
    lat: raw.lat ? Number(raw.lat) : null,
    lon: raw.lon ? Number(raw.lon) : null,
  };
  try {
    await api('/listings', { method: 'POST', body, auth: true });
    event.target.reset();
    setScope('mine');
  } catch (err) {
    showError('#listing-error', err.message);
  }
}

function setScope(scope) {
  state.scope = scope;
  document.querySelectorAll('#listing-scope .seg-btn').forEach((b) =>
    b.classList.toggle('is-on', b.dataset.scope === scope));
  $('#listing-title').childNodes[0].nodeValue =
    scope === 'mine' ? '내 매물 ' : '공개 매물 ';
  loadListings();
}

async function loadListings() {
  if (!state.apiAvailable) return;
  const mine = state.scope === 'mine' && state.broker;
  try {
    state.listings = await api(`/listings${mine ? '?mine=true' : ''}`,
                               { auth: Boolean(state.broker) });
  } catch (err) {
    $('#listing-list').innerHTML = `<p class="empty">${err.message}</p>`;
    state.listings = [];
    return;
  }
  renderListings();
  renderListingMarkers();
}

async function onListingAction(event) {
  const btn = event.target.closest('button[data-act]');
  if (!btn) return;
  const id = btn.dataset.id;
  try {
    if (btn.dataset.act === 'publish') {
      await api(`/listings/${id}/publish`, { method: 'POST', auth: true });
    } else if (btn.dataset.act === 'delete') {
      if (!confirm('이 매물을 내리시겠습니까?')) return;
      await api(`/listings/${id}`, { method: 'DELETE', auth: true });
    } else if (btn.dataset.act === 'locate') {
      const item = state.listings.find((l) => String(l.id) === id);
      if (item && item.nearest_tollgate_id) focusOnMap(item.nearest_tollgate_id);
      return;
    }
    loadListings();
  } catch (err) {
    alert(err.message);
  }
}

const STATUS_LABEL = {
  pending_payment: { text: '결제 대기', cls: 'pending' },
  active: { text: '게시중', cls: 'active' },
  expired: { text: '만료', cls: 'expired' },
};

function renderListings() {
  const items = state.listings;
  $('#listing-count').textContent = items.length;
  const list = $('#listing-list');
  if (!items.length) {
    list.innerHTML = `<p class="empty">${
      state.scope === 'mine' ? '등록한 매물이 없습니다.' : '공개된 매물이 없습니다.'}</p>`;
    return;
  }
  const mine = state.scope === 'mine';
  list.innerHTML = items.map((it) => {
    const st = STATUS_LABEL[it.status] || { text: it.status, cls: 'pending' };
    const near = it.nearest_name
      ? `<button type="button" class="link" data-act="locate" data-id="${it.id}">
           ${it.nearest_name} ${it.nearest_km.toFixed(1)}km · ${it.band}</button>`
      : '<span class="hint">좌표 없음 — IC 거리 미계산</span>';
    return `<article class="listing">
      <div class="top">
        <strong>${KIND_LABEL[it.kind] || it.kind}</strong>
        <span class="tag ${st.cls}">${st.text}</span>
        <span>${it.deal_type === 'lease' ? '임대' : '매매'}</span>
        <span class="price">${it.price_manwon.toLocaleString('ko-KR')}만원</span>
      </div>
      <div>${it.address}</div>
      <div class="who">${Number(it.area_m2).toLocaleString('ko-KR')}㎡
        · ㎡당 ${num(it.price_per_m2)}원</div>
      <div class="who">${near}</div>
      ${it.memo ? `<div class="memo">${escapeHtml(it.memo)}</div>` : ''}
      <div class="who">${it.office_name} · ${it.agent_name}
        · 등록번호 ${it.license_no} · ${it.contact_phone}</div>
      ${mine ? `<div class="actions">
        ${it.status === 'pending_payment'
          ? `<button type="button" class="btn small" data-act="publish" data-id="${it.id}">결제하고 게시</button>`
          : ''}
        <button type="button" class="btn ghost small" data-act="delete" data-id="${it.id}">내리기</button>
      </div>` : ''}
    </article>`;
  }).join('');
}

/* 중개사가 입력한 텍스트는 그대로 innerHTML 에 넣지 않는다 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/* ─────────── 매물을 지도에 ─────────── */
function renderListingMarkers() {
  if (!map) return;
  if (!listingLayer) listingLayer = L.layerGroup().addTo(map);
  listingLayer.clearLayers();
  state.listings.filter((l) => l.lat && l.lon).forEach((l) => {
    const marker = L.marker([l.lat, l.lon], {
      icon: L.divIcon({ className: 'listing-pin', iconSize: [14, 14] }),
      pane: 'tradePane',
    });
    marker.bindTooltip(
      `${KIND_LABEL[l.kind] || l.kind} · ${l.price_manwon.toLocaleString('ko-KR')}만원`,
      { direction: 'top' });
    listingLayer.addLayer(marker);
  });
  // 검사용 들여다보기 창 — window.__tradeStyles 와 같은 취지다.
  window.__listingStyles = listingLayer.getLayers
    ? listingLayer.getLayers().map((l) => ({
        pane: l.options.pane,
        className: (l.options.icon && l.options.icon.options
                    && l.options.icon.options.className) || '',
      }))
    : undefined;
}

function startPick() {
  if (!map) { alert('지도를 사용할 수 없어 좌표를 직접 입력해야 합니다.'); return; }
  state.pickMode = true;
  document.querySelector('.tab[data-view="explore"]').click();
  document.body.classList.add('picking');
  $('#map').insertAdjacentHTML('beforeend',
    '<div class="pick-hint" id="pick-hint">매물 위치를 지도에서 클릭하세요 · Esc 취소</div>');
}

function endPick(latlng) {
  state.pickMode = false;
  document.body.classList.remove('picking');
  const hint = $('#pick-hint');
  if (hint) hint.remove();
  if (latlng) {
    document.querySelector('#listing-form [name=lat]').value = latlng.lat.toFixed(6);
    document.querySelector('#listing-form [name=lon]').value = latlng.lng.toFixed(6);
  }
  document.querySelector('.tab[data-view="listings"]').click();
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && state.pickMode) endPick(null);
});

/* 레일 접기 로직은 레일과 함께 사라졌다 (2026-09-08). 필터는 이제
   아래 시트에 있고, 시트는 닫혀서 시작하므로 접을 것이 없다. */

/* ─── 지역 검색 ───────────────────────────────────────────────────
 *
 * 요구사항(2026-09-09, 3번): "첫 화면이 전국인데, 정작 쓸 사람은
 * 자기 지역부터 봅니다."
 *
 * **필지로는 못 간다.** 실거래 지번이 마스킹돼 있어(1**) 어느 필지인지
 * 특정할 수가 없다(scripts/cadastral_probe.py 1절). 갈 수 있는 가장
 * 아래가 읍·면·동이고, 안내문이 그것을 밝힌다.
 *
 * 색인(places.json)은 **누르기 전까지 안 받는다.** 첫 화면에 5천 줄을
 * 얹으면 지도가 그만큼 늦게 뜨는데, 검색은 대부분의 방문에서 안 쓰인다.
 */
const FIND_MAX = 8;
const FIND_ZOOM = { sido: 9, sigungu: 11, umd: 13, addr: 18 };
// 지번이 붙어 있는가 — '건업리 140-25', '산 12', '140번지'. 끝에 숫자가
// 오면 지번으로 본다 (요구사항 2026-09-11: 주소를 치면 그 필지로).
const FIND_JIBUN_RE = /(^|\s)(산\s?)?\d{1,4}(-\d{1,4})?(번지)?$/;
let findIndex = null;
let findLoading = null;

async function findLoad() {
  if (findIndex) return findIndex;
  if (findLoading) return findLoading;
  findLoading = (async () => {
    const rows = [];
    // 시·도와 시·군·구는 이미 받아 둔 regions.json 에 있다. 같은 것을
    // 두 번 받지 않는다.
    const sido = new Map();
    (state.regions || []).forEach((r) => {
      rows.push({ k: 'sigungu', n: r.name, p: r.sido || '',
                  lat: r.office_lat || r.lat, lon: r.office_lon || r.lon });
      const sd = r.sido || '';
      if (sd && !sido.has(sd)) sido.set(sd, { lat: r.lat, lon: r.lon, n: 0 });
      if (sd) { const g = sido.get(sd); g.n += 1; }
    });
    sido.forEach((v, k) => rows.push({ k: 'sido', n: k, p: '',
                                       lat: v.lat, lon: v.lon }));
    try {
      const r = await fetch('/app/data/places.json');
      if (r.ok) {
        const body = await r.json();
        (body.places || []).forEach((x) => rows.push(x));
      }
    } catch (err) {
      // 읍·면·동이 없어도 시·군·구까지는 찾을 수 있다. 통째로 죽이지 않는다.
    }
    findIndex = rows.filter((x) => typeof x.lat === 'number'
                                   && typeof x.lon === 'number');
    return findIndex;
  })();
  return findLoading;
}

/* 앞에서 맞는 것을 먼저. '동' 을 쳤을 때 '공도읍' 보다 '동면' 이
   위로 와야 한다 — 사람은 자기가 친 글자로 시작하는 것을 먼저 찾는다. */
function findMatch(rows, q) {
  const s2 = q.trim();
  if (s2.length < 1) return [];
  const starts = [];
  const inside = [];
  for (const r of rows) {
    const name = String(r.n || '');
    const i = name.indexOf(s2);
    if (i === 0) starts.push(r);
    else if (i > 0) inside.push(r);
    else if (String(r.p || '').indexOf(s2) === 0) inside.push(r);
    if (starts.length >= FIND_MAX * 3) break;
  }
  const rank = { sido: 0, sigungu: 1, umd: 2 };
  const by = (a, b) => (rank[a.k] - rank[b.k]) || ((b.c || 0) - (a.c || 0));
  return starts.sort(by).concat(inside.sort(by)).slice(0, FIND_MAX);
}

/* 지번 검색의 주소 보완. '곤지암읍 건업리 140-25' 라고만 치면 지오코더가
   어느 광주인지 모른다. 색인에서 읍·면·동을 찾아 시·도와 시·군·구를 앞에
   붙인다 — '경기도 광주시 곤지암읍 건업리 140-25'. 이미 시·군·구가 들어
   있으면 시·도만 채운다. 못 찾으면 친 그대로 보낸다. */
// 시·군·구 코드 앞 두 자리 → 시·도. 지역 표(regions.json)에 없을 때의 뒷받침이다.
const SIDO_BY_PREFIX = {
  11: '서울특별시', 26: '부산광역시', 27: '대구광역시', 28: '인천광역시', 29: '광주광역시',
  30: '대전광역시', 31: '울산광역시', 36: '세종특별자치시', 41: '경기도', 43: '충청북도',
  44: '충청남도', 46: '전라남도', 47: '경상북도', 48: '경상남도', 50: '제주특별자치도',
  51: '강원특별자치도', 52: '전북특별자치도',
};
// 끝의 지번을 떼어 낸다 — '산 12', '140-25', '140번지'.
function findJibun(q) {
  const m = /(?:^|\s)(산\s?)?(\d{1,4})(?:-(\d{1,4}))?(?:번지)?$/.exec(q.trim());
  if (!m) return null;
  return { san: !!m[1], bon: m[2], bu: m[3] || '0',
           head: q.trim().slice(0, m.index).trim() };
}

/* 법정동코드(10자리). 명부 조각(umd-roster-NN.json)의 일곱째 칸이다 —
   내보내기(webexport._umd_roster)가 2026-09-11 부터 싣는다. 이름과
   시군구 코드가 같은 줄을 찾는다. 없으면 '' (지오코더로 물러난다). */
async function findLdCode(sg, name) {
  const idx = (state.landPrice || {}).umd_roster || [];
  const c = idx.find((x) => String(x.p) === String(sg || '').slice(0, 2));
  if (!c) return '';
  if (!lpRosterCache[c.p]) {
    try {
      const r = await fetch(`/app/data/${c.f}`, { cache: 'no-cache' });
      if (r.ok) lpRosterCache[c.p] = await r.json();
    } catch (e) { /* 못 받으면 지오코더로 */ }
  }
  const rows = ((lpRosterCache[c.p] || {}).rows) || [];
  const hit = rows.find((row) => row[0] === name && String(row[1]) === String(sg))
    || rows.find((row) => row[0] === name);
  const ld = hit ? String(hit[6] || '') : '';
  return /^\d{10}$/.test(ld) ? ld : '';
}

/* 검색어를 주소로 푼다: 완성한 주소 글(text)과, PNU 를 만들 재료(색인에서
   찾은 읍·면·동 이름 name · 시군구 코드 sg · 지번). */
function findAddressParse(q, rows) {
  const jb = findJibun(q);
  const clean = q.replace(/\s+/g, ' ').trim();
  const words = clean.split(' ');
  const regions = state.regions || [];
  const out = { text: clean, name: '', sg: '', jibun: jb };
  const head = (jb ? jb.head : clean).split(' ').filter(Boolean);
  for (let n = Math.min(head.length, 2); n >= 1; n -= 1) {
    const name = head.slice(head.length - n).join(' ');
    const hit = (rows || []).find((r) => r.k === 'umd' && (r.n === name || r.n.endsWith(' ' + name)));
    if (hit) { out.name = hit.n; out.sg = String(hit.sg || ''); break; }
  }
  const hasSg = regions.find((r) => words.includes(r.name));
  if (hasSg) {
    const sd = hasSg.sido || '';
    out.text = sd && !words.includes(sd) ? `${sd} ${clean}` : clean;
    if (!out.sg) out.sg = String(hasSg.sigungu_cd || '');
  }
  return out;
}

function findAddressText(q, rows) {
  const clean = q.replace(/\s+/g, ' ').trim();
  const words = clean.split(' ');
  const regions = state.regions || [];
  const sidoOf = (sgName, code) => {
    const byName = regions.find((r) => r.name === sgName);
    if (byName && byName.sido) return byName.sido;
    const c = String(code || '');
    const byCode = regions.find((r) => String(r.sigungu_cd || '').slice(0, 2) === c.slice(0, 2));
    return (byCode && byCode.sido) || SIDO_BY_PREFIX[c.slice(0, 2)] || '';
  };
  // 이미 시·군·구가 들어 있나 (시·도도 함께면 그대로).
  const hasSg = regions.find((r) => words.includes(r.name));
  if (hasSg) {
    const sd = hasSg.sido || '';
    return sd && !clean.startsWith(sd) && !words.includes(sd) ? `${sd} ${clean}` : clean;
  }
  // 숫자 앞의 낱말들로 읍·면·동(·리) 을 찾는다 — 긴 것부터.
  const head = words.filter((w) => !/^(산\s?)?\d/.test(w) && !/^\d/.test(w));
  for (let n = Math.min(head.length, 2); n >= 1; n -= 1) {
    const name = head.slice(head.length - n).join(' ');
    const hit = (rows || []).find((r) => r.k === 'umd' && (r.n === name || r.n.endsWith(' ' + name)));
    if (hit && hit.p) {
      const sd = sidoOf(hit.p, hit.sg);
      // 색인의 이름('곤지암읍 건업리')이 친 것보다 길면 그것으로 갈아 끼운다.
      const rest = words.filter((w) => !head.slice(head.length - n).includes(w));
      return [sd, hit.p, hit.n].filter(Boolean).join(' ') + (rest.length ? ' ' + rest.join(' ') : '');
    }
  }
  return clean;
}

/* 주소 → 좌표 → 그 필지. 서버(api/tile mode=geocode)가 브이월드 지오코더를
   대신 부른다 (키가 페이지에 없다). 좌표가 오면 그 자리로 옮기고 지도를
   누른 것과 같은 길(askParcel)로 필지 윤곽과 카드를 연다. */
async function findGoAddress(row, list) {
  const tab = document.querySelector('.tab[data-view="explore"]');
  if (tab && !tab.classList.contains('is-active')) tab.click();
  if (list) {
    list.innerHTML = `<li class="find-none">주소를 찾는 중… <em>${escapeHtml(row.p)}</em></li>`;
    list.hidden = false;
  }
  let hit = null;
  let why = '';
  let via = 'geocode';
  // 1) 연속지적도 — 법정동코드 + 지번 → PNU. 건물 없는 땅도 찾는다.
  const ps = row.parsed || {};
  if (ps.jibun && ps.name && ps.sg) {
    try {
      const ld = await findLdCode(ps.sg, ps.name);
      if (ld) {
        const pnu = ld + (ps.jibun.san ? '2' : '1')
          + String(ps.jibun.bon).padStart(4, '0') + String(ps.jibun.bu).padStart(4, '0');
        const r = await fetch(`/api/tile?mode=pnu&pnu=${pnu}`);
        if (r.ok) { hit = await r.json(); via = 'pnu'; if (hit && hit.addr) hit.text = hit.addr; }
        else if (r.status === 429) why = '요청이 너무 잦습니다. 잠시 뒤 다시 해 주세요.';
        else if (r.status === 404) why = '그 지번의 필지가 연속지적도에 없습니다.';
      }
    } catch (err) { /* 지오코더로 */ }
  }
  // 2) 지오코더 — 명부에 없거나(코드 없음) 지적에 없으면 주소 DB 로.
  if (!hit && !/너무 잦습니다/.test(why)) {
    try {
      const r = await fetch(`/api/tile?mode=geocode&q=${encodeURIComponent(row.p)}`);
      if (r.status === 429) why = '요청이 너무 잦습니다. 잠시 뒤 다시 해 주세요.';
      else if (r.ok) { hit = await r.json(); via = 'geocode'; }
      else if (!why) why = ((await r.json().catch(() => ({}))).tileError) || '주소를 찾지 못했습니다.';
    } catch (err) {
      why = why || '서버에 닿지 못했습니다.';
    }
  }
  if (!hit || !Number.isFinite(Number(hit.lat)) || !Number.isFinite(Number(hit.lon))) {
    if (list) {
      list.innerHTML = `<li class="find-none">${escapeHtml(why || '주소를 찾지 못했습니다.')}`
        + ' <em>(예: 광주시 곤지암읍 건업리 140-25 — 시·군·읍·면·리와 지번을 함께)</em></li>';
      list.hidden = false;
    }
    window.__find = { went: null, level: 'addr', failed: why || true };
    return;
  }
  const lat = Number(hit.lat);
  const lon = Number(hit.lon);
  if (list) list.hidden = true;
  if (!map) return;
  map.setView([lat, lon], FIND_ZOOM.addr);
  setTimeout(() => map.invalidateSize(), 0);
  window.__find = { went: hit.text || row.p, level: 'addr', at: [lat, lon], via };
  // 지도를 누른 것과 같다 — 필지 윤곽 + 카드.
  askParcel({ lat, lng: lon });
}

function findGo(row, list) {
  if (row.k === 'addr') { findGoAddress(row, list); return; }
  // 검색칸이 머리띠로 올라가면서(2026-09-09) 다른 탭에서도 보인다.
  // 거기서 고르면 지도가 안 보이는 채로 움직인다 — 탭부터 옮긴다.
  const tab = document.querySelector('.tab[data-view="explore"]');
  if (tab && !tab.classList.contains('is-active')) tab.click();
  if (!map) return;
  map.setView([row.lat, row.lon], FIND_ZOOM[row.k] || 12);
  // 탭을 막 옮겼으면 지도가 방금 보이기 시작한 것이라 크기를 모른다.
  setTimeout(() => map.invalidateSize(), 0);
  window.__find = { went: row.n, level: row.k };
}

function wireFind() {
  const input = document.getElementById('find-q');
  const list = document.getElementById('find-list');
  if (!input || !list) return;
  let hits = [];
  let cur = -1;

  const close = () => {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    cur = -1;
  };
  const paint = () => {
    if (!hits.length) {
      list.innerHTML = '<li class="find-none">찾는 이름이 없습니다'
        + ' <em>(읍·면·동까지 찾고, 지번까지 적으면 그 필지로 갑니다 —'
        + ' 예: 곤지암읍 건업리 140-25)</em></li>';
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      return;
    }
    const kind = { sido: '시·도', sigungu: '시·군·구', umd: '읍·면·동', addr: '필지로 이동' };
    list.innerHTML = hits.map((r, i) =>
      `<li role="option" data-i="${i}"${i === cur ? ' class="is-on"' : ''}`
      + `${r.k === 'addr' ? ' data-k="addr"' : ''}`
      + ` aria-selected="${i === cur}">`
      + `<b>${escapeHtml(r.n)}</b>`
      + `<span>${escapeHtml(r.p || '')}</span>`
      + `<em>${kind[r.k] || ''}</em></li>`).join('');
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };

  const run = async () => {
    const q = input.value;
    if (!q.trim()) { close(); return; }
    const rows = await findLoad();
    hits = findMatch(rows, q);
    // 지번이 붙어 있으면 **필지로 가는 줄을 맨 위에** 둔다. 이름 후보는
    // 그 아래 — '건업리 140-25' 를 쳤는데 건업리 중심으로 가면 틀린 답이다.
    if (FIND_JIBUN_RE.test(q.trim())) {
      hits = [{ k: 'addr', n: q.trim(), p: findAddressText(q, rows),
                parsed: findAddressParse(q, rows) }].concat(hits);
    }
    cur = -1;
    paint();
  };

  input.addEventListener('input', run);
  input.addEventListener('focus', () => { if (input.value.trim()) run(); });
  input.addEventListener('keydown', (e) => {
    if (list.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      cur = Math.max(0, Math.min(hits.length - 1,
                                 cur + (e.key === 'ArrowDown' ? 1 : -1)));
      paint();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = hits[cur >= 0 ? cur : 0];
      if (pick) { input.blur(); if (pick.k !== 'addr') close(); findGo(pick, list); }
    } else if (e.key === 'Escape') {
      close();
    }
  });
  list.addEventListener('mousedown', (e) => {
    const li = e.target.closest('li[data-i]');
    if (!li) return;
    e.preventDefault();
    const pick = hits[Number(li.dataset.i)];
    input.blur();
    if (!pick || pick.k !== 'addr') close();   // 주소는 찾는 동안 목록에 진행을 보인다
    if (pick) findGo(pick, list);
  });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.map-find')) close();
  });
}

/* 지도 위 스위치 — IC·영업소 · 용도지역 · 필지경계. */
(function mapSwitches() {
  const zbox = document.getElementById('zoning-bg');
  if (zbox) {
    zbox.checked = state.zoning;
    zbox.addEventListener('change', () => toggleZoning(zbox.checked));
  }

  // 필지 경계선 (요구사항 2026-09-10). 기본 켬.
  const cbox = document.getElementById('cadastral-bg');
  if (cbox) {
    cbox.checked = state.cadastral;
    cbox.addEventListener('change', () => toggleCadastral(cbox.checked));
  }

  // IC·영업소도 끌 수 있다 (기본 꺼짐, 요구사항 2026-09-08).
  const gbox = document.getElementById('gate-bg');
  if (gbox) {
    gbox.checked = state.showGates;
    gbox.addEventListener('change', () => {
      state.showGates = gbox.checked;
      // 영업소를 끄면 선택도 풀어야 한다. 안 그러면 안 보이는 영업소의
      // 반경만 지도에 남아 '이게 뭔가' 가 된다.
      if (!state.showGates && state.selected) {
        state.selected = null;
        showDetail(false);
        if (bandLayer) bandLayer.clearLayers();
      }
      refreshMap();
    });
  }

})();

wireFind();

/* 머리띠의 Admin 링크 — 관리자에게만 보인다 (2026-09-12 지시).
   관문(gate.js)이 window.ME 를 세운 뒤 이 파일이 실행되므로 여기서 안다.
   링크를 보이는 것뿐이고, 자물쇠는 /admin 화면과 데이터베이스다. */
if (typeof window.tojiAdminNav === 'function') window.tojiAdminNav(myAccess().admin);

boot();

// 지도와 regions.json 이 다 준비된 뒤에 처음 한 번 붙는다. boot 안에서
// 부르면 state.regions 가 아직 비어 있어 아무 지역도 못 고른다.
setTimeout(viewersOnMove, 3000);


/* ══════════════════════════════════════════════════════════════════
   지역 태그 조회 배지 — 24시간 누적 'N명 조회 중', 그리고 화면 1등 별표

   요구사항(2026-09-09, 2차 → 2026-09-11 개정):
     "누적으로 조회하는 사람 수 실시간 추가 (XX명 조회 중) — 호갱노노처럼
      태그 아래에 조금 겹쳐서 따로 표시"
     "24시간 동안 보는 사람 누적 (1시간마다 옛 한 시간 누적을 삭제)"
     "화면에 보이는 지역 태그에서 24시간 누적 제일 많은 곳 별표 (10명 미만 제외)"

   그래서 **세는 단위가 태그 하나**다. 두계리와 두계리가 속한 계룡시는
   서로 다른 열쇠를 갖는다.

     u:41220:안중읍 청북리   읍·면·동 / 리
     g:41220                 시·군·구
     s:경기도                시·도

   ── 두 숫자는 성격이 다르다 ──────────────────────────────────

     지금 N   Realtime Presence. 창을 닫으면 곧 사라진다.
     오늘 M   place_view 표에 쌓인 값. 한국 날짜로 자정에 0으로 돌아간다
              (RPC 안에서 Asia/Seoul 로 끊는다).

   ── 채널은 태그마다 파지 않는다 ──────────────────────────────

   화면에 태그가 쉰 개인데 태그마다 채널을 열면 무료 요금제(동시접속
   200 · 메시지 월 200만)를 하루에 태운다. 그래서 **시·군·구 하나당
   채널 하나**를 열고, 거기에 '나는 지금 이 태그를 가운데 두고 있다' 는
   열쇠 하나만 싣는다. 같은 시·군·구를 보는 사람끼리는 서로의 열쇠가
   보이므로, 그것을 세면 태그별 '지금 N' 이 나온다.

   그래서 '보고 있다' 의 뜻은 **화면 한가운데 두었다** 이다. 눈에
   들어온 태그 전부가 아니다 — 그렇게 세면 한 사람이 한 번에 쉰 곳을
   보고 있는 것이 된다.

   ── 내보내는 것 ──────────────────────────────────────────────

   신원은 안 보낸다. 로그인해도 이름·아이디를 싣지 않고, 새로고침하면
   없어지는 임의의 글자를 열쇠로 쓴다. 지도 좌표도 안 보낸다 — 나가는
   것은 태그 열쇠와 시·군·구 코드뿐이다.                              */

const VIEW_MIN_ZOOM = 9;      // 전국을 보고 있으면 '이 지역' 이랄 것이 없다
const VIEW_DEBOUNCE = 1200;   // 지도를 끄는 동안 채널을 갈아치우지 않는다
const VIEW_MAX_KEYS = 200;    // RPC 가 받는 만큼만 (SQL 에서도 잘라 둔다)

const viewers = {
  sg: '',            // 지금 붙어 있는 시군구 채널
  pk: '',            // 내가 가운데 둔 태그
  ch: null,
  timer: 0,
  live: new Map(),   // 태그 열쇠 → 지금 보는 사람 수 (Presence)
  stat: new Map(),   // 태그 열쇠 → { n24 } 24시간 누적
  star: null,        // 화면에서 24시간 누적 1등인 태그 열쇠 (10명 미만이면 없음)
  asked: '',         // 마지막으로 통계를 물어본 열쇠 묶음
  seen: new Set(),   // 이번 방문에 이미 센 태그 (새로고침해야 다시 센다)
  sent: '',          // 마지막으로 채널에 실은 태그 (같으면 다시 안 싣는다)
  // 새로고침하면 바뀐다. 저장하지 않는다 — 저장하는 순간 그것이 신원이 된다.
  me: Math.random().toString(36).slice(2, 10),
};

/* 지역 단계 태그의 조회수 열쇠. 이름만으로는 안 된다 — '고성군' 은
   강원과 경남에 둘이고 '중구' 는 여섯이다. */
function placeKey(levelKey, member, name) {
  const cd = String((member || {}).sigungu_cd || '');
  if (levelKey === 'sido') return `s:${name}`;
  if (levelKey === 'si') return `g:${cd.slice(0, 2)}:${name}`;
  return `g:${cd}`;
}

/* 화면 한가운데가 어느 태그인가. 지금 그려져 있는 것 중에서 고른다 —
   태그가 없는 자리(바다·산)를 가운데 두면 아무 태그도 아니다. */
function viewerCenterTag(items) {
  if (!map || map.getZoom() < VIEW_MIN_ZOOM || !items.length) return null;
  const c = map.getCenter();
  let best = null;
  let bestD = Infinity;
  items.forEach((it) => {
    if (!it.pk || !it.at) return;
    // 위도 1도와 경도 1도의 길이가 달라서 경도를 cos 로 줄인다.
    const dy = it.at[0] - c.lat;
    const dx = (it.at[1] - c.lng) * Math.cos((c.lat * Math.PI) / 180);
    const d = dy * dy + dx * dx;
    if (d < bestD) { bestD = d; best = it; }
  });
  return best;
}

/* 태그 셋째 줄. 아무 숫자도 없으면 **줄 자체를 안 만든다** — 새로
   생긴 동네마다 '지금 0 / 오늘 0명' 이 붙으면 그것만 눈에 띈다. */
function viewerLine(pk) {
  // 요구사항(2026-09-11): "누적으로 조회하는 사람 수 실시간 추가 (XX명
  // 조회 중) — 호갱노노처럼 태그 아래에 조금 겹쳐서 따로 표시. 24시간
  // 동안 본 사람 누적 (1시간마다 옛 한 시간을 뺀다)".
  //
  // 그래서 숫자는 **24시간 굴림 누적**이다 (place_view 시간 칸의 합).
  // 사람 수에 가깝게 하려고 한 방문에서 태그 하나는 한 번만 센다
  // (viewersBump 의 seen). '실시간' 은 Presence 가 맡는다 — 같은 시·군을
  // 보는 누군가가 태그를 가운데 두면 sync 가 오고, 그때 통계를 다시
  // 묻는다 (viewersChannel). 0 이면 배지 자체를 안 만든다.
  const n = (viewers.stat.get(pk) || {}).n24 || 0;
  if (!n) return '';
  return `<s>${n}명 조회 중</s>`;
}

/* 별표 — **화면에 보이는 태그 중** 24시간 누적 1등, 단 10명 미만이면
   없음 (요구사항 2026-09-11). 하나뿐이다. */
function viewerStar(it) {
  return viewers.star && viewers.star === it.pk ? '<mark>★</mark>' : '';
}

/* 지도가 멎으면 그때. 끄는 동안 채널을 갈아치우면 지나온 시군구마다
   접속을 한 번씩 열게 된다. */
function viewersOnMove(items) {
  if (!window.SB) return;
  if (items) viewers.items = items;
  const list = viewers.items || [];
  const tag = viewerCenterTag(list);
  // **같은 화면이면 다시 부르지 않는다.** 이 함수를 부르는 것이
  // drawLandPrice 인데 viewersSync 가 끝나면 다시 drawLandPrice 를
  // 부른다 — 지문으로 끊지 않으면 1.2초마다 영원히 돈다.
  const sig = (tag ? tag.pk : '') + '\u0000'
    + list.map((x) => x.pk).filter(Boolean)
        .slice(0, VIEW_MAX_KEYS).sort().join('\n');
  if (sig === viewers.sig) return;
  viewers.sig = sig;
  clearTimeout(viewers.timer);
  viewers.timer = setTimeout(viewersSync, VIEW_DEBOUNCE);
}

async function viewersSync() {
  const items = viewers.items || [];
  const tag = viewerCenterTag(items);
  const sg = tag ? String(tag.sg || '') : '';
  const pk = tag ? String(tag.pk || '') : '';

  // 보이는 태그의 오늘·이번 주를 **한 번에** 묻는다. 태그마다 물으면
  // 지도를 한 번 끌 때마다 쉰 번을 부른다.
  const keys = items.map((x) => x.pk).filter(Boolean).slice(0, VIEW_MAX_KEYS);
  await viewersStats(keys);

  if (pk && pk !== viewers.pk) {
    viewers.pk = pk;
    viewersBump(pk);
  }
  if (sg !== viewers.sg) await viewersChannel(sg);
  else if (viewers.ch) viewersTrack();
  drawLandPrice();
}

/* 채널을 옮긴다. 전에 보던 곳에서 손을 떼지 않으면 그 지역의 '지금 N'
   에 내가 계속 남아, 아무도 안 보는 곳이 붐비는 곳으로 보인다. */
async function viewersChannel(sg) {
  // **먼저 자리를 차지하고 나서 기다린다.** 아래를 기다리는 동안 다시
  // 불리면 같은 지역에 채널을 두 번 붙인다.
  viewers.sg = sg;
  viewers.live = new Map();
  // 새 채널은 내가 어디 있는지 모른다. 태그가 그대로여도 다시 싣는다.
  viewers.sent = '';
  if (viewers.ch) {
    const gone = viewers.ch;
    viewers.ch = null;
    try { await window.SB.removeChannel(gone); } catch { /* 이미 끊김 */ }
  }
  if (!sg || viewers.sg !== sg) return;

  const ch = window.SB.channel(`view:${sg}`, {
    config: { presence: { key: viewers.me } },
  });
  ch.on('presence', { event: 'sync' }, () => {
    if (viewers.ch !== ch) return;             // 이미 다른 지역으로 옮겼다
    const live = new Map();
    Object.values(ch.presenceState() || {}).forEach((metas) => {
      const m = (metas || [])[0] || {};
      if (m.p) live.set(m.p, (live.get(m.p) || 0) + 1);
    });
    viewers.live = live;
    // 누군가 새로 왔다 — 24시간 누적이 바뀌었을 수 있다. 다시 묻는다
    // ('실시간'). 같은 화면 지문은 viewersStats 가 걸러 주므로 asked 를 비운다.
    viewers.asked = '';
    viewersStats((viewers.items || []).map((x) => x.pk).filter(Boolean).slice(0, VIEW_MAX_KEYS))
      .then(() => { if (viewers.ch === ch) drawLandPrice(); });
    drawLandPrice();
  });
  // **subscribe 보다 먼저 세워 둔다.** 붙었다는 신호가 곧바로 오면
  // (검사의 가짜 클라이언트가 그렇다) 아래 대입이 아직 안 돼 있어
  // viewersTrack 이 조용히 아무것도 안 한다.
  viewers.ch = ch;
  ch.subscribe((status) => {
    if (status === 'SUBSCRIBED' && viewers.ch === ch) viewersTrack();
  });
}

/* 내가 가운데 둔 태그 하나만 싣는다. 신원도 좌표도 안 보낸다.

   **바뀌었을 때만 싣는다.** 무료 요금제의 급소는 월 200만 메시지가
   아니라 **Presence 초당 20**이다(supabase.com/docs/guides/realtime/limits).
   내가 한 번 실으면 그 시·군을 보는 **모든** 사람에게 갱신이 가므로,
   같은 시·군에 네댓 명만 모여 함께 지도를 끌어도 초당 20에 닿는다.

   그런데 지도를 조금만 끌어도 보이는 태그 목록이 바뀌어 이 함수가
   불렸다 — 가운데 둔 태그는 그대로인데 같은 값을 다시 실었다. 그
   메시지는 아무것도 안 바꾸면서 한도만 먹는다. */
function viewersTrack() {
  if (!viewers.ch || !viewers.pk) return;
  if (viewers.sent === viewers.pk) return;
  viewers.sent = viewers.pk;
  try { viewers.ch.track({ p: viewers.pk }); } catch { /* 아직 안 붙었다 */ }
}

/* 오늘 조회수를 올린다. 이번 방문에 처음 가운데 둔 태그만 — 지도를
   앞뒤로 흔들 때마다 세면 혼자서 백 명이 된다. */
async function viewersBump(pk) {
  if (viewers.seen.has(pk)) return;
  viewers.seen.add(pk);
  try {
    const { data, error } = await window.SB.rpc('bump_place_view', { k: pk });
    if (error) throw error;
    // 되돌아온 값이 이 태그의 **24시간 누적**이다.
    const st = viewers.stat.get(pk) || { n24: 0 };
    viewers.stat.set(pk, { n24: Number(data) || st.n24 + 1 });
    viewersRankStars();
    drawLandPrice();
  } catch (err) {
    // 조회수를 못 세는 것으로 지도를 세우지 않는다. 숫자만 안 나온다.
  }
}

async function viewersStats(keys) {
  if (!keys.length) return;
  const sig = keys.slice().sort().join('\n');
  if (sig === viewers.asked) return;           // 같은 화면을 또 묻지 않는다
  viewers.asked = sig;
  try {
    const { data, error } = await window.SB
      .rpc('place_view_stats', { keys });
    if (error) throw error;
    // **화면에 있는 열쇠만 지우고 다시 채운다.** 통째로 비우면 방금
    // 올린 내 숫자가 사라졌다 되살아나 깜빡인다.
    (data || []).forEach((r) => viewers.stat.set(String(r.place_key),
      { n24: Number(r.n24) || 0 }));
    keys.forEach((k) => {
      if (!(data || []).some((r) => String(r.place_key) === k)
          && !viewers.seen.has(k)) viewers.stat.delete(k);
    });
    viewersRankStars();
  } catch (err) {
    /* 못 읽으면 숫자만 안 나온다 */
  }
}

/* 화면에 보이는 태그 중 24시간 누적 1등에 별 하나. **10명 미만이면 별이
   없다** (요구사항 2026-09-11) — 셋이 본 시골 면에 별이 붙으면 별의 뜻이
   사라진다. */
const VIEW_STAR_MIN = 10;
function viewersRankStars() {
  let best = null;
  (viewers.items || []).forEach((it) => {
    if (!it.pk) return;
    const n = (viewers.stat.get(it.pk) || {}).n24 || 0;
    if (n < VIEW_STAR_MIN) return;
    if (!best || n > best.n) best = { n, pk: it.pk };
  });
  viewers.star = best ? best.pk : null;
}
