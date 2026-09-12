/* 머리띠의 Admin 링크를 관리자에게만 보인다 (2026-09-12 지시).
 *
 * 이것은 **자물쇠가 아니다.** /admin 화면은 스스로 관리자인지 확인하고,
 * 그 화면의 숫자는 관리자 전용 집계(appraisal_admin_stats)와 비공개
 * 버킷에서만 온다. 여기서 하는 일은 링크를 감추는 것뿐이다 — 관리자가
 * 아닌 사람에게 쓸 수 없는 메뉴를 보여 주지 않으려는 배려다.
 *
 * 가이드처럼 로그인 연결을 아예 안 부르는 쪽에서도 링크가 서야 하므로,
 * 지도·계정·Admin 화면이 로그인 상태를 확인할 때 남겨 둔 힌트
 * (localStorage 'toji-admin')를 본다. 힌트가 조작돼도 링크만 보인다.
 */
(function () {
  'use strict';
  var KEY = 'toji-admin';

  function read() {
    try { return localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
  }

  function paint(on) {
    var links = document.querySelectorAll('[data-admin-link]');
    for (var i = 0; i < links.length; i++) links[i].hidden = !on;
  }

  /* 로그인 상태를 아는 화면이 부른다. 관리자면 힌트를 남기고, 아니면 지운다
     — 관리자 계정에서 로그아웃한 뒤에도 메뉴가 남아 있으면 안 된다. */
  window.tojiAdminNav = function (isAdmin) {
    try { localStorage.setItem(KEY, isAdmin ? '1' : '0'); } catch (e) { /* 사생활 창 */ }
    paint(!!isAdmin);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { paint(read()); });
  } else {
    paint(read());
  }
})();
