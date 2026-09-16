/* 주소 검색 — 같은 이름의 딴 동네를 집지 않는가 (2026-09-16 지시).
 *
 *   "주소 검색이 이상합니다 (대구)"
 *   "도로명 주소 입력시 오류 발생"
 *
 * 받은 캡처에서 '대구광역시 북구 금호동 834' 를 쳤더니 제안이
 * '전남광주통합특별시 대구광역시 북구 금호동 834' 로 나왔고, '대구광역시
 * 중구 동성로2가 5-2' 는 '서울특별시 …' 가 앞에 붙었다.
 *
 * regions 를 보면 까닭이 그대로 있다.
 *
 *   북구 4곳 → 전남광주통합특별시 · 부산 · 대구 · 울산   ← 첫 줄이 광주
 *   중구 4곳 → 서울특별시 · 대구 · 대전 · 울산            ← 첫 줄이 서울
 *
 * 이름만으로 find 하면 **첫 줄**이 잡힌다. 사용자가 시·도를 이미 쳤는데도
 * 딴 시·도가 앞에 붙는 것이다. 이 검사는 그 자리를 잠근다 — 네이버 지도
 * 흉내가 아니라, **친 글에 있는 시·도를 존중하는가**만 본다.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
let FAIL = 0;
function check(name, ok, note) {
  console.log(`  ${ok ? '통과' : '실패'}  ${name}${note ? ' — ' + note : ''}`);
  if (!ok) FAIL += 1;
}

// app.js 를 통째로 돌리지 않고 두 함수만 떼어 온다 — 지도도 DOM 도 없다.
const src = fs.readFileSync(path.join(ROOT, 'public/app/app.js'), 'utf8');
const grab = (name) => {
  const i = src.indexOf(`function ${name}(`);
  if (i < 0) throw new Error(`${name} 을 못 찾았습니다`);
  let depth = 0; let j = src.indexOf('{', i);
  for (let k = j; k < src.length; k += 1) {
    if (src[k] === '{') depth += 1;
    else if (src[k] === '}') { depth -= 1; if (!depth) { j = k; break; } }
  }
  return src.slice(i, j + 1);
};

const regions = JSON.parse(
  fs.readFileSync(path.join(ROOT, 'public/app/data/regions.json'), 'utf8'));

const ctx = { console, state: { regions }, window: {} };
vm.createContext(ctx);
vm.runInContext(
  [grab('findSido'), grab('findSigungu'), grab('findAddressText'),
   'const SIDO_BY_PREFIX = {};'].join('\n'), ctx);

console.log('주소 검색 — 같은 이름의 딴 동네\n');

// 1. 시·도를 알아듣는가 (긴 이름도 줄인 이름도)
const sido = (q) => vm.runInContext(
  `findSido(${JSON.stringify(q.split(' '))}, state.regions)`, ctx);
check("'대구광역시' 를 시·도로 읽는다",
      sido('대구광역시 북구 금호동 834') === '대구광역시', sido('대구광역시 북구'));
check("'대구' 라고만 쳐도 알아듣는다",
      sido('대구 중구 동성로2가') === '대구광역시', sido('대구 중구'));
check('시·도가 없으면 빈칸을 돌려준다',
      sido('곤지암읍 건업리 140-25') === '', `'${sido('곤지암읍 건업리')}'`);

// 2. **핵심.** 같은 이름의 시·군·구 중 친 시·도의 것을 고르는가
const sg = (q) => {
  const w = JSON.stringify(q.split(' '));
  return vm.runInContext(
    `(findSigungu(${w}, state.regions, findSido(${w}, state.regions))||{}).sido`,
    ctx);
};
check("'대구광역시 북구' 는 대구를 집는다 (광주 아님)",
      sg('대구광역시 북구 금호동 834') === '대구광역시',
      sg('대구광역시 북구 금호동 834'));
check("'대구광역시 중구' 는 대구를 집는다 (서울 아님)",
      sg('대구광역시 중구 동성로2가 5-2') === '대구광역시',
      sg('대구광역시 중구 동성로2가 5-2'));
check("'부산광역시 북구' 는 부산을 집는다",
      sg('부산광역시 북구 구포동 1') === '부산광역시',
      sg('부산광역시 북구 구포동 1'));

// 3. 제안 글에 엉뚱한 시·도가 앞에 붙지 않는가 (받은 캡처 그대로)
const text = (q) => vm.runInContext(
  `findAddressText(${JSON.stringify(q)}, [])`, ctx);
const a = text('대구광역시 북구 금호동 834');
check('제안이 친 글을 그대로 둔다 (대구 북구)',
      a === '대구광역시 북구 금호동 834' && !/광주|전남/.test(a), a);
const b = text('대구광역시 중구 동성로2가 5-2');
check('제안이 친 글을 그대로 둔다 (대구 중구)',
      b === '대구광역시 중구 동성로2가 5-2' && !/서울/.test(b), b);

// 4. 시·도를 안 쳤으면 붙여 주는 것은 그대로 (예전 동작을 안 깬다)
const c = text('안성시 공도읍 1');
check('시·도를 안 쳤으면 앞에 붙여 준다', /^경기도 /.test(c), c);

/* 5. **이름이 두 낱말인 시·군·구.** regions 에 '성남시 분당구' 로
      들어 있어, 낱말을 하나씩만 견주면 영영 안 맞았다 — 이 자리는 내
      변경 이전부터 비어 있던 곳이다. */
const d = text('성남시 분당구 정자동 1');
check('두 낱말짜리 시·군·구도 알아본다', /^경기도 /.test(d), d);
check("'분당구' 만 쳐도 경기도를 붙인다", /^경기도 /.test(text('분당구 정자동 1')),
      text('분당구 정자동 1'));

console.log('\n' + (FAIL ? `실패 ${FAIL}건` : '모두 통과'));
process.exit(FAIL ? 1 : 0);
