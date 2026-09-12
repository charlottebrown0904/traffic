/* 테마 전환 — 자동 · 밝게 · 어둡게 (2026-09-12 지시).
 *
 * 예전에는 OS 설정만 따랐습니다. CSS 에 [data-theme] 자리는 있었지만
 * 그 값을 세우는 코드가 없어 죽은 코드였고, 사람이 고를 방법도 없었습니다.
 *
 * 이 파일은 <head> 에서 **defer 없이** 부릅니다. 그림이 그려지기 전에
 * <html data-theme> 를 세워야 밝은 화면이 한 번 번쩍이지 않습니다.
 * 그래서 크기를 작게 유지합니다.
 */
(function () {
  'use strict';
  var KEY = 'toji-theme';                 // auto | light | dark
  var ORDER = ['auto', 'light', 'dark'];
  var LABEL = { auto: '자동', light: '밝게', dark: '어둡게' };
  var MARK = { auto: '◐', light: '☀', dark: '☾' };

  function read() {
    try {
      var v = localStorage.getItem(KEY);
      return ORDER.indexOf(v) >= 0 ? v : 'auto';
    } catch (e) { return 'auto'; }        // 사생활 보호 창에서는 던진다
  }

  function apply(mode) {
    var root = document.documentElement;
    if (mode === 'auto') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', mode);
  }

  var mode = read();
  apply(mode);

  function paint(btn) {
    btn.innerHTML = '';
    var m = document.createElement('span');
    m.className = 'theme-switch-mark';
    m.setAttribute('aria-hidden', 'true');
    m.textContent = MARK[mode];
    var t = document.createElement('span');
    t.className = 'theme-switch-label';
    t.textContent = LABEL[mode];
    btn.appendChild(m);
    btn.appendChild(t);
    btn.setAttribute('aria-label', '화면 테마: ' + LABEL[mode] + ' (눌러서 바꾸기)');
    btn.title = '화면 테마 — 자동 · 밝게 · 어둡게';
  }

  function mount(host) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-switch';
    paint(btn);
    btn.addEventListener('click', function () {
      mode = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
      try { localStorage.setItem(KEY, mode); } catch (e) { /* 못 적어도 이번 화면은 바뀐다 */ }
      apply(mode);
      // 같은 화면에 단추가 둘 이상 있어도 글자가 어긋나지 않게 전부 다시 그린다.
      var all = document.querySelectorAll('.theme-switch');
      for (var i = 0; i < all.length; i++) paint(all[i]);
    });
    host.appendChild(btn);
  }

  function mountAll() {
    var hosts = document.querySelectorAll('[data-theme-switch]');
    for (var i = 0; i < hosts.length; i++) {
      if (!hosts[i].querySelector('.theme-switch')) mount(hosts[i]);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mountAll);
  } else {
    mountAll();
  }
  window.tojiThemeMount = mountAll;       // 나중에 그린 머리띠도 붙일 수 있게
})();
