/* 게시판 — 목록 · 글쓰기 · 상세 · 댓글.
   주소의 # 로 화면을 나눈다. 페이지를 여러 개 만들지 않아도 뒤로가기가 동작한다.
     #/            목록
     #/write       새 글
     #/p/<id>      글 하나

   누가 무엇을 할 수 있는지는 이 파일이 아니라 데이터베이스의 RLS 정책이 정한다.
   여기서 버튼을 숨기는 것은 편의일 뿐, 실제 차단은 서버에서 일어난다. */
(function () {
  var root = document.getElementById("root");
  var E = window.SBUtil.esc;
  var CATS = { free: "자유", question: "질문", notice: "공지" };
  var me = null;

  function route() {
    var h = location.hash.replace(/^#/, "");
    if (h.indexOf("/p/") === 0) return viewPost(h.slice(3));
    if (h === "/write") return viewWrite();
    return viewList();
  }

  /* 작성자 이름.
     profile 은 본인 행만 읽히므로 남의 닉네임은 profile_public 뷰에서
     가져온다. post → profile 은 외래키로 이어져 있지 않아(둘 다 auth.users
     를 가리킨다) 서버 조인이 안 된다. 그래서 id 를 모아 한 번에 조회하고
     여기서 맞춰 넣는다 — 글 50개라도 요청은 한 번이다. */
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

  /* 작성자 이름은 **누를 수 있는 것**이다 (지시 2026-09-17: "글 작성자/댓글
     작성자 프로필 클릭 시 메일 보내기 팝업"). 링크가 아니라 단추다 —
     갈 곳이 있는 것이 아니라 그 자리에서 열리는 것이므로. */
  function who(map, uid) {
    if (!uid) return E(whoName(map, uid));
    return '<button type="button" class="who-btn" data-uid="' + E(uid) +
           '" data-name="' + E(whoName(map, uid)) + '">' + E(whoName(map, uid)) + "</button>";
  }

  /* 프로필 쪽지창.

     **메일 주소는 아무에게나 보여주지 않는다.** profile 의 RLS 가 본인 행과
     관리자에게만 열려 있고(0001·0003), 게시판이 이름을 읽는 profile_public
     뷰에는 id 와 nickname 두 칸뿐이다 — 그 뷰에 칸을 늘리는 순간 그 뷰가
     안전한 근거가 깨진다(0002 의 경고).

     그래서 이 창은 **보는 사람에 따라 다른 것을 말한다.** 관리자에게는
     메일 주소와 '메일 보내기' 를, 그 밖에는 왜 주소가 없는지와 댓글로
     답하는 길을 적는다. 화면이 숨기는 것이 아니라 자료가 안 오는 것이라,
     개발자 도구를 열어도 나오지 않는다. */
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
              // 이름 단추는 **링크 밖**에 둔다. <a> 안에 <button> 을 넣으면
              // 문법도 틀리고, 눌렀을 때 글로 넘어가 버려 창이 안 열린다.
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
    // 관리자는 남의 글도 내릴 수 있어야 신고를 처리할 수 있다. RLS 는 이미
    // 허용하고 있었는데 버튼만 없어서 못 하던 상태였다.
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
        ? '<div class="field" style="margin-top:1.25rem"><textarea id="cbody" style="min-height:5rem" placeholder="댓글"></textarea></div>' +
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
    /* 머리띠 끝 칸은 **'내 계정'** 그대로 둔다 (지시 2026-09-17:
       "게시판 화면에서 우측 '토지랩'은 '내 계정'으로 수정").

       예전에는 여기에 내 표시 이름을 넣었다. 그러면 같은 자리가 화면마다
       다른 말을 하고 — 지도·가이드에서는 '내 계정', 게시판에서만 이름 —
       게다가 그 이름이 서비스 이름과 같으면(토지랩) 머리띠 왼쪽 상표와
       겹쳐 보여 무엇을 누르는 칸인지 알 수 없게 된다. */

    /* 승인 전이면 목록이 **빈 채로** 뜬다. RLS 가 글을 안 내주기 때문에
       오류도 안 난다. 빈 게시판은 '글이 없구나' 로 읽히므로, 왜 비었는지를
       말해준다. 막는 것은 여기가 아니라 데이터베이스다. */
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
