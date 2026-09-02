/* 교통량 순위 탭(지시4)과 색 구분(지시5) 검사.

   순위표는 숫자를 보여주는 화면이라, 필터가 조용히 안 먹으면 틀린 순위를
   맞는 것처럼 보여준다. 그게 가장 나쁜 실패라 여기서 막는다.

   실행: node scripts/test_rank.js   (make test 에 포함)                     */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

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
if (!pw) { console.log('순위 탭 검사 건너뜀 — playwright 가 없습니다.'); process.exit(0); }
const { chromium } = pw;

const ROOT = path.resolve(__dirname, '..');
const PORT = 8201;
const BASE = `http://127.0.0.1:${PORT}`;

let failed = 0;
function check(name, ok, detail) {
  console.log(`  ${ok ? '통과' : '실패'}  ${name}${ok || !detail ? '' : ' — ' + detail}`);
  if (!ok) failed++;
}

/* 관문을 통과한 것처럼 꾸미고, 실제 Supabase·CDN 은 부르지 않는다. */
async function openApp(browser) {
  const page = await browser.newPage();
  await page.route('**/lib/supabase-init.js', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/app/supabase.js', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/supabase-js*/**', (r) => r.fulfill({ status: 200, body: '' }));
  await page.addInitScript(() => {
    window.SB = {};
    window.SBUtil = { me: async () => ({ user: { id: 'u1' }, profile: null }) };
  });
  await page.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
  // 탭을 눌러야 뷰가 보인다. 눌러서 여는 것까지가 이 화면의 동작이다.
  await page.waitForSelector('.tab[data-view="rank"]', { timeout: 15000 });
  await page.click('.tab[data-view="rank"]');
  await page.waitForSelector('#rank-table tbody tr', { timeout: 15000 });
  return page;
}

const rows = (page) => page.evaluate(() =>
  Array.from(document.querySelectorAll('#rank-table tbody tr')).map((tr) => {
    const td = tr.querySelectorAll('td');
    return {
      rank: Number(td[0].textContent),
      name: td[1].textContent,
      region: td[2].textContent,
      value: Number(td[3].textContent.replace(/[^0-9.-]/g, '')),
      growth: td[4].textContent.trim(),
      share: td[5].textContent.trim(),
    };
  }));

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PORT),
                                '--directory', path.join(ROOT, 'public')],
                    { stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 900));
  const browser = await chromium.launch({ executablePath: chromiumPath() });
  try {
    const page = await openApp(browser);

    // 1) 기본 렌더링
    let list = await rows(page);
    check('순위표에 행이 그려진다', list.length > 0, `${list.length}행`);
    check('교통량 내림차순이다',
          list.every((r, i) => i === 0 || list[i - 1].value >= r.value));
    check('순위가 1부터 이어진다', list.every((r, i) => r.rank === i + 1));
    check('영업소 이름이 비어 있지 않다', list.every((r) => r.name.trim().length > 0));

    // 2) 연도 필터가 실제로 값을 바꾼다
    const years = await page.$$eval('#rank-year option', (o) => o.map((x) => x.value));
    check('연도 선택지가 두 개 이상', years.length > 1, years.join(','));
    if (years.length > 1) {
      const before = (await rows(page))[0].value;
      await page.selectOption('#rank-year', years[0]);
      await page.waitForTimeout(200);
      const after = (await rows(page))[0].value;
      check('연도를 바꾸면 값이 달라진다', before !== after, `${before} → ${after}`);
      await page.selectOption('#rank-year', years[years.length - 1]);
      await page.waitForTimeout(200);
    }

    // 3) 차종 필터 — 화물은 전체보다 작아야 한다
    const total = (await rows(page)).find((r) => r.rank === 1);
    await page.selectOption('#rank-vehicle', 'g:freight');
    await page.waitForTimeout(200);
    list = await rows(page);
    const freightForSame = list.find((r) => r.name === total.name);
    check('화물 교통량은 전체보다 작다',
          !freightForSame || freightForSame.value < total.value,
          freightForSame ? `${freightForSame.value} vs ${total.value}` : '동일 영업소 없음');
    check('차종을 고르면 비중이 100% 미만으로 표시된다',
          list.every((r) => r.share === '—' || parseFloat(r.share) <= 100));

    // 4) 개별 차종도 고를 수 있다
    const opts = await page.$$eval('#rank-vehicle option', (o) => o.map((x) => x.value));
    check('개별 차종 선택지가 있다', opts.some((v) => v.startsWith('t:')), opts.join(','));
    await page.selectOption('#rank-vehicle', 'g:total');
    await page.waitForTimeout(200);

    // 5) 정렬 바꾸기
    await page.selectOption('#rank-sort', 'growth');
    await page.waitForTimeout(200);
    const growths = (await rows(page))
      .map((r) => (r.growth === '—' ? null : parseFloat(r.growth)))
      .filter((v) => v !== null);
    check('증가율 정렬이 내림차순이다',
          growths.every((v, i) => i === 0 || growths[i - 1] >= v));
    await page.selectOption('#rank-sort', 'volume');
    await page.waitForTimeout(200);

    // 6) 검색
    const target = (await rows(page))[0].name;
    await page.fill('#rank-search', target);
    await page.waitForTimeout(250);
    list = await rows(page);
    check('검색이 결과를 좁힌다', list.length > 0 && list.every((r) => r.name.includes(target)),
          `${list.length}행`);
    await page.fill('#rank-search', '');
    await page.waitForTimeout(250);

    // 7) 차종 분류 기준이 화면에 있다
    const vt = await page.$$eval('#vt-table tbody tr', (t) =>
      t.map((tr) => tr.querySelector('td').textContent.trim()));
    check('차종 6종의 분류 기준이 적혀 있다', vt.length === 6 && vt.every((d) => d.length > 10),
          `${vt.length}행`);
    const vg = await page.$$eval('#vg-table tbody tr', (t) => t.length);
    check('묶음 설명이 적혀 있다', vg >= 4, `${vg}행`);

    // 8) 지시5 — 밴드 색이 서로 달라야 한다
    const ringColors = await page.$$eval('#band-legend .row .ring',
      (els) => els.map((e) => getComputedStyle(e).borderTopColor));
    check('거리 밴드가 다섯 개 그려진다', ringColors.length === 5, `${ringColors.length}개`);
    check('밴드 색이 모두 다르다', new Set(ringColors).size === ringColors.length,
          ringColors.join(' / '));

    const bandVars = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      return [1, 2, 3, 4, 5].map((i) => cs.getPropertyValue(`--band-${i}`).trim());
    });
    check('--band-1..5 가 모두 정의돼 있다', bandVars.every((v) => v.length > 0),
          bandVars.join(','));

    const kindVars = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      return ['--kind-land', '--kind-factory'].map((n) => cs.getPropertyValue(n).trim());
    });
    check('토지와 공장 색이 서로 다르다',
          kindVars[0] && kindVars[1] && kindVars[0] !== kindVars[1], kindVars.join(' / '));

    // 9) hidden 이 실제로 감추는가
    //     .banner{display:flex} 가 hidden 을 이겨서, 실자료 화면에 '데모 데이터,
    //     합성 데이터입니다' 배너가 계속 떠 있었다. 회원 가입까지 하고 들어온
    //     사람에게 자기 제품을 가짜라고 말하는 셈이었다.
    const hiddenLeaks = await page.evaluate(() =>
      Array.from(document.querySelectorAll('[hidden]'))
        .filter((e) => getComputedStyle(e).display !== 'none')
        .map((e) => e.id || e.className));
    check('hidden 인 요소는 실제로 안 보인다', hiddenLeaks.length === 0,
          hiddenLeaks.join(', '));
    const bannerShown = await page.evaluate(() => {
      const b = document.getElementById('demo-banner');
      return b && getComputedStyle(b).display !== 'none';
    });
    check('실자료에서는 데모 배너가 안 뜬다', !bannerShown);

    // 10) 지도 범례가 밴드까지 설명한다
    const legendText = await page.$eval('#map-legend', (e) => e.textContent);
    check('지도 범례에 거리 밴드가 들어 있다', /km/.test(legendText));
    check('지도 범례에 실거래 종류가 들어 있다',
          /토지/.test(legendText) && /공장/.test(legendText));

    await page.close();
  } finally {
    await browser.close();
    srv.kill();
  }
  console.log(failed ? `\n실패 ${failed}건` : '\n모두 통과');
  process.exit(failed ? 1 : 0);
})();
