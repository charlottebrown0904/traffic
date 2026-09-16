/* /l/<코드> — 자체 단축 링크. 클릭 하나를 세고 목적지로 보낸다.
 *
 * 왜 우리가 직접 만드나. bit.ly 같은 데를 쓰면 클릭 수가 남의 계정에
 * 남고, 그 클릭이 우리 가입과 이어지지 않는다. 우리가 알고 싶은 것은
 * '몇 명이 눌렀나' 가 아니라 **'누른 사람 중 몇이 회원이 됐나'** 다.
 *
 * 지키는 것 여섯 (전부 실제로 데어 본 자리다):
 *
 *   302 + no-store   301 이면 브라우저가 캐시해 **두 번째 클릭부터
 *                    서버에 요청이 안 온다.** 그러면 클릭이 1 에서 멈춘다.
 *   미리보기 봇 제외  카카오톡·페북·슬랙이 링크를 먼저 열어 본다. 안
 *                    거르면 아무도 안 눌러도 숫자가 오른다.
 *   HEAD 는 안 셈     링크 검사기가 HEAD 를 보낸다.
 *   한 번의 SQL      합계 +1 과 기록 insert 를 함수 하나로. 나누면
 *                    동시에 눌렸을 때 어긋난다.
 *   DB 의 url 만     주소 파라미터로 받은 URL 로는 절대 안 보낸다
 *                    (오픈 리다이렉트). DB 에도 같은 제약이 걸려 있다.
 *   모르는 코드도 랜딩  손님을 막다른 곳에 두지 않는다. 대신 꼬리표를
 *                    붙여 '어떤 코드가 헛돌았나' 를 남긴다.
 */

const SITE = 'https://toji.fyi';
const SB_URL = process.env.SUPABASE_URL || 'https://caykbxvnebpifcduqjre.supabase.co';
/* 공개(publishable) 키다. 이 키로 할 수 있는 일은 RLS 가 정하고,
   hit_link 가 하는 일은 '코드를 주소로 바꾸고 1 을 더하는 것' 뿐이다. */
const SB_KEY = process.env.SUPABASE_ANON_KEY || 'sb_publishable_S1otGjMvBab-ZtXUO_cM2Q_4VYxrdkQ';

const BOT_UA = /bot|crawl|spider|slurp|facebookexternalhit|facebookcatalog|kakaotalk-scrap|kakaostory|twitterbot|slackbot|discordbot|telegrambot|whatsapp|linkedinbot|pinterest|skypeuripreview|embedly|line-poker|yeti|daum|preview|curl\/|wget\//i;

/* 같은 곳에서 몰아치는 것만 막는다. 사람이 누르는 속도로는 절대 안 걸린다. */
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT = 120;
const RATE_MAX_KEYS = 5000;
const rateHits = new Map();

function tooMany(req) {
  const ip = (req.headers['x-forwarded-for'] || '').split(',')[0].trim() || 'unknown';
  const now = Date.now();
  if (rateHits.size > RATE_MAX_KEYS) rateHits.clear();
  const cur = rateHits.get(ip);
  if (!cur || now - cur.at > RATE_WINDOW_MS) {
    rateHits.set(ip, { at: now, n: 1 });
    return false;
  }
  cur.n += 1;
  return cur.n > RATE_LIMIT;
}

function normCode(v) {
  return String(v == null ? '' : v).trim().toLowerCase()
    .replace(/[^a-z0-9._-]/g, '').slice(0, 40);
}

function deviceOf(ua) {
  if (!ua) return 'other';
  if (/mobile|iphone|ipod|android.+mobile|windows phone/i.test(ua)) return 'mobile';
  if (/ipad|tablet|android/i.test(ua)) return 'mobile';
  if (/macintosh|windows nt|x11|linux/i.test(ua)) return 'desktop';
  return 'other';
}

/* 추천인은 **도메인만.** 전체 주소에는 검색어나 남의 사이트의 개인정보가
   붙어 오는 일이 있다. */
function hostOf(referer) {
  if (!referer) return null;
  try { return new URL(referer).hostname.replace(/^www\./, '').slice(0, 200); }
  catch (e) { return null; }
}

function fallbackUrl(code) {
  return SITE + '/?utm_source=short-link&utm_medium=unknown&utm_content='
    + encodeURIComponent(code || 'empty');
}

/* fn='hit_link' 이면 세고, 'peek_link' 면 목적지만 본다.
   **봇에게 hit_link 를 부르면 결국 세어진다** — 문을 둘로 나눠야 한다. */
async function ask(fn, body) {
  const r = await fetch(SB_URL + '/rest/v1/rpc/' + fn, {
    method: 'POST',
    headers: {
      apikey: SB_KEY,
      Authorization: 'Bearer ' + SB_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(fn + ' ' + r.status);
  const url = await r.json();
  return typeof url === 'string' && url ? url : null;
}

module.exports = async function handler(req, res) {
  const method = (req.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    res.status(405).json({ error: 'GET 또는 HEAD 만 받습니다' });
    return;
  }

  const raw = (req.query && (req.query.code || req.query.c)) || '';
  const code = normCode(Array.isArray(raw) ? raw[0] : raw);
  const ua = req.headers['user-agent'] || '';
  // 미리보기 봇과 HEAD 는 보내 주되 세지 않는다.
  const countIt = Boolean(code) && method === 'GET' && !BOT_UA.test(ua) && !tooMany(req);

  let url = null;
  try {
    if (code) {
      url = countIt
        ? await ask('hit_link', { p_code: code, p_device: deviceOf(ua),
                                  p_referer: hostOf(req.headers.referer || req.headers.referrer) })
        // 세지 않는 쪽. 봇에게도 제대로 된 목적지를 보여 준다.
        : await ask('peek_link', { p_code: code });
    }
  } catch (e) {
    console.error('[short-link]', e && e.message);
  }

  // 301 이 아니라 302 + no-store. 캐시되면 다음 클릭이 서버에 안 온다.
  res.setHeader('Cache-Control', 'no-store, max-age=0');
  res.setHeader('Location', url || fallbackUrl(code));
  res.status(302).end();
};

module.exports.__test = { normCode, deviceOf, hostOf, BOT_UA, fallbackUrl };
