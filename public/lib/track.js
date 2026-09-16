/* 유입 경로(UTM)와 방문 통계(GA) — 한 파일에서 (2026-09-16 지시).
 *
 *   "admin 탭 대쉬보드에 UTM, GA 준비합시다."
 *
 * 두 가지는 **하는 일이 다르다.**
 *
 *   UTM   '이 사람이 어디서 왔나' 를 **가입에 붙인다.** 광고를 한 건 돌리고
 *         그 건에서 몇 명이 가입했는지는 우리 자료에만 있다. GA 로는
 *         '방문 수' 는 보이지만 '누가 회원이 됐나' 는 안 보인다.
 *   GA    쪽수·머문 시간·기기처럼 **우리가 안 쌓는 것**을 본다.
 *
 * ## 첫 접점을 쓴다 (last touch 아님)
 *
 * 광고를 보고 들어왔다가 며칠 뒤 검색으로 다시 와서 가입하는 일이 흔하다.
 * 마지막 접점만 보면 그 가입이 '자연 검색' 이 되고, 광고비를 쓴 쪽이
 * 공을 못 받는다. 그래서 **처음 온 경로를 덮어쓰지 않는다.** 마지막 접점도
 * 따로 남겨 둔다 — 나중에 둘을 견줄 수 있게.
 *
 * ## 개인을 식별하지 않는다
 *
 * 여기 담기는 것은 광고 꼬리표(utm_*)와 어디서 눌러 왔는지(referrer)의
 * **도메인**뿐이다. referrer 의 경로·질의는 버린다 — 거기에 검색어나
 * 남의 사이트의 개인정보가 붙어 오는 일이 있다.
 */
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

  /** 이번 방문의 꼬리표. 하나도 없으면 null. */
  function pick() {
    var q = new URLSearchParams(location.search);
    var out = {};
    var any = false;
    FIELDS.forEach(function (f) {
      var v = (q.get(f) || '').trim().slice(0, 80);
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
    // **첫 접점은 덮어쓰지 않는다.** 광고로 왔다가 며칠 뒤 검색으로
    // 돌아와 가입하면, 마지막만 보는 순간 그 가입은 '자연 검색' 이 된다.
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
    /** GA 에 사건 하나. GA 가 없으면 조용히 아무것도 안 한다. */
    event: function (name, params) {
      if (typeof window.gtag === 'function') window.gtag('event', name, params || {});
    },
  };

  /* ── GA4 ────────────────────────────────────────────────────────
     측정 ID 는 window.ANALYTICS.ga4 에서 온다 (app/supabase.js). **비어
     있으면 스크립트를 아예 안 붙인다** — 붙여 놓고 ID 만 비우면 구글로
     요청은 나가면서 아무 데도 안 쌓인다. 없는 것과 고장난 것이 같은
     얼굴이 되는 자리다.

     측정 ID(G-...)는 공개 값이다. 브라우저가 그것으로 구글에 보내는 것이
     본래 하는 일이므로 숨길 수 없고 숨길 이유도 없다. */
  var ga = (window.ANALYTICS || {}).ga4 || '';
  if (/^G-[A-Z0-9]+$/i.test(ga)) {
    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(ga);
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    /* anonymize_ip — 구글이 IP 마지막 자리를 지우고 받는다. GA4 는 기본으로
       그렇게 하지만 명시해 둔다. 나중에 이 줄이 지워지면 눈에 띈다. */
    window.gtag('config', ga, { anonymize_ip: true });
  }
})();
