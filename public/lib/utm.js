/* UTM 값 규칙 — 화면과 어드민이 **같은 파일**을 쓴다.
 *
 * 규칙이 두 곳에 흩어지면 반드시 갈라진다. 링크를 만들 때 쓰는 규칙과
 * 들어온 값을 받을 때 쓰는 규칙이 다르면, 만든 링크가 자기 장부와 안 맞는다.
 */
(function () {
  'use strict';

  /* 소문자 · 공백→하이픈 · 허용 문자 외 제거.
     **소문자로 내리는 것이 요점이다.** GA 도 우리 집계도 'Naver' 와
     'naver' 를 다른 채널로 센다. 광고 대행사가 대문자로 적어 보내는 일이
     흔해서, 받는 쪽에서 눕혀 두지 않으면 캠페인 하나가 두 줄로 쪼개진다. */
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

  /* 한글이 들어오면 거부한다. 주소에 넣으면 %EC%9E%90… 로 부풀어
     카카오톡·문자에서 잘리고, 잘린 링크는 아무 데도 안 간다. */
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
