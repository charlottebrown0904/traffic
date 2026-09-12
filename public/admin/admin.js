/* Admin 전용 화면 (2026-09-12 지시).
 *
 * "산출식과 데이터베이스 기반 내용, 판단 근거, 논문 숫자, 실거래 숫자,
 *  필지 분석 정보, 감정평가서 준비 현황 및 보완 등 모든 내용을 자세히.
 *  제목 / 간략 내용 형태로 작성 후 클릭하면 완벽히 자세한 내용."
 *
 * 두 가지를 지킨다.
 *
 *   1. **관리자만.** 화면에서 한 번 보고(여기), 자료에서 또 본다 —
 *      원장 집계는 appraisal_admin_stats() 안에서 is_admin() 을 다시
 *      확인하고, 격차율 표는 비공개 버킷(premium)이 로그인 토큰을 본다.
 *      화면 코드는 자물쇠가 아니다. 이 파일도 누구나 받아 볼 수 있다.
 *   2. **숫자를 이 파일에 적지 않는다.** 적는 순간 공개다. 숫자는 전부
 *      실행할 때 가져온다 — 공개 자료는 /app/data, 비밀은 버킷·RPC.
 *      여기 적는 것은 '무엇을 어떻게 하는가' 라는 설명뿐이다.
 */
(function () {
  'use strict';

  var root = document.getElementById('root');
  var E = function (v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var N = function (v, d) {
    if (v == null || v === '' || (typeof v === 'number' && !isFinite(v))) return '<em class="adm-miss">—</em>';
    var x = Number(v);
    if (!isFinite(x)) return E(v);
    return x.toLocaleString('ko-KR', { maximumFractionDigits: d == null ? 0 : d });
  };
  var pct = function (a, b) { return (!b ? '—' : (100 * a / b).toFixed(1) + '%'); };
  var when = function (s) {
    if (!s) return '—';
    var d = new Date(s);
    return isNaN(d) ? E(s) : d.toLocaleString('ko-KR');
  };

  function table(head, rows, opt) {
    var o = opt || {};
    var th = head.map(function (h, i) {
      return '<th' + (o.num && o.num.indexOf(i) >= 0 ? ' class="num"' : '') + '>' + E(h) + '</th>';
    }).join('');
    var tb = rows.map(function (r) {
      return '<tr>' + r.map(function (c, i) {
        var num = o.num && o.num.indexOf(i) >= 0;
        return '<td' + (num ? ' class="num"' : '') + '>' + (c == null ? '<em class="adm-miss">—</em>' : c) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    return '<div class="adm-scroll"><table><thead><tr>' + th + '</tr></thead><tbody>'
      + (tb || '<tr><td colspan="' + head.length + '"><em class="adm-miss">자료 없음</em></td></tr>')
      + '</tbody></table></div>';
  }
  function kpi(items) {
    return '<div class="adm-kpi">' + items.map(function (it) {
      return '<div><b>' + it[1] + '</b><span>' + E(it[0]) + '</span></div>';
    }).join('') + '</div>';
  }
  /* 지수표는 [열쇠, 값] 짝의 목록으로 오기도 하고(순서가 뜻을 가지는 것),
     그냥 객체로 오기도 한다. 둘 다 받는다. */
  function idxTable(v, label) {
    if (!v) return '<p><em class="adm-miss">비공개 자료를 못 받았습니다.</em></p>';
    var rows = Array.isArray(v)
      ? v.map(function (pair) { return [E(pair[0]), N(pair[1], 3)]; })
      : Object.keys(v).map(function (k) { return [E(k), N(v[k], 3)]; });
    return table([label || '값', '지수'], rows, { num: [1] });
  }

  /* ── 자료 모으기 ─────────────────────────────────────────────
     공개(/app/data)와 비밀(버킷·RPC)을 나눠 부른다. 하나가 없어도
     나머지는 그린다 — 없는 칸은 '—' 로 둔다. */
  function getJSON(url) {
    return fetch(url, { cache: 'no-cache' }).then(function (r) {
      return r.ok ? r.json() : null;
    }).catch(function () { return null; });
  }
  function getPremium(name) {
    var sb = window.SB;
    if (!sb || !sb.storage) return Promise.resolve(null);
    return sb.storage.from('premium').download(name).then(function (res) {
      if (res.error || !res.data) return null;
      return res.data.text().then(JSON.parse);
    }).catch(function () { return null; });
  }
  function getStats() {
    var sb = window.SB;
    if (!sb) return Promise.resolve({ error: '로그인 연결이 없습니다' });
    return sb.rpc('appraisal_admin_stats').then(function (res) {
      if (res.error) return { error: res.error.message || '집계를 못 받았습니다' };
      return res.data || {};
    }).catch(function (e) { return { error: String(e && e.message || e) }; });
  }

  /* ── 카드 ────────────────────────────────────────────────────
     [묶음, 제목, 간략 내용, 자세히(ctx → HTML)] */
  var CARDS = [

    // ══ 1. 값을 어떻게 내는가 ══
    ['값을 어떻게 내는가', '현재 가치 산출식 — 공시지가기준법 다섯 마디',
      '감정평가에 관한 규칙 §14 의 순서 그대로. 표준지공시지가에 네 마디를 곱해 단가를 내고, 자리수 규칙으로 결정단가를 정합니다. 마디가 하나라도 비면 1.00 으로 메우지 않고 보류합니다.',
      function (c) {
        var v = c.val || {};
        return '<pre><code>토지단가 = 표준지공시지가 × 시점수정 × 지역요인 × 개별요인 × 그 밖의 요인</code></pre>'
          + '<h4>마디마다 무엇을 넣는가</h4>'
          + table(['마디', '무엇', '자료'], [
            ['표준지공시지가', '대상과 조건이 가장 가까운 비교표준지의 공시지가', '<code>std_land</code> (표준지 조각, 비공개 버킷)'],
            ['시점수정', '공시기준일 → 오늘. 지가변동률이 없으면 또래 실거래 추세로 대신', '<code>trend</code> · 상한 ' + (v.time_clamp ? E(v.time_clamp.join(' ~ ')) : '—')],
            ['지역요인', '같은 인근지역에서 표준지를 고르므로 1.000', '평가서 41건 전부 1.00 이었음'],
            ['개별요인', '도로접면 · 형상 · 지세 · 면적 · 지목군 격차율의 곱', '아래 3번 카드'],
            ['그 밖의 요인', '공시지가와 시세의 벌어진 폭. 평가선례 + 거래사례', '아래 2번 카드'],
          ])
          + '<h4>결정단가 자리수</h4>'
          + '<p>1만 원 아래는 100원, 100만 원 아래는 1,000원, 그 위는 10,000원 단위로 끊습니다. 원장에서 이 규칙과 맞은 건수가 대부분이었습니다.</p>'
          + '<h4>검산</h4>'
          + '<p><code>표준지공시지가 × 네 마디 ≈ 평가서의 산출단가</code> 가 0.5% 안에 들어오면 판독이 맞다고 봅니다. 지금 원장의 검산 결과는 10번 카드에 있습니다.</p>'
          + '<div class="adm-note">보류 규칙이 중요합니다. 비어 있는 마디를 1.00 으로 채우면 값이 <b>나오기는</b> 합니다. 그 값은 근거가 없는데도 근거가 있는 것처럼 보입니다. 그래서 화면은 "산출 보류 — 비어 있는 마디" 를 적습니다.</div>';
      }],

    ['값을 어떻게 내는가', '그 밖의 요인 — 두 갈래와 합치는 법',
      '공시지가가 시세에 얼마나 못 미치는지. 어디에도 공표되지 않는 숫자이고, 값을 가르는 가장 큰 마디입니다. 평가선례(감정평가서)와 거래사례(실거래) 두 갈래를 건수로 가중해 합칩니다.',
      function (c) {
        var v = c.val || {};
        var nOther = v.other ? Object.keys(v.other).length : 0;
        var filled = 0;
        if (v.other) Object.keys(v.other).forEach(function (k) {
          var cell = v.other[k] && v.other[k]['*'];
          if (cell && cell.median) filled += 1;
        });
        var nTrade = v.trade ? Object.keys(v.trade).length : 0;
        return kpi([
          ['평가선례 칸 (용도지역군 × 지목군)', N(nOther)],
          ['그중 전국 값이 선 칸', N(filled)],
          ['거래사례 칸 (시군구별)', N(nTrade)],
          ['원장 건수 (표에 실린)', N(v.ledger_n)],
        ])
          + '<h4>칸을 고르는 순서</h4>'
          + '<ol><li>같은 시군구 · 용도지역군 · 지목군</li>'
          + '<li>같은 시·도 · 용도지역군 · 지목군</li>'
          + '<li>전국 · 용도지역군 · 지목군</li>'
          + '<li>전국 · 용도지역군</li><li>전국 전체</li></ol>'
          + '<p>칸에 최소 표본(3건)이 없으면 다음 단계로 물러납니다. 어디까지 물러났는지는 산출표에 그대로 적습니다.</p>'
          + '<h4>지목군은 대상이 아니라 표준지 기준</h4>'
          + '<p>이 배율은 <b>비교표준지</b>에 붙는 값입니다. 그래서 칸도 표준지의 지목군으로 고릅니다. 1차 원장(52건)은 표준지 지목을 안 적어 대상 필지 것으로 갈랐고, 2차부터 <code>std_jimok</code> 을 채워 바로잡았습니다.</p>'
          + '<h4>두 갈래를 합치는 식</h4>'
          + '<pre><code>가중치 w = min(건수, 30)\n합친 값 = exp( Σ w·ln(중앙값) / Σ w )   (건수 가중 기하평균)</code></pre>'
          + '<p>한쪽만 있으면 그 값을 그대로 씁니다. 거래사례는 최근 ' + N(v.trade_years) + '년, 취소 제외, 거래면적이 필지면적의 0.5~2배인 것만 씁니다 — 지번 지오코딩이 옆 필지에 떨어진 거래를 걸러내는 장치입니다.</p>'
          + '<div class="adm-note">지역이 값을 많이 가릅니다. 같은 조건에서도 시·도를 바꾸면 전국 중앙값의 0.6~1.7배까지 벌어집니다. 그래서 지역을 먼저 보고, 표본이 얇을 때만 물러납니다.</div>';
      }],

    ['값을 어떻게 내는가', '개별요인 격차율 표 — 도로 · 형상 · 지세 · 면적',
      '감정평가서 수백 건의 개별요인 비교표에서 배운 지수입니다. 대상과 표준지의 지수를 나눠 조건별 격차율을 만들고, 그것을 모두 곱합니다.',
      function (c) {
        var v = c.val || {};
        return '<pre><code>조건 격차율 = 대상 지수 ÷ 표준지 지수      개별요인 = 조건 격차율의 곱</code></pre>'
          + '<h4>도로접면</h4>' + idxTable(v.road_index, '도로접면')
          + (v.road_corner_bonus ? '<p>각지(두 면 이상 접함) 가산 ' + N(v.road_corner_bonus, 3) + '</p>' : '')
          + '<h4>형상</h4>' + idxTable(v.shape_index, '형상')
          + '<p>임야는 형상을 보지 않습니다 — 평가서가 임야지대에서는 지세만 봅니다.</p>'
          + '<h4>지세</h4>'
          + (v.slope_index
            ? Object.keys(v.slope_index).map(function (k) {
              return '<p><b>' + E(k) + '</b></p>' + idxTable(v.slope_index[k], '지세');
            }).join('')
            : '<p><em class="adm-miss">비공개 자료를 못 받았습니다.</em></p>')
          + '<h4>면적</h4>'
          + (v.area_rules
            ? Object.keys(v.area_rules).map(function (k) {
              return '<p><b>' + E(k) + '</b></p>' + table(['대상÷표준지', '격차율', '근거'],
                (v.area_rules[k] || []).map(function (r) {
                  return [E((r[0] == null ? '' : r[0]) + ' ~ ' + (r[1] == null ? '∞' : r[1])), N(r[2], 3), E(r[3] || '')];
                }), { num: [1] });
            }).join('')
            : '<p><em class="adm-miss">비공개 자료를 못 받았습니다.</em></p>')
          + '<h4>지목군이 다를 때</h4>'
          + (v.use_mismatch
            ? table(['대상 지목군 | 표준지 지목군', '격차율', '근거'],
              Object.keys(v.use_mismatch).map(function (k) {
                var r = v.use_mismatch[k];
                return [E(k), N(r && r[0], 3), E(r && r[1] || '')];
              }), { num: [1] })
            : '<p><em class="adm-miss">비공개 자료를 못 받았습니다.</em></p>')
          + '<h4>특례 — 표가 아니라 규칙이 정하는 것</h4>'
          + (v.special
            ? table(['경우', '격차율', '근거'], Object.keys(v.special).map(function (k) {
              var r = v.special[k];
              return [E(k), N(r && r[0], 3), E(r && r[1] || '')];
            }), { num: [1] })
            : '<p><em class="adm-miss">비공개 자료를 못 받았습니다.</em></p>')
          + '<h4>반드시 같아야 하는 구역</h4>'
          + '<p>' + (v.must_match ? v.must_match.map(function (x) { return '<code>' + E(x) + '</code>'; }).join(' · ') : '—')
          + '</p><p>대상과 표준지 중 한쪽만 걸려 있으면 표준지를 다시 고릅니다. 표준지 자료에 그 구역 정보가 없으면 "확인하지 못했다" 를 참고사항에 남깁니다 — 모르는 것을 같다고 처리하지 않습니다.</p>';
      }],

    ['값을 어떻게 내는가', '표준지를 고르는 벌점',
      '대상과 조건이 가까운 표준지를 벌점이 작은 순으로 고릅니다. 용도지역이 다르면 아예 후보에서 뺍니다.',
      function (c) {
        var v = c.val || {};
        return '<h4>후보에서 빼는 것</h4>'
          + '<ul><li>용도지역군이 다른 표준지</li>'
          + '<li>반드시 같아야 하는 구역(' + (v.must_match ? E(v.must_match.join(' · ')) : '—') + ')이 한쪽만 걸린 표준지</li></ul>'
          + '<h4>벌점</h4>'
          + '<ul><li>같은 법정동리가 아니면 벌점 1.0 — 같은 동리를 강하게 선호합니다</li>'
          + '<li>거리가 멀수록 벌점 가산</li>'
          + '<li>지목군이 다르면 벌점 가산</li>'
          + '<li>도로·형상·지세가 다를수록 벌점 가산</li></ul>'
          + '<p>고른 표준지와 그 이유(조건 일치 / 지목군 다름 등)는 산출표 첫 줄에 적습니다. '
          + '후보를 셋까지 계산해 두지만 화면에는 하나만 냅니다 — 평가서는 표준지를 하나 고르고 그 근거를 적습니다.</p>'
          + '<div class="adm-note">표준지 조각(<code>stdland-시군구코드.json</code>)은 비공개 버킷에 있습니다. 시군구 하나를 열 때 그 조각만 받습니다.</div>';
      }],

    // ══ 2. 필지 진단 ══
    ['필지 진단', '레이더 여섯 축 — 무엇을 재고 무엇과 견주는가',
      '도로 · 물류 교통 · 개발 여지 · 시장 동향 · 모양·지세 · 주변 이용. 모두 비슷한 조건의 거래와 견준 백분위입니다.',
      function () {
        return table(['축', '재는 것', '또래·비교 대상'], [
          ['도로', '지적상 도로접면 (맹지 ~ 광대로)', '같은 시군구 · 용도지역군 · 지목군의 거래'],
          ['물류 교통', '10km 안 영업소의 화물(2·3·4·5종) 통행량을 거리로 나눠 더한 값', '같은 또래'],
          ['개발 여지', '용도지역의 건폐율·용적률 사다리. 농업진흥·개발제한이 겹치면 한 단 아래', '같은 시군구'],
          ['시장 동향', '이 동네·용도지역 실거래 단가의 연평균 상승률', '전국의 다른 동네·용도 (또래 안에서는 모두 같은 값이 되므로)'],
          ['모양·지세', '형상과 경사. 임야는 지세만', '같은 또래'],
          ['주변 이용', '법정동리에서 주거·상업·공업으로 쓰이는 땅의 면적 비율', '같은 시군 안 동리들'],
        ])
          + '<h4>또래 열쇠와 물러남</h4>'
          + '<p>또래는 <code>시군구 · 용도지역군 · 지목군</code> 입니다. 또래가 30건 아래면 시·도로, 그다음 전국으로 물러납니다. 어디까지 물러났는지는 화면이 말합니다.</p>'
          + '<p>지목군을 열쇠에 넣은 이유가 있습니다. 자연녹지 임야의 도로접면을 자연녹지 대지 거래와 견주면 임야는 전부 하위로 찍힙니다. 같은 땅을 잘못된 잣대로 재는 것입니다.</p>'
          + '<h4>방향이 없는 축</h4>'
          + '<p>주변 이용은 높으면 전용 압력, 낮으면 외딴 곳입니다. 좋고 나쁨의 방향이 없어 화면에도 그렇게 적습니다. 시장 동향도 "지금 비싼지" 가 아니라 "오르는 중인지" 입니다.</p>'
          + '<h4>화면에 적는 것</h4>'
          + '<p>2026-09-12 지시로 축 설명에서 <b>재는 방법</b>을 뺐습니다. 몇 km 안의 어느 차종인지, 또래를 무슨 열쇠로 묶는지는 이 화면에만 둡니다.</p>';
      }],

    ['필지 진단', '필지 특성 — 도로접면 · 형상 · 지세를 어디서 받나',
      '브이월드 토지특성 조회로 필지마다 받아 parcel 표에 넣습니다. 전국을 나눠 받는 중이고, 아직 안 받은 필지는 "조사 전" 이라고 말합니다.',
      function (c) {
        var m = c.meta || {};
        var rm = m.road_mix || {};
        var rows = Object.keys(rm).map(function (k) { return [E(k), N(rm[k])]; });
        return (rows.length ? '<h4>화면 자료에 담긴 도로접면 분포</h4>' + table(['도로접면', '건수'], rows, { num: [1] }) : '')
          + '<h4>없는 것을 없다고 말하는 규칙</h4>'
          + '<p>도로접면이 비어 있으면 <b>맹지라는 뜻이 아닙니다.</b> 아직 조사 전이라는 뜻입니다. 말풍선에 그렇게 적습니다 — 빈 값을 맹지로 읽으면 없는 감점이 생깁니다.</p>'
          + '<p>또 지적상 접면이라 현황 진입로와 다를 수 있습니다. 개별요인에서 이 차이를 보정하지 않습니다(할 수 없습니다). 대신 화면에 주의를 적습니다.</p>'
          + '<h4>필지 경계</h4>'
          + '<p>연속지적도(브이월드 WFS)를 <code>api/tile</code> 이 대신 받아 옵니다. 지번 검색은 법정동코드로 PNU 를 만들어 그 필지를 정확히 집습니다 — 주소 지오코더는 건물 없는 땅의 지번을 모르는 경우가 많습니다.</p>';
      }],

    // ══ 3. 판단 근거 ══
    ['판단 근거', '다섯 가설 판정 — 무엇을 말할 수 있고 없는지',
      '교통량과 지가의 관계를 다섯 갈래로 나눠 검정했습니다. "아직 모름" 과 "효과 없음" 은 다릅니다.',
      function (c) {
        var v = c.verdicts || {};
        var hs = v.hypotheses || [];
        return '<p class="adm-stamp">판정 자료 만든 때 <b>' + when(v.generated_at) + '</b>'
          + (v.synthetic ? ' · <span class="adm-miss">합성 자료</span>' : '') + '</p>'
          + table(['가설', '주장', '판정'], hs.map(function (h) {
            return [E(h.key), E(h.claim || h.name), '<b>' + E(h.verdict) + '</b>'];
          }))
          + hs.map(function (h) {
            var rows = (h.rows || []).map(function (r) {
              return [E(r.model || r.label || ''), N(r.n), N(r.clusters),
                (r.beta == null ? null : N(r.beta, 3)), (r.p == null ? null : N(r.p, 3)),
                (r.ci_lo == null ? null : N(r.ci_lo, 3) + ' ~ ' + N(r.ci_hi, 3))];
            });
            return '<h4>' + E(h.key) + ' · ' + E(h.name) + ' — ' + E(h.verdict) + '</h4>'
              + '<p>' + E(h.why || '') + '</p>'
              + (rows.length ? table(['모형', 'n', '군집', 'β', 'p', '95% 구간'], rows, { num: [1, 2, 3, 4, 5] }) : '');
          }).join('')
          + '<div class="adm-note">유의수준 ' + N(v.alpha, 2) + ' · 최소 관측 ' + N(v.min_obs)
          + ' · 최소 군집 ' + N(v.min_clusters) + '. 이 문턱을 못 넘으면 계수가 있어도 "아직 모름" 입니다.</div>'
          + '<div class="adm-warn">이것이 서비스의 약한 고리입니다. 교통량이 늘면 오른다는 말을 우리는 <b>아직 증명하지 못했습니다.</b> 그래서 화면에서 미래 가치를 팔지 않고, 현재 가치(공시지가기준법)를 먼저 냅니다.</div>';
      }],

    ['판단 근거', '선행연구 숫자 — 설계를 어디서 가져왔나',
      'IC 가까울수록 비싼 것이 아니라는 연구, 10km 라는 경계의 근거, 빨대효과라는 반대 경로.',
      function () {
        return '<h4>1. IC 이격거리와 가격</h4>'
          + '<p>오흥운·김태호 (2009). 「고속도로 인터체인지 이격거리와 주변 아파트 가격의 관계연구 — 서울외곽순환고속도로 영향권을 중심으로」. 대한교통학회지 27(6), 89–96.</p>'
          + '<p>IC 인접 지역은 오히려 가격이 <b>낮고</b>, 약 <b>2.0~4.0km 에서 정점</b>을 찍은 뒤 멀어질수록 급감.</p>'
          + '<p><b>우리 설계에 준 영향.</b> 0–3km 한 칸에 "너무 가까워 깎이는 구간" 과 "접근성 프리미엄 구간" 이 섞이면 서로 상쇄되어 계수가 0 으로 나옵니다. 그래서 <b>0–1 / 1–3</b> 으로 쪼갰습니다. 다만 이 연구는 아파트입니다 — 소음·매연이 주거에는 감점이지만 공장·물류에는 아닐 수 있고, 부호가 반대로 나오면 그 차이가 우리 이야기의 핵심이 됩니다.</p>'
          + '<h4>2. 10km — 공단 입지의 실제 경계</h4>'
          + '<p>국토연구원. 「고속도로 사업효과 조사 — 경부·중부 고속도로 사례연구」.</p>'
          + '<p>IC 10km 이내에 <b>국가공단의 58.6%, 지방공단의 61.6%</b> 가 입지.</p>'
          + '<p><b>영향.</b> 10km 가 임의로 고른 숫자가 아니라는 근거이고, 위약 밴드를 10–20km 로 둔 것이 타당하다는 뒷받침입니다. 그 바깥에서도 계수가 나오면 우리 모형이 IC 가 아닌 다른 것을 잡고 있다는 뜻입니다.</p>'
          + '<h4>3. 빨대효과 — 우리 가설이 틀릴 수 있는 경로</h4>'
          + '<p>김윤식 (2009). 「고속도로 개통이 지역경제에 미치는 영향 — 빨대효과를 중심으로」.</p>'
          + '<p>고속도로는 운송비를 낮춰 지역경제를 살리기도 하지만, 그 지역의 소득을 <b>인근 대도시로 흡수</b>하기도 합니다. 차가 머무는 것이 아니라 지나가는 것이라면 교통량이 늘어도 땅값은 안 오릅니다.</p>'
          + '<p><b>영향.</b> 회귀식에 수도권까지 거리와의 교호작용을 넣습니다. 이것을 확인하지 않으면 "교통량 늘면 오른다" 는 반쪽 주장입니다.</p>'
          + '<h4>4. 방법론 선례 — 이중차분(DID)</h4>'
          + '<p>「신설고속도로가 지역경제에 미치는 효과 분석」. 개통이 1인당 지방세와 제조업 사업체 수를 늘렸다는 결과. 우리 패널 고정효과와 같은 계열이고, 2003년부터의 장기 자료가 들어오면 개통 전후 비교로 넘어갑니다.</p>'
          + '<h4>5. 인구·고용 축의 선례</h4>'
          + '<p>「서해안 고속도로의 지역성장 효과분석 — 인구 및 고용 변화를 중심으로」. 분석 단위를 <b>시군구</b>로 잡은 것을 따랐습니다 — 읍면동은 경계 변경이 잦아 장기 시계열이 끊깁니다.</p>'
          + '<h4>6. 그 밖에</h4>'
          + '<p>이주왕·송호창 (2020). 「고속도로 인터체인지 개통이 아파트 가격에 미치는 영향」.</p>';
      }],

    // ══ 4. 자료 ══
    ['자료', '데이터베이스 현황 — 무엇이 얼마나 들어와 있나',
      '실거래 · 교통량 · 필지 · 표준지 · 인구 · 조례. 화면이 쓰는 숫자는 모두 이 표에서 나옵니다.',
      function (c) {
        var m = c.meta || {};
        var n = m.counts || {};
        return '<p class="adm-stamp">화면 자료 만든 때 <b>' + when(m.generated_at) + '</b>'
          + ' · 연도 범위 <b>' + N(m.year_min) + '~' + N(m.year_max) + '</b>'
          + (m.is_synthetic ? ' · <span class="adm-miss">합성 자료</span>' : '') + '</p>'
          + kpi([
            ['실거래 (전체)', N(n.trades_total)],
            ['좌표 붙은 거래', N(n.trades_mapped)],
            ['영업소', N(n.tollgates)],
            ['점수 낸 영업소', N(n.scored)],
            ['행정구역', N(n.regions)],
          ])
          + '<h4>표와 원천</h4>'
          + table(['표', '무엇', '원천'], [
            ['<code>trade</code>', '토지·공장 실거래 (연도·단가·면적·거래유형)', '국토교통부 실거래가 공개시스템'],
            ['<code>trade_parcel</code>', '거래 ↔ 필지(PNU) 연결', '지번 지오코딩'],
            ['<code>parcel</code>', '필지 특성 (지목·면적·공시지가·도로접·형상·지세)', '브이월드 토지특성'],
            ['<code>std_land</code>', '표준지공시지가', '드라이브 CSV · odcloud · 브이월드'],
            ['<code>tollgate</code> · <code>tcs</code>', '영업소 마스터와 영업소 간 통행량', '한국도로공사 TCS'],
            ['<code>region_year</code>', '시군구 인구·사업체 연도별', '통계청 KOSIS'],
            ['<code>zone_event</code>', '산업단지·택지지구 지정 사건', '전국도시개발사업정보'],
            ['<code>appraisal_case</code> · <code>appraisal_factor</code>', '감정평가서 원장 (비공개)', '감정평가서 판독'],
          ])
          + '<h4>화면으로 나가는 길</h4>'
          + '<p>DB → <code>webexport</code> → <code>public/app/data/*.json</code>(공개) 와 비공개 버킷 <code>premium</code>(격차율 표·표준지 조각). '
          + '격차율 표와 표준지는 공개 폴더에 두지 않습니다 — 주소를 알면 누구나 받을 수 있기 때문입니다.</p>';
      }],

    ['자료', '실거래 숫자 — 어떤 거래가 들어와 있나',
      '용도지역·이용상황·개발단계·도로접면별 분포. 필터가 무엇을 감추고 무엇을 보이는지도 여기서 봅니다.',
      function (c) {
        var m = c.meta || {};
        var mk = function (obj, label) {
          if (!obj) return '';
          var tot = Object.keys(obj).reduce(function (a, k) { return a + Number(obj[k] || 0); }, 0);
          return '<h4>' + E(label) + '</h4>' + table([label, '건수', '비중'],
            Object.keys(obj).sort(function (a, b) { return Number(obj[b]) - Number(obj[a]); })
              .map(function (k) { return [E(k), N(obj[k]), pct(Number(obj[k]), tot)]; }),
            { num: [1, 2] });
        };
        return kpi([
          ['거래 (전체)', N((m.counts || {}).trades_total)],
          ['지도에 한 번에 그리는 수', N((m.counts || {}).trades_plotted)],
          ['거리 밴드', m.bands ? E(m.bands.join(' / ')) + 'km' : '—'],
          ['교통량 칸', E(m.volume_col || '—')],
        ])
          + mk(m.land_use_mix, '용도지역')
          + mk(m.usage_mix, '이용상황')
          + mk(m.stage_mix, '개발단계')
          + mk(m.road_mix, '도로접면')
          + '<div class="adm-note">지도는 한 번에 ' + N((m.counts || {}).trades_plotted)
          + '건까지만 그립니다. 더 그리면 브라우저가 멈추고, 점이 서로 덮여 읽을 수도 없습니다. '
          + '그래서 화면에 보이는 것은 표본이고, 통계는 전체로 냅니다.</div>';
      }],

    ['자료', '개발 한도 — 법령 상한과 시·군 조례',
      '건폐율·용적률은 법이 상한을 정하고 조례가 그보다 낮게 정합니다. 경사도·표고·입목축적 기준은 조례에만 있습니다.',
      function (c) {
        var z = c.zoning || {};
        var law = z.law || {};
        var ord = z.ord || {};
        var sg = z.sg || {};
        var lawRows = Object.keys(law).map(function (k) {
          var r = law[k] || {};
          return [E(k), N(r.bcr_max) + '%', N(r.far_min) + '~' + N(r.far_max) + '%'];
        });
        return '<p class="adm-stamp">조례 자료 뽑은 날 <b>' + E(z.generated || '—') + '</b>'
          + ' · 조례 <b>' + N(Object.keys(ord).length) + '건</b>'
          + ' · 시·군 <b>' + N(Object.keys(sg).length) + '곳</b></p>'
          + '<h4>법령 상한 (국토계획법 시행령 §84·§85)</h4>'
          + table(['용도지역', '건폐율 상한', '용적률 범위'], lawRows, { num: [1, 2] })
          + '<h4>조례에만 있는 기준</h4>'
          + '<p>개발행위허가 경사도, 표고, 입목축적률은 시·군 도시계획조례가 정합니다. 같은 계획관리지역이어도 시·군마다 다릅니다. '
          + '국가법령정보센터 API 로 받아 <code>zoning-limits.json</code> 에 담고 가이드 05 에서 시·군별로 보여 줍니다.</p>'
          + '<div class="adm-warn">조례는 개정됩니다. 뽑은 날을 화면에 함께 적고, 원문 링크를 답니다. 우리가 요약한 값으로 판단하지 말고 원문을 보게 하는 것이 맞습니다.</div>';
      }],

    // ══ 5. 감정평가서 ══
    ['감정평가서', '원장 현황 — 몇 건이 들어와 있고 얼마나 믿을 만한가',
      '감정평가서를 판독해 필지 단위로 쌓은 비공개 원장입니다. 건수, 검산 통과율, 판독 종류, 지역·조건별 분포를 봅니다.',
      function (c) {
        var s = c.stats || {};
        if (s.error) return '<div class="adm-block">원장 집계를 못 받았습니다 — ' + E(s.error) + '</div>';
        var ck = s['check'] || {};
        var sgg = s.sgg_cells || {};
        var f = s.factors || {};
        return '<p class="adm-stamp">집계한 때 <b>' + when(s.generated_at) + '</b></p>'
          + kpi([
            ['원장 (필지 행)', N(s.total)],
            ['검산 통과', N(ck.pass) + ' / ' + N(ck.checkable)],
            ['격차율 행', N(f.rows)],
            ['시군구 칸 (3건 이상)', N(sgg.ready) + ' / ' + N(sgg['all'])],
          ])
          + '<h4>회차</h4>'
          + table(['회차', '건수'], (s.by_batch || []).map(function (b) {
            return [E(b.batch === 1 ? '1차 (2026-09-10)' : b.batch === 2 ? '2차 (2026-09-12)' : b.batch), N(b.n)];
          }), { num: [1] })
          + '<h4>판독 종류</h4>'
          + table(['종류', '건수'], (s.readable || []).map(function (r) {
            var name = { text: '글자층', ocr: 'OCR층', partial: '부분', image: '이미지(판독 못함)', error: '오류' };
            return [E(name[r.kind] || r.kind), N(r.n)];
          }), { num: [1] })
          + '<h4>검산</h4>'
          + '<p><code>표준지공시지가 × 시점수정 × 지역요인 × 개별요인 × 그 밖의 요인</code> 이 평가서의 산출단가와 0.5% 안에 드는지 봅니다. '
          + '통과 ' + N(ck.pass) + '건 / 검산 가능 ' + N(ck.checkable) + '건'
          + (ck.worst == null ? '' : ' · 가장 크게 벗어난 것 ' + N(100 * Number(ck.worst), 1) + '%') + '.</p>'
          + '<p>안 맞는 건은 대개 용도지역이 둘에 걸려 면적가중을 한 건입니다 — 곱셈 한 줄로는 안 맞는 것이 정상이고, 비고에 적어 둡니다.</p>'
          + '<h4>시·도별</h4>'
          + table(['시·도', '건수', '그 밖의 요인 중앙', '공시지가 대비 배율 중앙'],
            (s.by_sido || []).map(function (r) {
              return [E(r.sido), N(r.n), N(r.other, 2), N(r.ratio, 2)];
            }), { num: [1, 2, 3] })
          + '<h4>용도지역군 × 지목군</h4>'
          + table(['용도지역군', '지목군', '건수', '중앙', '1사분위', '3사분위'],
            (s.by_cell || []).map(function (r) {
              return [E(r.zg), E(r.ug), N(r.n), N(r.med, 2), N(r.q1, 2), N(r.q3, 2)];
            }), { num: [2, 3, 4, 5] })
          + '<h4>시군구 칸이 선 곳 (3건 이상)</h4>'
          + table(['시군구', '용도지역군', '지목군', '건수', '중앙'],
            (s.sgg_top || []).map(function (r) {
              return [E(r.sigungu), E(r.zg), E(r.ug), N(r.n), N(r.med, 2)];
            }), { num: [3, 4] })
          + '<h4>조건별 격차율 (개별요인 비교표)</h4>'
          + table(['조건', '행', '중앙', '1 미만', '1 초과', '1.00'],
            (f.by_group || []).map(function (r) {
              return [E(r.g), N(r.n), N(r.med, 3), N(r.lo), N(r.hi), N(r.eq1)];
            }), { num: [1, 2, 3, 4, 5] })
          + '<div class="adm-note">1차 원장은 1.00(차이 없음)을 적지 않았고 2차부터 조건마다 적습니다. '
          + '그래서 중앙값이 1.00 으로 몰립니다 — 분포를 볼 때는 1 미만·1 초과 칸을 보십시오.</div>';
      }],

    ['감정평가서', '보완 계획 — 다음에 무엇을 모아야 하나',
      '빈 칸과 얇은 칸을 메우는 순서입니다. 칸 하나에 최소 세 건, 쓸 만하려면 열 건이 목표입니다.',
      function (c) {
        var s = c.stats || {};
        if (s.error) return '<div class="adm-block">원장 집계를 못 받았습니다 — ' + E(s.error) + '</div>';
        var g = s.gaps || {};
        var sgg = s.sgg_cells || {};
        var thin = (s.by_cell || []).filter(function (r) { return r.n < 10; });
        return kpi([
          ['그 밖의 요인이 빈 건', N(g.no_other)],
          ['개별공시지가가 빈 건', N(g.no_official)],
          ['표준지 공시지가가 빈 건', N(g.no_std)],
          ['이미지라 못 읽은 건', N(g.image)],
        ])
          + '<h4>1. 남은 판독</h4>'
          + '<p>2차로 올려 주신 드라이브 폴더 164개 파일 중 109개를 읽었습니다. 남은 55개는 목록으로 저장해 두었고, 한도가 풀리는 대로 이어서 읽습니다. '
          + '이미지 PDF ' + N(g.image) + '건은 글자층이 없어 OCR 이 필요합니다.</p>'
          + '<h4>2. 빈 칸 메우기</h4>'
          + '<p>개별공시지가가 빈 건은 평가서에 그 값이 없던 경우입니다. 주소 → PNU → 우리 <code>parcel</code> 표에서 채울 수 있지만 '
          + '<b>기준시점의 공시지가</b>여야 하므로 연도가 다르면 어긋납니다. 평가서에 적힌 값이 있으면 그쪽이 낫습니다.</p>'
          + '<h4>3. 얇은 칸 (10건 미만)</h4>'
          + table(['용도지역군', '지목군', '건수', '더 필요한 건수(10건 기준)'],
            thin.map(function (r) { return [E(r.zg), E(r.ug), N(r.n), N(10 - r.n)]; }), { num: [2, 3] })
          + '<h4>4. 지역을 좁히는 일</h4>'
          + '<p>시군구 칸은 ' + N(sgg['all']) + '개 중 ' + N(sgg.ready) + '개만 최소 표본을 넘습니다('
          + N(sgg.covered) + '건이 그 칸에 듭니다). 시·도 값으로 물러나는 건이 아직 많습니다. '
          + '같은 조건에서도 시·도를 바꾸면 값이 0.6~1.7배까지 달라지므로, 시군구 칸을 채우는 것이 정확도를 가장 크게 올립니다.</p>'
          + '<h4>5. 모아야 하는 것의 우선순위</h4>'
          + '<ol><li>도시 대지(주거·상업) — 표본이 가장 얇습니다</li>'
          + '<li>공장용지·창고용지 — 우리 기준 물건인데 건수가 적습니다</li>'
          + '<li>경기·충청 밖 — 시·도 칸을 세우려면 시·도마다 3건 이상</li>'
          + '<li>같은 시군구 안의 서로 다른 용도지역 — 시군구 칸을 세우는 데 직접 쓰입니다</li></ol>'
          + '<div class="adm-note">판독 규칙에 사람 이름·연락처를 적지 않게 못 박아 두었습니다. 원장 표에는 이름 칸이 아예 없고, '
          + '원본 PDF 는 저장소에 두지 않습니다(드라이브에만).</div>';
      }],

    // ══ 6. 운영 ══
    ['운영', '화면에 공개하는 것과 감추는 것',
      '값은 보여 주고 만드는 법은 감춥니다. 어디까지 보여 주는지 한 줄로 정리했습니다.',
      function () {
        return table(['자료', '어디까지', '왜'], [
          ['결정단가 · 총액', '회원에게 공개', '이것이 서비스가 답해야 하는 질문입니다'],
          ['산출표 다섯 마디', '회원에게 공개', '근거 없는 숫자는 믿을 수 없습니다 (2026-09-12 지시로 되돌림)'],
          ['격차율 지수 표 원본', '<b>감춤</b>', '표 자체가 만드는 법입니다. 비공개 버킷에서 화면이 계산에만 씁니다'],
          ['평가선례·거래사례 칸 값', '합친 결과만', '칸별 원본은 버킷에만 있습니다'],
          ['표준지 조각', '<b>감춤</b>', '전국 표준지를 통째로 내주면 그것으로 같은 서비스를 만들 수 있습니다'],
          ['레이더 축 재는 방법', '<b>감춤</b>', '무엇을 재는지와 주의만 화면에 적습니다'],
          ['원장 원본 행', '<b>감춤</b>', 'RLS 에 정책이 없어 아무도 못 읽습니다. 집계만 관리자에게'],
          ['가설 판정 · 논문 근거', '공개', '틀릴 수 있는 경로를 숨기면 그것은 과장입니다'],
        ])
          + '<div class="adm-warn">이 화면(<code>/admin</code>)의 HTML·JS 는 누구나 받아 볼 수 있습니다. 자물쇠는 화면이 아니라 자료입니다. '
          + '그래서 이 파일에는 숫자를 적지 않고, 실행할 때 버킷·RPC 에서 가져옵니다. 새 내용을 더할 때도 같게 하십시오.</div>';
      }],

    ['운영', '등급과 자물쇠 — 무엇이 무엇을 막나',
      '화면에서 가리는 것은 편의이고, 진짜 자물쇠는 데이터베이스입니다.',
      function (c) {
        var acc = c.acc || {};
        return '<p>지금 이 화면을 보는 계정: 등급 <b>' + E(acc.label || '?') + '</b>'
          + (acc.admin ? ' · 관리자' : '') + '</p>'
          + table(['등급', '이름', '무엇을 보나'], [
            ['<code>admin</code>', '관리자', '모두 + 이 화면 + 남의 등급 변경'],
            ['<code>A</code>', 'VIP', '현재 가치·미래 가치'],
            ['<code>B</code>', '회원', '현재 가치·미래 가치 (만료일까지)'],
            ['<code>C</code>', '손님', '로그인 없이 들어온 사람의 자리. 가치는 안내만'],
          ])
          + '<h4>자물쇠 셋</h4>'
          + '<ul><li><b>RLS</b> — 승인 안 된 계정은 글·댓글도 못 읽습니다. 원장 두 표는 정책이 아예 없어 service key 로만 읽힙니다.</li>'
          + '<li><b>비공개 버킷</b> — <code>premium</code>. 로그인 토큰 + <code>premium_ok</code> 가 맞아야 내려갑니다.</li>'
          + '<li><b>SECURITY DEFINER 함수</b> — <code>appraisal_admin_stats()</code> 는 안에서 <code>is_admin()</code> 을 다시 봅니다. '
          + '집계만 나가고 원본 행은 나가지 않습니다.</li></ul>'
          + '<h4>남은 구멍</h4>'
          + '<p><code>/app/data</code> 의 공개 JSON 은 주소를 알면 누구나 받습니다(거래·영업소·인구·용도지역). '
          + '가리려면 인증을 거치는 API 뒤로 옮겨야 합니다. 지금 목적은 가입을 받는 것이라 여기까지 해 두었습니다.</p>';
      }],

    ['운영', '한도와 비용 — 어디서 먼저 막히나',
      'Vercel 함수 호출, GitHub Actions 분, Supabase 무료 한도, 브이월드 키 쿼터.',
      function () {
        return table(['자원', '한도', '지금 쓰는 곳'], [
          ['Vercel 함수 호출', '월 1,000,000 (Hobby)', '<code>api/tile</code> — 배경·용도지역·필지 경계 타일, 지번 검색'],
          ['Vercel 대역', '월 100GB', '화면 자료 JSON'],
          ['GitHub Actions', '월 2,000분', '수집·산출·내보내기 워크플로'],
          ['Actions 캐시', '10GB (브랜치별)', '복원된 DB'],
          ['Supabase', '무료 티어', '회원·게시판·원장·비공개 버킷'],
          ['브이월드 키', '일 쿼터', '지오코딩 · 연속지적도 · 배경 타일'],
        ])
          + '<h4>타일이 제일 위험합니다</h4>'
          + '<p>지도를 한 번 움직이면 타일 수십 장이 함수를 깨웁니다. 그래서 엣지 캐시를 한 달로 두고, 타일 층 옵션으로 배율 바꾸는 동안은 받지 않게 했습니다. '
          + '지도 전용 브이월드 키를 <code>config.js</code> 에 넣으면 배경 타일이 브라우저에서 브이월드로 바로 가고 함수 호출은 0 이 됩니다.</p>'
          + '<h4>캐시는 브랜치별</h4>'
          + '<p>Actions 캐시가 브랜치마다 따로여서, 복원된 DB 를 쓰는 워크플로는 <b>작업 브랜치에서</b> 돌린 뒤 main 으로 밀어야 합니다. '
          + 'main 에서 바로 돌리면 "복원된 DB 가 없습니다" 로 멈춥니다.</p>';
      }],
  ];

  /* ── 그리기 ─────────────────────────────────────────────── */
  function render(ctx) {
    var groups = [];
    CARDS.forEach(function (card) {
      if (!groups.length || groups[groups.length - 1].name !== card[0]) {
        groups.push({ name: card[0], items: [] });
      }
      groups[groups.length - 1].items.push(card);
    });
    var i = 0;
    var html = '<div class="adm-head"><h1>Admin</h1>'
      + '<p>산출식 · 데이터베이스 · 판단 근거 · 논문 숫자 · 실거래 숫자 · 필지 분석 · 감정평가서 현황을 한곳에 모았습니다. '
      + '제목을 누르면 자세한 내용이 열립니다.</p>'
      + '<p class="adm-stamp">관리자 전용 · 이 화면의 숫자는 비공개 버킷과 관리자 전용 집계에서 실시간으로 받아옵니다</p></div>';
    groups.forEach(function (g) {
      html += '<div class="adm-group">' + E(g.name) + '</div>';
      g.items.forEach(function (card) {
        i += 1;
        var body;
        try { body = card[3](ctx); } catch (e) {
          body = '<div class="adm-block">이 칸을 그리다 막혔습니다 — ' + E(e && e.message || e) + '</div>';
        }
        html += '<details class="adm-card"><summary>'
          + '<span class="adm-n">' + (i < 10 ? '0' : '') + i + '</span>'
          + '<span class="adm-t">' + E(card[1]) + '</span>'
          + '<span class="adm-more">자세히</span>'
          + '<span class="adm-s">' + E(card[2]) + '</span>'
          + '</summary><div class="adm-body">' + body + '</div></details>';
      });
    });
    root.innerHTML = html;
    if (window.tojiThemeMount) window.tojiThemeMount();
  }

  function deny(msg, cta) {
    root.innerHTML = '<div class="auth-card"><h1>Admin</h1>'
      + '<p class="lead">' + E(msg) + '</p>'
      + (cta || '') + '</div>';
  }

  (async function () {
    if (!window.SB || !window.SBUtil) {
      deny('로그인 연결이 없습니다. 잠시 뒤 새로고침해 주세요.');
      return;
    }
    var me = null;
    try { me = await window.SBUtil.me(); } catch (e) { me = null; }
    if (!me || !me.user) {
      deny('관리자만 볼 수 있는 화면입니다. 로그인해 주세요.',
        '<p><a class="btn" href="/account?next=%2Fadmin">로그인</a></p>');
      return;
    }
    var acc = (typeof window.accessOf === 'function')
      ? window.accessOf(me.profile) : { admin: false, label: '?' };
    // 머리띠의 Admin 링크는 이 힌트를 보고 나타난다 (링크를 보이는 것뿐, 자물쇠가 아니다).
    try { localStorage.setItem('toji-admin', acc.admin ? '1' : '0'); } catch (e) { /* 사생활 창 */ }
    if (!acc.admin) {
      deny('관리자만 볼 수 있는 화면입니다. 지금 등급은 ' + (acc.label || '?') + ' 입니다.',
        '<p><a href="/app">지도로 돌아가기</a></p>');
      return;
    }
    root.innerHTML = '<p class="note">자료를 모으는 중…</p>';
    var got = await Promise.all([
      getJSON('/app/data/meta.json'),
      getJSON('/app/data/verdicts.json'),
      getJSON('/app/data/zoning-limits.json'),
      getPremium('valuation.json'),
      getStats(),
    ]);
    render({ meta: got[0], verdicts: got[1], zoning: got[2], val: got[3], stats: got[4], acc: acc });
  })();
})();
