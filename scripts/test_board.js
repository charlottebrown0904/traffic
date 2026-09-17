/* 게시판 화면 검사 — 네트워크 없이 렌더링 로직만 본다.

   누가 무엇을 지울 수 있는지는 결국 데이터베이스의 RLS 가 정하지만,
   버튼이 안 보이면 권한이 있어도 못 쓴다. 실제로 관리자에게 삭제 버튼이
   없어서 신고를 처리할 수 없던 적이 있다. 그 회귀를 여기서 막는다.

   Supabase 클라이언트를 스텁으로 갈아끼우고 board.js 만 실행한다.
   실행: node scripts/test_board.js   (make test 에 포함)   */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

/* playwright 와 크로미움이 없는 환경(CI 등)에서는 조용히 건너뛴다.
   웹 검사를 통째로 막아서 파이프라인을 세우는 것보다 낫다. */
function loadPlaywright() {
  for (const m of ['playwright', '/tmp/node_modules/playwright',
                   '/opt/node22/lib/node_modules/playwright']) {
    try { return require(m); } catch (e) { /* 다음 후보 */ }
  }
  return null;
}

function chromiumPath() {
  const base = '/opt/pw-browsers';
  if (!fs.existsSync(base)) return undefined;   // playwright 가 알아서 찾게 둔다
  for (const d of fs.readdirSync(base)) {
    const p = `${base}/${d}/chrome-linux/headless_shell`;
    if (d.startsWith('chromium_headless_shell') && fs.existsSync(p)) return p;
  }
  return undefined;
}

const pw = loadPlaywright();
if (!pw) {
  console.log('게시판 검사 건너뜀 — playwright 가 없습니다.');
  process.exit(0);
}
const { chromium } = pw;

const ROOT = path.resolve(__dirname, '..');
const PORT = 8199;

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PORT), '--directory', path.join(ROOT, 'public')],
                    { stdio: 'ignore' });
  const done = code => { srv.kill(); process.exit(code); };
  await new Promise(r => setTimeout(r, 800));

  const b = await chromium.launch({ executablePath: chromiumPath() });
  const page = await b.newPage({ viewport: { width: 390, height: 844 } });
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));

  // Supabase 를 흉내 낸 스텁. 실제 네트워크 없이 렌더링만 검증한다.
  await page.addInitScript(() => {
    const ME = { id: 'u-me', nickname: '나' };
    const OTHER = { id: 'u-other', nickname: '<script>남</script>' };
    const POSTS = [
      { id: 'p1', category: 'notice', title: '공지 글', body: '본문1', created_at: '2026-08-31T01:00:00Z', user_id: OTHER.id, is_deleted: false },
      { id: 'p2', category: 'free',   title: '내 글',   body: '본문2', created_at: '2026-08-30T01:00:00Z', user_id: ME.id,    is_deleted: false },
    ];
    const CMTS = [
      { id: 'c1', post_id: 'p1', user_id: OTHER.id, body: '남의 댓글', created_at: '2026-08-31T02:00:00Z', is_deleted: false },
      { id: 'c2', post_id: 'p1', user_id: ME.id,    body: '내 댓글',   created_at: '2026-08-31T03:00:00Z', is_deleted: false },
    ];
    // 새로고침해도 유지되도록 주소에서 읽는다
    window.__role = new URLSearchParams(location.search).get('role') || 'user';
    window.__status = new URLSearchParams(location.search).get('status') || 'approved';

    function result(table, filters) {
      if (table === 'post') {
        if (filters.id) return { data: POSTS.find(p => p.id === filters.id) || null, error: null };
        return { data: POSTS, error: null };
      }
      if (table === 'comment') return { data: CMTS.filter(c => c.post_id === filters.post_id), error: null };
      if (table === 'profile_public') {
        return { data: [ME, OTHER].filter(p => (filters.in || []).includes(p.id)), error: null };
      }
      /* profile 은 **RLS 가 본인 행과 관리자에게만 연다.** 스텁도 그렇게
         군다 — 일반 회원에게 빈 결과를 주지 않으면, 화면이 '못 읽었을 때'
         무엇을 하는지를 검사가 영영 못 본다. */
      if (table === 'profile') {
        const mine = filters.id === ME.id;
        if (window.__role !== 'admin' && !mine) return { data: null, error: null };
        return { data: { email: filters.id === OTHER.id ? 'other@x.com' : 'me@x.com' }, error: null };
      }
      return { data: [], error: null };
    }

    function q(table) {
      const f = {};
      const o = {
        select() { return o }, order() { return o }, limit() { return o },
        eq(k, v) { f[k] = v; return o },
        in(k, v) { f.in = v; return o },
        insert() { return Promise.resolve({ error: null }) },
        update() { return o },
        maybeSingle() { return Promise.resolve(result(table, f)) },
        then(res, rej) { return Promise.resolve(result(table, f)).then(res, rej) },
      };
      return o;
    }
    window.SB = { from: q };
    window.SBUtil = {
      esc: s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])),
      when: () => '방금',
      guard: () => true,
      // status 를 밖에서 바꿀 수 있게 둔다. 기본은 승인된 회원이라
      // 기존 검사들의 뜻이 그대로 유지된다.
      me: async () => ({ user: { id: 'u-me', email: 'me@x.com' },
        profile: { nickname: '나', role: window.__role,
                   status: window.__status || 'approved' } }),
    };
  });

  // 실제 클라이언트를 만드는 스크립트는 막는다 — 스텁을 덮어쓰기 때문이다.
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.includes('supabase-init.js') || u.includes('cdn.jsdelivr.net') || u.includes('/app/supabase.js')) {
      return route.fulfill({ status: 200, contentType: 'application/javascript', body: '' });
    }
    return route.continue();
  });

  await page.goto(`http://127.0.0.1:${PORT}/board/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('.post-list'));

  const list = await page.evaluate(() => document.getElementById('root').innerText);
  console.log('게시판 검사\n— 목록 —\n' + list.trim());

  const checks = [];
  checks.push(['목록에 남의 닉네임', /남/.test(list)]);
  checks.push(['목록에 내 닉네임', /나/.test(list)]);
  const rawList = await page.evaluate(() => document.getElementById('root').innerHTML);
  checks.push(['닉네임 XSS 이스케이프', !/<script>남<\/script>/.test(rawList)]);

  // 남의 글 상세 — 일반 회원
  await page.evaluate(() => { location.hash = '#/p/p1'; });
  await page.waitForFunction(() => /본문1/.test(document.getElementById('root').innerText));
  let html = await page.evaluate(() => document.getElementById('root').innerHTML);
  checks.push(['일반회원: 남의 글 삭제 버튼 없음', !/id="del"/.test(html)]);
  checks.push(['일반회원: 내 댓글만 삭제 가능 (1개)', (html.match(/data-c=/g) || []).length === 1]);
  checks.push(['상세에 작성자 표시', /남/.test(await page.evaluate(() => document.getElementById('root').innerText))]);

  // 관리자로 다시
  await page.goto(`http://127.0.0.1:${PORT}/board/?role=admin#/p/p1`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => /본문1/.test(document.getElementById('root').innerText));
  html = await page.evaluate(() => document.getElementById('root').innerHTML);
  checks.push(['관리자: 남의 글 삭제 버튼 있음', /id="del"/.test(html)]);
  checks.push(['관리자: 모든 댓글 삭제 가능 (2개)', (html.match(/data-c=/g) || []).length === 2]);

  // 승인 전 회원 — 목록이 **빈 채로** 뜨면 '글이 없구나' 로 읽힌다.
  // 진짜로 막는 것은 데이터베이스의 RLS 이고, 여기서는 왜 비었는지를
  // 말해주는지만 본다.
  for (const [label, status] of [['대기(pending)', 'pending'],
                                 ['거절(rejected)', 'rejected']]) {
    await page.goto(`http://127.0.0.1:${PORT}/board/?status=${status}`,
                    { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(400);
    const text = await page.evaluate(() => document.getElementById('root').innerText);
    checks.push([`${label}: 왜 못 쓰는지 말해준다`, /승인/.test(text)]);
    checks.push([`${label}: 글 목록을 안 보여준다`,
                 !(await page.evaluate(() => !!document.querySelector('.post-list')))]);
  }

  /* ── 2026-09-17 지시 ────────────────────────────────────────────
     · "게시판 화면에서 우측 '토지랩'은 '내 계정'으로 수정"
     · "글 작성자/댓글 작성자 프로필 클릭 시 메일 보내기 팝업"

     둘째는 **보는 사람에 따라 다른 것을 말해야 한다.** 회원 메일 주소는
     아무에게나 보이면 안 되므로, 일반 회원에게는 주소가 아니라 왜 없는지가
     떠야 한다. 화면이 숨기는 것이 아니라 자료가 안 오는 것이라는 점이
     중요해서, 스텁도 RLS 처럼 빈 결과를 준다. */
  await page.goto(`http://127.0.0.1:${PORT}/board/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('.post-list'));
  const navText = await page.evaluate(() => document.getElementById('nav-me').textContent.trim());
  checks.push(["머리띠 끝 칸이 '내 계정' 이다 (내 이름으로 안 바뀐다)", navText === '내 계정']);

  const btnCount = await page.evaluate(() => document.querySelectorAll('.who-btn').length);
  checks.push(['목록의 작성자 이름이 누를 수 있는 단추다', btnCount === 2]);
  // 단추가 링크 **안**에 있으면 눌러도 글로 넘어가 버린다.
  checks.push(['이름 단추는 글 링크 밖에 있다',
               await page.evaluate(() => !document.querySelector('.post-list a .who-btn'))]);

  // 일반 회원이 남의 이름을 눌렀을 때
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.who-btn')].find((x) => x.dataset.uid === 'u-other');
    b.click();
  });
  await page.waitForFunction(() => {
    const el = document.querySelector('#who-body');
    return el && !/불러오는 중/.test(el.textContent);
  });
  let pop = await page.evaluate(() => document.getElementById('who-pop').innerText);
  checks.push(['일반회원: 창이 뜬다', /남/.test(pop)]);
  checks.push(['일반회원: 남의 메일 주소가 안 보인다', !/other@x\.com/.test(pop)]);
  checks.push(['일반회원: 왜 없는지 말한다', /공개하지 않습니다/.test(pop)]);
  checks.push(['일반회원: mailto 링크가 없다',
               await page.evaluate(() => !document.querySelector('#who-pop a[href^="mailto:"]'))]);
  // Esc 로 닫힌다 — 닫는 길이 없으면 화면이 잠긴다.
  await page.keyboard.press('Escape');
  checks.push(['Esc 로 닫힌다', await page.evaluate(() => !document.getElementById('who-pop'))]);

  // 관리자가 같은 이름을 눌렀을 때
  await page.goto(`http://127.0.0.1:${PORT}/board/?role=admin`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.querySelector('.who-btn'));
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.who-btn')].find((x) => x.dataset.uid === 'u-other');
    b.click();
  });
  await page.waitForFunction(() => {
    const el = document.querySelector('#who-body');
    return el && !/불러오는 중/.test(el.textContent);
  });
  pop = await page.evaluate(() => document.getElementById('who-pop').innerText);
  const mailHref = await page.evaluate(() => {
    const a = document.querySelector('#who-pop a[href^="mailto:"]');
    return a ? a.getAttribute('href') : '';
  });
  checks.push(['관리자: 메일 주소가 보인다', /other@x\.com/.test(pop)]);
  checks.push(['관리자: 메일 보내기가 그 주소로 간다', /^mailto:other%40x\.com/.test(mailHref)]);
  checks.push(['관리자: 제목이 미리 적힌다', /subject=/.test(mailHref)]);

  // 공지는 관리자만 (지시). 진짜 자물쇠는 RLS(0016) 이고 여기서는 칸을 본다.
  await page.goto(`http://127.0.0.1:${PORT}/board/#/write`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.getElementById('cat'));
  const opts = await page.evaluate(() =>
    [...document.querySelectorAll('#cat option')].map((o) => o.value));
  checks.push(['일반회원 글쓰기 칸에 공지가 없다', opts.indexOf('notice') < 0, opts.join(',')]);
  await page.goto(`http://127.0.0.1:${PORT}/board/?role=admin#/write`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => document.getElementById('cat'));
  const optsA = await page.evaluate(() =>
    [...document.querySelectorAll('#cat option')].map((o) => o.value));
  checks.push(['관리자 글쓰기 칸에는 공지가 있다', optsA.indexOf('notice') >= 0, optsA.join(',')]);

  console.log('');
  let bad = 0;
  for (const [name, ok] of checks) { console.log((ok ? '  ok   ' : '  FAIL ') + name); if (!ok) bad++; }
  if (errs.length) { console.log('\nJS 오류:'); errs.forEach(e => console.log('  ' + e)); bad += errs.length; }
  console.log(bad ? `\n실패 ${bad}건` : '\n모두 통과');
  await b.close();
  done(bad ? 1 : 0);
})();
