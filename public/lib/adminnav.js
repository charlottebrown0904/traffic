/* N0721 */
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

  /* N0722 */
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
