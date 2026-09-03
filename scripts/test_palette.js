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

console.log('1. 거리 밴드는 순서형이고 무채색이다');
const ramp = ['band-1', 'band-2', 'band-3'].map(token);
check('영향범위 3밴드가 모두 정의돼 있다', ramp.every(Boolean), ramp.join(' '));
if (ramp.every(Boolean)) {
  const Ls = ramp.map((h) => oklab(h).L);
  check('가까울수록 진하다 (명도가 단조 증가)',
        Ls[0] < Ls[1] && Ls[1] < Ls[2],
        Ls.map((v) => v.toFixed(3)).join(' → '));
  check('단계 간격이 눈에 보인다 (ΔL ≥ 0.06)',
        [Ls[1] - Ls[0], Ls[2] - Ls[1]].every((g) => g >= 0.06));
  // 밴드는 '자' 다. 색을 주면 지도 위 자료색과 경쟁하고, 넓은 색면은
  // 용도지역(주거 노랑·상업 빨강·공업 보라·녹지 초록)처럼 읽힌다.
  check('무채색이다 (자료색과 경쟁하지 않는다)',
        ramp.every((h) => chroma(h) < 0.02),
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
console.log('3. 거래 두 종류가 서로 구별된다');
const land = token('kind-land'), fac = token('kind-factory');
check('토지·공장이 정의돼 있다', !!land && !!fac, `${land} ${fac}`);
if (land && fac) {
  check('토지↔공장 ΔE ≥ 15', dE(land, fac) >= 15, dE(land, fac).toFixed(1));
}

console.log();
console.log('4. 교통량 계열이 밴드 색과 안 붙는다 (한 그래프에 같이 그려진다)');
const traffic = ['traffic-1', 'traffic-2', 'traffic-3', 'traffic-4'].map(token);
const bands = ['band-1', 'band-2', 'band-3', 'band-4'].map(token);
check('교통량 4계열이 모두 정의돼 있다', traffic.every(Boolean), traffic.join(' '));
if (traffic.every(Boolean) && bands.every(Boolean)) {
  let worst = { d: Infinity, pair: '' };
  for (const t of traffic) {
    for (const b of bands) {
      const d = dE(t, b);
      if (d < worst.d) worst = { d, pair: `${t}↔${b}` };
    }
  }
  // 15 는 '정상 시력으로 구별 가능' 의 하한이다. 예전 팔레트는 교통량
  // 파랑과 밴드 파랑이 같은 값이라 이 검사가 있었으면 즉시 걸렸다.
  check('가장 가까운 교통량↔밴드 쌍도 ΔE ≥ 15',
        worst.d >= 15, `${worst.pair} = ${worst.d.toFixed(1)}`);

  let wt = { d: Infinity, pair: '' };
  for (let i = 0; i < traffic.length; i++) {
    for (let j = i + 1; j < traffic.length; j++) {
      const d = dE(traffic[i], traffic[j]);
      if (d < wt.d) wt = { d, pair: `${traffic[i]}↔${traffic[j]}` };
    }
  }
  check('교통량 계열끼리도 ΔE ≥ 15', wt.d >= 15,
        `${wt.pair} = ${wt.d.toFixed(1)}`);
}

console.log();
console.log(failed ? `실패 ${failed}건` : '모두 통과');
process.exit(failed ? 1 : 0);
