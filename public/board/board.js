/* N0675 */
(function () {
  var root = document.getElementById("root");
  var E = window.SBUtil.esc;
  var CATS = { free: "자유", question: "질문", notice: "공지" };
  var me = null;
  /* N0676 */
  var nameDup = false;

  async function checkNameDup() {
    var nick = me && me.profile && me.profile.nickname;
    if (!nick) { nameDup = false; return; }
    try {
      var r = await window.SB.rpc("nickname_taken", { p_nick: nick });
      // N0677
      nameDup = !r.error && r.data === true;
    } catch (e) { nameDup = false; }
  }

  // 글쓰기·댓글 자리에 붙는 안내. 막지는 않는다 — 고치라고 권한다.
  function dupNotice() {
    if (!nameDup) return "";
    var nick = (me.profile && me.profile.nickname) || "";
    return '<div class="note block dup-name">' +
      "<b>표시 이름 <em>" + E(nick) + "</em> 을 쓰는 회원이 또 있습니다.</b><br>" +
      "게시판은 이름으로 글쓴이를 가리키므로, 지금 이름으로 글을 쓰면 다른 분의 글과 헷갈립니다. " +
      '<a href="/account">내 계정에서 이름 바꾸기</a>' +
      "</div>";
  }

  function route() {
    var h = location.hash.replace(/^#/, "");
    if (h.indexOf("/p/") === 0) return viewPost(h.slice(3));
    if (h === "/write") return viewWrite();
    return viewList();
  }

  /* N0678 */
  async function namesFor(rows) {
    var ids = [];
    (rows || []).forEach(function (r) {
      if (r.user_id && ids.indexOf(r.user_id) < 0) ids.push(r.user_id);
    });
    if (!ids.length) return {};
    var { data } = await window.SB.from("profile_public").select("id,nickname").in("id", ids);
    var map = {};
    (data || []).forEach(function (r) { map[r.id] = r.nickname; });
    return map;
  }

  // 닉네임을 아직 정하지 않은 계정도 있다. 빈칸으로 두면 줄이 어긋난다.
  function whoName(map, uid) {
    return (map && map[uid]) || "이용자";
  }

  /* N0679 */
  function who(map, uid) {
    if (!uid) return E(whoName(map, uid));
    return '<button type="button" class="who-btn" data-uid="' + E(uid) +
           '" data-name="' + E(whoName(map, uid)) + '">' + E(whoName(map, uid)) + "</button>";
  }

  /* N0680 */
  function closeWho() {
    var el = document.getElementById("who-pop");
    if (el) el.remove();
    document.removeEventListener("keydown", whoEsc);
  }
  function whoEsc(e) { if (e.key === "Escape") closeWho(); }

  async function openWho(uid, name) {
    closeWho();
    var wrap = document.createElement("div");
    wrap.id = "who-pop";
    wrap.className = "who-pop";
    wrap.innerHTML =
      '<div class="who-card" role="dialog" aria-modal="true" aria-label="' + E(name) + ' 프로필">' +
      "<h3>" + E(name) + "</h3>" +
      '<div id="who-body"><p class="note">불러오는 중…</p></div>' +
      '<p style="margin:.9rem 0 0"><button class="btn sm ghost" id="who-close">닫기</button></p>' +
      "</div>";
    document.body.appendChild(wrap);
    wrap.addEventListener("click", function (e) { if (e.target === wrap) closeWho(); });
    document.getElementById("who-close").addEventListener("click", closeWho);
    document.addEventListener("keydown", whoEsc);
    document.getElementById("who-close").focus();

    // 관리자가 아니면 행이 아예 안 온다 — 오류가 아니라 빈 결과다.
    var r = await window.SB.from("profile").select("email").eq("id", uid).maybeSingle();
    var mail = r && r.data && r.data.email;
    var body = document.getElementById("who-body");
    if (!body) return;                       // 기다리는 사이에 닫혔다
    if (mail) {
      var href = "mailto:" + encodeURIComponent(mail) +
                 "?subject=" + encodeURIComponent("[토지랩] 문의");
      body.innerHTML =
        '<p class="who-mail">' + E(mail) + "</p>" +
        '<p style="display:flex;gap:.5rem;flex-wrap:wrap">' +
        '<a class="btn sm" href="' + E(href) + '">메일 보내기</a>' +
        '<button class="btn sm ghost" id="who-copy">주소 복사</button></p>';
      var copy = document.getElementById("who-copy");
      if (copy) copy.addEventListener("click", function () {
        navigator.clipboard.writeText(mail).then(function () { copy.textContent = "복사했습니다"; });
      });
    } else {
      body.innerHTML =
        '<p class="note">회원의 메일 주소는 공개하지 않습니다.</p>' +
        // 두 줄 다 상자로 두면 작은 창이 상자 두 개로 꽉 찬다. 아랫줄은 맨 글이다.
        '<p class="who-tip">이 글에 <b>댓글</b>을 남기면 글쓴이가 볼 수 있습니다.</p>';
    }
  }

  // 이름 단추는 목록·상세·댓글 어디에나 생긴다. 자리마다 걸지 않고 한 번만 건다.
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".who-btn");
    if (!b) return;
    e.preventDefault();
    openWho(b.dataset.uid, b.dataset.name || "이용자");
  });

  function needLogin(what) {
    return (
      '<div class="note" style="margin:1.5rem 0">' + what +
      ' <a href="/account?next=' + encodeURIComponent(location.pathname + location.hash) + '">로그인</a>이 필요합니다.</div>'
    );
  }

  async function viewList() {
    root.innerHTML = '<p class="note" style="margin-top:2rem">불러오는 중…</p>';
    var cat = new URLSearchParams(location.search).get("cat") || "";
    var q = window.SB.from("post")
      .select("id,category,title,created_at,user_id")
      .eq("is_deleted", false)
      .order("created_at", { ascending: false })
      .limit(50);
    if (cat) q = q.eq("category", cat);
    var { data, error } = await q;

    if (error) {
      root.innerHTML = '<div class="note block" style="margin-top:2rem">글을 불러오지 못했습니다 — ' + E(error.message) + "</div>";
      return;
    }

    var tabs = ["", "free", "question", "notice"]
      .map(function (c) {
        return '<button data-cat="' + c + '" aria-selected="' + (c === cat) + '">' +
          (c ? CATS[c] : "전체") + "</button>";
      })
      .join("");

    var names = await namesFor(data);
    var rows = (data || []).length
      ? data
          .map(function (p) {
            return (
              "<li><a href=\"#/p/" + p.id + '">' +
              '<span class="t">' +
              '<span class="badge ' + (p.category === "notice" ? "notice" : "") + '">' + CATS[p.category] + "</span>" +
              E(p.title) + "</span>" +
              "</a>" +
              // N0681
              '<div class="m">' + who(names, p.user_id) + " · " +
              window.SBUtil.when(p.created_at) + "</div></li>"
            );
          })
          .join("")
      : '<li><p class="empty">아직 글이 없습니다. 첫 글을 남겨보세요.</p></li>';

    root.innerHTML =
      '<div class="board-head"><h1 style="margin:0;font-size:1.5rem">게시판</h1>' +
      (me ? '<a class="btn" href="#/write">글쓰기</a>' : "") +
      "</div>" +
      '<div class="tabs">' + tabs + "</div>" +
      (me ? "" : needLogin("글을 쓰려면")) +
      '<ul class="post-list">' + rows + "</ul>";

    Array.prototype.forEach.call(root.querySelectorAll("[data-cat]"), function (b) {
      b.addEventListener("click", function () {
        var c = b.dataset.cat;
        history.replaceState(null, "", c ? "?cat=" + c : location.pathname);
        viewList();
      });
    });
  }

  function viewWrite() {
    if (!me) { root.innerHTML = needLogin("글을 쓰려면"); return; }
    var isAdmin = me.profile && me.profile.role === "admin";
    root.innerHTML =
      '<div class="board-head"><h1 style="margin:0;font-size:1.4rem">새 글</h1>' +
      '<a class="btn ghost" href="#/">목록</a></div>' +
      dupNotice() +
      '<div class="field"><label for="cat">분류</label><select id="cat">' +
      '<option value="free">자유</option><option value="question">질문</option>' +
      (isAdmin ? '<option value="notice">공지</option>' : "") +
      "</select></div>" +
      '<div class="field"><label for="title">제목</label><input id="title" maxlength="200" placeholder="제목을 입력하세요"></div>' +
      '<div class="field"><label for="body">내용</label><textarea id="body" placeholder="내용을 입력하세요"></textarea></div>' +
      '<p id="msg"></p><button class="btn" id="save">등록</button>';

    document.getElementById("save").addEventListener("click", async function (e) {
      var btn = e.target;
      var title = document.getElementById("title").value.trim();
      var body = document.getElementById("body").value.trim();
      var msg = document.getElementById("msg");
      if (!title || !body) { msg.innerHTML = '<span class="note block">제목과 내용을 모두 입력하세요.</span>'; return; }
      btn.disabled = true;
      var { data, error } = await window.SB.from("post")
        .insert({ user_id: me.user.id, category: document.getElementById("cat").value, title: title, body: body })
        .select("id").single();
      if (error) {
        btn.disabled = false;
        msg.innerHTML = '<span class="note block">등록하지 못했습니다 — ' + E(error.message) + "</span>";
        return;
      }
      location.hash = "#/p/" + data.id;
    });
  }

  async function viewPost(id) {
    root.innerHTML = '<p class="note" style="margin-top:2rem">불러오는 중…</p>';
    var { data: p, error } = await window.SB.from("post").select("*").eq("id", id).maybeSingle();
    if (error || !p) {
      root.innerHTML = '<div class="note block" style="margin-top:2rem">글을 찾지 못했습니다.</div>';
      return;
    }
    var admin = !!(me && me.profile && me.profile.role === "admin");
    var mine = !!(me && me.user.id === p.user_id);
    // N0682
    var canDelPost = mine || admin;
    var { data: cmts } = await window.SB.from("comment")
      .select("*").eq("post_id", id).eq("is_deleted", false).order("created_at");
    // 글쓴이와 댓글쓴이를 한 번에 조회한다
    var names = await namesFor([p].concat(cmts || []));

    root.innerHTML =
      '<div class="board-head"><a class="btn ghost" href="#/">← 목록</a>' +
      (canDelPost ? '<button class="btn ghost" id="del">삭제</button>' : "") + "</div>" +
      '<h1 style="font-size:1.45rem;margin:.5rem 0 .35rem">' +
      '<span class="badge ' + (p.category === "notice" ? "notice" : "") + '">' + CATS[p.category] + "</span>" +
      E(p.title) + "</h1>" +
      '<p class="m" style="color:var(--faint);font-size:.85rem">' +
      who(names, p.user_id) + " · " + window.SBUtil.when(p.created_at) + "</p>" +
      '<div class="post-body">' + E(p.body) + "</div>" +
      '<h2 style="font-size:1.05rem">댓글 ' + (cmts ? cmts.length : 0) + "</h2>" +
      '<div id="cmts">' +
      ((cmts || []).map(function (c) {
        var canDel = admin || (me && me.user.id === c.user_id);
        return '<div class="cmt"><div class="m">' +
          "<strong>" + who(names, c.user_id) + "</strong> · " + window.SBUtil.when(c.created_at) +
          (canDel ? ' <button class="link-del" data-c="' + c.id + '">삭제</button>' : "") +
          "</div>" + E(c.body) + "</div>";
      }).join("") || '<p class="empty">첫 댓글을 남겨보세요.</p>') +
      "</div>" +
      (me
        ? dupNotice() +
          '<div class="field" style="margin-top:1.25rem"><textarea id="cbody" style="min-height:5rem" placeholder="댓글"></textarea></div>' +
          '<button class="btn" id="csave">댓글 등록</button>'
        : needLogin("댓글을 쓰려면"));

    Array.prototype.forEach.call(root.querySelectorAll("[data-c]"), function (btn) {
      btn.addEventListener("click", async function () {
        if (!confirm("이 댓글을 삭제할까요?")) return;
        btn.disabled = true;
        var { error } = await window.SB.from("comment")
          .update({ is_deleted: true }).eq("id", btn.dataset.c);
        if (error) { btn.disabled = false; alert("삭제하지 못했습니다 — " + error.message); return; }
        viewPost(id);
      });
    });

    if (canDelPost) {
      document.getElementById("del").addEventListener("click", async function () {
        if (!confirm("이 글을 삭제할까요?")) return;
        await window.SB.from("post").update({ is_deleted: true }).eq("id", id);
        location.hash = "#/";
      });
    }
    if (me) {
      document.getElementById("csave").addEventListener("click", async function (e) {
        var body = document.getElementById("cbody").value.trim();
        if (!body) return;
        e.target.disabled = true;
        var { error } = await window.SB.from("comment")
          .insert({ post_id: id, user_id: me.user.id, body: body });
        if (error) { e.target.disabled = false; alert("등록하지 못했습니다 — " + error.message); return; }
        viewPost(id);
      });
    }
  }

  (async function () {
    if (!window.SBUtil.guard(root)) return;
    me = await window.SBUtil.me();
    /* N0683 */

    /* N0684 */
    // 승인된 회원일 때만 묻는다. 승인 전에는 글을 못 쓰므로 물을 이유가 없다.
    if (me && me.profile && me.profile.status === "approved") await checkNameDup();

    var status = me && me.profile && me.profile.status;
    if (me && status !== "approved") {
      root.innerHTML =
        '<div class="note block"><b>' +
        (status === "rejected" ? "가입이 승인되지 않았습니다."
                               : "가입 승인을 기다리고 있습니다.") +
        "</b><br>관리자 승인 후 게시판을 이용하실 수 있습니다. " +
        '<a href="/account">내 계정</a></div>';
      return;
    }

    window.addEventListener("hashchange", route);
    route();
  })();
})();
