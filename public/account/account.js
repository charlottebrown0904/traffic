/* 로그인 화면.
   비밀번호를 받지 않는다 — 구글·카카오가 본인 확인을 대신하고, 우리는
   보관할 비밀번호가 없다. 유출될 것이 없는 쪽이 안전하다. */
(function () {
  var root = document.getElementById("root");

  var ICON = {
    google:
      '<svg class="ic" viewBox="0 0 48 48" aria-hidden="true"><path fill="#4285F4" d="M45 24c0-1.6-.1-2.7-.4-3.9H24v7.1h12c-.2 1.9-1.5 4.7-4.4 6.6l6.7 5.2C42.2 35.5 45 30.3 45 24z"/><path fill="#34A853" d="M24 46c5.9 0 10.9-2 14.5-5.3l-6.9-5.4c-1.9 1.3-4.4 2.2-7.6 2.2-5.8 0-10.7-3.8-12.5-9.1l-7.1 5.5C8.1 41.1 15.4 46 24 46z"/><path fill="#FBBC05" d="M11.5 28.4c-.5-1.4-.7-2.9-.7-4.4s.3-3 .7-4.4l-7.1-5.5C2.9 17 2 20.4 2 24s.9 7 2.4 9.9l7.1-5.5z"/><path fill="#EA4335" d="M24 10.6c3.3 0 5.5 1.4 6.8 2.6l6-5.9C33 3.9 29.9 2 24 2 15.4 2 8.1 6.9 4.4 14.1l7.1 5.5C13.3 14.4 18.2 10.6 24 10.6z"/></svg>',
    kakao:
      '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 3C6.9 3 2.8 6.3 2.8 10.3c0 2.6 1.7 4.9 4.3 6.2-.2.7-.7 2.6-.8 3-.1.5.2.5.4.4.2-.1 2.7-1.8 3.7-2.6.5.1 1.1.1 1.6.1 5.1 0 9.2-3.3 9.2-7.3S17.1 3 12 3z"/></svg>',
  };
  var LABEL = { google: "구글로 계속하기", kakao: "카카오로 계속하기" };

  function loginView(msg) {
    var cfg = window.SUPABASE || {};
    var list = (cfg.providers || ["google", "kakao"])
      .map(function (p) {
        return (
          '<button class="btn-oauth ' + p + '" data-p="' + p + '">' +
          (ICON[p] || "") + "<span>" + (LABEL[p] || p) + "</span></button>"
        );
      })
      .join("");

    root.innerHTML =
      '<div class="auth-card">' +
      "<h1>로그인 · 회원가입</h1>" +
      '<p class="lead">따로 가입 절차가 없습니다. 아래 계정으로 바로 시작하세요.</p>' +
      (msg ? '<div class="note block" style="margin-bottom:1rem">' + msg + "</div>" : "") +
      list +
      '<p class="note" style="margin-top:1.25rem">' +
      "지도와 관심 매물, 게시판 글쓰기에 로그인이 필요합니다. 가이드는 로그인 없이 볼 수 있습니다." +
      "</p></div>";

    Array.prototype.forEach.call(root.querySelectorAll("[data-p]"), function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        try {
          var back = new URLSearchParams(location.search).get("next") || "/account";
          var r = await window.SBUtil.signIn(btn.dataset.p, location.origin + back);
          if (r && r.error) throw r.error;
        } catch (err) {
          btn.disabled = false;
          loginView("로그인을 시작하지 못했습니다 — " + (err.message || err));
        }
      });
    });
  }

  var STATUS_LABEL = {
    pending: "승인 대기 중",
    approved: "이용 중",
    rejected: "승인되지 않음",
  };

  /* 관리자 승인 화면.

     대시보드를 열지 않고 휴대폰에서 처리하실 수 있어야 한다. 그래서
     대기자 목록을 여기에 둔다. 실제 권한은 RLS 가 정하므로, 관리자가
     아닌 사람에게 이 화면이 보이더라도 승인은 서버에서 거부된다 —
     화면은 편의이지 자물쇠가 아니다. */
  async function renderPending(box) {
    box.innerHTML = '<p class="note">대기자를 불러오는 중…</p>';
    var r = await window.SB.from("profile")
      .select("id,nickname,email,role,status,created_at")
      .eq("status", "pending")
      .order("created_at", { ascending: true });

    if (r.error) {
      box.innerHTML = '<div class="note block">대기자 목록을 못 읽었습니다 — ' +
        window.SBUtil.esc(r.error.message) + "</div>";
      return;
    }
    var rows = r.data || [];
    if (!rows.length) {
      box.innerHTML = '<p class="note">승인을 기다리는 가입자가 없습니다.</p>';
      return;
    }

    box.innerHTML =
      '<h2 style="font-size:1rem;margin:0 0 .5rem">가입 승인 대기 ' +
      rows.length + "명</h2><ul id=\"pend\" style=\"list-style:none;padding:0;margin:0\">" +
      rows.map(function (u) {
        return '<li data-id="' + window.SBUtil.esc(u.id) + '" ' +
          'style="border-top:1px solid #e7ded2;padding:.75rem 0">' +
          "<b>" + window.SBUtil.esc(u.nickname || "(이름 없음)") + "</b> " +
          '<span class="note">' + window.SBUtil.esc(u.email || "") + "</span><br>" +
          '<span class="note">신청 ' + window.SBUtil.when(u.created_at) + "</span>" +
          '<span style="display:inline-flex;gap:.4rem;margin-left:.75rem">' +
          '<button class="btn" data-act="approved">승인</button>' +
          '<button class="btn ghost" data-act="rejected">거절</button></span></li>';
      }).join("") + "</ul>";

    Array.prototype.forEach.call(box.querySelectorAll("[data-act]"), function (btn) {
      btn.addEventListener("click", async function () {
        var li = btn.closest("li");
        var id = li.getAttribute("data-id");
        btn.disabled = true;
        var r2 = await window.SB.from("profile")
          .update({ status: btn.dataset.act }).eq("id", id);
        if (r2.error) {
          btn.disabled = false;
          alert("처리하지 못했습니다 — " + r2.error.message);
          return;
        }
        renderPending(box);
      });
    });
  }

  function accountView(me) {
    var u = me.user;
    var p = me.profile || {};
    var name = p.nickname || u.email || "이용자";
    var role = { user: "일반 회원", broker: "중개사", admin: "관리자" }[p.role] || p.role;
    // profile 이 아직 없으면 승인 전으로 본다. 모르는 것을 통과로
    // 처리하면 안 된다 — gate.js 와 같은 판단이다.
    var status = p.status || "pending";
    var ok = status === "approved";

    root.innerHTML =
      '<div class="auth-card">' +
      "<h1>" + window.SBUtil.esc(name) + "</h1>" +
      '<p class="lead">' + window.SBUtil.esc(u.email || "") + " · " + role + "</p>" +
      '<div class="note" style="margin-bottom:1.25rem">가입일 ' +
      new Date(u.created_at).toLocaleDateString("ko-KR") +
      " · 상태 " + (STATUS_LABEL[status] || status) + "</div>" +
      (ok ? "" :
        '<div class="note block" style="margin-bottom:1rem">' +
        (status === "rejected"
          ? "가입이 승인되지 않았습니다. 문의가 필요하시면 관리자에게 연락해 주세요."
          : "관리자 승인 후 지도와 게시판을 이용하실 수 있습니다.") + "</div>") +
      '<p style="display:flex;gap:.5rem;flex-wrap:wrap">' +
      (ok ? '<a class="btn" href="/app">지도 보기</a>' +
            '<a class="btn ghost" href="/board">게시판 가기</a>' : "") +
      '<button class="btn ghost" id="out">로그아웃</button></p>' +
      '<div id="admin" style="margin-top:1.5rem"></div>' +
      "</div>";

    document.getElementById("out").addEventListener("click", async function () {
      await window.SBUtil.signOut();
      location.reload();
    });

    if (p.role === "admin") renderPending(document.getElementById("admin"));
  }

  (async function () {
    if (!window.SBUtil.guard(root)) return;
    var me = await window.SBUtil.me();
    if (me) accountView(me);
    else loginView(null);
  })();
})();
