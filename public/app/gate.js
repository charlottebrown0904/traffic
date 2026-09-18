/* N0514 */
(function () {
  var NEXT = "/account?next=" + encodeURIComponent("/app");
  var el = document.documentElement;

  // 확인이 끝나기 전에는 아무것도 보여주지 않는다.
  el.style.visibility = "hidden";

  function show() {
    el.style.visibility = "";
  }

  function enter() {
    show();
    var s = document.createElement("script");
    // N0515
    s.src = "/app/app.js?v=20260918a";
    document.body.appendChild(s);
  }

  function toLogin() {
    location.replace(NEXT);
  }

  /* N0516 */
  function pending(status) {
    show();
    var rejected = status === "rejected";
    document.body.innerHTML =
      '<div style="max-width:34rem;margin:18vh auto;padding:0 1.5rem;' +
      'font:400 15px/1.7 system-ui,sans-serif;color:var(--ink)">' +
      "<h1 style='font-size:1.3rem;margin:0 0 .75rem'>" +
      (rejected ? "가입이 승인되지 않았습니다" : "가입 승인을 기다리고 있습니다") +
      "</h1><p style='color:var(--muted);margin:0 0 1.25rem'>" +
      (rejected
        ? "문의가 필요하시면 관리자에게 연락해 주세요."
        : "관리자가 확인한 뒤 이용하실 수 있습니다. 승인되면 이 화면 대신 지도가 열립니다.") +
      "</p><p><a href=\"/account\" style=\"color:var(--accent)\">내 계정</a>" +
      ' &nbsp;·&nbsp; <a href="/" style="color:var(--accent)">홈으로</a></p></div>';
  }

  /* N0517 */
  function broken(why) {
    show();
    document.body.innerHTML =
      '<div style="max-width:34rem;margin:18vh auto;padding:0 1.5rem;' +
      'font:400 15px/1.7 system-ui,sans-serif;color:var(--ink)">' +
      "<h1 style='font-size:1.3rem;margin:0 0 .75rem'>로그인 상태를 확인하지 못했습니다</h1>" +
      "<p style='color:var(--muted);margin:0 0 1.25rem'>" + why + "</p>" +
      '<p><a href="' + NEXT + '" style="color:var(--accent)">로그인 화면으로 가기</a>' +
      ' &nbsp;·&nbsp; <a href="/" style="color:var(--accent)">홈으로</a></p></div>';
  }

  async function check() {
    if (!window.SBUtil || !window.SB) {
      broken("로그인 기능이 초기화되지 않았습니다. 잠시 뒤 새로고침해 주세요.");
      return;
    }
    try {
      var me = await window.SBUtil.me();
      if (!me || !me.user) {
        toLogin();
        return;
      }
      /* N0518 */
      var status = me.profile && me.profile.status;
      if (status !== "approved") {
        pending(status);
        return;
      }
      // 앱이 등급을 본다 (프리미엄 가림). 자물쇠는 데이터베이스다.
      window.ME = me;
      enter();
    } catch (err) {
      broken("확인 중 오류가 났습니다 — " + (err && err.message ? err.message : err));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", check);
  } else {
    check();
  }
})();
