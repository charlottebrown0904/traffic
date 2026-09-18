/* N0743 */
(function () {
  'use strict';

  /* N0744 */
  function normValue(v) {
    return String(v == null ? '' : v)
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9._-]/g, '')
      .replace(/-{2,}/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 60);
  }

  /* N0745 */
  function hasHangul(v) {
    return /[ㄱ-ㆎ가-힣]/.test(String(v == null ? '' : v));
  }

  function buildUrl(base, p) {
    var q = [];
    var add = function (k, v) { var n = normValue(v); if (n) q.push(k + '=' + n); };
    add('utm_source', p.source);
    add('utm_medium', p.medium);
    add('utm_campaign', p.campaign);
    add('utm_content', p.content);
    add('utm_term', p.term);
    var clean = String(base || '').trim().replace(/[?#].*$/, '');
    return q.length ? clean + '?' + q.join('&') : clean;
  }

  /* 사람이 읽을 수 있는 단축 코드. ig-reel + reel02 → ig-reel02 */
  function suggestCode(channelCode, content) {
    var ch = normValue(channelCode);
    var ct = normValue(content);
    if (!ct) return ch;
    var last = ch.split('-').pop() || '';
    if (last && ct.indexOf(last) === 0 && ct.length > last.length) {
      return (ch.slice(0, ch.length - last.length) + ct).slice(0, 40);
    }
    return (ch + '-' + ct).slice(0, 40);
  }

  /* 채널 방식에 맞는 다음 소재 코드 */
  function suggestContent(channel, existing, today) {
    var d = today || new Date();
    switch (channel && channel.content_mode) {
      case 'date':
        return String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0');
      case 'serial': {
        var prefix = normValue(channel.content_prefix) || 'n';
        var re = new RegExp('^' + prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\d+)$');
        var max = 0;
        (existing || []).forEach(function (l) {
          var m = l && l.content && String(l.content).match(re);
          if (m) max = Math.max(max, Number(m[1]));
        });
        return prefix + String(max + 1).padStart(2, '0');
      }
      default:
        return '';
    }
  }

  function randomSuffix() {
    var chars = 'abcdefghjkmnpqrstuvwxyz23456789', s = '';
    for (var i = 0; i < 4; i++) s += chars[Math.floor(Math.random() * chars.length)];
    return s;
  }

  function rate(clicks, signups) {
    if (!clicks) return '—';
    return (Math.round((signups / clicks) * 1000) / 10) + '%';
  }

  window.UTM = {
    normValue: normValue, hasHangul: hasHangul, buildUrl: buildUrl,
    suggestCode: suggestCode, suggestContent: suggestContent,
    randomSuffix: randomSuffix, rate: rate,
  };
})();
