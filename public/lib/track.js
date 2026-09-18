/* N0735 */
(function () {
  var KEY_FIRST = 'toji.utm.first';
  var KEY_LAST = 'toji.utm.last';
  var FIELDS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];

  function readStore(k) {
    try { return JSON.parse(localStorage.getItem(k) || 'null'); }
    catch (e) { return null; }
  }
  function writeStore(k, v) {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 사생활 모드 */ }
  }

  /** 어디서 눌러 왔나 — **도메인만.** 경로·질의는 버린다. */
  function refHost() {
    var r = document.referrer || '';
    if (!r) return null;
    try {
      var h = new URL(r).hostname;
      // 우리 안에서의 이동은 유입이 아니다.
      return h && h !== location.hostname ? h : null;
    } catch (e) { return null; }
  }

  /* N0736 */
  function norm(v) {
    if (window.UTM && window.UTM.normValue) return window.UTM.normValue(v);
    return String(v == null ? '' : v).trim().toLowerCase()
      .replace(/\s+/g, '-').replace(/[^a-z0-9._-]/g, '')
      .replace(/-{2,}/g, '-').replace(/^-|-$/g, '').slice(0, 60);
  }

  /** 이번 방문의 꼬리표. 하나도 없으면 null. */
  function pick() {
    var q = new URLSearchParams(location.search);
    var out = {};
    var any = false;
    FIELDS.forEach(function (f) {
      // N0737
      var v = norm(q.get(f));
      if (v) { out[f] = v; any = true; }
    });
    // 광고 클릭 식별자. 꼬리표를 안 붙였어도 이것만 오는 경우가 있다.
    ['gclid', 'fbclid', 'kclid'].forEach(function (f) {
      if (q.get(f)) { out.click_id = f; any = true; }
    });
    var ref = refHost();
    if (ref) { out.referrer = ref; any = true; }
    if (!any) return null;
    out.at = new Date().toISOString();
    out.landing = location.pathname.slice(0, 120);
    return out;
  }

  var now = pick();
  if (now) {
    // N0738
    if (!readStore(KEY_FIRST)) writeStore(KEY_FIRST, now);
    writeStore(KEY_LAST, now);
  }

  window.TRACK = {
    first: function () { return readStore(KEY_FIRST); },
    last: function () { return readStore(KEY_LAST); },
    /** 프로필에 넣을 모양. 없으면 null. */
    forProfile: function () {
      var f = readStore(KEY_FIRST);
      if (!f) return null;
      return {
        utm_source: f.utm_source || (f.referrer ? 'referral' : null),
        utm_medium: f.utm_medium || (f.referrer ? 'referral' : null),
        utm_campaign: f.utm_campaign || null,
        utm_term: f.utm_term || null,
        utm_content: f.utm_content || null,
        landing_ref: f.referrer || null,
        landing_path: f.landing || null,
        landing_at: f.at || null,
      };
    },
    /* N0739 */
    event: function (name, params) {
      if (typeof window.gtag !== 'function') return;
      var f = readStore(KEY_FIRST) || {};
      var p = {};
      Object.keys(params || {}).forEach(function (k) { p[k] = params[k]; });
      p.campaign = f.utm_campaign || '(none)';
      p.first_source = f.utm_source || (f.referrer ? 'referral' : '(direct)');
      window.gtag('event', name, p);
    },

    /* N0740 */
    once: function (name, params) {
      var k = 'toji.ev.' + name;
      try {
        if (sessionStorage.getItem(k)) return;
        sessionStorage.setItem(k, '1');
      } catch (e) { /* 사생활 창 — 그때는 매번 보낸다 */ }
      window.TRACK.event(name, params);
    },
  };

  /* N0741 */
  if (now && typeof window.gtag === 'function') {
    window.gtag('event', 'utm_seen', {
      utm_source: now.utm_source || (now.referrer ? 'referral' : '(none)'),
      utm_medium: now.utm_medium || (now.referrer ? 'referral' : '(none)'),
      utm_campaign: now.utm_campaign || '(none)',
    });
  }

  /* N0742 */
  var path = location.pathname.replace(/\/$/, '') || '/';
  if (path === '/') window.TRACK.once('landing_view', { landing: '/' });
  else if (path === '/app') window.TRACK.once('map_open', {});
})();
