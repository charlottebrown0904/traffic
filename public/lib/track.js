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

  /** 값을 눕히고 다듬는다. 규칙은 window.UTM(public/lib/utm.js) 한 곳에
      있다 — 링크를 만드는 쪽과 받는 쪽이 같은 규칙을 써야 장부가 맞는다.
      utm.js 를 못 불렀을 때를 대비해 같은 규칙의 간이판을 둔다. */
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
      // **소문자로 눕힌다.** 'Naver' 와 'naver' 를 따로 세면 같은 캠페인이
      // 집계에서 두 줄로 쪼개진다 — 광고를 켜기 전이라 지금 고치면 공짜다.
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

  /* GA4 초기화는 여기서 하지 않는다 — **각 쪽의 <head> 인라인**이 맡는다
     (public/lib/ga-head.html 과 같은 모양). 이 파일은 defer 로 늦게 붙으므로,
     여기서 gtag 를 세우면 페이지가 뜨자마자 쏘는 첫 이벤트가 gtag 없는
     상태로 버려진다. 그 증상은 '아무것도 안 뜬다' 가 아니라 '초기 이벤트만
     안 뜬다' 여서 찾는 데 오래 걸린다.

     여기서는 첫 접점이 잡혔을 때 그것을 GA 에도 한 번 알린다 — 그래야
     구글 쪽 보고서와 우리 장부가 같은 캠페인을 가리킨다. */
  if (now && typeof window.gtag === 'function') {
    window.gtag('event', 'utm_seen', {
      utm_source: now.utm_source || (now.referrer ? 'referral' : '(none)'),
      utm_medium: now.utm_medium || (now.referrer ? 'referral' : '(none)'),
      utm_campaign: now.utm_campaign || '(none)',
    });
  }
})();
