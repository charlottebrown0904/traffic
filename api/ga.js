/* GA4 숫자를 우리 어드민으로 — **키 파일 없이.**
 *
 * 흔한 방법은 서비스 계정 JSON 키를 환경변수에 통째로 넣는 것인데, 그러면
 * 영구 자격증명이 하나 더 생긴다. 대신 Vercel 이 배포마다 발급하는 OIDC
 * 토큰으로 구글에게 '나는 이 프로젝트의 production 이다' 를 증명하고,
 * 짧은 수명의 토큰을 받아 쓴다. **키가 없으니 샐 키도 없다.**
 *
 *   ① Vercel OIDC 토큰 (VERCEL_OIDC_TOKEN, 배포마다 자동)
 *   ② → STS 토큰 교환 (Workload Identity 연합)
 *   ③ → 서비스 계정 가장 (IAM Credentials)
 *   ④ → GA Data API runReport
 *
 * 라이브러리를 쓰지 않고 fetch 넷으로 한다. 이 저장소에는 package.json 이
 * 없고, 없는 편이 배포가 단순하다. 덤으로 google-auth-library 를 쓸 때
 * 흔히 걸리는 audience 어긋남(invalid_grant)도 애초에 안 생긴다 —
 * 우리가 audience 를 직접 적기 때문이다.
 *
 * 환경변수 (전부 비밀이 아니다. 식별자일 뿐):
 *   GA_PROPERTY_ID · GCP_PROJECT_NUMBER · GCP_WIF_POOL_ID
 *   GCP_WIF_PROVIDER_ID · GCP_SERVICE_ACCOUNT_EMAIL
 * 설정 절차는 docs/ga-oidc.md.
 */

const NEED = ['GA_PROPERTY_ID', 'GCP_PROJECT_NUMBER', 'GCP_WIF_POOL_ID',
              'GCP_WIF_PROVIDER_ID', 'GCP_SERVICE_ACCOUNT_EMAIL'];

const CACHE_MS = 5 * 60_000;   // 구글 할당량을 아낀다. 5분이면 충분하다.
let cache = { at: 0, body: null };

function missingEnv() {
  const miss = NEED.filter((k) => !process.env[k]);
  if (!process.env.VERCEL_OIDC_TOKEN) miss.push('VERCEL_OIDC_TOKEN');
  return miss;
}

async function post(url, body, headers) {
  const r = await fetch(url, {
    method: 'POST',
    headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}),
    body: JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) {
    // 구글 오류 본문을 자르지 않는다. 자르면 원인이 통째로 사라진다.
    throw new Error(url.replace(/https:\/\/([^/]+).*/, '$1') + ' ' + r.status + ' ' + text.slice(0, 500));
  }
  return JSON.parse(text);
}

async function accessToken() {
  const num = process.env.GCP_PROJECT_NUMBER;
  const audience = '//iam.googleapis.com/projects/' + num
    + '/locations/global/workloadIdentityPools/' + process.env.GCP_WIF_POOL_ID
    + '/providers/' + process.env.GCP_WIF_PROVIDER_ID;

  const sts = await post('https://sts.googleapis.com/v1/token', {
    audience,
    grantType: 'urn:ietf:params:oauth:grant-type:token-exchange',
    requestedTokenType: 'urn:ietf:params:oauth:token-type:access_token',
    scope: 'https://www.googleapis.com/auth/cloud-platform',
    subjectTokenType: 'urn:ietf:params:oauth:token-type:jwt',
    subjectToken: process.env.VERCEL_OIDC_TOKEN,
  });

  const sa = await post(
    'https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'
      + encodeURIComponent(process.env.GCP_SERVICE_ACCOUNT_EMAIL) + ':generateAccessToken',
    { scope: ['https://www.googleapis.com/auth/analytics.readonly'], lifetime: '600s' },
    { Authorization: 'Bearer ' + sts.access_token });

  return sa.accessToken;
}

async function report(token, body) {
  return post('https://analyticsdata.googleapis.com/v1beta/properties/'
    + encodeURIComponent(process.env.GA_PROPERTY_ID) + ':runReport', body,
    { Authorization: 'Bearer ' + token });
}

const rows = (r) => (r.rows || []).map((x) => ({
  key: (x.dimensionValues || []).map((d) => d.value),
  v: (x.metricValues || []).map((m) => Number(m.value) || 0),
}));

module.exports = async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');

  const miss = missingEnv();
  if (miss.length) {
    // **왜 안 되는지를 화면에 그대로 보낸다.** '연결 실패' 네 글자만
    // 보여 주면 무엇을 고쳐야 하는지 아무도 모른다.
    res.status(200).json({
      connected: false,
      reason: '환경변수가 아직 없습니다: ' + miss.join(', '),
      how: 'docs/ga-oidc.md 의 절차를 따라 GCP 를 세우고 Vercel 환경변수에 넣습니다.',
    });
    return;
  }

  if (cache.body && Date.now() - cache.at < CACHE_MS) {
    res.status(200).json(cache.body);
    return;
  }

  try {
    const token = await accessToken();
    const range = [{ startDate: '28daysAgo', endDate: 'today' }];
    const [total, bySource, byDay, byEvent] = await Promise.all([
      report(token, { dateRanges: range,
        metrics: [{ name: 'sessions' }, { name: 'totalUsers' }, { name: 'engagementRate' }] }),
      report(token, { dateRanges: range, limit: 20,
        dimensions: [{ name: 'sessionSource' }, { name: 'sessionMedium' }],
        metrics: [{ name: 'sessions' }],
        orderBys: [{ metric: { metricName: 'sessions' }, desc: true }] }),
      report(token, { dateRanges: [{ startDate: '14daysAgo', endDate: 'today' }],
        dimensions: [{ name: 'date' }], metrics: [{ name: 'sessions' }],
        orderBys: [{ dimension: { dimensionName: 'date' } }] }),
      report(token, { dateRanges: range, limit: 20,
        dimensions: [{ name: 'eventName' }], metrics: [{ name: 'eventCount' }],
        orderBys: [{ metric: { metricName: 'eventCount' }, desc: true }] }),
    ]);

    const body = {
      connected: true,
      at: new Date().toISOString(),
      property: process.env.GA_PROPERTY_ID,
      total: rows(total)[0] ? rows(total)[0].v : [0, 0, 0],
      by_source: rows(bySource),
      by_day: rows(byDay),
      by_event: rows(byEvent),
    };
    cache = { at: Date.now(), body };
    res.status(200).json(body);
  } catch (e) {
    res.status(200).json({
      connected: false,
      reason: String((e && e.message) || e).slice(0, 600),
      how: 'docs/ga-oidc.md 의 "막혔을 때" 절을 봅니다.',
    });
  }
};
