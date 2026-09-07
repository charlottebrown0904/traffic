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
  trend: { id: null, scale: 'index', base: null, on: new Set() },
  activeTiers: new Set([0, 1, 2, 3, 'new', 'none']),
  // 용도지역 배경은 기본으로 켜 둔다 — 사장님이 요청하신 화면이다.
  zoning: true,
  tgYear: null, tgVehicle: 'total', dealFrom: null, dealTo: null,
  activeKinds: new Set(),
  parcelOnly: false, selected: null, showAllBands: false, tiers: null,
  token: null, broker: null, listings: [], scope: 'public', pickMode: false,
  apiAvailable: false, verdicts: null,
  verdictSets: {}, verdictKind: 'land',
  regions: null, showPop: true, popYear: null,
};

let map, tollgateLayer, tradeLayer, bandLayer, listingLayer, zoningLayer, popLayer;
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

  // 사장님 지시(2026-09-04): "모든 실거래는 초기 기본설정은 표기 끄는 것."
  // 거래가 2천 점이라 처음 화면이 온통 점으로 덮인다. 필요할 때 켠다.
  state.activeKinds = new Set();
  state.dealFrom = `${state.meta.year_min}-01`;
  state.dealTo = `${state.meta.year_max}-12`;

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
  // 행정구역 인구. 없으면 그 스위치만 숨긴다.
  try {
    const r = await fetch('/app/data/regions.json');
    if (r.ok) state.regions = await r.json();
  } catch (err) {
    state.regions = null;
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
  buildRank();
  buildTrend();
  buildMap();
  drawPopulation();
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

function wireTabs() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((t) => {
        const on = t === tab;
        t.classList.toggle('is-active', on);
        t.setAttribute('aria-selected', String(on));
      });
      document.querySelectorAll('.view').forEach((v) => v.classList.remove('is-active'));
      $(`#view-${tab.dataset.view}`).classList.add('is-active');
      if (tab.dataset.view === 'explore' && map) map.invalidateSize();
    });
  });
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

  const vSel = $('#tg-vehicle');
  [['total', '전체 차종']].concat(
    ((state.traffic || {}).vehicle_types || [])
      .map((v) => [String(v.code), v.label])
  ).forEach(([val, label]) => {
    const o = el('option', null, label);
    o.value = val;
    vSel.append(o);
  });
  vSel.value = state.tgVehicle;
  vSel.addEventListener('change', () => {
    state.tgVehicle = vSel.value;
    recolorTollgates();
  });

  // 구간 필터 — 예전 '분면 필터'(저평가·과열 등) 자리다. 분면은 평가라
  // 오해를 부르고, 지도 색과 뜻이 달라 혼란스러웠다. 지도 색과 필터가
  // 같은 것을 가리키는 편이 낫다.
  const tierBox = $('#tier-filters');
  TRAFFIC_LABEL.forEach((label, i) => {
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
  state.meta.kinds.forEach((kind) => {
    const label = el('label', 'check');
    const input = el('input');
    input.type = 'checkbox';
    // 처음에는 꺼 둔다 (state.activeKinds 가 비어 있는 것과 짝이 맞아야 한다).
    input.checked = state.activeKinds.has(kind);
    input.addEventListener('change', () => {
      input.checked ? state.activeKinds.add(kind) : state.activeKinds.delete(kind);
      refreshMap();
    });
    label.append(input, el('span', null, KIND_LABEL[kind] || kind));
    kinds.append(label);
  });

  // ── 실거래 기간: 시작·끝 년월 ──
  // 슬라이더는 '언제부터' 만 고를 수 있었다. 특정 구간(예: 2015-03 ~
  // 2018-06)을 보려면 끝도 정할 수 있어야 한다.
  const from = $('#deal-from'), to = $('#deal-to');
  from.min = to.min = `${state.meta.year_min}-01`;
  from.max = to.max = `${state.meta.year_max}-12`;
  from.value = `${state.meta.year_min}-01`;
  to.value = `${state.meta.year_max}-12`;
  const onRange = () => {
    state.dealFrom = from.value || null;
    state.dealTo = to.value || null;
    refreshMap();
  };
  from.addEventListener('change', onRange);
  to.addEventListener('change', onRange);

  $('#parcel-only').addEventListener('change', (e) => {
    state.parcelOnly = e.target.checked;
    refreshMap();
  });

  // 처음 그릴 때도 개수를 채운다. 안 하면 전부 0 으로 보인다.
  updateTierCounts();
}

function buildLegend() {
  // 위약 대조 밴드(가장 바깥)는 화면에 안 그린다 — 분석 절차이지
  // 사용자가 볼 것이 아니다. shownBands() 참고.
  $('#band-legend').innerHTML = shownBands()
    .map(([lo, hi], i) =>
      `<div class="row" style="--c:${bandColor(i)}">` +
      `<span class="ring"></span>${lo}–${hi} km</div>`)
    .join('');

  // 범례는 좁은 화면에서 접힌다(CSS). 여는 단추와 내용을 나눠 둔다 —
  // 지도를 키워 놓고 그 위를 12줄짜리 범례로 다시 덮으면 의미가 없다.
  const legend = $('#map-legend');
  // 범례도 지도와 같은 모양이어야 한다 — 파스텔 채움 + 진한 링.
  const qRow = (i) =>
    `<div class="row"><span class="sw" style="background:var(--tg-${i + 1});` +
    `border:1.5px solid #fff;box-shadow:0 0 0 1px rgba(0,0,0,.2)"></span>` +
    `${TRAFFIC_LABEL[i]}</div>`;
  legend.innerHTML =
    '<button type="button" class="legend-peek" aria-expanded="false">' +
    '<span aria-hidden="true">◍</span>범례</button>' +
    '<div class="legend-rows">' +
    // 지도에서 먼저 찾는 것은 거래와 매물이다. 그것을 위에 둔다.
    // 범례 스와치는 지도의 표식과 **같은 모양**이어야 한다. 지도에서는
    // 네모인데 범례에서는 동그라미면 눈으로 짝을 못 맞춘다.
    '<div class="grp">실거래</div>' +
    '<div class="row"><span class="sw sw-trade trade-land"></span>토지</div>' +
    '<div class="row"><span class="sw sw-trade trade-factory"></span>공장·창고</div>' +
    '<div class="grp">매물</div>' +
    '<div class="row"><span class="sw sw-listing"></span>등록 매물</div>' +
    `<div class="grp">영업소 · ${state.tgYear}년 교통량</div>` +
    TRAFFIC_LABEL.map((_, i) => qRow(i)).join('') +
    `<div class="row"><span class="sw" style="background:var(--tg-new);` +
    `border:2px solid var(--tg-new-ring)"></span>${state.tgYear}년 신설</div>` +
    // 속이 빈 점 = 값이 없다. 민자 운영사가 요금을 직접 걷는 노선이라
    // 도로공사 TCS 에 통행량이 없습니다 (마도 등).
    '<div class="row"><span class="sw" style="background:var(--surface);' +
    'border:2px solid var(--tg-none)"></span>통행량 미공개 (민자)</div>' +
    '<div class="grp">거리 밴드</div>' +
    shownBands().map(([lo, hi], i) =>
      `<div class="row" style="--c:${bandColor(i)}">` +
      `<span class="sw ring"></span>${lo}–${hi} km</div>`).join('') +
    popLegendRows() +
    '</div>';

  const peek = legend.querySelector('.legend-peek');
  peek.addEventListener('click', () => {
    const open = legend.classList.toggle('is-open');
    peek.setAttribute('aria-expanded', String(open));
  });
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
  if (note) note.textContent = message;
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
  state.rank.vehicle = 'g:total';
  renderRank();
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
    const g = r.growth == null
      ? '<span class="hint">—</span>'
      : `<span class="delta ${r.growth >= 0 ? 'up' : 'down'}">` +
        `${r.growth >= 0 ? '+' : ''}${(r.growth * 100).toFixed(1)}%</span>`;
    const region = [r.sido, r.sigungu].filter(Boolean).join(' ') ||
                   '<span class="hint">미상</span>';
    return `<tr>
      <td class="rank">${i + 1}</td>
      <td>${escapeHtml(r.name)}</td>
      <td>${region}</td>
      <td class="num bar"><span style="width:${width}%"></span><b>${num(r.value)}</b></td>
      <td class="num">${g}</td>
      <td class="num">${r.share == null ? '—' : (r.share * 100).toFixed(1) + '%'}</td>
    </tr>`;
  }).join('');

  const missing = data.rows.length - rows.length;
  $('#rank-note').innerHTML =
    `<strong>${state.rank.year}년 · ${escapeHtml(label)}</strong> — ` +
    `${data.unit || '일평균 통행량 (대/일)'}. 영업소 ${rows.length}개` +
    (missing > 0 ? ` (그해 자료가 없는 ${missing}개 제외)` : '') + '.<br>' +
    escapeHtml(data.note || '') +
    ' 순위는 통행량일 뿐 투자 가치가 아닙니다 — 통행이 많은 IC 는 대개 서울에 가깝고,' +
    ' 그 값은 이미 땅값에 반영돼 있습니다.';
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
const TRAFFIC_LABEL = ['1만대 미만', '1만~2만대', '2만~3만대', '3만대 이상'];
const TRAFFIC_TIERS = TRAFFIC_CUTS.length + 1;

/* 선택한 연도·차종의 영업소별 교통량. 둘 다 사용자가 고른다 —
 * 2003년 화물만 보고 싶을 수도 있고, 올해 전체를 보고 싶을 수도 있다. */
function tollgateVolumes(year, vehicle) {
  const tr = state.traffic || {};
  const years = tr.years || [];
  const types = tr.types || [];
  const yi = years.indexOf(year);
  if (yi < 0) return new Map();
  const vi = vehicle === 'total' ? -1 : types.indexOf(Number(vehicle));
  const out = new Map();
  (tr.rows || []).forEach((r) => {
    const yv = (r.v || [])[yi];
    if (!Array.isArray(yv)) return;
    const total = vi < 0
      ? yv.reduce((a, b) => a + (Number(b) || 0), 0)
      : (Number(yv[vi]) || 0);
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
  const vol = tollgateVolumes(year, state.tgVehicle);
  const fresh = newTollgates(year);
  const tier = new Map();
  vol.forEach((v, id) => {
    if (fresh.has(id)) { tier.set(id, 'new'); return; }
    let q = 0;
    while (q < TRAFFIC_CUTS.length && v >= TRAFFIC_CUTS[q]) q++;
    tier.set(id, q);
  });
  // 통행량 미공개 — 도로공사 TCS 에 한 해도 값이 없는 영업소. 민자
  // 운영사가 요금을 직접 걷는 노선이라 도로공사가 자료를 갖고 있지
  // 않다(마도 등). 0 으로 두면 '가장 한산한 IC' 로 줄을 서서 정반대의
  // 결론이 나오므로, 구간이 아니라 별도 상태로 둔다.
  (state.tollgates || []).forEach((t) => {
    if (t.no_traffic) tier.set(String(t.tollgate_id), 'none');
  });
  return { rank: tier, vol, cut: TRAFFIC_CUTS, fresh };
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
  drawPopulation();
  buildLegend();
}

function updateTierCounts() {
  const counts = {};
  (state.tiers ? state.tiers.rank : new Map()).forEach((q) => {
    counts[q] = (counts[q] || 0) + 1;
  });
  document.querySelectorAll('#tier-filters .quad-btn').forEach((btn) => {
    const t = btn.dataset.tier;
    const key = (t === 'new' || t === 'none') ? t : Number(t);
    btn.querySelector('.n').textContent = String(counts[key] || 0);
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
  map = L.map('map', { zoomControl: true, preferCanvas: true })
    .setView([36.5, 127.8], 7);
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
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '© OpenStreetMap',
  }).addTo(map);

  addZoningLayer();

  // 인구 원은 **가장 아래**에 깐다. 배경 맥락이지 읽을 값이 아니라,
  // 영업소나 거래를 가리면 안 된다. 370 은 배경 타일(200)보다 위,
  // 거래(380)와 밴드·영업소(400)보다 아래다.
  map.createPane('popPane').style.zIndex = 370;
  popLayer = L.layerGroup().addTo(map);
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
    if (state.zoning && map.getZoom() >= ZONING_MIN_ZOOM) askZoning(e.latlng);
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
    // 밴드는 **누를 수 없어야 한다.** 사장님 지적(2026-09-04):
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

/* 상단에서 '전체 IC 반경' 을 켜면 모든 영업소의 반경을 한 번에 그린다.
 * 어디가 비어 있는지, 어디가 겹치는지를 전국 단위로 보려는 용도라
 * 선을 얇게 하고 음영도 더 옅게 깐다 — 442곳을 진하게 그리면 지도가
 * 통째로 덮인다. */
function drawAllBands() {
  if (!map || !bandLayer) return;
  if (!state.showAllBands) return;
  bandLayer.clearLayers();
  const bands = shownBands();
  state.tollgates.forEach((t) => {
    if (!t.lat || !t.lon) return;
    for (let i = bands.length - 1; i >= 0; i--) {
      bandLayer.addLayer(bandRing(t.lat, t.lon, bands[i][1], i, false, true));
    }
  });
}

function visibleTrades() {
  // 거래에는 연·월이 다 있지만 화면 자료에는 연도만 실려 있다.
  // 년월 입력의 연도 부분으로 자른다 — 월까지 자르려면 export 에
  // deal_month 를 실어야 하고, 그건 파일이 커지는 값에 비해 이득이 적다.
  const fy = state.dealFrom ? Number(state.dealFrom.slice(0, 4)) : -Infinity;
  const ty = state.dealTo ? Number(state.dealTo.slice(0, 4)) : Infinity;
  return state.trades.filter((t) =>
    state.activeKinds.has(t.kind) &&
    t.deal_year >= fy && t.deal_year <= ty &&
    (!state.parcelOnly || t.geocode_level === 'parcel'));
}

function refreshMap() {
  if (!map) return;
  tollgateLayer.clearLayers();
  const rank = (state.tiers || {}).rank || new Map();
  state.tollgates.forEach((t) => {
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
  // 필터를 만질 때마다 밴드를 다시 그린다. 선택이 있으면 선택이 이긴다.
  if (state.showAllBands) {
    if (state.selected) selectTollgate(state.selected);
    else { bandLayer.clearLayers(); drawAllBands(); }
  }

  tradeLayer.clearLayers();
  visibleTrades().forEach((t) => tradeLayer.addLayer(tradeMarker(t)));
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
      }))
    : undefined;
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
const CADASTRAL_MIN_ZOOM = 15;

function addZoningLayer() {
  zoningLayer = L.layerGroup();
  // 색면 — 용도지역 네 장을 서버가 한 요청에 겹쳐 받아온다
  // (api/tile.js 의 LAYERS.zoning). 브이월드 공식 색이라 지적편집도를
  // 읽어온 분들에게는 설명이 필요 없다.
  L.tileLayer('/api/tile?layer=zoning&z={z}&y={y}&x={x}', {
    maxZoom: 19,
    minZoom: ZONING_MIN_ZOOM,
    // 위에 거래 점과 영업소가 얹히므로 반투명해야 한다. 불투명하면
    // 배경 지도의 도로까지 같이 가린다.
    opacity: .42,
    attribution: '용도지역 © 국토교통부 브이월드',
  }).addTo(zoningLayer);
  // 필지 경계선 — 지적편집도의 그 선. 이것이 있어야 '이 필지' 를
  // 눈으로 짚을 수 있다. 색면보다 깊은 배율에서만 켠다.
  L.tileLayer('/api/tile?layer=cadastral&z={z}&y={y}&x={x}', {
    maxZoom: 19,
    minZoom: CADASTRAL_MIN_ZOOM,
    opacity: .55,
  }).addTo(zoningLayer);
  if (state.zoning) zoningLayer.addTo(map);
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

function tradeMarker(t) {
  const factory = t.kind === 'factory';
  const coarse = t.geocode_level !== 'parcel';
  return L.marker([t.lat, t.lon], {
    // divIcon 을 쓰는 이유는 하나다 — Leaflet 의 circleMarker 는 원밖에
    // 못 그린다. 모양으로 가르려면 이 길뿐이다.
    icon: L.divIcon({
      className: 'trade-icon',
      html: '<i class="trade-mark ' + (factory ? 'trade-factory' : 'trade-land')
            + (coarse ? ' trade-coarse' : '') + '"></i>',
      iconSize: [TRADE_PX, TRADE_PX],
      iconAnchor: [TRADE_PX / 2, TRADE_PX / 2],
    }),
    pane: 'tradePane',
    // 표식을 눌러도 용도지역 말풍선이 뜨게 둔다. 거래 점 위가 곧
    // 그 땅이므로 막을 이유가 없다.
    interactive: false,
    keyboard: false,
    // 검사와 화면 양쪽이 같은 값을 본다.
    kind: t.kind,
    geocodeLevel: t.geocode_level || '',
  });
}

function selectTollgate(id) {
  const t = state.tollgates.find((x) => x.tollgate_id === id);
  if (!t) return;
  state.selected = id;
  renderDetail(t);
  if (!map) return;

  markers.forEach((m, key) => m.setStyle({ weight: key === id ? 4 : 2 }));
  // 전체 보기 중이면 얇은 밴드를 지우지 않고 그 위에 진하게 얹는다.
  // 지우면 '전체' 를 켜 둔 채로 하나를 눌렀을 때 나머지가 사라져,
  // 스위치가 꺼진 것처럼 보인다.
  if (state.showAllBands) {
    bandLayer.clearLayers();
    drawAllBands();
  } else {
    bandLayer.clearLayers();
  }
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
  box.innerHTML = '';
  box.append(el('h2', null, t.name || t.tollgate_id));
  box.append(el('div', 'sub',
    [t.sido, t.sigungu, t.route_no ? `노선 ${t.route_no}` : null].filter(Boolean).join(' · ')));

  const badge = el('span', 'badge', info.label);
  badge.style.setProperty('--c', info.color);
  box.append(badge);
  if (t.quadrant_note) box.append(el('p', 'hint', t.quadrant_note));

  const stats = el('div', 'stats');
  stats.append(
    statCard('교통량 증가율', pct(t.traffic_cagr), t.traffic_cagr),
    statCard('가격 증가율', pct(t.price_cagr), t.price_cagr),
    statCard('반경 내 거래', num(t.n_trades)),
    statCard('신뢰도', t.confidence || '—'));
  box.append(stats);

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

/* 인구 원은 크기가 곧 값이다. 색 스와치로는 설명이 안 되므로 **원 세 개**를
   실제 크기 비율로 그려 둔다 — 큰 것·중간·작은 것이 각각 몇 명인지. */
function popLegendRows() {
  const info = window.__pop || {};
  if (!state.showPop || !info.year) return '';
  // 지도와 **같은 크기**로 그린다. 범례 원이 지도 원보다 크거나 작으면
  // 짝을 못 맞춘다 — 크기가 곧 값인 표시라 그것이 유일한 단서다.
  return '<div class="grp">행정구역 인구 · ' + info.year + '년</div>' +
    POP_TIERS.map((t) =>
      `<div class="row"><span class="sw sw-pop" style="width:${t.r * 2}px;`
      + `height:${t.r * 2}px"></span>${t.label}</div>`).join('');
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
/* 크기를 **세 단**으로 끊는다 (2026-09-04 사장님 지시: "간단하게").
 *
 * 원 넓이를 인구에 그대로 비례시키면 크기가 235가지가 된다. 그러면 두 원을
 * 나란히 놓고도 어느 쪽이 큰지 눈으로 못 가른다 — 크기는 순서를 말할 때는
 * 좋지만 값을 읽는 데는 나쁘다. 세 단이면 한눈에 갈린다.
 *
 * 자르는 자리는 5만·20만·50만이다. 2025년 기준 49 / 75 / 102 / 9 곳으로
 * 나뉜다. 마지막 자리를 70만이 아니라 50만에 둔 이유 — 70만을 넘는 곳이
 * 남양주 한 곳뿐이라(729,754명) 단 하나에 시군구 하나만 든다. 50만이면
 * 9곳이라 '가장 큰 무리' 라고 부를 만하다. */
const POP_TIERS = [
  { max: 50000, r: 6, label: '5만 이하' },
  { max: 200000, r: 11, label: '20만 이하' },
  { max: 500000, r: 16, label: '50만 이하' },
  { max: Infinity, r: 22, label: '50만 초과' },
];
const popTier = (v) => POP_TIERS.find((t) => v <= t.max) || POP_TIERS[POP_TIERS.length - 1];

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

function drawPopulation() {
  const have = Array.isArray(state.regions) && state.regions.length > 0;
  // 자료가 없으면 스위치를 아예 안 보여준다. 눌러도 아무 일이 없는
  // 스위치가 있으면 사람은 고장으로 읽는다.
  const pswitch = document.getElementById('pop-switch');
  const pbox = document.getElementById('pop-bg');
  if (pswitch) pswitch.hidden = !have;
  if (pbox) pbox.checked = state.showPop && have;

  if (!map || !popLayer) return;
  popLayer.clearLayers();
  window.__pop = { year: null, n: 0, max: 0 };
  if (!state.showPop || !have) return;

  const year = popYear();
  if (!year) return;
  const vals = state.regions
    .map((r) => (r.pop || {})[year])
    .filter((v) => typeof v === 'number' && v > 0);
  if (!vals.length) return;
  const max = Math.max(...vals);

  state.regions.forEach((r) => {
    const v = (r.pop || {})[year];
    if (!(typeof v === 'number' && v > 0)) return;
    const marker = L.circleMarker([r.lat, r.lon], {
      pane: 'popPane',
      radius: popTier(v).r,
      color: cssVar('--pop-ring'),
      weight: 1,
      fillColor: cssVar('--pop-fill'),
      fillOpacity: .22,
      opacity: .55,
    });
    marker.bindTooltip(
      `${r.name} · ${year}년 인구 ${v.toLocaleString('ko-KR')}명`
      + '<br><em>점 위치는 법정동 중심점의 중앙값(대표점)입니다</em>',
      { direction: 'top' });
    popLayer.addLayer(marker);
  });
  window.__pop = { year, n: popLayer.getLayers ? popLayer.getLayers().length : 0, max };
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

/* 모바일 필터 접기.
 *
 * 좁은 화면에서는 접은 채로 시작한다. 필터가 펼쳐진 채로 지도 위에 있으면
 * 지도를 보려고 매번 스크롤해야 하고, 지도가 화면 아래쪽 조각으로 남는다.
 * 폭 기준은 CSS 의 56rem 미디어쿼리와 같은 값을 쓴다 — 둘이 어긋나면
 * 데스크톱에서 필터가 사라지거나 모바일에서 단추가 안 보인다.
 *
 * 접었다 펴면 지도 높이가 바뀌므로 Leaflet 에 알려줘야 한다. 안 그러면
 * 새로 드러난 부분이 회색으로 남는다.
 */
(function foldRail() {
  const rail = document.querySelector('.rail');
  const btn = document.getElementById('rail-toggle');
  if (!rail || !btn) return;
  const narrow = () => window.matchMedia('(max-width:56rem)').matches;

  const apply = (folded) => {
    rail.classList.toggle('is-folded', folded);
    btn.setAttribute('aria-expanded', String(!folded));
    if (map) setTimeout(() => map.invalidateSize(), 220);
  };

  if (narrow()) apply(true);
  btn.addEventListener('click', () => apply(!rail.classList.contains('is-folded')));

  // 가로/세로를 돌리거나 창을 넓히면 데스크톱 배치로 돌아간다. 접힌 상태가
  // 남아 있으면 넓은 화면에서 필터가 통째로 사라진다.
  window.matchMedia('(max-width:56rem)').addEventListener('change', (e) => {
    apply(e.matches);
  });
})();

/* 상단 '전체 IC 반경' 스위치. */
(function allBandsSwitch() {
  const zbox = document.getElementById('zoning-bg');
  if (zbox) {
    zbox.checked = state.zoning;
    zbox.addEventListener('change', () => toggleZoning(zbox.checked));
  }

  // 이 함수는 스크립트를 읽자마자 돈다 — 자료를 받기 **전**이다.
  // 그래서 여기서는 누름만 잇고, 보일지 말지는 drawPopulation 이 정한다.
  // 여기서 state.regions 를 보면 항상 비어 있어 스위치가 영영 안 뜬다.
  const pbox = document.getElementById('pop-bg');
  if (pbox) {
    pbox.addEventListener('change', () => {
      state.showPop = pbox.checked;
      drawPopulation();
    });
  }

  const box = document.getElementById('all-bands');
  if (!box) return;
  box.addEventListener('change', () => {
    state.showAllBands = box.checked;
    if (!map || !bandLayer) return;
    bandLayer.clearLayers();
    if (box.checked) {
      drawAllBands();
    } else if (state.selected) {
      // 켜기 전에 고른 영업소가 있으면 그것만 다시 그린다.
      selectTollgate(state.selected);
    }
  });
})();

boot();
