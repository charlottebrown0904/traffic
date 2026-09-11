/* 회원 등급 → 무엇을 볼 수 있나. 한 곳에서만 정한다 (지도·계정 화면이 같이 쓴다).
 *
 *   admin  모든 권한 (등급 변경 포함)
 *   A      제한 없음
 *   B      유료 프리미엄 — grade_until 이 있으면 그날까지
 *   C      무료 — 프리미엄(현재 가치·미래 가치)은 안내만
 *
 * 같은 규칙이 데이터베이스에도 있다 (supabase/migrations/0003_grade.sql
 * premium_ok). 여기는 화면용 판단이지 자물쇠가 아니다. */
(function () {
  var LABEL = { admin: '관리자', A: 'A · 제한 없음', B: 'B · 프리미엄', C: 'C · 무료' };
  window.accessOf = function (profile) {
    var p = profile || {};
    var grade = p.grade || 'C';
    var until = p.grade_until ? new Date(p.grade_until) : null;
    var live = grade === 'admin' || grade === 'A'
      || (grade === 'B' && (!until || until.getTime() > Date.now()));
    return {
      grade: grade,
      label: LABEL[grade] || grade,
      until: until,
      expired: grade === 'B' && !live,
      admin: grade === 'admin' || p.role === 'admin',
      premium: p.status === 'approved' && live,
    };
  };
})();
