/* /app 은 회원 전용이다.

   로그인을 확인한 뒤에야 앱 코드를 붙인다. 확인 전에 app.js 를 미리
   실행해두면 지도가 한 번 그려졌다가 사라지는 깜빡임이 생기고, 로그인
   없이 들어온 사람에게도 화면이 잠깐 보인다.

   이것은 화면 관문이지 자물쇠가 아니다. /app/data 의 JSON 은 주소를
   알면 그대로 받을 수 있다. 자료 자체를 가리려면 인증을 거치는 API
   뒤로 옮겨야 한다. 지금 목적은 가입을 받는 것이므로 여기까지 한다. */
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
    // 캐시 무효화용 꼬리표. 이것이 없으면 style.css·app.js 를 고쳐도
    // 이미 받아 둔 브라우저에는 영영 안 간다 — 화면이 반만 바뀐다.
    s.src = "/app/app.js?v=20260911c";
    document.body.appendChild(s);
  }

  function toLogin() {
    location.replace(NEXT);
  }

  /* 로그인은 됐는데 아직 승인 전인 경우.
     로그인 화면으로 되돌리면 안 된다 — 다시 로그인해도 같은 자리로
     돌아오므로, 사람은 무엇이 문제인지 모른 채 같은 고리를 돈다. */
  function pending(status) {
    show();
    var rejected = status === "rejected";
    document.body.innerHTML =
      '<div style="max-width:34rem;margin:18vh auto;padding:0 1.5rem;' +
      'font:400 15px/1.7 system-ui,sans-serif;color:#3d3227">' +
      "<h1 style='font-size:1.3rem;margin:0 0 .75rem'>" +
      (rejected ? "가입이 승인되지 않았습니다" : "가입 승인을 기다리고 있습니다") +
      "</h1><p style='color:#7a6a58;margin:0 0 1.25rem'>" +
      (rejected
        ? "문의가 필요하시면 관리자에게 연락해 주세요."
        : "관리자가 확인한 뒤 이용하실 수 있습니다. 승인되면 이 화면 대신 지도가 열립니다.") +
      "</p><p><a href=\"/account\" style=\"color:#8A6547\">내 계정</a>" +
      ' &nbsp;·&nbsp; <a href="/" style="color:#8A6547">홈으로</a></p></div>';
  }

  /* 로그인 여부를 확인할 수 없을 때. 들여보내는 것도 막는 것도 틀렸다 —
     둘 다 사실이 아닌 것을 사실인 양 처리하는 것이다. 무엇이 안 되는지
     말하고 사람이 판단하게 둔다. */
  function broken(why) {
    show();
    document.body.innerHTML =
      '<div style="max-width:34rem;margin:18vh auto;padding:0 1.5rem;' +
      'font:400 15px/1.7 system-ui,sans-serif;color:#3d3227">' +
      "<h1 style='font-size:1.3rem;margin:0 0 .75rem'>로그인 상태를 확인하지 못했습니다</h1>" +
      "<p style='color:#7a6a58;margin:0 0 1.25rem'>" + why + "</p>" +
      '<p><a href="' + NEXT + '" style="color:#8A6547">로그인 화면으로 가기</a>' +
      ' &nbsp;·&nbsp; <a href="/" style="color:#8A6547">홈으로</a></p></div>';
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
      /* 승인 상태를 화면에서도 본다.
         진짜 자물쇠는 데이터베이스의 RLS 다 — 승인 안 된 계정은 글도
         댓글도 못 읽는다. 여기서 막는 것은 '왜 화면이 비었는지' 를
         사람이 알 수 있게 하기 위해서지, 이것이 보안은 아니다.

         profile 이 아직 없을 수도 있다(가입 직후 트리거 시차). 그때는
         승인 전으로 본다 — 모르는 것을 통과로 처리하면 안 된다. */
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
