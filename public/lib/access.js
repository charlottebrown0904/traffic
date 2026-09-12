/* 회원 등급 → 무엇을 볼 수 있나. 한 곳에서만 정한다 (지도·계정 화면이 같이 쓴다).
 *
 *   admin  관리자 — 모든 권한 (등급 변경 포함)
 *   A      VIP — 제한 없음
 *   B      회원 (유료) — grade_until 이 있으면 그날까지
 *   C      손님 — **로그인 없이 들어온 사람**의 자리이기도 하다. 지금은
 *          가입이 필수라 '아직 등급을 못 받은 계정' 이지만, 나중에 로그인
 *          없이 들어올 수 있게 풀면 그 사람이 여기에 해당한다.
 *          현재 가치·미래 가치는 안내만 본다.
 *
 * 이름은 2026-09-12 지시로 A→VIP · B→회원 · C→손님. 코드값(A·B·C)은
 * 데이터베이스와 같아 그대로 둔다.
 *
 * 같은 규칙이 데이터베이스에도 있다 (supabase/migrations/0003_grade.sql
 * premium_ok). 여기는 화면용 판단이지 자물쇠가 아니다. */
(function () {
  /* 등급 이름 (2026-09-12 지시). 코드값(admin·A·B·C)은 그대로 두고 이름만
     바꾼다 — 데이터베이스·정책이 코드값을 본다. */
  var LABEL = { admin: '관리자', A: 'VIP', B: '회원', C: '손님' };
  window.accessOf = function (profile) {
    var p = profile || {};
    var grade = p.grade || 'C';
    var until = p.grade_until ? new Date(p.grade_until) : null;
    /* 2026-09-12 방향 전환: **등급 장벽 없이 가입하면 전부 무료.**
       호갱노노·밸류맵도 결국 광고와 매물로 먹고 삽니다. 개인에게 월 얼마를
       받는 것보다 사람을 모으는 것이 먼저라는 판단입니다. 등급 칸(A·B·C)과
       만료일은 그대로 둡니다 — 나중에 다시 잠글 수 있어야 하고, 관리자
       화면이 그것으로 회원을 봅니다. 지금은 '승인되었는가' 만 봅니다. */
    var live = grade === 'admin' || grade === 'A'
      || (grade === 'B' && (!until || until.getTime() > Date.now()));
    var open = p.status === 'approved';
    return {
      grade: grade,
      label: LABEL[grade] || grade,
      status: p.status || '',
      approved: open,               // 승인되었는가 (이것이 지금의 유일한 문턱)
      until: until,
      expired: grade === 'B' && !live,
      admin: grade === 'admin' || p.role === 'admin',
      premium: open,                 // 승인된 회원이면 현재·미래 가치가 열린다
    };
  };
})();
