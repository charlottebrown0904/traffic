/* N0067 */
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
  // N0068
  placeTags: true,
  zoning: false,
  // N0069
  develop: false,
  /* N0070 */
  devParts: { industry: false, housing: false, planroad: false, rail: false,
              highway: false },
  /* N0071 */
  devPick: {
    industry: { 국가: true, 일반: true, 첨단: true, 농공: true },
    housing: { 지구지정: true, 개발계획: true, 실시계획: true,
               부분준공: true, 준공: false },
    planroad: { 미집행: true, 부분집행: true, 집행완료: false },
    rail: { 많이: true, 적게: true, 모름: true },
    highway: { 계획: true, 공사중: true, 준공: false },
  },
  // N0072
  cadastral: (() => {
    try { return localStorage.getItem('toji.cadastral') !== 'off'; }
    catch (e) { return true; }
  })(),
  tgYear: null,
  // N0073
  tgVehicles: new Set([1, 2, 3, 4, 5, 6]),
  dealYear: 'all', tradeCache: {}, tradesShown: null,
  activeStages: new Set(), activeLandUse: new Set(),
  hasStageFilter: false, hasLandUseFilter: false,
  activeKinds: new Set(),
  selected: null, tiers: null,
  token: null, broker: null, listings: [], scope: 'public', pickMode: false,
  apiAvailable: false, verdicts: null,
  verdictSets: {}, verdictKind: 'land',
  // N0074
  regions: null, popYear: null, showGates: false,
  // 거래 연도 범위 (좌/우 손잡이). yearWide 면 전 기간 표본으로 물러난 것이다.
  yearFrom: null, yearTo: null, yearWide: false,
  // N0075
  landPrice: null, lpStat: 'p50', lpWindow: '',
  // N0076
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
let developLayer, railLayer, roadLayer, adminLayer;
/* 고른 필지의 윤곽. 한 번에 하나만 그린다. */
let parcelLayer = null;
/* N0077 */
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
/* N0078 */
const BAND_COLORS = 5;
const bandColor = (i) => `var(--band-${(i % BAND_COLORS) + 1})`;

/* N0079 */
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
/* N0080 */
/* N0081 */
const DATA_BUCKET = 'https://caykbxvnebpifcduqjre.supabase.co/storage/v1/object/public/appdata';
const DATA_LOCAL = '/app/data';

function dataUrl(name) {
  return `${DATA_BUCKET}/${name}`;
}

/* N0082 */
async function fetchData(name, opts) {
  try {
    const r = await fetch(`${DATA_BUCKET}/${name}`, opts);
    if (r.ok) return r;
  } catch (e) { /* 아래에서 배포 쪽으로 */ }
  return fetch(`${DATA_LOCAL}/${name}`, opts);
}

async function boot() {
  // N0083
  wireTabs();
  wireWhy();
  wireSheet();
  try {
    const [meta, tollgates, trades, series] = await Promise.all(
      ['meta', 'tollgates', 'trades', 'series'].map((n) =>
        fetchData(`${n}.json`).then((r) => {
          if (!r.ok) throw new Error(`data/${n}.json 을 읽지 못했습니다 (${r.status})`);
          return r.json();
        }))
    );
    Object.assign(state, { meta, tollgates, trades, series });
  } catch (err) {
    showFatal(err.message);
    return;
  }

  // N0084
  state.activeKinds = new Set();
  state.tradesShown = state.trades;

  if (state.meta.is_synthetic) $('#demo-banner').hidden = false;
  $('#disclaimer').textContent = state.meta.disclaimer;

  if (CONFIG.homeUrl) {
    const home = $('#home-link');
    home.href = CONFIG.homeUrl;
    home.hidden = false;
  }

  // 순위 탭 자료는 없어도 나머지 화면은 살아야 한다. 실패하면 그 탭만 끈다.
  try {
    const r = await fetchData('traffic.json');
    if (r.ok) state.traffic = await r.json();
  } catch (err) {
    state.traffic = null;
  }
  try {
    const r = await fetchData('chart.json');
    if (r.ok) state.chart = await r.json();
  } catch (err) {
    state.chart = null;
  }
  // 행정구역. 인구와 관청 좌표가 여기서 온다.
  try {
    const r = await fetchData('regions.json');
    if (r.ok) state.regions = await r.json();
  } catch (err) {
    state.regions = null;
  }
  // 행정구역별·연도별 땅값. 없으면 그 테마 막대만 숨긴다.
  try {
    const r = await fetchData('landprice.json');
    if (r.ok) state.landPrice = await r.json();
  } catch (err) {
    state.landPrice = null;
  }
  // 철도 — '개발' 층의 한 갈래. 없으면 그 칸만 아무것도 안 그린다.
  try {
    const r = await fetchData('rail.json');
    if (r.ok) state.rail = await r.json();
  } catch (err) {
    state.rail = null;
  }
  // N0085
  try {
    const r = await fetchData('road.json');
    if (r.ok) state.road = await r.json();
  } catch (err) {
    state.road = null;
  }
  // N0086
  state.verdictSets = {};
  await Promise.all([['land', 'verdicts'], ['factory', 'verdicts_factory']]
    .map(async ([k, name]) => {
      try {
        const r = await fetchData(`${name}.json`);
        if (r.ok) state.verdictSets[k] = await r.json();
      } catch (err) { /* 없으면 그 종류만 안 보인다 */ }
    }));
  state.verdictKind = state.verdictSets.land ? 'land' : 'factory';
  state.verdicts = state.verdictSets[state.verdictKind] || null;

  // N0087
  const _ty = (state.traffic || {}).years || [];
  state.tgYear = _ty.length ? _ty[_ty.length - 1] : null;
  state.tiers = buildTiers();

  // N0088
  window.__bands = state.meta.bands_km || [];

  buildFilters();
  // N0089
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

/* N0090 */
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

/* N0091 */
const SHEET_TITLE = {
  trade: '실거래 표시', ic: 'IC', price: '지역별 가격', develop: '개발',
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
    closeSheet();
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
  // N0092
  if (map) setTimeout(() => map.invalidateSize(), 220);
}

/* N0093 */
function closeSheet() {
  const sheet = document.getElementById('sheet');
  if (sheet) { sheet.hidden = true; sheet.dataset.cat = ''; }
  const side = document.getElementById('side');
  if (side) side.classList.remove('is-open');
  document.querySelectorAll('.cat').forEach((b) => b.classList.remove('is-on'));
  if (map) setTimeout(() => map.invalidateSize(), 220);
}

/** 지금 왼쪽 칸에 펼쳐진 갈래. 안 열렸으면 빈 글자. */
function openSheetCat() {
  const sheet = document.getElementById('sheet');
  return sheet && !sheet.hidden ? (sheet.dataset.cat || '') : '';
}

function wireSheet() {
  document.querySelectorAll('.cat').forEach((b) => {
    b.addEventListener('click', () => openSheet(b.dataset.cat));
  });
  const close = document.getElementById('sheet-close');
  if (close) close.addEventListener('click', closeSheet);
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

/* N0094 */
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

  // N0095
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

  // N0096
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
  // N0097
  const mix = state.meta.usage_mix || {};
  const options = [];
  (state.meta.kinds || []).forEach((kind) => {
    if (kind !== 'factory') {
      options.push({ key: kind, label: KIND_LABEL[kind] || kind });
      return;
    }
    // N0098
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

  // N0099
  state.hasStageFilter = false;

  // N0100

  // N0101
  state.hasLandUseFilter = false;
  state.activeLandUse.clear();
  // N0102

  // N0103
  const dealYears = (state.meta.trade_years || []).map((r) => r.year);
  if (dealYears.length) {
    const from = $('#year-from');
    const to = $('#year-to');
    const lo = dealYears[0];
    const hi = dealYears[dealYears.length - 1];
    [from, to].forEach((el) => { el.min = String(lo); el.max = String(hi); el.step = '1'; });
    // N0104
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
      // N0105
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

  // N0106

  // 처음 그릴 때도 개수를 채운다. 안 하면 전부 0 으로 보인다.
  updateTierCounts();
}

/* N0107 */
function buildLegend() {
  const box = $('#band-legend');
  if (!box) return;
  box.innerHTML = shownBands()
    .map(([lo, hi], i) =>
      `<div class="row" style="--c:${bandColor(i)}">` +
      `<span class="ring"></span>${lo}–${hi} km</div>`)
    .join('');
}

/* N0108 */

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

/* N0109 */
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

/* N0110 */
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

/* N0111 */
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

/* N0112 */
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
  // N0113
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

/* N0114 */
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

/* N0115 */
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
      // N0116
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
    /* N0117 */
    return `<tr>
      <td class="rank">${i + 1}</td>
      <td class="who"><span class="nm">${escapeHtml(r.name)}</span><span class="sub">${region}</span></td>
      <td class="reg">${region}</td>
      <td class="num bar"><span style="width:${width}%"></span><b>${num(r.value)}</b></td>
      <td class="act">${trendBtn}</td>
      <td class="num">${yoyBars(r.yoy)}</td>
      <td class="num">${r.share == null ? '—' : (r.share * 100).toFixed(1) + '%'}</td>
    </tr>`;
  }).join('');

  // N0118
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

/* N0119 */

const TREND_KIND_LABEL = { land: '토지', factory: '공장·창고' };

function trendDisabled(message) {
  const tab = document.querySelector('.tab[data-view="trend"]');
  if (tab) tab.hidden = true;
  const note = $('#trend-note');
  if (note) note.textContent = message;
}

/* N0120 */
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
    // N0121
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

// N0122
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

/* N0123 */
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

/* N0124 */
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

  // N0125
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
/* N0126 */
/* N0127 */
const TRAFFIC_CUTS = [10000, 20000, 30000];
const TRAFFIC_TIERS = TRAFFIC_CUTS.length + 1;

/* N0128 */
function niceStep(v) {
  // N0129
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
  // N0130
  const step = niceStep(max / 4);
  if (step * 3 >= TRAFFIC_CUTS[2]) return TRAFFIC_CUTS;
  return [step, step * 2, step * 3];
}

/* N0131 */
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

/* N0132 */
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

/* N0133 */
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
  // N0134
  (state.tollgates || []).forEach((t) => {
    if (t.no_traffic) tier.set(String(t.tollgate_id), 'none');
  });
  return { rank: tier, vol, cut: cuts, fresh };
}

/* N0135 */
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
  // N0136
  drawLandPrice();
  buildLegend();
}

function updateTierCounts() {
  const counts = {};
  (state.tiers ? state.tiers.rank : new Map()).forEach((q) => {
    counts[q] = (counts[q] || 0) + 1;
  });
  // N0137
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

/* N0138 */
const MAP_MIN_ZOOM = 7;
const MAP_MAX_ZOOM = 19;

/* N0139 */
const LABEL_ZOOM = 10;

/* N0140 */
const shownBands = () => (state.meta.bands_km || []).slice(0, -1);      // 이 배율부터 이름을 띄운다

function styleTollgate(marker, t, tier, vol) {
  const known = tier !== undefined && tier !== null;
  const isNew = tier === 'new';
  const isNone = tier === 'none';
  const q = (isNew || isNone) ? 0 : tier;
  marker.setStyle({
    // N0141
    radius: isNew ? 7 : isNone ? 4.5 : (known ? 4.5 + q * 1.4 : 3.5),
    // N0142
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
  // N0143
  /* N0144 */
  map = L.map('map', { zoomControl: false, preferCanvas: false,
                       minZoom: MAP_MIN_ZOOM, maxZoom: MAP_MAX_ZOOM })
    .setView([36.5, 127.8], MAP_MIN_ZOOM);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  // N0145
  try { addZoomReadout(); } catch (e) { /* 눈금은 없어도 지도는 돈다 */ }
  // N0146
  const holder = map.getContainer();
  const clearDrag = () => { lpDragged = false; };
  ['pointerdown', 'mousedown', 'touchstart'].forEach((ev) => {
    try { holder.addEventListener(ev, clearDrag, { capture: true, passive: true }); }
    catch (e) { holder.addEventListener(ev, clearDrag, true); }
  });
  map.on('dragstart', () => { lpDragged = true; });

  map.on('moveend', () => {
    drawTrades();
    // N0147
    drawCadastral();
    // N0148
    if (lpOpenPk != null) return;
    drawLandPrice();
  });
  // 닫으면 그때 다시 그린다 — 열려 있는 동안 밀린 갱신을 여기서 갚는다.
  map.on('moveend', () => { if (state.develop) drawDevVec(); });
  // 고속도로 필지는 칸 단위라 움직일 때마다 다시 고른다.
  map.on('moveend', drawRoadParcels);
  map.on('zoomend', () => { drawRoad(); drawRoadParcels(); });
  map.on('popupclose', (e) => {
    const cls = ((e.popup || {}).options || {}).className;
    if (cls !== 'lp-pop') return;
    lpOpenPk = null;
    // N0149
    clearAdminShape();
    // N0150
    if (!lpDrawing) drawLandPrice();
  });
  // N0151
  map.on('zoomend', () => {
    if (state.develop) drawDevVec();
    drawLandPrice();
    // N0152
    if (state.meta) buildLegend();
  });
  // N0153
  map.createPane('tradePane').style.zIndex = 380;
  // N0154
  addZoningLayer();

  // N0155
  map.createPane('cadastralPane').style.zIndex = 250;
  addCadastralLayer();

  // N0156
  map.createPane('parcelPane').style.zIndex = 370;
  parcelLayer = L.layerGroup().addTo(map);

  // 땅값 분위지도. 배경 타일(200)보다 위, 거래(380)보다 아래.
  map.createPane('lpPane').style.zIndex = 375;
  lpLayer = L.layerGroup().addTo(map);
  addDevelopLayer();
  addAdminLayer();
  bandLayer = L.layerGroup().addTo(map);
  tradeLayer = L.layerGroup().addTo(map);
  tollgateLayer = L.layerGroup().addTo(map);

  // N0157
  const { rank, vol } = state.tiers || buildTiers();
  withCoords.forEach((t) => {
    const marker = L.circleMarker([t.lat, t.lon], { radius: 5, weight: 1.6 });
    styleTollgate(marker, t, rank.get(String(t.tollgate_id)),
                  vol.get(String(t.tollgate_id)));
    marker.on('click', () => selectTollgate(t.tollgate_id));
    markers.set(t.tollgate_id, marker);
  });

  // N0158
  map.on('zoomend', syncTollgateLabels);

  map.on('click', (e) => {
    if (state.pickMode) { endPick(e.latlng); return; }
    // N0159
    const t = e.originalEvent && e.originalEvent.target;
    if (t && t.closest && t.closest('.leaflet-interactive')) return;
    // N0160
    if (map.getZoom() >= ZONING_MIN_ZOOM) askParcel(e.latlng);
    else if (state.zoning) askZoning(e.latlng);
  });

  if (withCoords.length) {
    map.fitBounds(L.latLngBounds(withCoords.map((t) => [t.lat, t.lon])).pad(0.15));
  }
  refreshMap();
}

/* N0161 */
function bandRing(lat, lon, hi, i, isControl, faint) {
  const color = cssVar(`--band-${(i % BAND_COLORS) + 1}`);
  return L.circle([lat, lon], {
    radius: hi * 1000,
    color,
    weight: faint ? 1.2 : (isControl ? 2 : 2.5),
    opacity: faint ? .55 : (isControl ? .85 : 1),
    // N0162
    dashArray: isControl ? '2 8' : '7 5',
    // N0163
    fill: false,
    // N0164
    interactive: false,
  });
}


/* N0165 */
/* N0166 */
const MAX_YEAR_FILES = 5;

async function loadTradeYear(year) {
  if (year === 'all') { state.tradesShown = state.trades; return; }
  if (state.tradeCache[year]) { state.tradesShown = state.tradeCache[year]; return; }
  try {
    const r = await fetchData(`trades-${year}.json`);
    if (!r.ok) throw new Error(String(r.status));
    state.tradeCache[year] = await r.json();
  } catch (err) {
    state.tradeCache[year] = [];
  }
  state.tradesShown = state.tradeCache[year];
}

/* N0167 */
async function loadTradeYears(from, to) {
  const years = [];
  for (let y = from; y <= to; y += 1) years.push(y);
  state.yearWide = years.length > MAX_YEAR_FILES;
  if (state.yearWide) {
    // N0168
    state.tradesShown = state.trades.filter(
      (t) => t.deal_year >= from && t.deal_year <= to);
    return;
  }
  await Promise.all(years.map((y) => loadTradeYear(y)));
  const out = [];
  years.forEach((y) => { (state.tradeCache[y] || []).forEach((t) => out.push(t)); });
  state.tradesShown = out;
}

/* N0169 */
function tradeMinZoomNow() {
  return state.yearWide ? TRADE_LABEL_ZOOM : TRADE_MIN_ZOOM;
}

/* N0170 */
function updateYearNote() {
  const node = document.getElementById('deal-year-note');
  if (!node) return;
  const n = (v) => v.toLocaleString('ko-KR');
  // N0171
  if (!state.activeKinds.size) {
    node.innerHTML = '실거래가 <strong>꺼져 있습니다</strong> — 바로 위 '
      + '<strong>물건 종류</strong>에서 토지·공장을 켜면 지도에 찍힙니다.'
      + ' <em>(처음에는 꺼 둡니다 — 거래 점이 첫 화면을 덮지 않도록)</em>';
    return;
  }
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
  // N0172
  if (state.yearWide) {
    text += ` <em>(${MAX_YEAR_FILES}년이 넘어 전 기간 표본에서 골랐습니다 —`
      + ` 좁히면 그 해 자료를 통째로 받습니다)</em>`;
  }
  // N0173
  if (map && map.getZoom() < TRADE_MIN_ZOOM) {
    node.innerHTML = text
      + ' · <em>실거래는 더 당겨야 나옵니다 — 지금 배율에서는 점 하나가'
      + ' 수 km 를 가리켜 어느 땅인지 짚을 수 없습니다. 그 대신 읍·면·동'
      + ' 땅값을 색으로 보여주고 있습니다.</em>';
    return;
  }
  // N0174
  if (state.yearWide && map && map.getZoom() < TRADE_LABEL_ZOOM) {
    node.innerHTML = text
      + ' · <em>선택한 기간이 넓어 전 기간 표본으로 보여드리는 중입니다 —'
      + ' 이 표본은 <strong>더 당겨야</strong> 나타납니다 (필지 구획이'
      + ' 보이는 배율부터). 기간을 5년 이내로 좁히면 지금 배율에서도'
      + ' 바로 보입니다.</em>';
    return;
  }
  // 화면에 실제로 몇 개가 그려졌는지. 잘렸으면 반드시 말한다.
  if (typeof state.tradeInView === 'number') {
    text += ` · 지금 보이는 영역 ${n(state.tradeInView)}건`;
    if (state.tradeDrawn < state.tradeInView) {
      // N0175
      text += state.tradeLabelled
        ? ` <em>(핀은 겹치지 않게 ${n(state.tradeDrawn)}건만 —`
          + ' 최근 거래부터입니다)</em>'
        : ` <em>(그중 ${n(state.tradeDrawn)}건만 표시 — 확대하면 다 보입니다)</em>`;
    }
    if (!state.tradeLabelled) {
      text += ' <em>(필지 경계가 보이는 배율까지 당기면 핀에 값이'
        + ' 적힙니다)</em>';
    }
  }
  node.innerHTML = text + '.';
}

/* N0176 */
function tradeFilterKey(t) {
  if (t.kind !== 'factory') return t.kind;
  return `factory:${t.usage || '구분 없음'}`;
}

function visibleTrades() {
  const rows = state.tradesShown || state.trades || [];
  // 연도는 파일을 고를 때 이미 갈렸다. 여기서 또 자르지 않는다.
  return rows.filter((t) => {
    if (!state.activeKinds.has(tradeFilterKey(t))) return false;
    // N0177
    if (t.geocode_level !== 'parcel') return false;
    // N0178
    if (t.kind === 'land') {
      if (state.hasStageFilter
          && !state.activeStages.has(t.stage || '지목 미상')) return false;
      if (state.hasLandUseFilter
          && !state.activeLandUse.has(t.land_use || '용도 미상')) return false;
    }
    return true;
  });
}

/* N0179 */
const TRADE_MIN_ZOOM = 14;
/* N0180 */
const TRADE_DRAW_CAP = 3000;

function drawTrades() {
  if (!map || !tradeLayer) return;
  tradeLayer.clearLayers();
  // N0181
  if (map.getZoom() < tradeMinZoomNow()) {
    state.tradeInView = null;
    state.tradeDrawn = 0;
    state.tradeLabelled = false;
    window.__tradeStyles = [];
    window.__pins = { kind: state.pinKind, labelled: false, drawn: 0,
                      inView: null, belowMinZoom: true };
    // N0182
    updateYearNote();
    return;
  }
  const rows = visibleTrades();
  const bounds = map.getBounds();
  const inView = rows.filter((t) => bounds.contains([t.lat, t.lon]));
  // N0183
  state.tradeInView = inView.length;
  // N0184
  const labelled = map.getZoom() >= TRADE_LABEL_ZOOM;
  let rowsToDraw = inView;
  if (labelled && inView.length > TRADE_LABEL_CAP) {
    // N0185
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
  // N0186
  window.__tradeStyles = tradeLayer.getLayers
    ? tradeLayer.getLayers().map((l) => ({
        kind: l.options.kind,
        geocodeLevel: l.options.geocodeLevel,
        // N0187
        pane: l.options.pane,
        // N0188
        html: (l.options.icon && l.options.icon.options
               && l.options.icon.options.html) || '',
        // N0189
        interactive: l.options.interactive === true,
        // N0190
        at: (l.getLatLng && l.getLatLng()) ? [l.getLatLng().lat, l.getLatLng().lng]
          : (Array.isArray(l.__latlng) ? l.__latlng : null),
        srcAt: l.options.srcAt || null,
        popup: (l.getPopup && l.getPopup() && l.getPopup().getContent
                && l.getPopup().getContent()) || l.__popupHtml || '',
      }))
    : undefined;
  window.__pins = { kind: state.pinKind, labelled, drawn: state.tradeDrawn,
                    inView: state.tradeInView };
  updateYearNote();
}

function refreshMap() {
  // N0191
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
    // N0192
    if (tier === undefined || state.activeTiers.has(tier)) {
      tollgateLayer.addLayer(marker);
    }
  });
  syncTollgateLabels();

  drawTrades();
  // N0193
}

/* N0194 */
const ZONING_MIN_ZOOM = 12;
// N0195
const CADASTRAL_MIN_ZOOM = 16;

/* N0196 */
/* N0197 */
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
  /* N0198 */
  { key: 'hybrid', label: '위성+지명',
    url: vworldTileUrl('satellite'),
    overlay: vworldTileUrl('hybrid'),
    attribution: '위성영상·지명 © 국토교통부 브이월드' },
  { key: 'midnight', label: '야간',
    url: vworldTileUrl('midnight'),
    attribution: '배경지도 © 국토교통부 브이월드' },
];

/* N0199 */
const TILE_OPTS = { updateWhenZooming: false, updateWhenIdle: true, keepBuffer: 4 };

let baseLayer = null;
let baseOverlay = null;         // 위성 위에 얹는 지명·경계 (hybrid)

function setBaseMap(key, first) {
  const spec = BASEMAPS.find((b) => b.key === key) || BASEMAPS[0];
  state.baseMap = spec.key;
  if (map) {
    if (baseLayer) map.removeLayer(baseLayer);
    if (baseOverlay) { map.removeLayer(baseOverlay); baseOverlay = null; }
    baseLayer = L.tileLayer(spec.url, {
      maxZoom: 19, attribution: spec.attribution,
      // OSM 은 남의 서버라 그대로 두고, 브이월드는 우리 함수를 아낀다.
      ...(spec.key === 'osm' ? {} : TILE_OPTS),
    }).addTo(map);
    // N0200
    if (baseLayer.bringToBack) baseLayer.bringToBack();
    // N0201
    if (spec.overlay) {
      baseOverlay = L.tileLayer(spec.overlay, {
        maxZoom: 19, ...TILE_OPTS,
      }).addTo(map);
      if (baseOverlay.bringToBack) baseOverlay.bringToBack();
      if (baseLayer.bringToBack) baseLayer.bringToBack();
    }
  }
  // N0202
  document.body.dataset.basemap = spec.key;
  document.querySelectorAll('#basemap-pick button').forEach((b) => {
    b.classList.toggle('is-on', b.dataset.key === spec.key);
    b.setAttribute('aria-pressed', String(b.dataset.key === spec.key));
  });
  // N0203
  if (!first) { try { localStorage.setItem('toji.basemap', spec.key); } catch (e) { /* 무시 */ } }
  window.__basemap = spec.key;
  window.__baseOverlay = spec.overlay || null;
}

/* N0204 */
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
    // N0205
    let pushed = false;
    const paint = (on) => {
      document.body.classList.toggle('is-mapmax', on);
      full.setAttribute('aria-pressed', on ? 'true' : 'false');
      full.title = on ? '원래대로' : '지도만 보기';
      full.textContent = on ? '✕' : '⛶';
      // N0206
      if (map) setTimeout(() => map.invalidateSize(), 60);
    };
    // N0207
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
  // N0208
  L.tileLayer('/api/tile?layer=zoning&z={z}&y={y}&x={x}', {
    ...TILE_OPTS,
    maxZoom: 19,
    minZoom: ZONING_MIN_ZOOM,
    // N0209
    opacity: .42,
    attribution: '용도지역 © 국토교통부 브이월드',
  }).addTo(zoningLayer);
  // **필지 경계선은 여기 없다.** addCadastralLayer 가 따로 깐다.
  if (state.zoning) zoningLayer.addTo(map);
}

/* N0210 */
const cadTiles = new Map();      // 'z/x/y' → L.GeoJSON (그린 것)
const cadAsked = new Set();      // 부르는 중인 칸
const cadFailed = new Map();     // 'z/x/y' → 실패 시각. 잠시 뒤 다시 묻는다.
const CAD_RETRY_MS = 30_000;
// N0211
const CAD_MAX_TILES = 12;
// N0212
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
  // N0213
  if ((x2 - x1 + 1) * (y2 - y1 + 1) > CAD_MAX_VIEW) return [];
  const out = [];
  for (let x = x1; x <= x2; x += 1) {
    for (let y = y1; y <= y2; y += 1) {
      if (x < 0 || y < 0 || x >= n || y >= n) continue;
      out.push([z, x, y]);
    }
  }
  // N0214
  const cx = (x1 + x2) / 2; const cy = (y1 + y2) / 2;
  out.sort((a, b) => (Math.abs(a[1] - cx) + Math.abs(a[2] - cy))
                   - (Math.abs(b[1] - cx) + Math.abs(b[2] - cy)));
  return out;
}

function drawCadastral() {
  if (!map || !cadastralLayer) return;
  // N0215
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

// N0216
let cadPausedUntil = 0;
let cadResumeTimer = null;

function fetchCadTile(z, x, y, key) {
  if (Date.now() < cadPausedUntil) {
    // N0217
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
          // N0218
          interactive: false,
          // N0219
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
      // N0220
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

/* N0221 */
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

/* N0222 */
function toggleZoning(on) {
  state.zoning = on;
  if (!map || !zoningLayer) return;
  on ? zoningLayer.addTo(map) : zoningLayer.remove();
}

/* N0223 */
const DEV_PARTS = [
  { key: 'industry', label: '산업단지', tile: 'industry', vec: null,
    note: '국가·일반·첨단·농공 — 갈래가 곧 층이다' },
  { key: 'housing', label: '택지·사업지구', tile: null, vec: 'zone',
    note: '색은 사업 단계: 지구지정→개발계획→실시계획→부분준공→준공' },
  { key: 'planroad', label: '계획도로', tile: null, vec: 'planroad',
    note: '색은 집행 단계: 미집행·부분집행·집행완료' },
  { key: 'rail', label: '철도역', tile: null, vec: null,
    note: '우리 자료. 종류 칸이 반만 차 있어 정차 규모로 가른다' },
  /* N0224 */
  { key: 'highway', label: '고속도로', tile: null, vec: null,
    note: '계획·공사중·준공 — 구간의 시작과 끝을 이은 선이다' },
];

/* N0225 */
const DEV_PICKS = {
  /* N0226 */
  /* N0227 */
  industry: [
    { id: '국가', label: '국가 68곳', tile: 'industry_gug',
      color: 'rgba(0,0,0,.6)' },
    { id: '일반', label: '일반 257곳', tile: 'industry_ilban',
      color: 'rgba(255,143,0,.6)' },
    { id: '첨단', label: '도시첨단 9곳', tile: 'industry_dosi',
      color: 'rgba(168,17,148,.6)' },
    { id: '농공', label: '농공 147곳', tile: 'industry_nong',
      color: 'rgba(207,252,0,.6)' },
  ],
  housing: [
    { id: '지구지정', label: '지구지정' }, { id: '개발계획', label: '개발계획' },
    { id: '실시계획', label: '실시계획' }, { id: '부분준공', label: '부분준공' },
    { id: '준공', label: '준공', done: true },
  ],
  planroad: [
    { id: '미집행', label: '미집행' }, { id: '부분집행', label: '부분집행' },
    { id: '집행완료', label: '집행완료', done: true },
  ],
  /* N0228 */
  highway: [
    { id: '계획', label: '계획', color: '#FFFFFF' },
    { id: '공사중', label: '공사중', color: '#1F2937' },
    { id: '준공', label: '준공', color: '#9CA3AF', done: true },
  ],
  /* N0229 */
  rail: [
    { id: '많이', label: '많이 서는 역', color: '#0C4A6E', r: 8 },
    { id: '적게', label: '적게 서는 역', color: '#7DD3FC', r: 5 },
    { id: '모름', label: '정차횟수 모름', color: '#64748B', r: 5, hollow: true },
  ],
};

/* N0230 */
function devPicked(part, id) {
  const m = (state.devPick || {})[part];
  if (!m || !(id in m)) return true;
  return !!m[id];
}
window.__devPicked = devPicked;

/* N0231 */
/* N0232 */
const DEV_STAGE = {
  '지구지정': { color: '#075985', rank: 1 },
  '개발계획': { color: '#0EA5E9', rank: 2 },
  '실시계획': { color: '#009E73', rank: 3 },
  '부분준공': { color: '#7C3AED', rank: 4 },
  '준공': { color: '#9CA3AF', rank: 5, done: true },
  // N0233
  '미집행': { color: '#DC2626', rank: 1 },
  '부분집행': { color: '#F59E0B', rank: 2, dash: '7 4' },
  '집행완료': { color: '#6B7280', rank: 3, done: true, dash: '2 5' },
};

/* N0234 */
const DEV_FILL = { housing: 0.2, planroad: 0 };
function devFillOpacity(part) {
  return DEV_FILL[part] != null ? DEV_FILL[part] : 0;
}
window.__devFillOpacity = devFillOpacity;

function devStage(p) {
  return String(p.cat_nam || p.exc_nam || '').trim();
}
const DEVELOP_MIN_ZOOM = 10;

/* N0235 */
const DEV_VEC_ZOOM = { zone: 12, planroad: 14 };
const DEVVEC_MIN_ZOOM = Math.min(...Object.values(DEV_VEC_ZOOM));

/* N0236 */
function devTileKey() {
  const on = DEV_PARTS.filter((p) => p.tile && state.devParts[p.key]);
  if (!on.length) return null;
  // N0237
  const keys = on.flatMap((p) => {
    if (p.key !== 'industry') return [p.tile];
    const picks = DEV_PICKS.industry.filter((k) => devPicked('industry', k.id));
    if (!picks.length) return [];
    return picks.length === DEV_PICKS.industry.length
      ? [p.tile] : picks.map((k) => k.tile);
  });
  if (!keys.length) return null;
  return keys.length === 1 ? keys[0] : keys.join('+');
}

function addDevelopLayer() {
  developLayer = L.layerGroup();
  railLayer = L.layerGroup();
  roadLayer = L.layerGroup();
  roadParcelLayer = L.layerGroup();
  if (state.develop) {
    developLayer.addTo(map); railLayer.addTo(map); roadLayer.addTo(map);
    roadParcelLayer.addTo(map);
  }
  drawDevelop();
  drawRoadParcels();
}

function drawDevelop() {
  if (!map || !developLayer) return;
  developLayer.clearLayers();
  const key = devTileKey();
  const keys = key === null ? []
    : (key.includes('+') ? key.split('+') : [key]);
  keys.forEach((k) => {
    L.tileLayer(`/api/tile?layer=${k}&z={z}&y={y}&x={x}`, {
      ...TILE_OPTS,
      maxZoom: 19,
      minZoom: DEVELOP_MIN_ZOOM,
      opacity: .55,
      attribution: '산업단지 © 국토교통부 브이월드',
    }).addTo(developLayer);
  });
  drawRail();
  drawRoad();
  drawRoadParcels();
  drawDevVec();
  updateDevLegend();
  window.__develop = { on: state.develop, key, parts: { ...state.devParts },
                       pick: JSON.parse(JSON.stringify(state.devPick)),
                       fill: { housing: devFillOpacity('housing'),
                               planroad: devFillOpacity('planroad') } };
}

/* N0238 */
/* N0239 */
const ZOOM_GATES = [
  [DEVELOP_MIN_ZOOM, '개발'],
  [DEV_VEC_ZOOM.zone, '택지·사업지구'],
  [DEV_VEC_ZOOM.planroad, '계획도로'],
  [ZONING_MIN_ZOOM, '용도지역'],
  [CADASTRAL_MIN_ZOOM, '필지경계'],
];

function zoomReadoutText() {
  const z = map.getZoom();
  const lo = map.getMinZoom();
  const hi = map.getMaxZoom();
  const next = ZOOM_GATES
    .filter(([g]) => Number.isFinite(g) && z < g)
    .sort((a, b) => a[0] - b[0])[0];
  return {
    main: `z ${z} / ${lo}~${hi}`,
    hint: next ? `z${next[0]} 부터 ${next[1]}` : '',
    atMin: z <= lo, atMax: z >= hi,
  };
}
window.__zoomReadout = zoomReadoutText;   // 검사가 부른다

function addZoomReadout() {
  const box = document.createElement('div');
  box.id = 'zoom-readout';
  box.className = 'zoom-readout';
  const host = document.querySelector('.leaflet-bottom.leaflet-right')
            || map.getContainer();
  host.insertBefore(box, host.firstChild);
  L.DomEvent.disableClickPropagation(box);
  const paint = () => {
    const r = zoomReadoutText();
    box.innerHTML = `<b>${escapeHtml(r.main)}</b>`
      + (r.hint ? `<span>${escapeHtml(r.hint)}</span>` : '');
    box.classList.toggle('at-min', r.atMin);
    box.classList.toggle('at-max', r.atMax);
    // 끝에 닿은 쪽 단추를 흐리게 — 더 눌러도 안 된다는 것을 눈으로.
    const zin = document.querySelector('.leaflet-control-zoom-in');
    const zout = document.querySelector('.leaflet-control-zoom-out');
    if (zin) zin.classList.toggle('is-end', r.atMax);
    if (zout) zout.classList.toggle('is-end', r.atMin);
  };
  map.on('zoomend', paint);
  map.on('zoomlevelschange', paint);
  // N0240
  setTimeout(() => { try { paint(); } catch (e) { /* 눈금뿐이다 */ } }, 0);
}

/* N0241 */
const DEVVEC_FETCH_PER_PASS = 12;
const devVecCache = new Map();      // 'kind/z/x/y' → {items}
const devVecAsked = new Set();
let devVecLayer = null;

function devVecTiles(kind) {
  const z = map.getZoom();
  // kind 를 안 주면 **가장 낮은 문턱**으로 본다. 검사와 눈금이 그렇게 쓴다.
  const gate = (kind && DEV_VEC_ZOOM[kind] != null)
    ? DEV_VEC_ZOOM[kind] : DEVVEC_MIN_ZOOM;
  if (z < gate) return [];
  const b = map.getBounds();
  const n = 2 ** z;
  const xy = (lat, lon) => [
    Math.floor((lon + 180) / 360 * n),
    Math.floor((1 - Math.log(Math.tan(lat * Math.PI / 180)
      + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * n),
  ];
  const [x0, y0] = xy(b.getNorth(), b.getWest());
  const [x1, y1] = xy(b.getSouth(), b.getEast());
  // N0242
  if ((x1 - x0 + 1) * (y1 - y0 + 1) > CAD_MAX_VIEW) return [];
  const out = [];
  for (let x = x0; x <= x1; x += 1) {
    for (let y = y0; y <= y1; y += 1) {
      if (x >= 0 && y >= 0 && x < n && y < n) out.push([z, x, y]);
    }
  }
  // N0243
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  out.sort((a, b) => ((a[1] - cx) ** 2 + (a[2] - cy) ** 2)
                   - ((b[1] - cx) ** 2 + (b[2] - cy) ** 2));
  return out;
}

window.__devVecTiles = (kind) => devVecTiles(kind);   // 배율 문턱을 검사가 본다

function devVecKinds() {
  return DEV_PARTS.filter((p) => p.vec && state.devParts[p.key])
    .map((p) => p.vec);
}

function drawDevVec() {
  if (!map) return;
  if (!devVecLayer) devVecLayer = L.layerGroup().addTo(map);
  devVecLayer.clearLayers();
  if (!state.develop) return;
  const kinds = devVecKinds();
  if (!kinds.length) return;
  let drawn = 0;
  let asked = 0;
  let missing = 0;
  let tiles = 0;
  /* N0244 */
  const seen = new Set();
  // N0245
  kinds.forEach((kind) => {
    const kindTiles = devVecTiles(kind);
    tiles += kindTiles.length;
    kindTiles.forEach(([z, x, y]) => {
      const key = `${kind}/${z}/${x}/${y}`;
      const got = devVecCache.get(key);
      // N0246
      if (got) { drawn += paintDevVec(kind, got, seen); return; }
      missing += 1;
      if (devVecAsked.has(key)) return;
      if (asked >= DEVVEC_FETCH_PER_PASS) return;   // 나머지는 다음 판에
      asked += 1;
      devVecAsked.add(key);
      fetch(`/api/tile?mode=devvec&kind=${kind}&z=${z}&x=${x}&y=${y}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          devVecAsked.delete(key);
          if (!d) return;
          devVecCache.set(key, d.items || []);
          if (state.develop) drawDevVec();
        })
        .catch(() => { devVecAsked.delete(key); });
    });
  });
  window.__devvec = { kinds, tiles, drawn, asked, missing,
                      unique: seen.size, cached: devVecCache.size };
}

/* N0247 */
window.__redrawDevVec = function () {
  devVecCache.clear();
  devVecAsked.clear();
  drawDevVec();
}

function paintDevVec(kind, items, seen) {
  let n = 0;
  const part = kind === 'planroad' ? 'planroad' : 'housing';
  const fill = devFillOpacity(part);
  items.forEach((it) => {
    // N0248
    if (seen && it.k) {
      const id = `${kind}/${it.k}`;
      if (seen.has(id)) return;
      seen.add(id);
    }
    const stage = devStage(it.p || {});
    const spec = DEV_STAGE[stage];
    // N0249
    if (stage && !devPicked(part, stage)) return;
    const color = (spec && spec.color) || '#6B7280';
    const road = kind === 'planroad';
    L.geoJSON(it.g, {
      style: {
        color,
        weight: road ? 3 : 2,
        opacity: .9,
        dashArray: (spec && spec.dash) || null,
        fillColor: color,
        // N0250
        fillOpacity: fill,
      },
    }).bindTooltip(devVecTip(kind, it.p || {}, stage),
                   { direction: 'top', sticky: true })
      .addTo(devVecLayer);
    n += 1;
  });
  return n;
}

/* N0251 */
const PLANROAD_STAGE_WHY = {
  '미집행': '결정된 폭으로는 아직 안 났습니다 (길이 있어도 넓히는 일이 안 됨)',
  '부분집행': '일부 구간만 결정된 폭으로 났습니다',
  '집행완료': '결정된 폭으로 다 났습니다',
};

/* N0252 */
const PLANROAD_WIDTH = {
  '광로': '40~70m 이상', '대로': '25~40m', '중로': '12~25m', '소로': '8~12m',
};
function planroadWidth(atr) {
  const t = String(atr || '');
  const k = Object.keys(PLANROAD_WIDTH).find((w) => t.includes(w));
  return k ? PLANROAD_WIDTH[k] : '';
}
window.__planroadWidth = planroadWidth;

function devVecTip(kind, p, stage) {
  if (kind === 'planroad') {
    const why = PLANROAD_STAGE_WHY[stage];
    const w = planroadWidth(p.atr_nam);
    return `<b>${escapeHtml(p.atr_nam || '계획도로')}</b>`
      + (w ? ` <span class="dev-why">결정 폭 ${escapeHtml(w)}</span>` : '')
      + (p.pmi_nam ? `<br>${escapeHtml(p.pmi_nam)}` : '')
      + (stage ? `<br><b>${escapeHtml(stage)}</b>` : '')
      + (why ? `<br><span class="dev-why">${escapeHtml(why)}</span>` : '')
      + (stage === '미집행' && w
          ? '<br><span class="dev-why">빨간 띠가 결정 폭의 자리입니다 —'
            + ' 지금 길보다 넓으면 그 차이가 아직 안 난 몫입니다</span>' : '');
  }
  return `<b>${escapeHtml(p.zonename || '사업지구')}</b>`
    + (stage ? `<br><b>${escapeHtml(stage)}</b>` : '');
}
window.__devVecTip = devVecTip;   // 검사(test_map.js)가 부른다

/* N0253 */
function devPickColor(part, k) {
  if (k.color) return k.color;
  const spec = DEV_STAGE[k.id];
  return spec ? spec.color : '';
}

function updateDevSubs() {
  document.querySelectorAll('#dev-parts .dev-subs').forEach((box) => {
    const part = box.dataset.part;
    box.hidden = !state.develop || !state.devParts[part];
    box.querySelectorAll('.dev-opt').forEach((btn) => {
      btn.setAttribute('aria-pressed', String(devPicked(part, btn.dataset.pick)));
    });
  });
}

function updateDevLegend() {
  updateDevSubs();
  // N0254
  const box = document.getElementById('dev-legend');
  if (!box) return;
  const on = state.develop && state.devParts.planroad
    && devPicked('planroad', '미집행');
  box.hidden = !on;
  box.innerHTML = on
    ? `<div class="dev-leg-row"><b>미집행</b>`
      + `<span class="dev-why">${escapeHtml(PLANROAD_STAGE_WHY['미집행'])}</span>`
      + '</div>'
    : '';
}

/* N0255 */
function railSize(s) {
  if (!(typeof s.trains === 'number' && s.trains > 0)) return '모름';
  return s.trains >= 100 ? '많이' : '적게';
}
window.__railSize = railSize;

/* 철도 — 우리 자료. 역은 점, 개통 예정은 테두리를 달리한다. */
function drawRail() {
  if (!railLayer) return;
  railLayer.clearLayers();
  if (!state.develop || !state.devParts.rail) return;
  const rows = (state.rail || {}).stations || [];
  const today = new Date().toISOString().slice(0, 10);
  rows.forEach((s) => {
    if (!Number.isFinite(s.lat) || !Number.isFinite(s.lon)) return;
    const soon = s.opened_on && s.opened_on > today;
    const size = railSize(s);
    if (!devPicked('rail', size)) return;
    const spec = DEV_PICKS.rail.find((k) => k.id === size) || {};
    /* N0256 */
    L.circleMarker([s.lat, s.lon], {
      pane: 'markerPane',
      radius: spec.r || 5,
      color: soon ? '#7C3AED' : (spec.hollow ? spec.color : '#FFFFFF'),
      weight: 2,
      dashArray: (soon || spec.hollow) ? '3 2' : null,
      // N0257
      fillColor: soon ? '#EDE9FE' : (spec.hollow ? '#FFFFFF' : spec.color),
      fillOpacity: spec.hollow ? .85 : .95,
    }).bindTooltip(
      `<b>${escapeHtml(s.name)}</b>`
      + (s.trains ? `<br>하루 ${s.trains.toLocaleString()}회 정차` : '')
      + (soon ? '<br><b>개통 예정</b>' : ''),
      { direction: 'top' }).addTo(railLayer);
  });
  /* N0258 */
  window.__railMarks = railLayer.getLayers
    ? railLayer.getLayers().map((l) => ({
        r: l.options.radius,
        fill: l.options.fillColor,
        line: l.options.color,
        dash: l.options.dashArray || null,
      }))
    : [];
}

/* N0259 */
function roadStageColor(stage) {
  const k = (DEV_PICKS.highway || []).find((x) => x.id === stage);
  return (k && k.color) || '#6B7280';
}

function roadTip(it) {
  const won = (n) => (n >= 10000 ? `${(n / 10000).toFixed(1)}조` : `${n.toLocaleString()}억`);
  return `<b>${escapeHtml(it.name || '')}</b>`
    + `<br><b>${escapeHtml(it.stage)}</b>`
    + (it.kind === '신설' || it.kind === '확장' ? ` · ${escapeHtml(it.kind)}` : '')
    + (it.km ? ` · ${it.km}km` : '')
    + (it.lanes ? `<br>왕복 ${escapeHtml(it.lanes)}차로` : '')
    + (it.cost_eok ? `<br>총사업비 ${won(it.cost_eok)}` : '')
    + (it.term ? `<br>공사기간 ${escapeHtml(it.term)}` : '')
    // N0260
    + (it.done_on ? `<br>준공 ${escapeHtml(String(it.done_on))}` : '')
    + (it.axis ? `<br>${escapeHtml(it.axis)}${it.line ? ' · ' + escapeHtml(it.line) : ''}` : '')
    /* N0261 */
    + (it.path
      ? '<br><span class="dev-why">실제 노선 선형입니다 · 선형 '
        + (it.path_src === '관'
          ? '© 국토교통부 브이월드'
          : '© OpenStreetMap 기여자 (ODbL)') + '</span>'
      : '<br><span class="dev-why">구간의 시작과 끝을 이은 선입니다 —'
        + ' 실제 노선 모양이 아닙니다</span>');
}

/* N0262 */
const ROADP_MIN_ZOOM = 15;
const ROADP_TILE_ZOOM = 17;        // 이보다 잘게 쪼개 부르지 않는다
const ROADP_MAX_TILES = 8;
const ROADP_RETRY_MS = 30_000;
let roadParcelLayer = null;
const rpTiles = new Map();
const rpAsked = new Set();
const rpFailed = new Map();

function rpTileList() {
  const z = Math.min(Math.round(map.getZoom()), ROADP_TILE_ZOOM);
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
  if ((x2 - x1 + 1) * (y2 - y1 + 1) > CAD_MAX_VIEW) return [];
  const out = [];
  for (let x = x1; x <= x2; x += 1) {
    for (let y = y1; y <= y2; y += 1) {
      if (x < 0 || y < 0 || x >= n || y >= n) continue;
      out.push([z, x, y]);
    }
  }
  const cx = (x1 + x2) / 2; const cy = (y1 + y2) / 2;
  out.sort((a, b2) => (Math.abs(a[1] - cx) + Math.abs(a[2] - cy))
                    - (Math.abs(b2[1] - cx) + Math.abs(b2[2] - cy)));
  return out;
}

function rpTip(p) {
  const road = p.r === 1;
  /* N0263 */
  return `<b>${escapeHtml(p.b || '')}</b>`
    + (p.s ? `<br>${escapeHtml(p.s)}` : '')
    + (p.t ? ` · ${escapeHtml(p.t)}` : '')
    + `<br><b>${escapeHtml(p.z || '도로구역')}</b>`
    + (p.c ? ` · ${escapeHtml(p.c)}` : '')
    + (road
      ? '<br><span class="dev-why">이미 도로인 땅입니다 (지목 도로)</span>'
      : `<br><b>아직 도로가 아닙니다</b>${p.j ? ` · 지목 ${escapeHtml(p.j)}` : ''}`
        + '<br><span class="dev-why">도로구역에 들어 있어 편입 대상입니다 —'
        + ' 보상 시기·범위는 사업시행자 고시로 확인하셔야 합니다</span>');
}

function drawRoadParcels() {
  if (!map || !roadParcelLayer) return;
  const on = state.develop && state.devParts.highway
    && map.getZoom() >= ROADP_MIN_ZOOM;
  if (!on) {
    roadParcelLayer.clearLayers();
    rpTiles.clear();
    window.__roadParcels = { on: false, drawn: 0 };
    return;
  }
  const want = rpTileList();
  const keep = new Set(want.map(([z, x, y]) => `${z}/${x}/${y}`));
  for (const [key, layer] of rpTiles) {
    if (!keep.has(key)) { roadParcelLayer.removeLayer(layer); rpTiles.delete(key); }
  }
  const now = Date.now();
  for (const [z, x, y] of want) {
    const key = `${z}/${x}/${y}`;
    if (rpTiles.has(key) || rpAsked.has(key)) continue;
    if (now - (rpFailed.get(key) || 0) < ROADP_RETRY_MS) continue;
    if (rpAsked.size >= ROADP_MAX_TILES) break;
    rpAsked.add(key);
    fetchRoadParcelTile(z, x, y, key);
  }
  let drawn = 0;
  for (const layer of rpTiles.values()) drawn += layer.getLayers().length;
  window.__roadParcels = { on: true, drawn, tiles: rpTiles.size };
}

function fetchRoadParcelTile(z, x, y, key) {
  let ok = false;
  fetch(`/api/tile?mode=roadparcels&z=${z}&x=${x}&y=${y}`)
    .then((r) => { if (r.ok) ok = true; return r.ok ? r.json() : null; })
    .then((d) => {
      if (!d || !roadParcelLayer) return;
      if (!state.develop || !state.devParts.highway) return;
      if (map.getZoom() < ROADP_MIN_ZOOM) return;
      if (!rpTileList().some(([a, b, c]) => `${a}/${b}/${c}` === key)) return;
      const group = L.layerGroup();
      (d.items || []).forEach((p) => {
        if (!devPicked('highway', p.t)) return;
        const core = roadStageColor(p.t);
        const road = p.r === 1;
        L.geoJSON({ type: 'Feature', properties: {}, geometry: p.g }, {
          pane: 'overlayPane',
          style: {
            color: core,
            weight: road ? 1 : 2,
            // N0264
            dashArray: road ? null : '5 4',
            fillColor: core,
            fillOpacity: road ? 0.35 : 0.2,
          },
        }).bindTooltip(rpTip(p), { direction: 'top', sticky: true })
          .addTo(group);
      });
      group.addTo(roadParcelLayer);
      rpTiles.set(key, group);
      window.__roadParcels = { on: true, tiles: rpTiles.size,
                              drawn: group.getLayers().length };
    })
    .catch(() => { /* 한 칸이 안 와도 나머지는 그린다. */ })
    .finally(() => {
      rpAsked.delete(key);
      if (!ok) rpFailed.set(key, Date.now());
      if (state.develop && state.devParts.highway) drawRoadParcels();
    });
}

function drawRoad() {
  if (!roadLayer) return;
  roadLayer.clearLayers();
  if (!state.develop || !state.devParts.highway) return;
  const items = (state.road || {}).items || [];
  let n = 0;
  items.forEach((it) => {
    if (!devPicked('highway', it.stage)) return;
    const a = it.a;
    const b = it.b;
    if (!Array.isArray(a) || !Array.isArray(b)) return;
    const core = roadStageColor(it.stage);
    const plan = it.stage === '계획';
    /* N0265 */
    const line = (Array.isArray(it.path) && it.path.length >= 2)
      ? it.path : [a, b];
    /* N0266 */
    const close = map.getZoom() >= ROADP_MIN_ZOOM;
    // N0267
    if (!close) {
      L.polyline(line, {
        pane: 'overlayPane', color: '#1F2937', weight: 8, opacity: .55,
        lineCap: 'round', lineJoin: 'round',
      }).addTo(roadLayer);
    }
    L.polyline(line, {
      pane: 'overlayPane', color: core,
      weight: close ? 2 : 4, opacity: close ? .35 : .95,
      dashArray: plan ? '10 7' : null, lineCap: 'round', lineJoin: 'round',
    }).bindTooltip(roadTip(it), { direction: 'top', sticky: true })
      .addTo(roadLayer);
    if (!n) window.__roadTipSample = roadTip(it);   // 검사가 본다
    /* N0268 */
    ((it.path || close) ? [] : [a, b]).forEach((pt) => {
      L.circleMarker(pt, {
        pane: 'markerPane', radius: 4, color: '#1F2937', weight: 2,
        fillColor: core, fillOpacity: 1,
      }).addTo(roadLayer);
    });
    n += 1;
  });
  window.__road = { on: state.devParts.highway, drawn: n,
                    total: items.length };
}

function togglePlaceTags(on) {
  state.placeTags = on;
  drawLandPrice();
}

function toggleDevelop(on) {
  state.develop = on;
  if (!map || !developLayer) return;
  if (on) {
    developLayer.addTo(map); railLayer.addTo(map);
    if (roadLayer) roadLayer.addTo(map);
    if (roadParcelLayer) roadParcelLayer.addTo(map);
  } else {
    developLayer.remove();
    railLayer.remove();
    if (roadLayer) { roadLayer.remove(); }
    if (roadParcelLayer) {
      roadParcelLayer.remove(); roadParcelLayer.clearLayers(); rpTiles.clear();
    }
    if (devVecLayer) devVecLayer.clearLayers();
  }
  drawDevelop();
}

/* N0269 */
const adminCache = new Map();      // 'level|lat|lon' → geom | null
let adminAsked = null;

function addAdminLayer() {
  adminLayer = L.layerGroup().addTo(map);
}

function clearAdminShape() {
  adminAsked = null;
  if (adminLayer) adminLayer.clearLayers();
}

function drawAdminShape(geom, fullName) {
  if (!adminLayer || !geom) return;
  adminLayer.clearLayers();
  const shape = L.geoJSON(geom, {
    // N0270
    style: { color: '#1D4ED8', weight: 3, opacity: .9,
             fillColor: '#3B82F6', fillOpacity: .12 },
    interactive: false,
  }).addTo(adminLayer);
  // N0271
  if (fullName) {
    shape.bindTooltip(String(fullName), {
      permanent: true, direction: 'center', className: 'admin-name',
    });
  }
}

/* N0272 */
function adminName(props) {
  const p = props || {};
  if (p.full_nm) return String(p.full_nm);
  const parts = ['sido_nm', 'sigg_nm', 'emd_nm', 'li_nm',
                 'sido_kor_nm', 'sig_kor_nm', 'emd_kor_nm', 'li_kor_nm']
    .map((k) => p[k]).filter(Boolean).map(String);
  return [...new Set(parts)].join(' ') || null;
}

async function showAdminShape(at, levelKey) {
  const lat = Number(at[0]).toFixed(6);
  const lon = Number(at[1]).toFixed(6);
  // N0273
  const level = levelKey === 'ri' ? 'ri'
    : (levelKey === 'umd' ? 'umd'
      : (levelKey === 'sido' ? 'sido' : 'sigungu'));
  const key = `${level}|${lat}|${lon}`;
  adminAsked = key;
  if (adminCache.has(key)) {
    // N0274
    const hit = adminCache.get(key) || {};
    drawAdminShape(hit.geom, hit.name);
    return;
  }
  try {
    const resp = await fetch(
      `/api/tile?mode=admin&level=${level}&lat=${lat}&lon=${lon}`);
    if (!resp.ok) return;
    const d = await resp.json();
    const name = adminName(d.props);
    adminCache.set(key, { geom: d.geom || null, name });
    // 기다리는 사이에 다른 태그를 눌렀으면 그린 것을 덮지 않는다.
    if (adminAsked !== key) return;
    drawAdminShape(d.geom, name);
  } catch (err) { /* 경계가 안 와도 값은 그대로 보인다 */ }
}

/* N0275 */
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

// N0276
const popNum = (v, digits = 0) =>
  (typeof v === 'number' && isFinite(v))
    ? v.toLocaleString('ko-KR', { maximumFractionDigits: digits }) : null;

/* N0277 */
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
  // N0278
  if (per) add('단가', `${perPy}/평 <span class="mut">· ${per}/㎡</span>`);

  // N0279
  add('지목', t.jimok && (escapeHtml(t.jimok)
      + (t.stage ? ` <span class="mut">(${escapeHtml(t.stage)})</span>` : '')));
  add('용도지역', t.land_use && escapeHtml(t.land_use));

  /* N0280 */
  if (t.road_side) {
    const ok = t.car_ok === 'Y';
    add('도로접', escapeHtml(t.road_side)
        + ` <span class="road-tag ${ok ? 'is-ok' : 'is-no'}">`
        + `${ok ? '차 진입 가능' : '진입 어려움'}</span>`);
  }
  // N0281
  add('형상', t.parcel_shape && escapeHtml(t.parcel_shape));
  add('지세', t.parcel_slope && escapeHtml(t.parcel_slope));
  if (t.official_price) {
    // N0282
    const mult = t.price_per_m2 ? t.price_per_m2 / t.official_price : null;
    add('공시지가', `${won(t.official_price)}/㎡`
        + (mult && isFinite(mult)
           ? ` <span class="mut">(실거래가 ${mult.toFixed(1)}배)</span>` : ''));
  }
  // N0283
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

  // N0284
  const coarse = t.geocode_level !== 'parcel';
  const warn = coarse
    ? '<p class="pop-warn">이 점은 <strong>법정동 중심점</strong>입니다 —'
      + ' 실제 필지 위치가 아닙니다 (오차 ±1~2km).</p>'
    : '';

  // N0285
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

/* N0286 */
/* N0287 */
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

/* N0288 */
/* N0289 */
const TRADE_LABEL_ZOOM = 16;
/* N0290 */
const TRADE_LABEL_CAP = 400;

/* N0291 */
function pinMoney(v) {
  const got = won(v);
  return got ? got.replace(/원$/, '') : null;
}

function pinPyeong(m2) {
  if (!(typeof m2 === 'number' && isFinite(m2) && m2 > 0)) return null;
  return `${Math.round(m2 / PYEONG_M2).toLocaleString('ko-KR')}평`;
}

/* N0292 */
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

/* N0293 */
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

/* N0294 */
const COARSE_SPREAD_M = 300;

function tradeLatLng(t, coarse) {
  if (!coarse || !(t.lat && t.lon)) return [t.lat, t.lon];
  const seed = String(t.trade_id || `${t.umd}|${t.jibun}|${t.price_krw}`);
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  h >>>= 0;
  const angle = (h % 3600) / 3600 * Math.PI * 2;
  // N0295
  const r = COARSE_SPREAD_M * Math.sqrt(((h >>> 12) & 1023) / 1023);
  const dLat = (r * Math.cos(angle)) / 111320;
  const dLon = (r * Math.sin(angle))
    / (111320 * Math.cos(t.lat * Math.PI / 180) || 1);
  return [t.lat + dLat, t.lon + dLon];
}

function tradeMarker(t, labelled) {
  const factory = t.kind === 'factory';
  const coarse = t.geocode_level !== 'parcel';
  if (labelled) return tradePin(t, coarse);
  return L.marker(tradeLatLng(t, coarse), {
    // N0296
    icon: L.divIcon({
      className: 'trade-icon',
      html: '<i class="trade-mark ' + tradeShape(t)
            + (coarse ? ' trade-coarse' : '') + '"></i>',
      iconSize: [TRADE_PX, TRADE_PX],
      iconAnchor: [TRADE_PX / 2, TRADE_PX / 2],
    }),
    pane: 'tradePane',
    // N0297
    interactive: true,
    keyboard: false,
    // 검사와 화면 양쪽이 같은 값을 본다.
    kind: t.kind,
    geocodeLevel: t.geocode_level || '',
    // 흩기 전의 자리. 검사가 '얼마나 옮겼나' 를 볼 수 있어야 한다.
    srcAt: [t.lat, t.lon],
  }).bindPopup(tradePopup(t), { className: 'trade-popup', maxWidth: 320 });
}

/* N0298 */
function tradePin(t, coarse) {
  const k = pinKind();
  const val = k.of(t);
  const sub = pinSub(t);
  return L.marker(tradeLatLng(t, coarse), {
    icon: L.divIcon({
      className: 'trade-pin-wrap',
      html: `<span class="trade-pin ${tradeShape(t)}`
        // N0299
        + (coarse ? ' is-coarse' : '') + '">'
        + `<b>${escapeHtml(pinTitle(t))}</b>`
        + `<i>${escapeHtml(val || '—')}</i>`
        + (sub ? `<s>${escapeHtml(sub)}</s>` : '')
        // N0300
        + '<u class="trade-pin-tail"></u></span>',
      iconSize: null,
      iconAnchor: [0, 0],
    }),
    pane: 'tradePane',
    interactive: true,
    keyboard: false,
    kind: t.kind,
    geocodeLevel: t.geocode_level || '',
    srcAt: [t.lat, t.lon],
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
  window.__detail = {
    on: true, selected: state.selected,
    bands: bandLayer.getLayers ? bandLayer.getLayers().length : 0,
  };
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

  // N0301

  // N0302
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

/* N0303 */
/* N0304 */
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
  // N0305
  document.body.classList.toggle('has-detail', !!on);
  if (on) {
    // N0306
    if (window.matchMedia && window.matchMedia('(max-width:56rem)').matches) {
      setTimeout(() => {
        try { box.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
        catch (err) { box.scrollIntoView(); }
      }, 60);
    }
  }
  if (!on) {
    box.innerHTML = '';
    // N0307
    drawParcelShape(null);
    /* N0308 */
    if (bandLayer) bandLayer.clearLayers();
    if (state.selected) {
      state.selected = null;
      markers.forEach((m) => m.setStyle({ weight: 2 }));
    }
  }
  // N0309
  if (map) setTimeout(() => map.invalidateSize(), 0);
  // N0310
  window.__detail = {
    on: !!on,
    selected: state.selected || null,
    bands: (bandLayer && bandLayer.getLayers) ? bandLayer.getLayers().length : 0,
  };
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
/* N0311 */
/* N0312 */
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

/* N0313 */
function popLevel(zoom) {
  let out = POP_LEVELS[0];
  POP_LEVELS.forEach((lv) => { if (zoom >= lv.minZoom) out = lv; });
  return out;
}

/* N0314 */
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

/* N0315 */
/* N0316 */
function popSkip(r, levelKey) {
  return r && r.pop_level === 'si' && levelKey === 'gu';
}

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

/* N0317 */
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

/* N0318 */

/* ─────────── 땅값 지도 ─────────── */
/* N0319 */

/* N0320 */
const LP_COLORS = ['#7FB3E0', '#5B93D6', '#3B73C4', '#2454A6', '#123B7A'];
const LP_LABELS = ['가장 싼 20%', '', '가운데', '', '가장 비싼 20%'];
/* N0321 */
const LP_NONE_COLOR = '#E4E8ED';

/* N0322 */
const LP_UMD_ZOOM = 12;
const LP_RI_ZOOM = 13;
/* 한 화면에 글자를 몇 개까지. 넘으면 거래가 많은 곳부터 남긴다. */
const LP_MAX_LABELS = 90;
/* 내보내기(webexport.LANDPRICE_MIN_N)와 같은 값. 안내문에 쓴다. */
const LP_MIN_LABEL = 5;

let lpUmdCache = {};      // N0323
const lpUmdPending = new Set();

/* N0324 */
let lpRosterCache = {};
const lpRosterPending = new Set();

/* N0325 */
const LP_RETRY_MS = 60000;
const lpFailed = new Map();          // 조각 열쇠 → 마지막으로 못 받은 때
const lpFresh = (k) => Date.now() - (lpFailed.get(k) || 0) >= LP_RETRY_MS;
// 검사가 들여다본다 — 무엇이 막혀 있는지(실패 기억 · 받는 중 · 받은 것).
window.__lpState = () => ({ failed: [...lpFailed.keys()], pending: [...lpUmdPending],
                            rosterPending: [...lpRosterPending],
                            cached: Object.keys(lpUmdCache), roster: Object.keys(lpRosterCache) });

/* N0326 */
let lpOpenPk = null;
let lpDrawing = false;
/* N0327 */
let lpDragged = false;
/* 말풍선이 열려 있는 동안 미뤄 둔 다시 그리기가 있는가. */
let lpPending = false;

/* N0328 */
/* N0329 */
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

/* N0330 */
/* N0331 */
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

/* N0332 */
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

/* N0333 */
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

/* N0334 */
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
  const groups = lpGroups();
  // N0335
  if (!groups.length) return lpRosterReady();
  return groups.some((g) =>
    lpUmdChunks(g).some((c) => lpUmdCache[`${g}|${c.p}`]));
}

/* N0336 */
function lpRosterReady() {
  if (lpRosterChunks().some((c) => lpRosterCache[c.p])) return true;
  return !!findIndex;
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
    (c) => !lpRosterCache[c.p] && !lpRosterPending.has(c.p)
           && lpFresh(`r|${c.p}`));
  if (!want.length) return;
  want.forEach((c) => lpRosterPending.add(c.p));
  let got = 0;
  await Promise.all(want.map(async (c) => {
    try {
      const r = await fetchData(`${c.f}`, { cache: 'no-cache' });
      if (r.ok) {
        lpRosterCache[c.p] = await r.json();
        lpFailed.delete(`r|${c.p}`);
        got += 1;
      } else { lpFailed.set(`r|${c.p}`, Date.now()); }
    } catch (e) {
      // 못 받아도 지도는 거래 있는 곳만으로 계속 돈다.
      lpFailed.set(`r|${c.p}`, Date.now());
    } finally {
      lpRosterPending.delete(c.p);
    }
  }));
  if (got) drawLandPrice();
}

/* N0337 */
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
    if (popSkip(r, levelKey)) return;   // 구 단위에서는 시 합계 줄을 안 쓴다
    const key = popGroupKey(r, levelKey);
    if (!bag.has(key)) {
      // **열쇠와 이름은 다르다.** 열쇠에는 시·도가 붙어 있다.
      bag.set(key, { name: popGroupName(r, levelKey), key,
                     members: [], wsum: 0, vsum: 0, n: 0, few: 0,
                     from: Infinity, years: new Map(), parts: new Map() });
    }
    const g = bag.get(key);
    // N0338
    g.members.push(r);
    if (!got) {
      // N0339
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
  // N0340
  const popByKey = new Map();
  (state.regions || []).forEach((r) => {
    if (popSkip(r, levelKey)) return;   // 구별 인구를 모르는 시 합계 줄
    const v = (r.pop || {})[year];
    if (!(typeof v === 'number' && v > 0)) return;
    const k = popGroupKey(r, levelKey);
    popByKey.set(k, (popByKey.get(k) || 0) + v);
  });
  return [...bag.values()].map((g) => ({
    name: g.name,
    // N0341
    few: g.few,
    // N0342
    pk: placeKey(levelKey, g.members[0], g.name),
    sg: String((g.members[0] || {}).sigungu_cd || ''),
    // N0343
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
        // N0344
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
    // N0345
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

/* N0346 */
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
    // N0347
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
        // N0348
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
    // N0349
    v: null, few: 0, n: 0, from: null, parts: g.n,
    at: [g.lat / g.n, g.lon / g.n],
    byGroup: [], trend: [],
  }));
}

/* N0350 */
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
      if (!lpUmdCache[key] && !lpUmdPending.has(key) && lpFresh(key))
        want.push({ key, f: c.f });
    });
  });
  if (!want.length) return;
  want.forEach((w) => lpUmdPending.add(w.key));
  let got = 0;
  await Promise.all(want.map(async (w) => {
    try {
      // N0351
      const r = await fetchData(`${w.f}`, { cache: 'no-cache' });
      if (r.ok) {
        const payload = await r.json();
        // N0352
        const cells = payload.cells || [];
        cells.headPop = payload.head_pop || {};
        lpUmdCache[w.key] = cells;
        lpFailed.delete(w.key);
        got += 1;
      } else { lpFailed.set(w.key, Date.now()); }
    } catch (e) {
      // 못 받아도 지도는 시군구로 계속 돈다.
      lpFailed.set(w.key, Date.now());
    } finally {
      lpUmdPending.delete(w.key);
    }
  }));
  // **새로 받은 것이 없으면 다시 안 그린다.** 그리면 곧장 여기로 돌아온다.
  if (got) drawLandPrice();
}

/* N0353 */
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

/* N0354 */
function lpNoneText() {
  return '';
}

function lpTip(it, level, w) {
  if (it.v == null) {
    // N0355
    const on = lpGroups();
    if (!on.length) {
      return `<div class="lp-tip-h">${escapeHtml(it.full || it.name)}</div>`
        + '<div class="lp-tip-m">용도지역을 켜면 이 자리에 평당 단가가'
        + ' 붙습니다</div>';
    }
    return `<div class="lp-tip-h">${escapeHtml(it.full || it.name)}</div>`
      + `<div class="lp-tip-m">${escapeHtml(w ? w.label : '')}`
      + ` · ${escapeHtml(on.join('·'))}`
      + ` · 거래 ${LP_MIN_LABEL}건 미만</div>`;
  }
  const per = perM2Str(it.v);
  const py = perPy(it.v);
  const stat = state.lpStat === 'avg' ? '평균' : '중앙값';
  let html = `<div class="lp-tip-h">${escapeHtml(it.full || it.name)}`
    + `${it.sub ? ` <em>${escapeHtml(it.sub)}</em>` : ''}</div>`
    // N0356
    + `<div class="lp-tip-v"><b>${py}원/평</b></div>`
    + `<div class="lp-tip-v2">${per}원/㎡ · ${stat}</div>`
    + `<div class="lp-tip-m">${escapeHtml(w ? w.label : '')}`
    + ` · 거래 ${it.n.toLocaleString('ko-KR')}건`
    // N0357
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
  /* N0358 */
  if (lpOpenPk != null) { lpPending = true; return; }
  lpPending = false;
  lpDrawing = true;
  try {
    drawLandPriceInner(have);
  } finally {
    lpDrawing = false;
  }
}

// N0359
window.__drawLandPrice = () => drawLandPrice();
// N0360
window.__drawCadastral = () => drawCadastral();
window.__cadTileList = () => cadTileList();
// 조회 배지·별표 검사가 안을 들여다볼 구멍.
window.__viewersPeek = () => ({ star: viewers.star, open: lpOpenPk, pending: lpPending,
  stat: [...viewers.stat].map(([k, v]) => [k, v.n24]),
  // N0361
  pk: viewers.pk, seen: [...viewers.seen],
  items: (viewers.items || []).map((x) => ({ pk: x.pk, at: x.at || null })) });
/* N0362 */
window.__viewersReset = () => { viewers.seen.clear(); viewers.pk = ''; };
// N0363
window.state = state;
window.__rebuildTiers = () => { recolorTollgates(); updateTierCounts(); };

function drawLandPriceInner(have) {
  lpLayer.clearLayers();
  const groups = lpGroups();
  window.__lp = { on: false, n: 0, groups, level: null };
  // N0364
  if (!state.placeTags) { clearAdminShape(); updateLpNote(null); return; }
  // N0365
  if (!have) { updateLpNote(null); return; }

  const zoom = map.getZoom();
  if (zoom >= LP_UMD_ZOOM) {
    lpLoadUmd();
    // N0366
    if (((state.landPrice || {}).umd_roster || []).length) {
      lpLoadRoster();
    } else if (!findIndex && !findLoading) {
      // N0367
      findLoad().then(() => drawLandPrice());
    }
  }
  const level = lpLevel(zoom);
  const all = (level.key === 'umd' || level.key === 'ri')
    ? lpItemsUmd(level.key) : lpItemsRegion(level.key);
  if (!all.length) { updateLpNote({ n: 0, level: level.label }); return; }

  // N0368
  const shown = lpVisible(all);
  // N0369
  const withValue = shown.filter((it) => it.v != null);
  const scale = lpScale(withValue.map((it) => it.v));
  const w = lpWindow();

  shown.forEach((it) => {
    const fill = lpColor(it.v, scale);
    // N0370
    const short = level.key === 'ri'
      ? String(it.name).split(' ').pop() : it.name;
    const marker = L.marker(it.at, {
      pane: 'lpPane',
      keyboard: false,
      icon: L.divIcon({
        className: 'lp-card-wrap',
        html: `<span class="lp-card${it.v == null ? ' is-none' : ''}"`
          + ` style="background:${fill}">`
          // N0371
          + `<b>${viewerStar(it)}${escapeHtml(short)}`
          // N0372
          + (it.pop ? `<em>${popMan(it.pop)}</em>` : '')
          + `</b>`
          // N0373
          + (it.v == null ? ''
            : `<i>${escapeHtml(lpMoney(it.v))}<u>/평</u></i>`)
          // N0374
          + viewerLine(it.pk)
          + '</span>',
        iconSize: null,
      }),
    });
    // N0375
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
      // N0376
      showAdminShape(it.at, level.key);
    });
    lpLayer.addLayer(marker);
  });

  window.__lp = {
    on: true, n: shown.length, withValue: withValue.length, total: all.length,
    groups, level: level.key, window: state.lpWindow, scale: scale.kind,
    // N0377
    chunks: groups.flatMap((g) => lpUmdChunks(g).map((c) => `${g}|${c.p}`)),
    cached: Object.keys(lpUmdCache),
    // N0378
    items: shown.map((it) => ({ pk: it.pk, sg: it.sg, name: it.name,
                                 v: it.v, pop: it.pop || 0 })),
  };
  updateLpNote({ n: shown.length, withValue: withValue.length,
                 total: all.length, level: level.label, scale, w });
  // 조회수는 **그린 뒤에** 챙긴다. 무엇이 화면에 있는지는 여기서만 안다.
  viewersOnMove(shown);
}

/* N0379 */
function drawLpScale(info) {
  const el = document.getElementById('lp-scale');
  if (!el) return;
  const groups = lpGroups();
  if (!info || !info.n || !groups.length || !info.scale) {
    el.hidden = true;
    window.__lpScale = null;
    return;
  }
  // N0380
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
  // N0381
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
    // N0382
    el.textContent = (info && info.n)
      ? `지금은 ${info.n}곳의 이름만 회색으로 적었습니다.` : '';
    lpSuggest(null);
    return;
  }
  // N0383
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

/* N0384 */
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
  // N0385
  const enough = best && best.n
    && (mine === 0 ? best.n >= 1 : best.n >= Math.max(3, mine * 2));
  if (!enough) { btn.hidden = true; return; }
  btn.hidden = false;
  btn.textContent = `이 화면엔 ${on.join('·') || '고른 것'} ${mine}곳 —`
    + ` ${best.group}(${best.kind})를 켜면 ${best.n}곳`;
  btn.dataset.group = best.group;
}

/* N0386 */
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
  // N0387
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

  // N0388
  const gbox = document.getElementById('lp-groups');
  if (gbox) {
    const have = Object.keys((lp && lp.groups) || {});
    const notes = (lp && lp.zone_notes) || {};
    const tree = (lp && lp.zone_tree) || [];
    // N0389
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
        // N0390
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'zone-opt';
        btn.dataset.group = g;
        const on = state.lpGroupSet.has(g);
        btn.setAttribute('aria-pressed', String(on));
        // N0391
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
/* N0392 */

/* N0393 */
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
let parcelStatsAt = 0;          // 마지막으로 받으려 한 때 — 실패해도 한동안은 안 두드린다
let parcelStatsLoading = null;
const PARCEL_STATS_RETRY_MS = 60000;

async function loadParcelStats() {
  if (parcelStats) return parcelStats;
  if (parcelStatsLoading) return parcelStatsLoading;
  // N0394
  if (Date.now() - parcelStatsAt < PARCEL_STATS_RETRY_MS) return null;
  parcelStatsAt = Date.now();
  parcelStatsLoading = (async () => {
    try {
      const r = await fetchData('parcelstats.json', { cache: 'no-cache' });
      if (r.ok) parcelStats = await r.json();
    } catch (e) { /* 없으면 진단만 못 보여준다. 지도는 그대로 돈다. */ }
    parcelStatsLoading = null;
    return parcelStats;
  })();
  return parcelStatsLoading;
}

/* N0395 */
function pctFromQuantiles(v, breaks) {
  if (!Array.isArray(breaks) || breaks.length < 2 || !Number.isFinite(v)) return null;
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

window.__pctFromQuantiles = (v, breaks) => pctFromQuantiles(v, breaks);

/* 우리 다섯 묶음 중 이 용도지역이 어디에 드는가. */
function parcelGroup(landUse) {
  const groups = Object.keys(((state.landPrice || {}).groups) || {});
  return groups.find((g) => String(landUse || '').indexOf(g) >= 0) || null;
}

/* N0396 */
/* N0397 */
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

/* N0398 */
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

/* N0399 */
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

/* N0400 */
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

  // N0401
  let zg = grade(st.zone_ladder, parcel.land_use);
  // N0402
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

  // N0403
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

  // N0404
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

  // N0405
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

/* N0406 */
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

/* N0407 */
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
  // N0408
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

/* N0409 */
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
    // N0410
    ['대장', parcel.register === '2' ? '임야대장'
      : parcel.register === '1' ? '토지대장' : null],
    // N0411
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

/* N0412 */
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
  // N0413
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

/* N0414 */
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

/* N0415 */
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

/* N0416 */
/* N0417 */
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

/* N0418 */
const VALUE_SERVICES = {
  now: { label: '현재 가치' },
  future: { label: '미래 가치' },
};

/* N0419 */
function myAccess() {
  const me = window.ME;
  /* N0420 */
  const guest = !(me && me.user);
  const prof = me && me.profile;
  const base = (typeof window.accessOf === 'function')
    ? window.accessOf(prof)
    : { grade: 'C', label: '손님', premium: false, expired: false, admin: false };
  return { ...base, guest, label: guest ? '손님' : base.label };
}

function valueButtons() {
  const acc = myAccess();
  const tag = '회원 전용';          // N0421
  return `<div class="pc-val-row${acc.premium ? '' : ' is-locked'}">`
    + Object.entries(VALUE_SERVICES).map(([k, s]) =>
      `<button type="button" class="pc-val" data-val="${k}" aria-expanded="false">`
      + `<b>${s.label}</b><span class="pcv-tag${acc.premium ? '' : ' pcv-lock'}">${tag}</span></button>`).join('')
    + '</div><div class="pc-val-box" id="pc-val-box" hidden></div>';
}

/* N0422 */
function premiumNotice(key, acc) {
  const s = VALUE_SERVICES[key] || { label: '' };
  const head = `<h4>${s.label} <span class="pcv-sub">회원 전용</span></h4>`;
  if (acc.guest) {
    return head
      + `<p class="pcv-lock-msg">이 필지의 ${s.label}는 회원에게 보여 드립니다.</p>`
      + '<p class="pcv-lock-msg"><a class="pcv-cta" href="/account?next=%2Fapp">무료 회원 가입</a></p>'
      + '<p class="pcv-lock-msg">구글·카카오 계정으로 가입하시면 됩니다.</p>';
  }
  /* N0423 */
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

/* N0424 */
const FUTURE_DISCLAIMER =
  '<p class="pcv-legal"><b>미래 가치는 예측이 아니라 참고 지표입니다.</b> '
  + '과거 실거래·교통량·개발 사건 자료로 만든 통계이며, 앞으로의 가격을 '
  + '약속하거나 보장하지 않습니다. 투자 판단과 그 결과는 이용자 본인의 '
  + '것이고, 저희는 그 결과에 책임지지 않습니다. 감정평가·투자자문이 '
  + '아닙니다.</p>';

/* N0425 */
const FUTURE_LAYERS = [
  ['시장 층', '전국이 어느 쪽으로 가는가 — 금리·물가·성장률이 지가변동률을 옮기는 폭'],
  ['지역 사건 층', '이 동네에 예정된 것 — IC·산업단지·철도·택지가 아직 값에 안 들어간 몫'],
  ['필지 층', '이 땅 자체가 바뀌는 것 — 시가화예정용지·토지거래허가구역'],
];

function valuePanel(key) {
  const s = VALUE_SERVICES[key];
  if (!s) return '';
  /* N0426 */
  if (key === 'future') {
    return `<h4>${s.label}</h4>`
      + '<p class="pcv-hold">산출 보류 — 미래 가치는 세 층이 다 서야 냅니다.</p>'
      + '<dl class="pcv-layers">'
      + FUTURE_LAYERS.map(([name, what]) =>
        `<dt>${escapeHtml(name)}</dt><dd>${escapeHtml(what)}</dd>`).join('')
      + '</dl>'
      + '<p class="pcv-desc">세 층이 서고 <b>뒤로 돌려 검산</b>까지 통과하면 그때 '
      + '숫자를 냅니다. 그 전에는 만들어 내지 않습니다.</p>'
      + FUTURE_DISCLAIMER;
  }
  return `<h4>${s.label}</h4>`
    + '<p class="pcv-soon">곧 공개합니다.</p>';
}

/* N0427 */
let valuationTables = null;
const stdlandCache = {};
let zoningLimits = null;

/* N0428 */
async function loadZoningLimits() {
  if (zoningLimits) return zoningLimits;
  try {
    const r = await fetchData('zoning-limits.json', { cache: 'no-cache' });
    if (r.ok) zoningLimits = await r.json();
  } catch (e) { /* 없으면 개발 한도 칸이 안 선다. 나머지는 그대로. */ }
  return zoningLimits;
}

/* N0429 */
/* N0430 */
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
    const r = await fetchData(`${name}`, { cache: 'no-cache' });
    if (!r.ok) window.__premiumLast = `${name}: ${r.status}`;
    return r.ok ? await r.json() : null;
  } catch (e) { window.__premiumLast = `${name}: ${e && e.message}`; return null; }
}

async function loadValuationTables() {
  if (valuationTables) return valuationTables;
  const t = await premiumFetch('valuation.json');
  if (t) valuationTables = t;
  return valuationTables;
}

/* N0431 */
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

/* N0432 */
function josa(word, withBat, without) {
  const w = String(word || '');
  const last = w.charCodeAt(w.length - 1);
  if (!(last >= 0xAC00 && last <= 0xD7A3)) return without;
  return ((last - 0xAC00) % 28) ? withBat : without;
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
  add('가로·접근 (도로접면)', subject.road_side, std.road_side, r, r === null ? '도로접면을 한쪽이라도 몰라 견주지 못합니다' : null);
  if (r === null) warnings.push('도로접면을 알 수 없어 격차율에서 뺐습니다');
  if (kind !== '임야지대') {
    r = ratioOf(idxOf(subject.shape, T.shape_index), idxOf(std.shape, T.shape_index));
    add('획지 (형상)', subject.shape, std.shape, r, r === null ? '형상을 한쪽이라도 몰라 견주지 못합니다' : null);
  }
  const slopeTable = T.slope_index[kind] || T.slope_index['*'];
  r = ratioOf(idxOf(subject.slope, slopeTable), idxOf(std.slope, slopeTable));
  add('자연·획지 (지세)', subject.slope, std.slope, r, r === null ? '지세를 한쪽이라도 몰라 견주지 못합니다' : null);
  if (r === null) warnings.push('지세를 알 수 없어 격차율에서 뺐습니다');
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
    add('행정·기타 (지목·이용상황)', ugS, ugD, m ? m[0] : null, m ? m[1] : '지목군이 달라 격차율로 메우지 않습니다');
    if (!m) warnings.push(`대상은 ${ugS}, 표준지는 ${ugD} 로 지목군이 다릅니다 — 표준지를 다시 고르는 것이 맞습니다`);
  }
  const zs = zoneNamesOf(subject, T);
  const zd = zoneNamesOf(std, T);
  (T.must_match || []).forEach((n) => {
    if (zs.includes(n) === zd.includes(n)) return;
    if ((T.std_known || []).includes(n)) warnings.push(`${n}${josa(n, '이', '가')} 대상·표준지 한쪽에만 있습니다 — 같은 구역의 표준지로 다시 골라야 합니다`);
    else if (zs.includes(n)) warnings.push(`대상은 ${n} 안인데 표준지 공시지가 자료에 그 구역이 적혀 있지 않아, 비교표준지도 같은 조건인지 확인하지 못했습니다`);
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

/* N0433 */
const PRICE_BAND = [0.5, 2.0];
const PRICE_PEN_PER_LOG = 4.0;
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
    // 같은 지목군일 때만 — 지목이 다르면 그 격차는 use_mismatch 가 맡는다.
    const sameUg = !!ug && useGroupOf(c.jimok, c.use_situation) === ug;
    const [ppen, k] = sameUg ? priceLevelPenalty(subject.official_price, c.price) : [0, null];
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

/* N0434 */
const RONE_CLASS_DEFAULT = [['계획관리', '계획관리지역'], ['보전관리', '보전관리지역'],
  ['생산관리', '생산관리지역'], ['관리', '관리지역'], ['녹지', '녹지지역'], ['주거', '주거지역'],
  ['상업', '상업지역'], ['공업', '공업지역'], ['농림', '농림지역'], ['자연환경', '자연환경보전지역']];

function roneClassOf(landUse, T) {
  const t = String(landUse || '');
  const table = (T && T.rone_class) || RONE_CLASS_DEFAULT;
  const hit = table.find(([key]) => t.indexOf(key) >= 0);
  return hit ? hit[1] : null;
}

/* 고시 ①② 순서로 칸을 고른다. 어느 칸인지 말도 같이 준다. */
function pickTimeRates(T, sigungu, landUse) {
  const table = (T && T.time_rates) || null;
  if (!table) return null;
  const sgg = String(sigungu || '');
  const cls = roneClassOf(landUse, T);
  const tries = [];
  if (sgg) {
    if (cls) tries.push([`${sgg}|${cls}`, `같은 시·군·구 · ${cls}`]);
    tries.push([`${sgg}|*`, '같은 시·군·구 · 용도지역 구분 없음']);
    if (cls) tries.push([`${sgg.slice(0, 2)}|${cls}`, `같은 시·도 · ${cls}`]);
    tries.push([`${sgg.slice(0, 2)}|*`, '같은 시·도 · 용도지역 구분 없음']);
  }
  for (const [key, label] of tries) {
    const got = table[key];
    if (got && Object.keys(got).length) return { rates: got, label };
  }
  return null;
}

function timeFromRates(rates, label, base, now) {
  const ym = (d) => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`;
  const cur = ym(now);
  let f = 1; let used = 0; let est = 0; let last = null; let firstP = null; let lastP = null;
  let y = base.getFullYear(); let m = base.getMonth() + 1;
  while (y < now.getFullYear() || (y === now.getFullYear() && m <= now.getMonth() + 1)) {
    const p = `${y}${String(m).padStart(2, '0')}`;
    const raw = rates[p];
    const r = (raw === null || raw === undefined || raw === '') ? null : Number(raw);
    if (p === cur) {
      const days = new Date(y, m, 0).getDate();
      const baseR = (r !== null && isFinite(r)) ? r : last;
      if (baseR !== null) f *= 1 + baseR / 100 * (now.getDate() / days);
      break;
    }
    if (r !== null && isFinite(r)) {
      f *= 1 + r / 100; used += 1; last = r; firstP = firstP || p; lastP = p;
    } else if (last !== null) {
      f *= 1 + last / 100; est += 1;
    }
    m += 1; if (m === 13) { y += 1; m = 1; }
  }
  if (!used) return null;
  let source = `지가변동률 ${used}개월 누계 (${firstP}~${lastP}${label ? ` · ${label}` : ''})`;
  const partial = cur !== ym(base) ? now.getDate() : 0;
  if (est || partial) {
    const bits = [];
    if (est) bits.push(`미고시 ${est}개월`);
    if (partial) bits.push(`${now.getMonth() + 1}월 ${now.getDate()}일분`);
    source += ` · ${bits.join('·')}은 최근 고시 월로 추정`;
  }
  return { factor: Math.round(f * 100000) / 100000, source, kind: 'rates',
           published: used, estimated: est };
}

function timeFactorOf(stdYear, trend, T, ctx) {
  if (!stdYear) return { factor: null, source: '표준지 연도 미상' };
  const base = new Date(stdYear, 0, 1); const now = new Date();
  const months = Math.max(0, (now - base) / (30.44 * 24 * 3600 * 1000));
  const picked = ctx ? pickTimeRates(T, ctx.sigungu, ctx.landUse) : null;
  if (picked) {
    const got = timeFromRates(picked.rates, picked.label, base, now);
    if (got) return { ...got, months: Math.round(months * 10) / 10 };
  }
  if (typeof trend !== 'number') return { factor: null, months, source: '자료 없음' };
  const [lo, hi] = T.time_clamp || [0.98, 1.03];
  const f = Math.min(hi, Math.max(lo, Math.pow(1 + trend, months / 12)));
  return { factor: Math.round(f * 100000) / 100000, months: Math.round(months * 10) / 10,
           source: '또래 실거래 추세로 대신함 (지가변동률 자료 없음)', kind: 'trend' };
}
window.__timeFactorOf = (stdYear, trend, T, ctx) => timeFactorOf(stdYear, trend, T, ctx);

/* N0435 */
const OTHER_WEIGHTS = {
  '현행': { cap: { 거래사례: 100, 평가선례: 30 }, src: { 거래사례: 1, 평가선례: 1 }, root: false },
  '선례2배': { cap: { 거래사례: 30, 평가선례: 30 }, src: { 거래사례: 1, 평가선례: 2 }, root: false },
  '선례3배': { cap: { 거래사례: 30, 평가선례: 30 }, src: { 거래사례: 1, 평가선례: 3 }, root: false },
  '선례3배√': { cap: { 거래사례: 30, 평가선례: 30 }, src: { 거래사례: 1, 평가선례: 3 }, root: true },
};
// N0436
const OTHER_WEIGHT = '선례3배√';

function otherWeightOf(o, prof) {
  const w = OTHER_WEIGHTS[prof || OTHER_WEIGHT] || OTHER_WEIGHTS['현행'];
  const src = String(o.source || '');
  let n = Math.min(Number(o.n) || 0, w.cap[src] == null ? 30 : w.cap[src]);
  if (w.root) n = Math.sqrt(n);
  const lv = String(o.level || '');
  const mult = lv.includes('시군구') ? 1 : (lv.includes('시·도') ? 0.5 : (lv.includes('전국') ? 0.25 : 1));
  return Math.max(n * mult * (w.src[src] == null ? 1 : w.src[src]), 0.5);
}

/* N0437 */
/* N0438 */
function blendOther(have, prof) {
  const w = have.map((o) => otherWeightOf(o, prof));
  const lg = have.reduce((acc, o, i) => acc + w[i] * Math.log(o.median), 0)
    / w.reduce((a, b) => a + b, 0);
  const f = Math.round(Math.exp(lg) * 100) / 100;
  const q1 = Math.min(...have.map((o) => o.q1 || f));
  const q3 = Math.max(...have.map((o) => o.q3 || f));
  return { factor: f, q1: Math.round(q1 * 100) / 100, q3: Math.round(q3 * 100) / 100,
           n: have.reduce((a, o) => a + Number(o.n), 0), sources: have, weights: w,
           basis: have.map((o) => `${o.source} ${Number(o.median).toFixed(2)} (n=${o.n})`).join(' · ')
                  + ` → ${otherBasisWord(prof)}` };
}
window.__blendOther = blendOther;            // 검사가 부른다

function otherBasisWord(prof) {
  const w = OTHER_WEIGHTS[prof || OTHER_WEIGHT] || OTHER_WEIGHTS['현행'];
  const led = w.src['평가선례'] || 1, trd = w.src['거래사례'] || 1;
  return led > trd ? `평가선례 ${Math.round(led / trd)}배 가중 기하평균` : '건수 가중 기하평균';
}
window.__otherWeightOf = otherWeightOf;      // 검사가 파이썬 쪽과 견준다

/* N0439 */
function otherFactorOf(subject, std, T) {
  const zg = zoneGroupOf(subject.land_use, T);
  if (!zg) return { factor: null, sources: [],
                    basis: '용도지역을 알 수 없어 견줄 칸을 못 찾습니다' };
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
  // N0440
  let trade = null;
  outer: for (const area of [code, sido, '*']) {
    for (const key of [...ugs.map((ug) => `${area}|${zg}|${ug}`), `${area}|${zg}|*`]) {
      const o = (T.trade || {})[key];
      if (o && o.median) { trade = o; break outer; }
    }
  }
  const have = [ledger, trade].filter(Boolean);
  if (!have.length) {
    /* N0441 */
    const jimok = String(subject.jimok || '').trim();
    const basis = subjUg
      ? `${zg}·${subjUg} 조건의 거래·평가선례가 아직 없습니다`
      : (jimok
        // '(이)라' 같은 자리표시자를 또 쓰지 않는다 — 조사가 필요 없게 쓴다.
        ? `지목 ${jimok} 에는 견줄 거래·평가선례가 없습니다`
        : '지목을 알 수 없어 견줄 거래·평가선례를 못 찾습니다');
    return { factor: null, basis, sources: [] };
  }
  if (have.length === 1) {
    const o = have[0];
    return { factor: o.median, q1: o.q1, q3: o.q3, n: o.n, sources: have,
             basis: `${o.source} 기준 (n=${o.n}, ${o.level})` };
  }
  return blendOther(have);
}
window.__otherFactorOf = otherFactorOf;      // 검사(test_map.js)가 부른다

function roundDecided(x) {
  const unit = x < 10000 ? 100 : (x < 1000000 ? 1000 : 10000);
  return Math.round(x / unit) * unit;
}

/* N0442 */
// N0443
const REGION_MIN = 0.5;
const REGION_MAX = 1.0;
// N0444
const REGION_ENABLED = false;
function regionFactorOf(subject, std, indFactor) {
  const same = { factor: 1.0, ratio: null,
                 why: '같은 인근지역에서 표준지를 골랐다고 봅니다 (평가서 414/414 이 1.00)' };
  const a = Number(subject.official_price); const b = Number(std.price);
  if (!(a > 0) || !(b > 0) || !(indFactor > 0)) return same;
  const ugS = useGroupOf(subject.jimok, subject.use_situation);
  const ugD = useGroupOf(std.jimok, std.use_situation);
  if (!ugS || ugS !== ugD) return { ...same, why: '지목군이 달라 지역요인은 보지 않습니다 — 그 격차는 지목군 격차율이 맡습니다' };
  const k = a / (b * indFactor);
  const f = Math.min(Math.max(k, REGION_MIN), REGION_MAX);
  const won = (v) => Math.round(v).toLocaleString('ko-KR');
  let why = `대상 개별공시지가 ${won(a)} ÷ (표준지 ${won(b)} × 개별요인 ${indFactor.toFixed(3)}) = ${k.toFixed(2)}`;
  if (f !== k) why += ` → ${f > k ? '하한' : '상한'} ${f.toFixed(2)}`;
  return { factor: Math.round(f * 1000) / 1000, ratio: Math.round(k * 1000) / 1000, why };
}

function appraiseNow(subject, std, T, trend) {
  // N0445
  const t = timeFactorOf(std.year, trend, T, {
    sigungu: std.sigungu || String(subject.pnu || '').slice(0, 5),
    landUse: std.land_use || subject.land_use,
  });
  const ind = individualFactor(subject, std, T);
  const other = otherFactorOf(subject, std, T);
  const reg = REGION_ENABLED ? regionFactorOf(subject, std, ind.factor)
    : { factor: 1.0, ratio: null, why: '같은 인근지역에서 표준지를 골랐다고 봅니다 (평가서 414/414 이 1.00)' };
  const parts = { '표준지공시지가': std.price || null, '시점수정': t.factor, '지역요인': reg.factor,
                  '개별요인': ind.factor, '그 밖의 요인': other.factor };
  const missing = Object.entries(parts).filter(([, v]) => v === null || v === undefined).map(([k]) => k);
  let unit = null; let decided = null; let range = null; let total = null;
  if (!missing.length) {
    unit = std.price * t.factor * reg.factor * ind.factor * other.factor;
    decided = roundDecided(unit);
    if (subject.area_m2) total = decided * Number(subject.area_m2);
    if (other.q1 && other.q3) range = [roundDecided(std.price * t.factor * reg.factor * ind.factor * other.q1),
                                       roundDecided(std.price * t.factor * reg.factor * ind.factor * other.q3)];
  }
  return { subject, std, time: t, region: reg, individual: ind, other, parts, missing,
           unit_calc: unit, unit_decided: decided,
           range, total_krw: total, warnings: ind.warnings };
}

/* N0446 */
function renderValuation(res) {
  const won = (v) => (v == null ? '—' : Math.round(v).toLocaleString('ko-KR'));
  const e = escapeHtml;
  const s = res.std;
  const sub = res.subject || {};
  const f3 = (v) => (v == null ? '—' : Number(v).toFixed(3));
  const desc = (o) => [o.land_use, o.jimok || o.use_situation, o.road_side, o.shape, o.slope]
    .filter(Boolean).join(' · ');
  // N0447
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
  const reg = res.region || { factor: 1.0, why: '' };
  rows.push(['지역요인 비교', `<b>${f3(reg.factor)}</b><span class="pcv-desc">${e(reg.why || '')}</span>`]);

  /* N0448 */
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
  // N0449
  rows.push(['그 밖의 요인 보정', res.other.factor == null
    ? `<em>자료 없음</em><span class="pcv-desc">${e(res.other.basis || '')}</span>`
    : `<b>${res.other.factor}</b><span class="pcv-desc">${e(res.other.basis)}</span>`]);

  /* N0450 */
  const holdWhy = (name) => {
    if (name === '그 밖의 요인') return (res.other || {}).basis;
    if (name === '시점수정') {
      const src = (res.time || {}).source;
      return src && src !== '자료 없음' ? src
        : '지가변동률도 또래 거래 추세도 없어 시점을 못 맞춥니다';
    }
    if (name === '표준지공시지가') return '비교표준지의 공시지가가 없습니다';
    return null;
  };

  let bottom;
  if (res.missing.length) {
    const why = res.missing.map(holdWhy).filter(Boolean);
    bottom = '<p class="pcv-hold">산출 보류'
      + (why.length ? ` — ${e(why.join(' · '))}` : ` — ${e(res.missing.join(', '))}`)
      + '</p>';
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
    /* N0451 */
    + '<p class="pcv-note">공시지가기준법의 다섯 마디를 데이터베이스로 산출한 <strong>예상값</strong>입니다. '
    + '감정평가가 아니며, 담보·소송·과세·보상 목적으로 쓸 수 없습니다. '
    + '<a href="/guide/law">산출 방법</a></p>';
}

/* N0452 */
async function nowResults() {
  const ctx = window.__parcel;
  if (!ctx || !ctx.parcel) return null;
  const parcel = ctx.parcel;
  const code = String(parcel.pnu || '').slice(0, 5);
  // N0453
  const [T, chunk] = await Promise.all([loadValuationTables(), loadStdland(code),
                                        loadParcelStats()]);
  if (!T || !chunk || !chunk.rows || !chunk.rows.length) return null;
  // 주소는 필지 자료가 아니라 따로 온다 (ctx.addr). 산출표 첫 줄에 적는다.
  const subject = { ...parcel, zones: ctx.zones || [], addr: ctx.addr || null };
  const cands = chunk.rows.map((r) => ({ ...stdAsParcel(r), sigungu: chunk.sigungu || code }));
  const picked = pickStandard(subject, cands, T, 3);
  if (!picked.length) return { picked: [], results: [] };
  const mo = pickTrend(code, parcelGroup(parcel.land_use));
  return { picked, results: picked.map((std) => appraiseNow(subject, std, T, mo ? mo.trend : null)) };
}
window.__nowResults = () => nowResults();
// 검사용 — 산출표가 안 나올 때 세 조각 중 무엇이 비었는지.
window.__nowParts = async (code) => ({
  T: !!(await loadValuationTables()), chunk: !!(await loadStdland(code)),
  stats: !!(await loadParcelStats()) });
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

/* N0454 */
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
  /* N0455 */
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
    // N0456
    + '<p class="pc-note">축을 더해 하나의 점수로 만들지 않습니다. '
    + '같은 땅이 창고에는 좋고 주택에는 나쁠 수 있어서, 그 차이가 '
    + '점수 하나로 뭉개지면 사라집니다.</p>'
    + eumLink(parcel)
    + '</div>';
}

/* N0457 */
const EUM_BASE = 'https://www.eum.go.kr/web/ar/lu/luLandDet.jsp';
function eumLink(parcel) {
  const pnu = String((parcel || {}).pnu || '');
  if (!/^\d{19}$/.test(pnu)) return '';
  return `<a class="pc-eum" href="${EUM_BASE}?pnu=${pnu}"`
    + ' target="_blank" rel="noopener noreferrer">'
    + '토지이음에서 더 보기'
    + '<em>소유·지역지구·토지이동 — 열람 단추를 한 번 누르세요</em></a>';
}

/* N0458 */
function drawParcelShape(geom) {
  if (!parcelLayer) return;
  parcelLayer.clearLayers();
  window.__parcelShape = null;
  if (!geom) return;
  const shape = L.geoJSON(geom, {
    pane: 'parcelPane',
    // N0459
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
  // N0460
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
  // N0461
  if (window.TRACK) window.TRACK.event('parcel_view', { zone: (res.zones && res.zones[0]) || '(unknown)' });
  detailBody(parcelCard(parcel, diag, [latlng.lat, latlng.lng],
                        res.addr, res.zones || [], limits));
  window.__parcel = { parcel, diag, geom: res.geom || null,
                      addr: res.addr || null, zones: res.zones || [] };
}

/* ─────────── 세 가설 판정 ─────────── */
/* N0462 */
const VERDICT_TONE = {
  '지지': 'ok',
  '기각': 'no',
};
function verdictTone(v) {
  const t = String(v || '');
  if (VERDICT_TONE[t]) return VERDICT_TONE[t];
  // N0463
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

  // N0464
  const notes = [];
  // N0465
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
      // N0466
      const has = r.ci_lo != null;
      const crosses = has && r.ci_lo <= 0 && r.ci_hi >= 0;
      const ci = has
        ? `<span class="${crosses ? 'ci-null' : 'ci-away'}">` +
          `${r.ci_lo >= 0 ? '+' : ''}${fixed(r.ci_lo)} ~ ` +
          `${r.ci_hi >= 0 ? '+' : ''}${fixed(r.ci_hi)}</span>`
        : '—';
      // N0467
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

/* N0468 */

/* N0469 */
const FIND_MAX = 8;
const FIND_ZOOM = { sido: 9, sigungu: 11, umd: 13, addr: 18 };
// N0470
const FIND_JIBUN_RE = /(^|\s)(산\s?)?\d{1,4}(-\d{1,4})?(번지)?$/;
let findIndex = null;
let findLoading = null;

async function findLoad() {
  if (findIndex) return findIndex;
  if (findLoading) return findLoading;
  findLoading = (async () => {
    const rows = [];
    // N0471
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
      const r = await fetchData('places.json');
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

/* N0472 */
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

/* N0473 */
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

/* N0474 */
async function findLdCode(sg, name) {
  const idx = (state.landPrice || {}).umd_roster || [];
  const c = idx.find((x) => String(x.p) === String(sg || '').slice(0, 2));
  if (!c) return '';
  if (!lpRosterCache[c.p]) {
    try {
      const r = await fetchData(`${c.f}`, { cache: 'no-cache' });
      if (r.ok) lpRosterCache[c.p] = await r.json();
    } catch (e) { /* 못 받으면 지오코더로 */ }
  }
  const rows = ((lpRosterCache[c.p] || {}).rows) || [];
  const hit = rows.find((row) => row[0] === name && String(row[1]) === String(sg))
    || rows.find((row) => row[0] === name);
  const ld = hit ? String(hit[6] || '') : '';
  return /^\d{10}$/.test(ld) ? ld : '';
}

/* N0475 */
/* N0476 */
function findSido(words, regions) {
  const names = [...new Set((regions || []).map((r) => r.sido).filter(Boolean))];
  for (const sd of names) {
    if (words.includes(sd)) return sd;
    // '대구광역시' 대신 '대구' 라고 쳐도 알아듣는다.
    const short = sd.replace(/(특별자치시|특별자치도|광역시|특별시|도)$/, '');
    if (short && short !== sd && words.includes(short)) return sd;
  }
  return '';
}
window.__findSido = findSido;          // 검사가 본다

function findSigungu(words, regions, sido) {
  const pool = sido ? (regions || []).filter((r) => r.sido === sido)
    : (regions || []);
  /* N0477 */
  for (let n = 2; n >= 1; n -= 1) {
    for (let i = 0; i + n <= words.length; i += 1) {
      const chunk = words.slice(i, i + n).join(' ');
      const hit = pool.find((r) => r.name === chunk);
      if (hit) return hit;
    }
  }
  /* N0478 */
  for (const w of words) {
    const hit = pool.find((r) => r.name.endsWith(' ' + w));
    if (hit) return hit;
  }
  return null;
}
window.__findSigungu = findSigungu;

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
  const sido = findSido(words, regions);
  const hasSg = findSigungu(words, regions, sido);
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
  // N0479
  const sido = findSido(words, regions);
  const hasSg = findSigungu(words, regions, sido);
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

/* N0480 */
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
  // N0481
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
    // N0482
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

  // N0483
  const pbox = document.getElementById('place-bg');
  if (pbox) {
    pbox.checked = state.placeTags;
    pbox.addEventListener('change', () => togglePlaceTags(pbox.checked));
  }

  /* N0484 */
  const dbox = document.getElementById('develop-bg');
  const dparts = document.getElementById('dev-parts');
  if (dparts) {
    DEV_PARTS.forEach((pt) => {
      const group = document.createElement('div');
      group.className = 'dev-group';
      group.dataset.part = pt.key;

      const lab = document.createElement('label');
      lab.className = 'dev-part';
      lab.title = pt.note;
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.dataset.part = pt.key;
      box.checked = !!state.devParts[pt.key];
      box.addEventListener('change', () => {
        state.devParts[pt.key] = box.checked;
        drawDevelop();
      });
      const span = document.createElement('span');
      span.textContent = pt.label;
      lab.appendChild(box);
      lab.appendChild(span);
      group.appendChild(lab);

      /* N0485 */
      const subs = document.createElement('div');
      subs.className = 'dev-subs';
      subs.dataset.part = pt.key;
      subs.hidden = true;
      (DEV_PICKS[pt.key] || []).forEach((k) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'dev-opt';
        btn.dataset.part = pt.key;
        btn.dataset.pick = k.id;
        btn.setAttribute('aria-pressed', String(devPicked(pt.key, k.id)));
        if (k.done) btn.title = '끝난 것 — 기본으로 감춥니다';
        const c = devPickColor(pt.key, k);
        /* N0486 */
        const shape = (k.r ? ' is-dot' : '') + (k.hollow ? ' is-hollow' : '')
          + (k.r >= 8 ? ' is-big' : '');
        btn.innerHTML = `<i class="dev-sw${c ? '' : ' is-none'}${shape}"`
          + `${c ? ` style="${k.hollow ? 'border-color' : 'background'}:${c}"` : ''}></i>`
          + `<span>${escapeHtml(k.label)}</span>`;
        btn.addEventListener('click', () => {
          const now = !(btn.getAttribute('aria-pressed') === 'true');
          btn.setAttribute('aria-pressed', String(now));
          state.devPick[pt.key][k.id] = now;
          drawDevelop();
        });
        subs.appendChild(btn);
      });
      if (subs.children.length) group.appendChild(subs);
      dparts.appendChild(group);
    });
    updateDevSubs();
  }
  if (dbox) {
    dbox.checked = state.develop;
    if (state.develop) openSheet('develop');
    dbox.addEventListener('change', () => {
      toggleDevelop(dbox.checked);
      // N0487
      if (dbox.checked) {
        if (openSheetCat() !== 'develop') openSheet('develop');
      } else if (openSheetCat() === 'develop') {
        closeSheet();
      }
    });
  }

  // N0488
  const cbox = document.getElementById('cadastral-bg');
  if (cbox) {
    cbox.checked = state.cadastral;
    cbox.addEventListener('change', () => toggleCadastral(cbox.checked));
  }

  // N0489
  const gbox = document.getElementById('gate-bg');
  if (gbox) {
    gbox.checked = state.showGates;
    gbox.addEventListener('change', () => {
      state.showGates = gbox.checked;
      // N0490
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

/* N0491 */
if (typeof window.tojiAdminNav === 'function') window.tojiAdminNav(myAccess().admin);

boot();

// N0492
setTimeout(viewersOnMove, 3000);


/* N0493 */

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

/* N0494 */
function placeKey(levelKey, member, name) {
  const cd = String((member || {}).sigungu_cd || '');
  if (levelKey === 'sido') return `s:${name}`;
  if (levelKey === 'si') return `g:${cd.slice(0, 2)}:${name}`;
  return `g:${cd}`;
}

/* N0495 */
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

/* N0496 */
function viewerLine(pk) {
  // N0497
  const n = (viewers.stat.get(pk) || {}).n24 || 0;
  if (!n) return '';
  return `<s>${n}명 조회 중</s>`;
}

/* N0498 */
function viewerStar(it) {
  return viewers.star && viewers.star === it.pk ? '<mark>★</mark>' : '';
}

/* N0499 */
function viewersOnMove(items) {
  if (!window.SB) return;
  if (items) viewers.items = items;
  const list = viewers.items || [];
  const tag = viewerCenterTag(list);
  // N0500
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

  // N0501
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

/* N0502 */
async function viewersChannel(sg) {
  // N0503
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
    // N0504
    viewers.asked = '';
    viewersStats((viewers.items || []).map((x) => x.pk).filter(Boolean).slice(0, VIEW_MAX_KEYS))
      .then(() => { if (viewers.ch === ch) drawLandPrice(); });
    drawLandPrice();
  });
  // N0505
  viewers.ch = ch;
  ch.subscribe((status) => {
    if (status === 'SUBSCRIBED' && viewers.ch === ch) viewersTrack();
  });
}

/* N0506 */
function viewersTrack() {
  if (!viewers.ch || !viewers.pk) return;
  if (viewers.sent === viewers.pk) return;
  viewers.sent = viewers.pk;
  try { viewers.ch.track({ p: viewers.pk }); } catch { /* 아직 안 붙었다 */ }
}

/* N0507 */
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
    // N0508
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

/* N0509 */
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
