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
  function who(map, uid) {
    return E((map && map[uid]) || "이용자");
  }

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
              '<span class="m">' + who(names, p.user_id) + " · " +
              window.SBUtil.when(p.created_at) + "</span></a></li>"
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
    var nav = document.getElementById("nav-me");
    if (me && nav) nav.textContent = (me.profile && me.profile.nickname) || "내 계정";
    window.addEventListener("hashchange", route);
    route();
  })();
})();
