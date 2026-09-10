/* 팔레트가 '서로 다른 색' 이 아니라 **구별되는 색** 인지 검사한다.
 *
 * 예전 검사는 밴드 색이 전부 다르기만 하면 통과했다. #C62828(0-1km)과
 * #C25E00(1-3km)은 서로 다른 값이지만 OKLab 거리가 10.2 로, 정상 시력으로도
 * 구별 한계(15) 아래였다. 가장 중요한 두 밴드가 안 구별되는데 검사는
 * 초록이었다.
 *
 * 여기서 보는 것
 *   1) 거리 밴드는 **순서형 램프** 다 — 한 색상, 가까울수록 진하게.
 *      무지개는 순서를 못 보여준다.
 *   2) 대조 밴드(마지막)는 중립이어야 한다 — 다섯 번째 계열로 읽히면 안 된다.
 *   3) 교통량 계열은 밴드 색과 안 붙어야 한다. 추이 차트가 둘을 한
 *      그래프에 그리기 때문이다.
 *
 * 색맹 시뮬레이션까지 하는 전체 검증은 설계할 때 dataviz 검증기로 돌렸다.
 * 여기서는 러너에서 의존성 없이 돌 수 있는 구조적 불변식만 못박는다.
 */
const fs = require('fs');
const path = require('path');

const CSS = fs.readFileSync(
  path.join(__dirname, '..', 'public', 'app', 'style.css'), 'utf8');

let failed = 0;
const check = (label, ok, note = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${note ? ` — ${note}` : ''}`);
  if (!ok) failed++;
};

const token = (name) => {
  const m = CSS.match(new RegExp(`--${name}\\s*:\\s*(#[0-9A-Fa-f]{6})`));
  return m ? m[1] : null;
};

// ── sRGB → OKLab ────────────────────────────────────────────────────
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
function oklab(hex) {
  const r = lin(parseInt(hex.slice(1, 3), 16) / 255);
  const g = lin(parseInt(hex.slice(3, 5), 16) / 255);
  const b = lin(parseInt(hex.slice(5, 7), 16) / 255);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return {
    L: 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    a: 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    b: 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  };
}
const chroma = (hex) => { const c = oklab(hex); return Math.hypot(c.a, c.b); };
const hueDeg = (hex) => {
  const c = oklab(hex);
  return (Math.atan2(c.b, c.a) * 180 / Math.PI + 360) % 360;
};
const dE = (x, y) => {
  const p = oklab(x), q = oklab(y);
  return Math.hypot(p.L - q.L, p.a - q.a, p.b - q.b) * 100;
};

console.log('1. 거리 밴드 3개가 서로 또렷이 구별된다');
// 화면에 그리는 밴드는 영향범위 3개까지다(위약 대조는 분석 전용이라
// 화면에서 뺐다). 동심원이라 **반지름이 이미 순서를 말하므로**, 색은
// 순서가 아니라 구분을 맡는다 — 명도 램프가 아니라 서로 다른 원색이다.
const ramp = ['band-1', 'band-2', 'band-3'].map(token);
check('영향범위 3밴드가 모두 정의돼 있다', ramp.every(Boolean), ramp.join(' '));
if (ramp.every(Boolean)) {
  let worst = { d: Infinity, p: '' };
  for (let i = 0; i < ramp.length; i++)
    for (let j = i + 1; j < ramp.length; j++) {
      const d = dE(ramp[i], ramp[j]);
      if (d < worst.d) worst = { d, p: `${ramp[i]}↔${ramp[j]}` };
    }
  check('세 밴드가 서로 ΔE ≥ 15', worst.d >= 15,
        `${worst.p} = ${worst.d.toFixed(1)}`);
  check('원색이다 (채도가 살아 있다)',
        ramp.every((h) => chroma(h) > 0.08),
        ramp.map((h) => chroma(h).toFixed(3)).join(' '));
}

console.log();
console.log('2. 영업소 4단계는 **색상**이 다르다 (명도만 다르면 확대 시 못 가린다)');
const tg = ['tg-1', 'tg-2', 'tg-3', 'tg-4'].map(token);
check('4단계가 모두 정의돼 있다', tg.every(Boolean), tg.join(' '));
if (tg.every(Boolean)) {
  const hues = tg.map(hueDeg);
  let minGap = 360;
  for (let i = 0; i < hues.length; i++)
    for (let j = i + 1; j < hues.length; j++) {
      let d = Math.abs(hues[i] - hues[j]);
      d = Math.min(d, 360 - d);
      minGap = Math.min(minGap, d);
    }
  check('색상이 서로 충분히 벌어져 있다 (≥ 40°)', minGap >= 40,
        `${minGap.toFixed(0)}° · ${hues.map((h) => h.toFixed(0)).join('/')}`);
  let worst = { d: Infinity, p: '' };
  for (let i = 0; i < tg.length; i++)
    for (let j = i + 1; j < tg.length; j++) {
      const d = dE(tg[i], tg[j]);
      if (d < worst.d) worst = { d, p: `${tg[i]}↔${tg[j]}` };
    }
  check('네 단계가 서로 ΔE ≥ 15', worst.d >= 15,
        `${worst.p} = ${worst.d.toFixed(1)}`);
  // 차가움 → 따뜻함이라야 색상이 달라도 순서를 잃지 않는다.
  const warm = tg.map((h) => { const c = oklab(h); return c.a; });
  check('차가운 색에서 따뜻한 색으로 간다 (순서를 잃지 않는다)',
        warm[0] < warm[3] && warm[1] < warm[3],
        warm.map((v) => v.toFixed(3)).join(' → '));
}

console.log();
console.log('3. 거래 두 종류가 서로 구별되고, 영업소 색과도 안 붙는다');
const land = token('kind-land'), fac = token('kind-factory');
check('토지·공장이 정의돼 있다', !!land && !!fac, `${land} ${fac}`);
if (land && fac) {
  check('토지↔공장 ΔE ≥ 15', dE(land, fac) >= 15, dE(land, fac).toFixed(1));

  // 보고된 문제(2026-09-04): "어느게 IC이고 어느게 거래건인지 구분이
  // 안됩니다." 모양으로 먼저 가르지만(원 vs 네모·마름모), 색까지 붙으면
  // 축소 배율에서 다시 뭉친다. 화면에 함께 있는 모든 색과 재 둔다.
  const ONSCREEN = {
    'tg-1': token('tg-1'), 'tg-2': token('tg-2'),
    'tg-3': token('tg-3'), 'tg-4': token('tg-4'),
    '신설': token('tg-new'), '미공개': token('tg-none'),
    'band-1': token('band-1'), 'band-2': token('band-2'), 'band-3': token('band-3'),
  };
  for (const [name, hex] of Object.entries(ONSCREEN)) {
    if (!hex) continue;
    const dl = dE(land, hex), df = dE(fac, hex);
    check(`토지·공장이 ${name} 과 안 붙는다 (ΔE ≥ 15)`,
          dl >= 15 && df >= 15, `토지 ${dl.toFixed(1)} · 공장 ${df.toFixed(1)}`);
  }

  // 원색으로 해달라는 요구였다. 채도가 낮으면 회색빛이 되어 배경에 묻힌다.
  check('토지·공장이 원색이다 (채도 ≥ .15)',
        chroma(land) >= .15 && chroma(fac) >= .15,
        `토지 ${chroma(land).toFixed(3)} · 공장 ${chroma(fac).toFixed(3)}`);
}

console.log();
console.log('4. 교통량 계열끼리 구별된다 (밴드와는 선 모양으로 가른다)');
// 추이 차트에는 교통량 4계열 + 지가 3밴드가 함께 들어간다. 일곱 색을
// 전부 구별되게 만드는 것은 색상환 안에서 불가능하다. 그래서 지가는
// 점선, 교통량은 실선으로 무리를 가르고(app.js trendSeriesFor), 색은
// 무리 안에서만 달라도 되게 했다. 지도에서 밴드가 점선인 것과도 말이 맞는다.
const traffic = ['traffic-1', 'traffic-2', 'traffic-3', 'traffic-4'].map(token);
check('교통량 4계열이 모두 정의돼 있다', traffic.every(Boolean), traffic.join(' '));
if (traffic.every(Boolean)) {
  let wt = { d: Infinity, p: '' };
  for (let i = 0; i < traffic.length; i++)
    for (let j = i + 1; j < traffic.length; j++) {
      const d = dE(traffic[i], traffic[j]);
      if (d < wt.d) wt = { d, p: `${traffic[i]}↔${traffic[j]}` };
    }
  check('교통량 계열끼리 ΔE ≥ 15', wt.d >= 15, `${wt.p} = ${wt.d.toFixed(1)}`);
}

console.log();
console.log('5. 신설 영업소가 네 구간 어느 것과도 안 붙는다');
const tgNew = token('tg-new');
const tiers = ['tg-1', 'tg-2', 'tg-3', 'tg-4'].map(token);
check('신설 색이 정의돼 있다', !!tgNew, String(tgNew));
if (tgNew && tiers.every(Boolean)) {
  const w = Math.min(...tiers.map((t) => dE(tgNew, t)));
  check('신설 ↔ 구간 최소 ΔE ≥ 15', w >= 15, w.toFixed(1));
}

console.log();
console.log('6. 통행량 미공개가 구간·신설과 안 붙는다');
// 이 상태는 지도에서 **속이 빈 점**으로 그립니다 — 모양이 먼저 갈라
// 줍니다. 그래도 테두리 색이 어느 구간과 비슷하면 작은 배율에서
// '통행량이 이만큼인 IC' 로 읽히므로, 색으로도 벌려 둡니다.
const tgNone = token('tg-none');
check('미공개 색이 정의돼 있다', !!tgNone, String(tgNone));
if (tgNone && tgNew && tiers.every(Boolean)) {
  const w = Math.min(...[...tiers, tgNew].map((t) => dE(tgNone, t)));
  check('미공개 ↔ 구간·신설 최소 ΔE ≥ 15', w >= 15, w.toFixed(1));
}

console.log();
console.log(failed ? `실패 ${failed}건` : '모두 통과');
process.exit(failed ? 1 : 0);
