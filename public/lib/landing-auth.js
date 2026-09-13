/* 첫 화면의 로그인·가입 단추 (지시 2026-09-13, 슬라이드 2).

   예전 길: '회원 가입하고 보기' → /account → 거기서 구글·카카오. 한 단계를
   뺀다 — 첫 화면에 구글·카카오 단추가 바로 선다. 로그인이 끝나면 /account 로
   돌아오고, 그 화면이 지도 보기·게시판·프로필 수정·로그아웃을 보여 준다.

   이 파일이 없어도 첫 화면은 멀쩡하다. [data-auth] 안의 링크가 예전 길이고,
   여기서는 그 링크를 단추로 바꿀 뿐이다. Supabase 설정이 없으면 손대지 않는다.
   이미 로그인한 사람에게는 가입 단추 대신 '지도 보기' 를 보여 준다. */
(function () {
  var ICON = {
    google:
      '<svg class="ic" viewBox="0 0 48 48" aria-hidden="true"><path fill="#4285F4" d="M45 24c0-1.6-.1-2.7-.4-3.9H24v7.1h12c-.2 1.9-1.5 4.7-4.4 6.6l6.7 5.2C42.2 35.5 45 30.3 45 24z"/><path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.3l-6.9-5.4c-1.9 1.3-4.4 2.2-7.6 2.2-5.8 0-10.7-3.8-12.5-9.1l-7.1 5.5C8.1 41.1 15.4 46 24 46z"/><path fill="#FBBC05" d="M11.5 28.4c-.5-1.4-.7-2.9-.7-4.4s.3-3 .7-4.4l-7.1-5.5C2.9 17 2 20.4 2 24s.9 7 2.4 9.9l7.1-5.5z"/><path fill="#EA4335" d="M24 10.6c3.3 0 5.5 1.4 6.8 2.6l6-5.9C33 3.9 29.9 2 24 2 15.4 2 8.1 6.9 4.4 14.1l7.1 5.5C13.3 14.4 18.2 10.6 24 10.6z"/></svg>',
    kakao:
      '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 3C6.9 3 2.8 6.3 2.8 10.3c0 2.6 1.7 4.9 4.3 6.2-.2.7-.7 2.6-.8 3-.1.5.2.5.4.4.2-.1 2.7-1.8 3.7-2.6.5.1 1.1.1 1.6.1 5.1 0 9.2-3.3 9.2-7.3S17.1 3 12 3z"/></svg>',
  };
  var LABEL = { google: "구글로 계속하기", kakao: "카카오로 계속하기" };

  function boxes() { return Array.prototype.slice.call(document.querySelectorAll("[data-auth]")); }

  function renderButtons(box, providers) {
    box.innerHTML =
      '<div class="auth-row">' +
      providers.map(function (p) {
        return '<button type="button" class="btn-oauth ' + p + '" data-p="' + p + '">' +
          (ICON[p] || "") + "<span>" + (LABEL[p] || p) + "</span></button>";
      }).join("") +
      "</div>";
    Array.prototype.forEach.call(box.querySelectorAll("[data-p]"), function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          // /account 로 돌아온다 — 그 화면이 지도·게시판·프로필·로그아웃을 보여 준다.
          var r = await window.SBUtil.signIn(btn.dataset.p, location.origin + "/account");
          if (r && r.error) throw r.error;
        } catch (err) {
          btn.disabled = false;
          var msg = box.querySelector(".auth-err") || document.createElement("p");
          msg.className = "auth-err";
          msg.textContent = "로그인을 시작하지 못했습니다 — " + (err && err.message ? err.message : err);
          box.appendChild(msg);
        }
      });
    });
  }

  function renderSignedIn(box, me) {
    var isHero = box.classList.contains("hero-auth");
    var name = (me.profile && me.profile.nickname) || (me.user && me.user.email) || "";
    var ok = me.profile && me.profile.status === "approved";
    box.innerHTML =
      '<div class="auth-row">' +
      (ok
        ? '<a class="' + (isHero ? "hero-link" : "tool-link") + '" href="/app">지도 보기 <span aria-hidden="true">→</span></a>'
        : '<a class="' + (isHero ? "hero-link" : "tool-link") + '" href="/account">내 계정 — 승인 대기 <span aria-hidden="true">→</span></a>') +
      '<a class="' + (isHero ? "hero-link" : "tool-link") + '" href="/account" style="font-weight:600;opacity:.92">' +
      (name ? window.SBUtil.esc(name) + " · " : "") + "내 계정</a>" +
      "</div>";
  }

  async function main() {
    if (!window.SB || !window.SBUtil) return;          // 설정 없음 — 링크 그대로 둔다
    var cfg = window.SUPABASE || {};
    var providers = cfg.providers || ["google", "kakao"];
    var me = null;
    try { me = await window.SBUtil.me(); } catch (e) { me = null; }
    boxes().forEach(function (box) {
      if (me) renderSignedIn(box, me);
      else renderButtons(box, providers);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
})();
