/* 내 계정 화면 검사 — 네트워크 없이 렌더링 로직만 본다.

   여기서 보는 두 가지는 **틀려도 화면이 멀쩡해 보이는** 것들이다.

     · 표시 이름 중복 — 물어보지 않고 저장하면 데이터베이스가 막지만
       (0016 의 유일 색인), 사람은 '저장하지 못했습니다' 만 보고 왜인지
       모른다. 묻는 것과 막는 것은 다른 일이다.
     · 선택 메일 — 받는 사람을 to 로 넣으면 **회원 명부를 회원들에게
       뿌리는 셈**이 된다. 메일 앱이 열리는 것만 보고 통과라고 하면
       그 사고를 못 잡는다. bcc 인지를 본다.

   Supabase 를 스텁으로 갈아끼우고 account.js 만 실행한다.
   실행: node scripts/test_account.js   */
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
if (!pw) { console.log('계정 검사 건너뜀 — playwright 가 없습니다.'); process.exit(0); }
const { chromium } = pw;

const ROOT = path.resolve(__dirname, '..');
const PORT = 8204;

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PORT),
                                '--directory', path.join(ROOT, 'public')], { stdio: 'ignore' });
  const done = (code) => { srv.kill(); process.exit(code); };
  await new Promise((r) => setTimeout(r, 800));

  const b = await chromium.launch({ executablePath: chromiumPath() });
  const page = await b.newPage({ viewport: { width: 1100, height: 900 } });
  const errs = [];
  page.on('pageerror', (e) => errs.push(e.message));

  await page.addInitScript(() => {
    const ROWS = [
      { id: 'u1', nickname: 'Jina Kim', email: 'jina@x.com', role: 'user',
        status: 'approved', grade: 'A', created_at: '2026-09-12T00:00:00Z', approved_at: '2026-09-12T00:00:00Z' },
      { id: 'u2', nickname: 'Longtermtube', email: 'ltt@x.com', role: 'user',
        status: 'approved', grade: 'B', created_at: '2026-09-11T00:00:00Z', approved_at: '2026-09-11T00:00:00Z' },
      { id: 'u3', nickname: 'club selfish', email: 'club@x.com', role: 'user',
        status: 'pending', grade: 'C', created_at: '2026-09-06T00:00:00Z', approved_at: null },
      { id: 'me', nickname: '토지랩', email: 'me@x.com', role: 'admin',
        status: 'approved', grade: 'admin', created_at: '2026-08-31T00:00:00Z', approved_at: '2026-08-31T00:00:00Z' },
    ];
    // 화면이 부른 것을 밖에서 세어 본다.
    window.__calls = { rpc: [], update: [] };
    // 이미 쓰고 있는 이름. nickname_taken() 이 서버에서 하는 일과 같은 규칙 —
    // 대소문자·앞뒤 공백 무시, 내 이름은 내가 쓸 수 있다.
    const TAKEN = ['Jina Kim', 'Longtermtube', 'club selfish'];

    function q(table) {
      const f = {};
      const o = {
        select() { return o }, order() { return o },
        eq(k, v) { f[k] = v; return o },
        update(v) { f.__set = v; return o },
        single() { return Promise.resolve(res(table, f)) },
        maybeSingle() { return Promise.resolve(res(table, f)) },
        then(a, r) { return Promise.resolve(res(table, f)).then(a, r) },
      };
      return o;
    }
    function res(table, f) {
      if (table !== 'profile') return { data: [], error: null };
      if (f.__set) {
        window.__calls.update.push(f.__set);
        if (f.__set.nickname && TAKEN.some((t) => t.toLowerCase() === String(f.__set.nickname).trim().toLowerCase())) {
          return { data: null, error: { code: '23505', message: 'duplicate key' } };
        }
        return { data: Object.assign({ nickname: '토지랩' }, f.__set), error: null };
      }
      return { data: ROWS, error: null };
    }
    window.SB = {
      from: q,
      rpc(name, args) {
        window.__calls.rpc.push([name, args]);
        if (name === 'nickname_taken') {
          const v = String((args || {}).p_nick || '').trim().toLowerCase();
          return Promise.resolve({ data: TAKEN.some((t) => t.toLowerCase() === v), error: null });
        }
        return Promise.resolve({ data: null, error: null });
      },
    };
    window.SBUtil = {
      esc: (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
      when: () => '방금',
      guard: () => true,
      signOut: async () => {},
      me: async () => ({ user: { id: 'me', email: 'me@x.com', created_at: '2026-08-31T00:00:00Z' },
                         profile: ROWS[3] }),
    };
    // 메일 앱을 진짜로 열면 안 된다. 어디로 가려 했는지만 붙든다.
    window.__mailto = null;
    Object.defineProperty(window, '__navGuard', { value: true });
  });

  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (u.includes('supabase-init.js') || u.includes('cdn.jsdelivr.net') || u.includes('/app/supabase.js')) {
      return route.fulfill({ status: 200, contentType: 'application/javascript', body: '' });
    }
    return route.continue();
  });
  // mailto: 로 넘어가려는 것을 막고 기록한다.
  page.on('request', () => {});
  await page.goto(`http://127.0.0.1:${PORT}/account/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('.mtable'));

  const checks = [];
  const ok = (n, c, d) => checks.push([n, c, d]);

  /* **대기자가 있으면 화면이 그 필터로 열린다** (승인이 가장 급한 일이라).
     검사는 넷 다 보이는 상태에서 시작해야 하므로 '전체' 로 돌린다 — 그
     열림 규칙 자체는 아래 '보이는 회원만' 검사가 따로 쓴다. */
  await page.evaluate(() => document.querySelector('[data-st="all"]').click());
  await page.waitForTimeout(150);

  // ── 1) 체크 상자 (지시 2026-09-17) ──────────────────────────────
  const boxes = await page.evaluate(() => document.querySelectorAll('.m-pick').length);
  ok('회원마다 체크 상자가 있다', boxes === 4, `${boxes}개`);
  const btn0 = await page.evaluate(() => {
    const b = document.getElementById('m-mail');
    return { text: b.textContent, off: b.disabled };
  });
  ok('아무도 안 골랐으면 메일 단추가 꺼져 있다', btn0.off === true, btn0.text);

  await page.evaluate(() => {
    document.querySelector('.m-pick[data-id="u1"]').click();
    document.querySelector('.m-pick[data-id="u2"]').click();
  });
  await page.waitForFunction(() => !document.getElementById('m-mail').disabled);
  const btn2 = await page.evaluate(() => document.getElementById('m-mail').textContent);
  ok('고른 사람 수가 단추에 적힌다', /2명/.test(btn2), btn2);

  /* **체크가 다시 그려도 살아남는다.** 표는 정렬·필터·저장마다 통째로 다시
     그려진다. 체크를 DOM 에만 두면 그때마다 사라져, 필터를 바꿔 가며 몇
     사람을 골라 담는다는 이 기능의 쓰임새가 통째로 없어진다. */
  await page.evaluate(() => { document.getElementById('m-sort').value = 'name_asc';
    document.getElementById('m-sort').dispatchEvent(new Event('change')); });
  await page.waitForTimeout(150);
  const kept = await page.evaluate(() =>
    [...document.querySelectorAll('.m-pick')].filter((c) => c.checked).map((c) => c.dataset.id).sort());
  ok('정렬을 바꿔도 체크가 남는다', kept.join(',') === 'u1,u2', kept.join(','));

  // 전체선택은 **보이는 것**에만 걸린다. 검색으로 좁혀 놓고 전체선택했다가
  // 엉뚱한 사람에게 메일이 가면 안 된다.
  await page.evaluate(() => {
    const q = document.getElementById('m-q');
    q.value = 'club'; q.dispatchEvent(new Event('input'));
  });
  await page.waitForTimeout(150);
  await page.evaluate(() => document.getElementById('m-all').click());
  await page.waitForTimeout(150);
  const afterAll = await page.evaluate(() => document.getElementById('m-mail').textContent);
  ok('전체선택은 보이는 회원만 더한다 (2 + 1 = 3)', /3명/.test(afterAll), afterAll);

  // ── 2) 메일은 숨은참조로 간다 ───────────────────────────────────
  const href = await page.evaluate(() => {
    window.__mailto = null;
    document.getElementById('m-mail').click();
    return window.__mailto || '';
  });
  ok('메일 앱으로 보낸다 (mailto)', href.indexOf('mailto:') === 0, href.slice(0, 60));
  ok('받는 사람은 숨은참조(bcc)다 — to 가 아니다',
     href.indexOf('mailto:?bcc=') === 0 && !/[?&]to=/.test(href), href.slice(0, 60));
  ok('고른 세 사람이 다 들어간다',
     ['jina%40x.com', 'ltt%40x.com', 'club%40x.com'].every((e) => href.includes(e)), href);

  // ── 3) 표시 이름 중복 (지시 2026-09-17) ─────────────────────────
  await page.evaluate(() => {
    document.getElementById('edit-profile').click();
    document.getElementById('pf-name').value = 'Jina Kim';
    document.getElementById('profile-form').dispatchEvent(new Event('submit', { cancelable: true }));
  });
  await page.waitForFunction(() => /이미 쓰고|확인하는/.test(document.getElementById('pf-msg').textContent));
  await page.waitForTimeout(200);
  const dup = await page.evaluate(() => ({
    msg: document.getElementById('pf-msg').textContent,
    rpc: window.__calls.rpc.map((c) => c[0]),
    updates: window.__calls.update.length,
  }));
  ok('겹치는 이름은 이유를 말한다', /이미 쓰고 있는 이름/.test(dup.msg), dup.msg);
  ok('저장 전에 물어본다 (nickname_taken)', dup.rpc.includes('nickname_taken'), dup.rpc.join(','));
  ok('겹치면 저장 자체를 안 보낸다', dup.updates === 0, `${dup.updates}번 보냄`);

  console.log('계정 검사\n');
  let bad = 0;
  for (const [n, c, d] of checks) { console.log((c ? '  ok   ' : '  FAIL ') + n + (c || !d ? '' : ' — ' + d)); if (!c) bad++; }
  if (errs.length) { console.log('\nJS 오류:'); errs.forEach((e) => console.log('  ' + e)); bad += errs.length; }
  console.log(bad ? `\n실패 ${bad}건` : '\n모두 통과');
  await b.close();
  done(bad ? 1 : 0);
})();
