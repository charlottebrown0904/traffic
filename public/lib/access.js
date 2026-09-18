/* N0718 */
(function () {
  /* N0719 */
  var LABEL = { admin: '관리자', A: 'VIP', B: '회원', C: '손님' };
  window.accessOf = function (profile) {
    var p = profile || {};
    var grade = p.grade || 'C';
    var until = p.grade_until ? new Date(p.grade_until) : null;
    /* N0720 */
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
