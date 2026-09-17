/* 가이드 쪽 구조 검사 — 네트워크 없이 파일만 본다.

   2026-09-17 지시 둘을 못 박는다.

     · "'이벤트 페이지'를 '홈'으로 수정"
     · "'법령과 조례'에서 '공장, 창고 설립 비용 - 항목표' 내용을 …
        '06. 공장, 창고 비용'으로 별도 가이드 탭 신규로 생성.
        공사-건축 창고/공장 금액은 (TBD)로 수정,
        계산 순서도 가이드 06번으로 같이 이동"

   **옮긴 것은 지운 것과 다르다.** 05 에서 사라졌는지만 보면, 06 을 만들다
   실수로 빠뜨려도 검사는 초록이다. 그래서 세 쪽을 같이 본다 — 05 에 없고,
   06 에 있고, 목차가 06 으로 간다.

   실행: node scripts/test_guide.js   */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const G = (f) => fs.readFileSync(path.join(ROOT, 'public/guide', f), 'utf8');
let bad = 0;
function ok(name, cond, detail) {
  console.log(`  ${cond ? '통과' : '실패'}  ${name}${cond || !detail ? '' : ' — ' + detail}`);
  if (!cond) bad++;
}

const pages = fs.readdirSync(path.join(ROOT, 'public/guide')).filter((f) => f.endsWith('.html'));

console.log('\n1. 바닥 링크 이름 (지시: 이벤트 페이지 → 홈)');
// 목차 한 장 + 주제 여섯 장.
ok('가이드가 목차 + 일곱 주제다', pages.length === 8, pages.join(', '));
for (const f of pages) {
  const s = G(f);
  ok(`${f} — '이벤트 페이지' 가 없다`, !s.includes('이벤트 페이지'));
  ok(`${f} — 바닥에 '홈' 링크가 있다`, /<a href="\/">홈<\/a>/.test(s));
}

console.log('\n2. 06 · 공장·창고 비용 쪽이 생겼다');
const cost = G('cost.html');
ok('파일이 있다', cost.length > 0);
ok('머리에 06 이라고 적는다', cost.includes('06 · 공장·창고 비용'));
ok('항목표가 여기 있다', cost.includes('<h2>항목표</h2>'));
ok('계산 순서도 여기 있다', cost.includes('<h2>계산 순서</h2>'));
// 표가 통째로 왔는지. 다섯 묶음 머리줄(전용·부담금·세금·인허가·공사)이 재료다.
for (const grp of ['전용', '부담금', '세금', '인허가', '공사']) {
  ok(`  '${grp}' 묶음이 왔다`, cost.includes(`class="grp">${grp}<`));
}
// 계산 순서 일곱 마디가 다 왔는가. 여섯만 와도 글은 말이 되므로 수를 센다.
const steps = (cost.match(/<li><b>/g) || []).length;
ok('계산 순서가 일곱 마디다', steps === 7, `${steps}마디`);
// ◎/○/△ 풀이는 표 없이는 뜻이 없다 — 표와 함께 왔어야 한다.
ok('◎/○/△ 풀이가 표 위에 있다', /class="legend"/.test(cost));
ok('풀이를 그릴 css 도 있다', /\.legend\{/.test(cost));

console.log('\n3. 공사·건축 금액은 (TBD) 다 (지시)');
ok('건축 줄이 (TBD) 라고 적는다',
   /<th>건축<\/th><td><strong>\(TBD\)<\/strong>/.test(cost));
// 어림값이 남아 있으면 그것이 근거인 양 쓰인다. 저장소 어디에도 없어야 한다.
for (const f of pages) {
  ok(`${f} — 옛 어림 단가가 안 남았다`, !G(f).includes('150~250만원'));
}

console.log('\n4. 05 는 가부·한도까지만 다룬다');
const law = G('law.html');
ok('비용 항목표가 05 에 없다', !law.includes('공장·창고 설립 비용'));
// **절이 없어야 한다**는 뜻이지 그 말이 없어야 한다는 뜻이 아니다 —
// 05 는 "표와 계산 순서는 06 에 있습니다" 라고 길을 알려 주어야 한다.
ok('계산 순서 절이 05 에 없다', !/<h[23]>계산 순서<\/h[23]>/.test(law));
ok('05 가 06 으로 보낸다', law.includes('href="/guide/cost"'));
// 옮겼다는 사실 자체를 적어 둔다 — 없어진 줄 알고 다시 쓰는 일을 막는다.
ok('어디로 갔는지 05 가 말한다', law.includes('06 · 공장·창고 비용'));
// 표가 갔으니 그 표만 쓰던 줄풀이 css 도 같이 갔어야 한다 (죽은 규칙 금지).
ok('05 에 남은 죽은 css 가 없다', !/\.legend\{/.test(law));

console.log('\n5. 목차가 일곱 칸이다');
const idx = G('index.html');
const cards = [...idx.matchAll(/<a class="card" href="([^"]+)"/g)].map((m) => m[1]);
ok('칸이 일곱이다', cards.length === 7, cards.join(' · '));
ok('여섯째가 /guide/cost 다', cards[5] === '/guide/cost', cards[5]);
ok('일곱째가 /guide/traffic 다', cards[6] === '/guide/traffic', cards[6]);
ok('번호가 01~07 이다',
   ['01', '02', '03', '04', '05', '06', '07'].every((n) => idx.includes(`<div class="n">${n}</div>`)));
ok('05 설명에서 비용 항목을 뺐다', !idx.includes('공장·창고 설립 비용 항목'));

/* 07 · 왜 교통량인가 (지시 2026-09-17: "홈화면의 아래 내용을 7번 항목
   (여기서만) 으로 옮겨주세요").

   **'여기서만' 이 요점이다.** 옮겼다고 하고 첫 화면에 그대로 두면 같은
   이야기가 두 곳이 되고, 숫자를 다시 뽑는 날 한쪽만 바뀐다. 그래서
   새 쪽에 있는지와 첫 화면에서 빠졌는지를 같이 본다. */
console.log('\n5-B. 왜 교통량인가는 가이드 07 에만 있다');
const tr = G('traffic.html');
const land = fs.readFileSync(path.join(ROOT, 'public/index.html'), 'utf8');
ok('07 쪽이 있다', tr.includes('07 · 왜 교통량인가'));
// **why-steps 안에서만 센다.** 쪽 전체의 <li><b> 는 신뢰 수치(why-kpi)
// 까지 잡아 여섯이 된다 — 처음 그렇게 세어 놓고 화면이 틀린 줄 알았다.
const steps3 = (tr.split('class="why-steps"')[1] || '').split('</ol>')[0];
ok('세 마디 설명이 옮겨 왔다', (steps3.match(/<li><b>/g) || []).length === 3,
   String((steps3.match(/<li><b>/g) || []).length));
ok('그림과 표가 옮겨 왔다',
   tr.includes('class="why-figs"') && tr.includes('class="why-table"')
   && (tr.match(/<figure class="why-fig"/g) || []).length === 3);
ok('신뢰 수치도 옮겨 왔다', tr.includes('class="why-kpi"'));
ok('스타일도 같이 왔다 (빈 칸만 옮기지 않았다)', /\.why-line\{/.test(tr));
ok('생성 구간 표시가 07 에 있다',
   tr.includes('<!-- why:start -->') && tr.includes('<!-- why:end -->'));
ok('첫 화면에는 그 덩어리가 없다',
   !land.includes('<section id="why">') && !land.includes('<!-- why:start -->')
   && !/\.why-figs\{/.test(land));
ok('첫 화면이 어디로 갔는지 적어 둔다', land.includes('/guide/traffic'));
// 숫자를 다시 뽑는 스크립트가 옛 파일을 채우면 안 된다.
const bw = fs.readFileSync(path.join(ROOT, 'scripts/build_why.py'), 'utf8');
ok('build_why.py 가 07 에 갈아 끼운다',
   /TARGET = os\.path\.join\('public', 'guide', 'traffic\.html'\)/.test(bw));

console.log('\n6. 새 쪽도 다른 쪽과 같은 껍데기를 쓴다');
ok('머리띠가 있다', cost.includes('class="sitebar-brand"'));
ok('Admin 링크는 기본이 숨김',
   cost.includes('href="/admin" data-admin-link hidden') && cost.includes('/lib/adminnav.js'));
ok('테마 토큰·전환을 쓴다',
   cost.includes('/lib/theme.css') && cost.includes('data-theme-switch'));
ok('가이드 공통 css 를 쓴다', cost.includes('/guide/style.css'));
ok('GA 초기화가 head 인라인이다',
   cost.indexOf("gtag('config'") > 0 && cost.indexOf("gtag('config'") < cost.indexOf('<body>'));

console.log(bad ? `\n${bad}건 실패` : '\n모두 통과');
process.exit(bad ? 1 : 0);
