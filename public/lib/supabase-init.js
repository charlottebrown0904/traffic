/* Supabase 클라이언트 한 곳에서 만든다.
   페이지마다 따로 만들면 로그인 상태가 어긋나 한쪽에서만 로그인된 것처럼 보인다. */
(function () {
  var cfg = window.SUPABASE || {};
  if (!window.supabase || !cfg.url || !cfg.key) {
    window.SB = null;
    return;
  }
  window.SB = window.supabase.createClient(cfg.url, cfg.key, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
})();

/* 화면 여러 곳에서 쓰는 작은 도구들 */
window.SBUtil = {
  /* 로그인 여부와 프로필을 한 번에. 없으면 null. */
  async me() {
    if (!window.SB) return null;
    var { data } = await window.SB.auth.getUser();
    if (!data || !data.user) return null;
    var prof = await window.SB.from("profile").select("*").eq("id", data.user.id).maybeSingle();
    return { user: data.user, profile: prof.data || null };
  },

  /* 소셜 로그인. 끝나면 원래 보던 페이지로 돌아온다. */
  async signIn(provider, redirectTo) {
    if (!window.SB) throw new Error("Supabase 설정이 없습니다");
    return window.SB.auth.signInWithOAuth({
      provider: provider,
      options: { redirectTo: redirectTo || window.location.origin + "/account" },
    });
  },

  async signOut() {
    if (window.SB) await window.SB.auth.signOut();
  },

  /* 사람이 읽는 시각. 오늘이면 시:분, 아니면 날짜. */
  when(iso) {
    var d = new Date(iso);
    var now = new Date();
    var sameDay = d.toDateString() === now.toDateString();
    return sameDay
      ? d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString("ko-KR", { year: "2-digit", month: "2-digit", day: "2-digit" });
  },

  /* 사용자가 쓴 글을 그대로 화면에 넣지 않는다 — 태그가 살아나면 스크립트가 실행된다. */
  esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  },

  /* 설정이 안 됐을 때 화면에 알린다. 조용히 빈 화면을 보여주면 원인을 못 찾는다. */
  guard(el) {
    if (window.SB) return true;
    el.innerHTML =
      '<div class="note block"><b>연결 설정이 없습니다.</b><br>' +
      "Supabase 주소·키가 비어 있거나 스크립트를 불러오지 못했습니다.</div>";
    return false;
  },
};
