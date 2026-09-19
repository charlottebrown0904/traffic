/* 사용자에게 알려야 할 고지를 한곳에 모은다. 화면마다 따로 적지 않는다. */
(function (w) {
  'use strict';

  // N0748
  const ITEMS = [
    {
      id: 'jibun-estimate',
      where: ['map'],
      since: '2026-09-19',
      lead: '지도에 찍힌 실거래의 위치는 추정입니다.',
      body: '국토교통부 실거래가 공개시스템은 지번 뒷자리를 가려서 줍니다'
        + '(예: “계륵리 1**”). 그래서 신고된 면적·지목·용도지역을 토지대장과'
        + ' 맞춰 위치를 되찾습니다. 되찾지 못한 거래는 지도에 올리지 않습니다.'
        + ' 올라와 있는 위치도 실제 필지와 다를 수 있으니, 계약·경계·권리'
        + ' 확인은 반드시 등기부와 지적도로 하십시오.',
    },
    {
      id: 'value-now',
      where: ['value.now'],
      since: '2026-09-19',
      lead: '현재 가치는 감정평가가 아니라 예상값입니다.',
      body: '공시지가기준법의 다섯 마디를 공개 자료로 계산한 참고 지표입니다.'
        + ' 감정평가사의 평가가 아니므로 담보·소송·과세·보상 목적으로 쓸 수'
        + ' 없습니다. 실제 거래가·담보가·보상가와 다를 수 있습니다.',
      more: { href: '/guide/law', text: '산출 방법' },
    },
    {
      id: 'value-future',
      where: ['value.future'],
      since: '2026-09-19',
      lead: '미래 가치는 예측이 아니라 참고 지표입니다.',
      body: '과거 실거래·교통량·개발 사건 자료로 만든 통계이며, 앞으로의'
        + ' 가격을 약속하거나 보장하지 않습니다. 투자 판단과 그 결과는'
        + ' 이용자 본인의 것이고, 저희는 그 결과에 책임지지 않습니다.'
        + ' 감정평가·투자자문이 아닙니다.',
    },
    {
      id: 'screening',
      where: ['map', 'landing'],
      since: '2026-08-20',
      lead: '이 서비스는 스크리닝 지표입니다.',
      body: '과거 실거래 신고 자료와 교통량 통계를 요약해 보여 줍니다.'
        + ' 미래 가격을 예측하거나 보장하지 않으며, 투자 판단의 책임은'
        + ' 이용자에게 있습니다.',
    },
  ];

  function items(where) {
    if (!where) return ITEMS.slice();
    return ITEMS.filter((it) => it.where.indexOf(where) >= 0);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
  }

  function one(it, cls) {
    const link = it.more
      ? ` <a href="${esc(it.more.href)}">${esc(it.more.text)}</a>`
      : '';
    return `<p class="${cls}" id="dc-${esc(it.id)}">`
      + `<b>${esc(it.lead)}</b> ${esc(it.body)}${link}</p>`;
  }

  // 한 화면에 들어가는 고지 묶음. 없으면 빈 문자열이라 붙여도 티가 안 난다.
  function html(where, cls) {
    return items(where).map((it) => one(it, cls || 'disclaimer-note')).join('');
  }

  // /legal 의 전체 목록. 날짜까지 보인다.
  function listHtml() {
    return ITEMS.map((it) => {
      const link = it.more
        ? ` <a href="${esc(it.more.href)}">${esc(it.more.text)}</a>`
        : '';
      return `<section class="dc-item" id="dc-${esc(it.id)}">`
        + `<h3>${esc(it.lead)}</h3>`
        + `<p class="dc-since">${esc(it.since)}부터</p>`
        + `<p>${esc(it.body)}${link}</p></section>`;
    }).join('');
  }

  function mount(el, where, cls) {
    const box = (typeof el === 'string') ? document.querySelector(el) : el;
    if (!box) return;
    box.innerHTML = html(where, cls);
  }

  w.Disclaimer = { ITEMS, items, html, listHtml, mount };
}(window));
