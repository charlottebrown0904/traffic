/* 이름 검사 — 화면에 낡은 이름이 남아 있지 않은지 본다.

   이름은 두 번 바뀌었다 (사도 토지 → 토지 고고 → 토지맥). 그때마다
   한두 곳이 옛 이름으로 남았다. 머리띠는 눈에 띄니 금방 고치지만,
   <title> · og:site_name · manifest 는 **화면을 봐도 안 보이는 자리**다.
   브라우저 탭과 공유 카드와 홈화면 아이콘에서만 보이므로, 사람이
   확인하려면 그 셋을 일부러 열어 봐야 한다. 그래서 검사가 대신 본다.

   실행: node scripts/test_brand.js   */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const NAME = '토지맥';
/* 다시 쓰면 안 되는 옛 이름. 'toji-gogo' 는 뺀다 — 그것은 Vercel·
   Cloudflare 의 프로젝트 이름이라 화면에 안 나오고, 함부로 바꾸면
   배포가 끊긴다. */
const DEAD = ['토지 고고', '토지고고', '사도 토지', '사도될까'];

let bad = 0;
function ok(name, cond, detail) {
  console.log(`  ${cond ? '통과' : '실패'}  ${name}${cond || !detail ? '' : ' — ' + detail}`);
  if (!cond) bad++;
}

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'data') continue;   // 내보낸 자료는 우리가 쓴 글이 아니다
      walk(p, out);
    } else out.push(p);
  }
  return out;
}

const pub = path.join(ROOT, 'public');
const files = walk(pub).filter((f) => /\.(html|css|js|webmanifest|json|svg)$/.test(f));

console.log('\n1. 공개 화면에 옛 이름이 남지 않았다');
for (const dead of DEAD) {
  const hit = files.filter((f) => fs.readFileSync(f, 'utf8').includes(dead));
  ok(`'${dead}' 가 없다`, hit.length === 0,
     hit.map((f) => path.relative(ROOT, f)).join(', '));
}

console.log('\n2. 사람이 보는 자리가 모두 같은 이름이다');
const pages = files.filter((f) => f.endsWith('.html'));
ok('화면이 하나 이상 있다', pages.length > 0);
for (const f of pages) {
  const s = fs.readFileSync(f, 'utf8');
  const rel = path.relative(ROOT, f);
  const title = (s.match(/<title>([\s\S]*?)<\/title>/) || [])[1];
  ok(`${rel} — <title> 에 이름이 있다`, !!title && title.includes(NAME),
     title ? `지금: ${title.trim()}` : '<title> 자체가 없다');
  // 머리띠는 모든 화면에 있는 것이 아니다. 있으면 이름이 맞아야 한다.
  const bar = (s.match(/class="sitebar-brand"[\s\S]*?<\/a>/) || [])[0];
  if (bar) ok(`${rel} — 머리띠 이름`, bar.includes(NAME), bar.slice(0, 120));
}

console.log('\n3. 화면 밖에서만 보이는 세 자리');
const land = fs.readFileSync(path.join(pub, 'index.html'), 'utf8');
const site = (land.match(/property="og:site_name"\s+content="([^"]*)"/) || [])[1];
ok('og:site_name — 공유 카드에 뜬다', site === NAME, `지금: ${site}`);
const ogt = (land.match(/property="og:title"\s+content="([^"]*)"/) || [])[1];
ok('og:title 에도 이름이 있다', !!ogt && ogt.includes(NAME), `지금: ${ogt}`);

const man = JSON.parse(fs.readFileSync(path.join(pub, 'site.webmanifest'), 'utf8'));
ok('manifest name — 홈화면 아이콘 밑에 뜬다', man.name === NAME, `지금: ${man.name}`);
ok('manifest short_name', man.short_name === NAME, `지금: ${man.short_name}`);

console.log('\n4. 이름을 적은 문서가 같은 값을 말한다');
const brand = fs.readFileSync(path.join(ROOT, 'docs/brand.md'), 'utf8');
ok('docs/brand.md 머리글', brand.startsWith(`# 브랜드 — ${NAME}`));
ok('docs/brand.md 가 옛 이름을 폐기라고 적는다', brand.includes('폐기'));
ok('상표 절차 문서가 있다', fs.existsSync(path.join(ROOT, 'docs/trademark.md')));

console.log(bad ? `\n${bad}건 실패` : '\n모두 통과');
process.exit(bad ? 1 : 0);
