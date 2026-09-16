/* QR 부호기 검사 — **널리 쓰이는 부호기와 모듈 하나하나를 맞춰 본다.**
 *
 * 눈으로 봐서는 맞는지 알 수 없다. 그럴듯하게 그려지면서 안 찍히는 QR 이
 * 가장 나쁘다 — 인쇄해서 뿌린 뒤에야 안다. 그래서 대조 부호기를 오라클로
 * 두고 29×29 또는 그 이상의 칸을 전부 견준다.
 *
 * 대조 부호기(qrcode)는 **검사에만 쓴다.** 배포되는 코드에는 의존성이 없다
 * — 저장소에 package.json 을 두지 않는 것이 이 프로젝트의 규칙이다.
 * 대조본이 없으면 그 절은 건너뛰고 그렇다고 적는다 (조용히 통과시키지 않는다).
 *
 * 실행: node scripts/test_qr.js   */
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const QR = require(path.join(ROOT, 'public/lib/qr.js'));

let bad = 0;
function ok(name, cond, detail) {
  console.log(`  ${cond ? '통과' : '실패'}  ${name}${cond || !detail ? '' : ' — ' + detail}`);
  if (!cond) bad++;
}

const CASES = [
  'https://toji.fyi/l/kakao-0916',
  'https://toji.fyi/l/naver-cpc-post01',
  'https://toji.fyi/',
  'https://toji.fyi/l/a',
  'https://toji.fyi/?utm_source=naver&utm_medium=cpc&utm_campaign=launch&utm_content=0916',
  'https://toji.fyi/l/offline-' + 'x'.repeat(28),
];

console.log('\n1. 모양이 규격대로다');
const r = QR.encode(CASES[0]);
ok('버전 3 · 29칸', r && r.size === 29 && r.version === 3, r ? `v${r.version} ${r.size}` : '없음');
ok('탐지 무늬 왼쪽 위', r.modules[0][0] === 1 && r.modules[0][6] === 1 && r.modules[1][1] === 0);
ok('탐지 무늬 세 귀퉁이', r.modules[0][r.size - 1] === 1 && r.modules[r.size - 1][0] === 1);
ok('오른쪽 아래에는 탐지 무늬가 없다', r.modules[r.size - 1][r.size - 1] === 0);
ok('타이밍 줄이 번갈아 간다',
  r.modules[6][8] === 1 && r.modules[6][9] === 0 && r.modules[6][10] === 1);
ok('어두운 모듈이 있다', r.modules[r.size - 8][8] === 1);
ok('모듈은 0 또는 1 뿐이다 (빈칸 -1 이 남지 않았다)',
  r.modules.every((row) => row.every((v) => v === 0 || v === 1)));

console.log('\n2. 길이에 따라 버전이 올라간다');
let prev = 0, mono = true;
for (const t of ['x', 'x'.repeat(30), 'x'.repeat(60), 'x'.repeat(120)]) {
  const e = QR.encode(t);
  if (!e || e.version < prev) mono = false;
  prev = e ? e.version : prev;
}
ok('글이 길수록 버전이 안 줄어든다', mono);
ok('버전 10 을 넘는 글은 받지 않는다 (지어내지 않고 null)',
  QR.encode('x'.repeat(400)) === null);

console.log('\n3. SVG');
const s = QR.svg(CASES[0]);
ok('SVG 가 나온다', typeof s === 'string' && s.indexOf('<svg') === 0);
ok('조용한 테두리 4모듈 (없으면 못 읽는다)', /viewBox="0 0 37 37"/.test(s));
ok('배경이 흰색으로 채워진다 (어두운 화면에서 반전되면 못 읽는다)', /<rect[^>]*fill="#fff"/.test(s));
ok('읽어 주는 이름표가 있다', /aria-label="QR 코드"/.test(s));

console.log('\n4. 대조 부호기와 모듈 전체를 맞춘다');
let oracle = null;
for (const p of ['qrcode',
  '/tmp/node_modules/qrcode']) {
  try { oracle = require(p); break; } catch (e) { /* 다음 후보 */ }
}
if (!oracle) {
  console.log('  건너뜀  대조 부호기(qrcode)가 없습니다 — 이 절은 확인하지 못했습니다.');
  console.log('          설치: npm i qrcode (검사 전용. 배포 코드에는 의존성이 없습니다)');
} else {
  /* **바이트 모드로 못 박고 견준다.** 대조 부호기는 모드를 섞어 줄인다 —
     'https://toji.fyi/l/kakao-' 는 바이트, 끝의 '0916' 은 숫자 모드로 쪼갠다.
     그러면 같은 글이라도 그림이 달라지는데, 둘 다 맞는 QR 이다. 우리는
     섞지 않으므로 대조본도 안 섞게 하고 맞춰야 사과와 사과를 견준다.
     (섞지 않아 가끔 버전이 하나 커질 수 있다 — 우리 링크 길이에서는
      29칸이 33칸이 되는 정도이고, 못 읽는 문제는 아니다.) */
  for (const t of CASES) {
    const mine = QR.encode(t);
    const ref = oracle.create([{ data: t, mode: 'byte' }], { errorCorrectionLevel: 'M' });
    const n = ref.modules.size;
    let same = mine && mine.size === n;
    let firstDiff = null;
    if (same) {
      for (let y = 0; y < n && !firstDiff; y++) {
        for (let x = 0; x < n; x++) {
          const a = mine.modules[y][x];
          const b = ref.modules.data[y * n + x] ? 1 : 0;
          if (a !== b) { firstDiff = `(${y},${x}) 우리=${a} 대조=${b}`; same = false; break; }
        }
      }
    }
    ok(`v${ref.version} ${n}×${n} — ${t.slice(0, 44)}${t.length > 44 ? '…' : ''}`,
      same, firstDiff || (mine ? `크기 ${mine.size} vs ${n}` : '못 만들었다'));
  }
}

console.log(bad ? `\n${bad}건 실패` : '\n모두 통과');
process.exit(bad ? 1 : 0);
