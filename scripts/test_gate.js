/* /app 회원 관문 검사 — 네트워크 없이 관문 로직만 본다.

   관문이 조용히 무너지는 경우가 둘이다. 로그인 없이 들어왔는데 지도가
   보이거나, 로그인했는데 못 들어가거나. 둘 다 화면을 열어봐야 알 수
   있고, 둘 다 한 줄 고치다 생기기 쉽다. 그래서 여기서 잡는다.

   실행: node scripts/test_gate.js   */
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
if (!pw) {
  console.log('관문 검사 건너뜀 — playwright 가 없습니다.');
  process.exit(0);
}
const { chromium } = pw;

const ROOT = path.resolve(__dirname, '..');
const PORT = 8201;
const BASE = `http://127.0.0.1:${PORT}`;

let failed = 0;
function check(name, ok, detail) {
  console.log(`  ${ok ? '통과' : '실패'}  ${name}${ok || !detail ? '' : ' — ' + detail}`);
  if (!ok) failed++;
}

/* 로그인 상태를 흉내 낸다. 실제 Supabase 는 부르지 않는다. */
function stub(page, user) {
  return page.addInitScript((u) => {
    window.SB = {};                      // 초기화된 것처럼
    window.SBUtil = { me: async () => (u ? { user: { id: 'u1' }, profile: null } : null) };
  }, user);
}

/* 진짜 supabase-init.js 가 스텁을 덮어쓰지 않게 막는다. CDN 도 막는다. */
async function blockAuthScripts(page) {
  await page.route('**/lib/supabase-init.js*', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/app/supabase.js*', (r) => r.fulfill({ status: 200, body: '' }));
  await page.route('**/supabase-js*/**', (r) => r.fulfill({ status: 200, body: '' }));
}

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PORT), '--directory', path.join(ROOT, 'public')],
                    { stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 900));

  const browser = await chromium.launch({ executablePath: chromiumPath() });
  try {
    // 1) 비회원 — 로그인 화면으로 넘어가야 한다
    {
      const page = await browser.newPage();
      await blockAuthScripts(page);
      await stub(page, false);
      await page.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
      await page.waitForURL(/\/account/, { timeout: 5000 }).catch(() => {});
      const url = page.url();
      check('비회원은 로그인 화면으로', /\/account/.test(url), url);
      check('돌아올 곳을 next 로 넘긴다', /next=%2Fapp/.test(url), url);
      await page.close();
    }

    // 2) 회원 — 앱이 실제로 붙어야 한다
    {
      const page = await browser.newPage();
      await blockAuthScripts(page);
      await stub(page, true);
      await page.goto(`${BASE}/app/`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(
        // 경로로 찾는다. 캐시 무효화 꼬리표(?v=...)가 붙어도 같은 파일이다.
        () => !!document.querySelector('script[src^="/app/app.js"]'),
        { timeout: 5000 }).catch(() => {});
      const hasApp = await page.evaluate(
        () => !!document.querySelector('script[src^="/app/app.js"]'));
      const visible = await page.evaluate(
        () => document.documentElement.style.visibility !== 'hidden');
      check('회원에게는 app.js 를 붙인다', hasApp);
      check('회원에게는 화면을 보여준다', visible);
      check('회원은 로그인 화면으로 안 넘어간다', !/\/account/.test(page.url()), page.url());
      await page.close();
    }

    // 3) 홈 화면 문구와 링크
    {
      const page = await browser.newPage();
      await page.goto(`${BASE}/index.html`, { waitUntil: 'domcontentloaded' });
      const hero = await page.evaluate(() => {
        const a = document.querySelector('a.hero-link');
        return a ? { text: a.textContent.trim(), href: a.getAttribute('href') } : null;
      });
      check('첫 버튼 문구가 회원 가입', !!hero && hero.text.startsWith('회원 가입하고 보기'),
            hero && hero.text);
      check('첫 버튼이 로그인 화면으로', !!hero && hero.href.indexOf('/account?next=') === 0,
            hero && hero.href);
      const leftovers = await page.evaluate(
        () => Array.prototype.filter.call(document.querySelectorAll('a[href="/app"]'), () => true).length);
      check('홈에 /app 직행 링크가 남아 있지 않다', leftovers === 0, `${leftovers}개 남음`);
      await page.close();
    }
  } finally {
    await browser.close();
    srv.kill();
  }

  console.log(failed ? `\n실패 ${failed}건` : '\n관문 검사 전부 통과');
  process.exit(failed ? 1 : 0);
})();
