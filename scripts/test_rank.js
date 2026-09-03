/* 교통량 순위 탭 · 추이 비교 탭 · 색 구분 검사.

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
  await page.route('**/lib/supabase-init.js*', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/app/supabase.js*', (r) => r.fulfill({ status: 200, body: '' }));
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
    const before = (await rows(page)).length;
    const target = (await rows(page))[0].name;
    await page.fill('#rank-search', target);
    await page.waitForTimeout(250);
    list = await rows(page);
    // 검색은 이름과 지역을 함께 봅니다 (placeholder 가 '영업소·시군구 검색').
    // 이름만으로 걸러진다고 가정하면, 지역으로 걸린 행을 오탐으로 셉니다 —
    // '서울' 로 검색하면 서울특별시 영업소들이 이름과 무관하게 걸립니다.
    check('검색이 결과를 좁힌다', list.length > 0 && list.length < before,
          `${before} → ${list.length}행`);
    check('걸린 행은 이름이나 지역에 검색어가 있다',
          list.every((r) => (r.name + ' ' + r.region).includes(target)),
          list.filter((r) => !(r.name + ' ' + r.region).includes(target))
              .map((r) => `${r.name}/${r.region}`).join(', '));
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
    // 밴드 개수는 설정에서 온다. 숫자를 박아 두면 밴드를 조정할 때마다 검사가
    // '깨진 것' 처럼 빨개진다 — 실제로 5개에서 4개로 줄이자 그랬다.
    const bandCount = await page.evaluate(() => (window.__bands || []).length);
    // 화면 범례는 **영향범위까지**다. 가장 바깥(위약 대조)은 분석 절차라
    // 화면에서 뺐다(2026-09-03 지시) — app.js shownBands() 참고.
    check('거리 밴드가 대조를 뺀 만큼 그려진다', ringColors.length === bandCount - 1,
          `범례 ${ringColors.length}개 vs 설정 ${bandCount}개 (대조 1개 제외)`);
    check('밴드 색이 모두 다르다', new Set(ringColors).size === ringColors.length,
          ringColors.join(' / '));
    // 영향범위 바깥의 대조 밴드가 하나는 있어야 위약 검정을 할 수 있다.
    const hasControl = await page.evaluate(
      () => (window.__bands || []).some((b) => b[1] > 5));
    check('영향범위(5km) 바깥 대조 밴드가 있다', hasControl);

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

    // ── 추이 비교 탭 ──────────────────────────────────────────────
    // chart.json 은 파이프라인이 만든다. 아직 없으면 탭이 스스로 숨는데,
    // 그건 정상 동작이므로 실패로 세지 않고 건너뛴다.
    const trendTab = await page.$('.tab[data-view="trend"]:not([hidden])');
    if (!trendTab) {
      console.log('  건너뜀  추이 비교 — chart.json 이 아직 없습니다 (export-web 전)');
    } else {
    await page.click('.tab[data-view="trend"]');
    await page.waitForSelector('#trend-chart path.series', { timeout: 15000 });

    const lines = () => page.$$eval('#trend-chart path.series', (p) => p.map((e) => ({
      d: e.getAttribute('d') || '',
      stroke: getComputedStyle(e).stroke,
      dashed: e.classList.contains('dashed'),
    })));

    let ls = await lines();
    check('추이 차트에 선이 그려진다', ls.length > 0, `${ls.length}개`);
    check('선마다 좌표가 들어 있다', ls.every((l) => l.d.length > 4));
    check('선 색이 실제 색으로 풀린다',
          ls.every((l) => l.stroke && l.stroke !== 'none'), ls.map((l) => l.stroke).join(','));

    // 켜져 있는 선끼리 같은 색이면 안 된다. 교통량 전체를 --q-under 로 쓰다가
    // 지가 5-10km(--band-4)와 똑같은 파랑이 나와, 한 그래프 안에서 두 선을
    // 구별할 수 없었다. 색이 이 화면에서 사실상 유일한 구분 수단이다.
    const strokes = ls.map((l) => l.stroke);
    check('켜진 선끼리 색이 겹치지 않는다',
          new Set(strokes).size === strokes.length, strokes.join(' / '));

    // 계열을 하나 더 켜면 선이 늘어야 한다
    const boxes = await page.$$('#trend-series input[type=checkbox]');
    const off = [];
    for (const b of boxes) if (!(await b.isChecked())) off.push(b);
    if (off.length) {
      const before = (await lines()).length;
      await off[0].check();
      await page.waitForTimeout(200);
      const after = (await lines()).length;
      check('계열을 켜면 선이 늘어난다', after === before + 1, `${before} → ${after}`);
      await off[0].uncheck();
      await page.waitForTimeout(200);
    }

    // 지수 모드에서는 기준연도 값이 100 이어야 한다
    const baseYear = await page.$eval('#trend-base', (e) => e.value);
    const readout = async (x) => {
      const box = await page.$('#trend-chart');
      const bb = await box.boundingBox();
      await page.mouse.move(bb.x + bb.width * x, bb.y + bb.height / 2);
      await page.waitForTimeout(120);
      return page.$eval('#trend-readout', (e) => e.textContent);
    };
    const baseYears = await page.$$eval('#trend-base option', (o) => o.map((x) => x.value));
    const idx = baseYears.indexOf(baseYear);
    const frac = baseYears.length > 1 ? idx / (baseYears.length - 1) : 0;
    const txt = await readout(Math.min(0.97, Math.max(0.03, frac)));
    check('기준연도에서 지수가 100 이다', /100\.0/.test(txt), txt.slice(0, 120));

    // 원값으로 바꾸면 안내 문구가 달라진다
    await page.click('#trend-scale .seg-btn[data-scale="raw"]');
    await page.waitForTimeout(200);
    const rawNote = await page.$eval('#trend-note', (e) => e.textContent);
    check('원값 모드는 축이 하나라는 것을 알린다', /축이 하나/.test(rawNote), rawNote.slice(0, 80));
    await page.click('#trend-scale .seg-btn[data-scale="index"]');
    await page.waitForTimeout(200);

    // 계열을 전부 끄면 빈 화면 대신 안내가 나와야 한다
    const allBoxes = await page.$$('#trend-series input[type=checkbox]:checked');
    for (const b of allBoxes) await b.uncheck();
    await page.waitForTimeout(250);
    const emptyNote = await page.$eval('#trend-note', (e) => e.textContent);
    check('계열이 없으면 이유를 말한다', /고르세요/.test(emptyNote), emptyNote.slice(0, 60));

    // 공시지가가 없으면 '없다' 고 적혀 있어야 한다 — 선이 안 보이는 것과 다른 말이다
    const lpText = await page.$eval('#trend-series', (e) => e.textContent);
    check('공시지가 칸에 설명이 있다', /공시지가/.test(lpText), lpText.slice(0, 60));
    }

    await page.close();
  } finally {
    await browser.close();
    srv.kill();
  }
  console.log(failed ? `\n실패 ${failed}건` : '\n모두 통과');
  process.exit(failed ? 1 : 0);
})();
