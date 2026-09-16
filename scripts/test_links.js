/* 단축 링크·UTM 규칙 검사 — 네트워크 없이 규칙만 본다.

   이 셋이 조용히 무너지면 숫자가 **틀린 채로 그럴듯하게** 나온다:
     · 값을 안 눕히면 같은 캠페인이 두 줄로 쪼개진다
     · 봇을 안 거르면 아무도 안 눌러도 클릭이 오른다
     · 301 로 보내면 두 번째 클릭부터 서버에 안 온다

   실행: node scripts/test_links.js   */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
let bad = 0;
function ok(name, cond, detail) {
  console.log(`  ${cond ? '통과' : '실패'}  ${name}${cond || !detail ? '' : ' — ' + detail}`);
  if (!cond) bad++;
}

/* utm.js 를 가짜 window 에 올린다 */
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(ROOT, 'public/lib/utm.js'), 'utf8'), sandbox);
const U = sandbox.window.UTM;

console.log('\n1. 값을 눕히고 다듬는다');
ok('대문자를 내린다', U.normValue('Naver') === 'naver', U.normValue('Naver'));
ok('공백을 하이픈으로', U.normValue('summer sale') === 'summer-sale', U.normValue('summer sale'));
ok('허용 안 되는 글자를 뺀다', U.normValue('a/b?c#d') === 'abcd', U.normValue('a/b?c#d'));
ok('연속 하이픈을 하나로', U.normValue('a -- b') === 'a-b', U.normValue('a -- b'));
ok('앞뒤 하이픈을 뗀다', U.normValue('-x-') === 'x', U.normValue('-x-'));
ok('60자에서 자른다', U.normValue('a'.repeat(200)).length === 60);
ok('빈 값은 빈 문자열', U.normValue(null) === '' && U.normValue(undefined) === '');

console.log('\n2. 한글은 거부한다 (주소에서 부풀어 잘린다)');
ok('한글을 잡는다', U.hasHangul('여름할인') === true);
ok('자모도 잡는다', U.hasHangul('ㄱㄴㄷ') === true);
ok('영문은 통과', U.hasHangul('summer') === false);

console.log('\n3. 주소를 만든다');
const url = U.buildUrl('https://toji.fyi/app', { source: 'Naver', medium: 'CPC', campaign: 'Launch' });
ok('세 칸이 소문자로 붙는다',
  url === 'https://toji.fyi/app?utm_source=naver&utm_medium=cpc&utm_campaign=launch', url);
ok('빈 칸은 아예 안 붙인다',
  U.buildUrl('https://toji.fyi', { source: 'a', medium: '', campaign: 'b' })
    === 'https://toji.fyi?utm_source=a&utm_campaign=b');
ok('원래 붙어 있던 물음표는 버린다',
  U.buildUrl('https://toji.fyi/app?old=1', { source: 'a', medium: 'b', campaign: 'c' })
    .indexOf('old=1') < 0);

console.log('\n4. 단축 코드');
// 채널 끝 조각과 소재 접두어가 **같을 때만** 합친다 (ig-reel + reel02 → ig-reel02).
ok('겹치는 접두어는 합친다', U.suggestCode('ig-reel', 'reel02') === 'ig-reel02',
  U.suggestCode('ig-reel', 'reel02'));
ok('안 겹치면 그대로 잇는다', U.suggestCode('naver-blog', 'post03') === 'naver-blog-post03',
  U.suggestCode('naver-blog', 'post03'));
ok('소재가 없으면 채널만', U.suggestCode('kakao', '') === 'kakao');
ok('겹치지 않는 접두어는 하이픈으로', U.suggestCode('band', '0916') === 'band-0916');
ok('꼬리 네 글자는 헷갈리는 글자를 안 쓴다', !/[il1o0]/.test(U.randomSuffix()));

console.log('\n5. 다음 소재 코드를 제안한다');
ok('순번은 다음 번호',
  U.suggestContent({ content_mode: 'serial', content_prefix: 'post' },
    [{ content: 'post01' }, { content: 'post07' }]) === 'post08');
ok('아무것도 없으면 01',
  U.suggestContent({ content_mode: 'serial', content_prefix: 'ep' }, []) === 'ep01');
ok('날짜 모드는 MMDD',
  U.suggestContent({ content_mode: 'date' }, [], new Date(2026, 8, 16)) === '0916');
ok('안 쓰는 모드는 빈 값', U.suggestContent({ content_mode: 'none' }, []) === '');

console.log('\n6. 리다이렉트 함수');
const L = require(path.join(ROOT, 'api/l.js')).__test;
ok('카카오 미리보기 봇을 거른다', L.BOT_UA.test('facebookexternalhit/1.1'));
ok('카카오톡 스크랩도', L.BOT_UA.test('kakaotalk-scrap/1.0'));
ok('슬랙·디스코드도', L.BOT_UA.test('Slackbot-LinkExpanding') && L.BOT_UA.test('Discordbot/2.0'));
ok('진짜 브라우저는 안 걸린다',
  !L.BOT_UA.test('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15'));
ok('모바일을 알아본다', L.deviceOf('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile') === 'mobile');
ok('데스크톱을 알아본다', L.deviceOf('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)') === 'desktop');
ok('추천인은 도메인만', L.hostOf('https://www.naver.com/search?q=땅') === 'naver.com');
ok('이상한 추천인은 null', L.hostOf('보통 글자') === null);
ok('코드를 눕히고 다듬는다', L.normCode(' AB/c ') === 'abc');
ok('모르는 코드도 랜딩으로 보내되 흔적을 남긴다',
  L.fallbackUrl('zzz').indexOf('utm_source=short-link') > 0);

console.log('\n7. 소스에 못 박아 둔 것');
const lsrc = fs.readFileSync(path.join(ROOT, 'api/l.js'), 'utf8');
ok('302 로 보낸다 (301 이면 두 번째 클릭이 안 온다)', /status\(302\)/.test(lsrc));
ok('캐시를 막는다', /no-store/.test(lsrc));
ok('세는 문과 안 세는 문이 갈려 있다',
  /hit_link/.test(lsrc) && /peek_link/.test(lsrc));
ok('HEAD 는 세지 않는다', /method === 'GET'/.test(lsrc));
ok('GET·HEAD 외에는 405', /405/.test(lsrc));

const vj = JSON.parse(fs.readFileSync(path.join(ROOT, 'vercel.json'), 'utf8'));
ok('/l/:code 가 함수로 이어진다',
  (vj.rewrites || []).some((r) => r.source === '/l/:code'));

const sql = fs.readFileSync(path.join(ROOT, 'supabase/migrations/0013_links_audit.sql'), 'utf8');
ok('목적지는 우리 사이트만 (오픈 리다이렉트)', /utm_link_own_site/.test(sql));
ok('값이 소문자여야 한다는 제약이 DB 에도 있다', /utm_link_lower/.test(sql));
ok('합계와 기록을 한 함수에서', /clicks = clicks \+ 1/.test(sql) && /insert into public\.link_click/.test(sql));
ok('집계 함수는 관리자만', /admin_link_stats[\s\S]*?is_admin\(\)/.test(sql));
ok('감사 로그는 트리거가 남긴다', /create trigger profile_audit/.test(sql));
ok('anon 에게서 표 권한을 회수한다', /revoke all on public\.utm_channel/.test(sql));

console.log('\n8. GA 초기화가 head 인라인이다');
for (const f of ['public/index.html', 'public/app/index.html', 'public/admin/index.html',
                 'public/account/index.html', 'public/board/index.html', 'public/legal/index.html']) {
  const h = fs.readFileSync(path.join(ROOT, f), 'utf8');
  const cfg = h.indexOf("gtag('config'");
  const body = h.search(/<(main|div id="root"|section|header)/);
  ok(`${f} — config 가 본문보다 앞에 있다`, cfg > 0 && (body < 0 || cfg < body));
  ok(`${f} — anonymize_ip`, /anonymize_ip/.test(h));
}

console.log('\n9. 대쉬보드와 그림');
const adm = fs.readFileSync(path.join(ROOT, 'public/admin/admin.js'), 'utf8');
ok('대쉬보드 탭은 칸이 여럿이어도 늘 펼쳐 둔다', /cur === 'board'\) \? ' open'/.test(adm));
ok('기간 칩 넷 (오늘·7일·30일·전체)', /\[0, '오늘'\][\s\S]*?\[null, '전체'\]/.test(adm));
ok('기간을 바꾸면 DB 에서 다시 센다 (화면에서 자르지 않는다)',
   /getLinks\(days\)/.test(adm) && /p_days/.test(adm));
ok('채널을 여러 개 고를 수 있다', /ch-pick:checked/.test(adm));
ok('막대는 SVG 를 늘이지 않는다 (모서리·글자가 찌그러진다)',
   !/preserveAspectRatio="none"/.test(adm));
ok('값 이름표는 막대 안에 떠 있다 (흐름에 두면 그 막대만 짧아진다)',
   /'<i style="height:'[\s\S]{0,200}<b>/.test(adm));
ok('값 이름표는 전부가 아니라 최대·마지막만', /i === maxAt \|\| i === last/.test(adm));
ok('막대마다 짚으면 값이 나온다 (title)', /title="' \+ E\(r\.day\)/.test(adm));
ok('채널 비교 막대는 같은 한 눈금을 쓴다', /function compareTable[\s\S]{0,400}?\/ max\) \* 100/.test(adm));
const css = fs.readFileSync(path.join(ROOT, 'public/admin/style.css'), 'utf8');
ok('막대 위만 둥글다 (아래는 기준선에 붙는다)', /border-radius:4px 4px 0 0/.test(css));
ok('이름표 자리를 위에 비워 둔다', /padding-top:16px/.test(css));

ok('계단 이벤트 여섯 칸이 있다',
   /landing_view[\s\S]{0,400}cta_click[\s\S]{0,400}login_start[\s\S]{0,400}signup_done[\s\S]{0,400}map_open[\s\S]{0,400}parcel_view/.test(adm));
ok('QR 은 눌러야 그린다 (미리 스무 장 그리지 않는다)', /lnk-qr[\s\S]{0,600}addEventListener\('click'/.test(adm));
const tr = fs.readFileSync(path.join(ROOT, 'public/lib/track.js'), 'utf8');
ok('한 번만 보낼 사건은 같은 탭에서 두 번 안 간다', /once: function/.test(tr) && /sessionStorage/.test(tr));
ok('모든 사건에 캠페인이 자동으로 붙는다', /p\.campaign = f\.utm_campaign/.test(tr));
ok('첫 접점 기준으로 붙인다 (마지막 접점이 아니다)', /readStore\(KEY_FIRST\)/.test(tr));
const qr = fs.readFileSync(path.join(ROOT, 'public/lib/qr.js'), 'utf8');
ok('QR 은 외부 서비스에 주소를 넘기지 않는다', !/https?:\/\/(?!www\.w3\.org)/.test(qr));
ok('조용한 테두리를 4모듈 둔다', /quiet == null \? 4/.test(qr));

console.log('\n10. 방침이 실제로 있다');
const legal = fs.readFileSync(path.join(ROOT, 'public/legal/index.html'), 'utf8');
ok('행태정보 절이 있다', /행태정보/.test(legal));
ok('거부 방법을 적는다', /차단|거부/.test(legal));
ok('Google 을 수탁자로 적는다', /Google LLC/.test(legal));
ok('첫 화면에서 방침으로 갈 수 있다',
  /href="\/legal"/.test(fs.readFileSync(path.join(ROOT, 'public/index.html'), 'utf8')));

console.log(bad ? `\n${bad}건 실패` : '\n모두 통과');
process.exit(bad ? 1 : 0);
