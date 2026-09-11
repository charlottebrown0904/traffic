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
    pending: "승인 대기",
    approved: "이용 중",
    rejected: "거절",
  };
  /* 등급 이름 (2026-09-11 지시): A→VIP · B→프리미엄 · C→일반. 코드값은
     데이터베이스(admin/A/B/C)와 같다 — 이름만 바꿨다. */
  var GRADE_OPTS = [["admin", "관리자"], ["A", "VIP"], ["B", "프리미엄 (유료)"], ["C", "일반"]];
  var GRADE_NAME = { admin: "관리자", A: "VIP", B: "프리미엄", C: "일반" };
  var GRADE_ORDER = { admin: 0, A: 1, B: 2, C: 3 };
  var STATUS_ORDER = { pending: 0, approved: 1, rejected: 2 };

  function day(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }

  /* 관리자 회원 목록 (2026-09-11 지시: "메일 취합 및 관리 편하게 — 리스트로,
     가입날짜·신청일자·등급, 필터로 소팅·정렬").

     승인 대기·등급 변경을 한 표에서 한다. **관리자에게만 보인다** — 화면은
     acc.admin 일 때만 이 함수를 부르고, 자물쇠는 데이터베이스다: profile 의
     읽기 정책이 '본인 행 또는 is_admin()' 이라 관리자가 아니면 남의 행이
     아예 안 온다 (0005_advisors.sql). 등급 변경(set_grade)·상태 변경(profile_guard)
     도 서버가 관리자인지 다시 본다.

       신청일  profile.created_at (로그인으로 가입한 순간)
       가입일  profile.approved_at (관리자가 승인한 순간 — 0006 트리거)        */
  var members = { rows: [], status: "all", grade: "all", q: "", sort: "created_desc" };

  function memberFiltered() {
    var q = members.q.trim().toLowerCase();
    var rows = members.rows.filter(function (u) {
      if (members.status !== "all" && (u.status || "pending") !== members.status) return false;
      if (members.grade !== "all" && (u.grade || "C") !== members.grade) return false;
      if (q && !((u.nickname || "") + " " + (u.email || "")).toLowerCase().includes(q)) return false;
      return true;
    });
    var s = members.sort.split("_");
    var key = s[0]; var dir = s[1] === "asc" ? 1 : -1;
    var val = function (u) {
      if (key === "name") return (u.nickname || "").toLowerCase();
      if (key === "grade") return GRADE_ORDER[u.grade || "C"];
      if (key === "status") return STATUS_ORDER[u.status || "pending"];
      if (key === "approved") return u.approved_at || "";
      return u.created_at || "";
    };
    rows.sort(function (a, b) { var x = val(a); var y = val(b); return x < y ? -dir : x > y ? dir : 0; });
    return rows;
  }

  function memberRow(u) {
    var E = window.SBUtil.esc;
    var st = u.status || "pending";
    var until = u.grade_until ? String(u.grade_until).slice(0, 10) : "";
    var acts = st === "approved" ? ""
      : (st === "pending" ? '<button class="btn sm" data-act="approved">승인</button> ' : "") +
        (st !== "rejected" ? '<button class="btn sm ghost" data-act="rejected">거절</button>' : '<button class="btn sm" data-act="approved">승인</button>');
    return '<tr data-id="' + E(u.id) + '">' +
      "<td><b>" + E(u.nickname || "(이름 없음)") + "</b>" + (u.role === "broker" ? ' <span class="badge">중개사</span>' : "") + "</td>" +
      '<td class="mono">' + E(u.email || "") + "</td>" +
      '<td><span class="st st-' + E(st) + '">' + (STATUS_LABEL[st] || E(st)) + "</span></td>" +
      '<td class="nowrap"><select data-f="grade">' + GRADE_OPTS.map(function (o) {
        return '<option value="' + o[0] + '"' + (o[0] === (u.grade || "C") ? " selected" : "") + ">" + o[1] + "</option>";
      }).join("") + "</select> " +
      '<input type="date" data-f="until" value="' + E(until) + '" title="프리미엄 만료일 (비우면 기한 없음)"> ' +
      '<button class="btn sm" data-act="save">저장</button></td>' +
      '<td class="nowrap">' + day(u.created_at) + "</td>" +
      '<td class="nowrap">' + (day(u.approved_at) || '<span class="note-in">—</span>') + "</td>" +
      '<td class="nowrap">' + acts + "</td></tr>";
  }

  function memberTable(box) {
    var rows = memberFiltered();
    var E = window.SBUtil.esc;
    var cnt = function (s) { return members.rows.filter(function (u) { return (u.status || "pending") === s; }).length; };
    var chip = function (v, label) {
      return '<button class="chip' + (members.status === v ? " on" : "") + '" data-st="' + v + '">' + label + "</button>";
    };
    var col = function (key, label) {
      var on = members.sort.indexOf(key + "_") === 0;
      var arrow = on ? (members.sort.endsWith("_asc") ? " ↑" : " ↓") : "";
      return '<th><button class="th" data-sort="' + key + '">' + label + arrow + "</button></th>";
    };
    box.innerHTML =
      '<h2 style="font-size:1rem;margin:0 0 .5rem">회원 ' + members.rows.length + "명" +
      (rows.length !== members.rows.length ? ' <span class="note-in">· 보이는 것 ' + rows.length + "명</span>" : "") + "</h2>" +
      '<div class="mtool">' +
      '<div class="chips">' + chip("all", "전체 " + members.rows.length) + chip("pending", "승인 대기 " + cnt("pending")) +
      chip("approved", "이용 중 " + cnt("approved")) + chip("rejected", "거절 " + cnt("rejected")) + "</div>" +
      '<div class="mtool-row">' +
      '<select id="m-grade" title="등급"><option value="all">등급 전체</option>' + GRADE_OPTS.map(function (o) {
        return '<option value="' + o[0] + '"' + (members.grade === o[0] ? " selected" : "") + ">" + o[1] + "</option>";
      }).join("") + "</select>" +
      '<input id="m-q" type="search" placeholder="이름·메일 검색" value="' + E(members.q) + '">' +
      '<select id="m-sort" title="정렬">' + [
        ["created_desc", "신청일 최근순"], ["created_asc", "신청일 오래된순"],
        ["approved_desc", "가입일 최근순"], ["approved_asc", "가입일 오래된순"],
        ["name_asc", "이름순"], ["grade_asc", "등급순"], ["status_asc", "상태순"],
      ].map(function (o) { return '<option value="' + o[0] + '"' + (members.sort === o[0] ? " selected" : "") + ">" + o[1] + "</option>"; }).join("") + "</select>" +
      '<button class="btn sm ghost" id="m-copy" title="보이는 회원의 메일을 쉼표로 이어 복사">메일 복사</button>' +
      '<button class="btn sm ghost" id="m-csv">CSV 내려받기</button>' +
      "</div></div>" +
      '<p class="note" style="margin:0 0 .5rem">프리미엄은 만료일을 적으면 그날까지, 비우면 기한 없음. 저장하면 기록이 남습니다.</p>' +
      '<div class="scroller"><table class="mtable"><thead><tr>' +
      col("name", "이름") + "<th>이메일</th>" + col("status", "상태") + col("grade", "등급") +
      col("created", "신청일") + col("approved", "가입일") + "<th>처리</th>" +
      "</tr></thead><tbody>" +
      (rows.length ? rows.map(memberRow).join("") : '<tr><td colspan="7" class="note-in">해당하는 회원이 없습니다.</td></tr>') +
      "</tbody></table></div>";

    var rerender = function () { memberTable(box); };
    Array.prototype.forEach.call(box.querySelectorAll("[data-st]"), function (b) {
      b.addEventListener("click", function () { members.status = b.dataset.st; rerender(); });
    });
    Array.prototype.forEach.call(box.querySelectorAll("[data-sort]"), function (b) {
      b.addEventListener("click", function () {
        var k = b.dataset.sort;
        var def = (k === "created" || k === "approved") ? "desc" : "asc";
        members.sort = members.sort === k + "_" + def ? k + "_" + (def === "asc" ? "desc" : "asc") : k + "_" + def;
        rerender();
      });
    });
    box.querySelector("#m-grade").addEventListener("change", function (e) { members.grade = e.target.value; rerender(); });
    box.querySelector("#m-sort").addEventListener("change", function (e) { members.sort = e.target.value; rerender(); });
    var qEl = box.querySelector("#m-q");
    qEl.addEventListener("input", function (e) {
      members.q = e.target.value;
      var pos = e.target.selectionStart;
      rerender();
      var q2 = box.querySelector("#m-q"); q2.focus(); try { q2.setSelectionRange(pos, pos); } catch (err) { /* */ }
    });
    box.querySelector("#m-copy").addEventListener("click", async function () {
      var text = memberFiltered().map(function (u) { return u.email; }).filter(Boolean).join(", ");
      var btn = this;
      try { await navigator.clipboard.writeText(text); btn.textContent = "복사됨"; }
      catch (err) { window.prompt("복사해 쓰세요", text); }
      setTimeout(function () { btn.textContent = "메일 복사"; }, 1500);
    });
    box.querySelector("#m-csv").addEventListener("click", function () {
      var esc = function (v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; };
      var lines = [["이름", "이메일", "상태", "등급", "만료일", "신청일", "가입일"].map(esc).join(",")]
        .concat(memberFiltered().map(function (u) {
          return [u.nickname, u.email, STATUS_LABEL[u.status] || u.status, GRADE_NAME[u.grade] || u.grade,
                  day(u.grade_until), day(u.created_at), day(u.approved_at)].map(esc).join(",");
        }));
      var blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "회원-" + day(new Date().toISOString()) + ".csv";
      document.body.appendChild(a); a.click(); a.remove();
    });

    Array.prototype.forEach.call(box.querySelectorAll("[data-act]"), function (btn) {
      btn.addEventListener("click", async function () {
        var tr = btn.closest("tr");
        var id = tr.getAttribute("data-id");
        var u = members.rows.find(function (x) { return x.id === id; });
        btn.disabled = true;
        if (btn.dataset.act === "save") {
          var grade = tr.querySelector("[data-f=grade]").value;
          var until = tr.querySelector("[data-f=until]").value;
          var r2 = await window.SB.rpc("set_grade", {
            target: id, new_grade: grade,
            until: grade === "B" && until ? until + "T23:59:59+09:00" : null, note: null,
          });
          btn.disabled = false;
          if (r2.error) { alert("바꾸지 못했습니다 — " + r2.error.message); return; }
          if (u) { u.grade = grade; u.grade_until = grade === "B" && until ? until : null; }
          btn.textContent = "저장됨";
          setTimeout(function () { btn.textContent = "저장"; }, 1500);
          return;
        }
        var r3 = await window.SB.from("profile").update({ status: btn.dataset.act }).eq("id", id)
          .select("status,approved_at").single();
        if (r3.error) { btn.disabled = false; alert("처리하지 못했습니다 — " + r3.error.message); return; }
        if (u) { u.status = r3.data.status; u.approved_at = r3.data.approved_at; }
        rerender();
      });
    });
  }

  async function renderMembers(box) {
    box.innerHTML = '<p class="note">회원 목록을 불러오는 중…</p>';
    var r = await window.SB.from("profile")
      .select("id,nickname,email,role,status,grade,grade_until,created_at,approved_at")
      .order("created_at", { ascending: false });
    if (r.error) {
      box.innerHTML = '<div class="note block">회원 목록을 못 읽었습니다 — ' +
        window.SBUtil.esc(r.error.message) + "</div>";
      return;
    }
    members.rows = r.data || [];
    // 대기자가 있으면 그 필터로 연다 — 승인이 가장 급한 일이다.
    if (members.rows.some(function (u) { return (u.status || "pending") === "pending"; })) members.status = "pending";
    memberTable(box);
  }

  function accountView(me) {
    var u = me.user;
    var p = me.profile || {};
    var name = p.nickname || u.email || "이용자";
    var role = { user: "일반 회원", broker: "중개사", admin: "관리자" }[p.role] || p.role;
    var acc = window.accessOf ? window.accessOf(p) : { label: p.grade || "C", premium: false };
    // profile 이 아직 없으면 승인 전으로 본다. 모르는 것을 통과로
    // 처리하면 안 된다 — gate.js 와 같은 판단이다.
    var status = p.status || "pending";
    var ok = status === "approved";

    root.innerHTML =
      '<div class="auth-card' + (acc.admin ? " wide" : "") + '">' +
      "<h1>" + window.SBUtil.esc(name) + "</h1>" +
      '<p class="lead">' + window.SBUtil.esc(u.email || "") + " · " + role + "</p>" +
      '<div class="note" style="margin-bottom:1.25rem">가입일 ' +
      new Date(p.approved_at || u.created_at).toLocaleDateString("ko-KR") +
      " · 상태 " + (STATUS_LABEL[status] || status) +
      " · 등급 <b>" + window.SBUtil.esc(acc.label) + "</b>" +
      (acc.until ? " (" + acc.until.toLocaleDateString("ko-KR") + "까지)" : "") +
      (acc.expired ? " · 기간 만료" : "") + "</div>" +
      (ok && !acc.premium
        ? '<div class="note block" style="margin-bottom:1rem">현재 가치·미래 가치는 프리미엄 등급 이상입니다. ' +
          "가입·결제 안내는 준비 중이며, 그때까지는 관리자가 등급을 올려 드립니다.</div>" : "") +
      (ok ? "" :
        '<div class="note block" style="margin-bottom:1rem">' +
        (status === "rejected"
          ? "가입이 승인되지 않았습니다. 문의가 필요하시면 관리자에게 연락해 주세요."
          : "관리자 승인 후 지도와 게시판을 이용하실 수 있습니다.") + "</div>") +
      '<p style="display:flex;gap:.5rem;flex-wrap:wrap">' +
      (ok ? '<a class="btn" href="/app">지도 보기</a>' +
            '<a class="btn ghost" href="/board">게시판 가기</a>' : "") +
      '<button class="btn ghost" id="out">로그아웃</button></p>' +
      '<div id="members" style="margin-top:1.5rem"></div>' +
      "</div>";

    document.getElementById("out").addEventListener("click", async function () {
      await window.SBUtil.signOut();
      location.reload();
    });

    // 관리자에게만. 자물쇠는 RLS 다 — 관리자가 아니면 목록이 아예 안 온다.
    if (acc.admin) renderMembers(document.getElementById("members"));
  }

  (async function () {
    if (!window.SBUtil.guard(root)) return;
    var me = await window.SBUtil.me();
    if (me) accountView(me);
    else loginView(null);
  })();
})();
