#!/usr/bin/env python3
"""첫 화면 '왜 교통량을 보나' 자료를 만든다.

회의 결론(2026-09-12): "그 검증 과정은 사용자에게 의미 없다. 왜 교통량을 봐야
하는지를 초보도 납득하게 첫 화면에서 설명해야 한다. 지역별 가격-교통량 추이
사례 몇 개 + 신뢰 수치를 간단히 노출."

그래서 이 스크립트는 **사례를 고르지 않는다** — 고르는 규칙만 적고, 숫자는
전부 public/app/data 의 자료에서 계산한다. 사람이 손으로 넣은 숫자는 없다.

규칙
  * 교통량 = 화물 (2·3·4·5종) 합. 화물이 공장·물류 수요를 가장 직접 반영한다
    (traffic.json vehicle_groups.freight 와 같은 정의).
  * 가격 = chart.json 의 land_use 계열 중 계획관리·생산관리·생산녹지.
    그 셋 중 관측 연도가 가장 많은 계열을 쓴다.
  * 두 계열이 겹치는 해가 MIN_YEARS 해 이상일 때만 후보.
  * 후보를 피어슨 상관으로 줄 세우고, 한 시·군에서 한 곳만 뽑아 위에서 CASES 개.
  * 두 계열을 첫 공통 연도 = 100 으로 지수화해서 내보낸다. 축이 하나여야
    하기 때문이다 (두 축 그래프는 만들지 않는다).

출력: public/app/data/why-traffic.json
"""
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'public', 'app', 'data')

FREIGHT_TYPES = [2, 3, 4, 5]          # traffic.json vehicle_groups.freight
USES = ['계획관리지역', '생산관리지역', '생산녹지지역']
MIN_YEARS = 12                         # 겹치는 해
MIN_TRAFFIC = 1500                     # 일평균 화물 대/일 — 표본이 너무 작은 영업소 제외
CASES = 3
ENDPOINT_AVG = 3                       # CAGR 을 양 끝 3년 평균으로 낸다


def load(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as fh:
        return json.load(fh)


def pearson(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / (sxx * syy) ** 0.5


def cagr(series):
    """양 끝 ENDPOINT_AVG 해 평균으로 연평균 성장률. 한 해 튐에 끌려가지 않는다."""
    k = min(ENDPOINT_AVG, len(series) // 2)
    if k < 1:
        return None
    head = statistics.fmean(series[:k])
    tail = statistics.fmean(series[-k:])
    span = (len(series) - 1) - (k - 1)
    if head <= 0 or span <= 0:
        return None
    return (tail / head) ** (1 / span) - 1


def freight_by_year(row, years):
    out = {}
    for i, year in enumerate(years):
        v = row['v'][i] if i < len(row['v']) else None
        if not v:
            continue
        tot = sum(v[t - 1] for t in FREIGHT_TYPES if t - 1 < len(v) and v[t - 1] is not None)
        if tot:
            out[year] = tot
    return out


def price_by_year(cell):
    """계획관리·생산관리·생산녹지 중 관측 연도가 가장 많은 계열."""
    best = None
    for use in USES:
        s = (cell.get('land_use') or {}).get(use)
        if not s:
            continue
        got = {int(y): v for y, v in s.items() if v}
        if best is None or len(got) > len(best[1]):
            best = (use, got)
    return best


def short_name(row):
    """시·군 토큰만 쓴다. traffic.json 의 sigungu 에는 '화성시 만세구' 처럼
    실재하지 않는 구 이름이 섞여 있어서, 첫 토큰(시·군)까지만 믿는다."""
    sg = (row.get('sigungu') or '').split()
    return sg[0] if sg else (row.get('sido') or '')


def index100(pairs):
    base = pairs[0][1]
    return [[y, round(v / base * 100, 1)] for y, v in pairs]


# ── 첫 화면에 박아 넣을 그림 ────────────────────────────────────────────────
#
# 왜 여기서 SVG 를 직접 쓰나: 첫 화면은 자바스크립트 없이도 완성돼 있어야
# 한다. 자료를 받아 그리면 느린 회선에서 빈 칸이 먼저 보이고, 그림을 못 본
# 사람은 "왜 교통량을 보나" 를 끝까지 못 읽는다. 그래서 이 스크립트가
# public/index.html 의 표시(marker) 사이를 통째로 갈아 끼운다.
#
# 그림 규칙 (dataviz):
#   * 축은 하나다. 통행량과 가격은 단위가 달라서 첫 공통 연도 = 100 으로
#     지수화해 한 축에 올린다. 축 두 개짜리 그래프는 만들지 않는다.
#   * 두 계열이면 범례는 항상 있고, 끝점에 이름을 직접 적는다 — 색만으로
#     구분하게 두지 않는다.
#   * 숫자·이름은 글자 색을 입는다. 계열 색은 점과 선만 입는다.
#   * 표도 함께 둔다 (색을 못 읽는 사람과 정확한 값을 원하는 사람 몫).

W, H = 346, 104
X0, X1 = 4, 246          # 그림 영역
Y0, Y1 = 14, 82
GUT = 252                # 끝점 이름·값을 적는 오른쪽 여백
YEAR_Y = 98
SERIES = [('traffic', 'a', '통행량'), ('price', 'b', '실거래가')]


def esc(t):
    return (t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def figure(case):
    xs = [y for y, _ in case['traffic']]
    vals = [v for _, v in case['traffic']] + [v for _, v in case['price']]
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1)
    lo, hi = lo - span * 0.08, hi + span * 0.08

    def px(y):
        return X0 + (X1 - X0) * (y - xs[0]) / max(xs[-1] - xs[0], 1)

    def py(v):
        return Y1 - (Y1 - Y0) * (v - lo) / (hi - lo)

    out = ['<svg class="why-svg" viewBox="0 0 %d %d" role="img" aria-label="%s '
           '화물 통행량과 토지 실거래가, %d년을 100 으로 맞춘 지수">'
           % (W, H, esc(case['sigungu'] + ' ' + case['name']), xs[0])]
    # 100 기준선 — 눈에 띄지 않게, 그러나 읽을 수 있게
    if lo < 100 < hi:
        out.append('<line class="why-base" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                   % (X0, py(100), X1, py(100)))
    ends = []
    for key, cls, label in SERIES:
        pts = ' '.join('%.1f,%.1f' % (px(y), py(v)) for y, v in case[key])
        out.append('<polyline class="why-line %s" points="%s"/>' % (cls, pts))
        ends.append((cls, label, case[key][-1][1]))
    # 끝점 두 개가 붙으면 글자가 겹친다 — 11px 아래로는 벌려 놓는다
    ys = [py(v) for _, _, v in ends]
    if abs(ys[0] - ys[1]) < 11:
        mid = (ys[0] + ys[1]) / 2
        ys = [mid - 5.5, mid + 5.5] if ys[0] <= ys[1] else [mid + 5.5, mid - 5.5]
    for (cls, label, v), ty, (key, _, _) in zip(ends, ys, SERIES):
        out.append('<circle class="why-dot %s" cx="%.1f" cy="%.1f" r="3.4"/>'
                   % (cls, px(xs[-1]), py(case[key][-1][1])))
        out.append('<circle class="why-tick %s" cx="%.1f" cy="%.1f" r="3.4"/>'
                   % (cls, GUT + 4, ty - 3))
        out.append('<text class="why-end" x="%.1f" y="%.1f">%s %d</text>'
                   % (GUT + 11, ty, label, round(v)))
    out.append('<text class="why-year" x="%.1f" y="%d">%d</text>' % (X0, YEAR_Y, xs[0]))
    out.append('<text class="why-year end" x="%.1f" y="%d">%d</text>' % (X1, YEAR_Y, xs[-1]))
    out.append('</svg>')

    head = ('<figure class="why-fig"><figcaption><b>%s %s</b>'
            '<span>화물 통행량 연 %+.1f%% · 실거래가 연 %+.1f%%</span></figcaption>'
            % (esc(case['sigungu']), esc(case['name']),
               case['traffic_cagr'], case['price_cagr']))
    return head + ''.join(out) + '</figure>'


def table(cases):
    rows = []
    for c in cases:
        rows.append('<tr><th scope="row">%s %s</th><td>%d → %d</td>'
                    '<td>100 → %d</td><td>100 → %d</td></tr>'
                    % (esc(c['sigungu']), esc(c['name']), c['years'][0], c['years'][1],
                       round(c['traffic'][-1][1]), round(c['price'][-1][1])))
    return ('<details class="why-table"><summary>숫자로 보기</summary>'
            '<table><thead><tr><th scope="col">자리</th><th scope="col">기간</th>'
            '<th scope="col">화물 통행량</th><th scope="col">토지 실거래가</th></tr></thead>'
            '<tbody>%s</tbody></table></details>' % ''.join(rows))


def spread(out):
    """모든 자리가 이렇지는 않다 — 그 사실을 첫 화면에 적는다.

    상위 셋만 보여 주고 넘어가면 고른 사례를 전부라고 말하는 셈이 된다.
    그리고 이 문장은 변명이 아니라 도구가 필요한 이유다. 자리마다 다르기
    때문에 자리마다 봐야 한다."""
    p = out['pool']
    return ('같은 기준(관측 %d년 이상 · 화물 일평균 %s대 이상)을 만족한 영업소 '
            '%d곳 중 %d곳은 화물차가 늘어도 실거래가가 따라오지 않았습니다. '
            '그래서 자리마다 따로 봅니다.'
            % (out['rule']['min_years'], format(out['rule']['min_traffic'], ','),
               p['n'], p['negative']))


def block(out):
    t = out['trust']
    stats = [('실거래 신고', '%s만 건' % format(round(t['trades'] / 10000), ',')),
             ('고속도로 영업소', '%s곳' % format(t['tollgates'], ',')),
             ('수집 기간', '%d~%d년' % (t['year_min'], t['year_max']))]
    kpi = ''.join('<li><b>%s</b><span>%s</span></li>' % (v, k) for k, v in stats)
    figs = ''.join(figure(c) for c in out['cases'])
    parts = [
        '<ul class="why-kpi">%s</ul>' % kpi,
        '<h3 class="why-h3">같이 움직인 자리들</h3>',
        '<ul class="why-legend"><li><i class="a"></i>화물 통행량</li>'
        '<li><i class="b"></i>토지 실거래가</li>'
        '<li><i class="base"></i>첫 해 = 100</li></ul>',
        '<div class="why-figs">%s</div>' % figs,
        table(out['cases']),
        '<p class="why-spread">%s</p>' % esc(spread(out)),
        '<p class="why-note">%s</p>' % esc(out['note']),
    ]
    return '\n    ' + '\n    '.join(parts) + '\n    '


def inject(out):
    path = os.path.join(ROOT, 'public', 'index.html')
    with open(path, encoding='utf-8') as fh:
        html = fh.read()
    a, b = '<!-- why:start -->', '<!-- why:end -->'
    if a not in html or b not in html:
        print('첫 화면에 %s / %s 표시가 없습니다.' % (a, b), file=sys.stderr)
        return False
    head, rest = html.split(a, 1)
    _, tail = rest.split(b, 1)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(head + a + block(out) + b + tail)
    return True


def main():
    traffic = load('traffic.json')
    chart = load('chart.json')
    meta = load('meta.json')
    years = traffic['years']
    rows = {r['id']: r for r in traffic['rows']}

    pool, cands = [], []
    for tid, cell in chart['rows'].items():
        row = rows.get(tid)
        if not row:
            continue
        pick = price_by_year(cell)
        if not pick:
            continue
        use, price = pick
        tr = freight_by_year(row, years)
        common = sorted(set(tr) & set(price))
        if len(common) < MIN_YEARS:
            continue
        tvals = [tr[y] for y in common]
        pvals = [price[y] for y in common]
        if statistics.fmean(tvals) < MIN_TRAFFIC:
            continue
        r = pearson(tvals, pvals)
        tg, pg = cagr(tvals), cagr(pvals)
        pool.append(r)        # 기준을 만족한 전부 — 고른 사례의 분모다
        if tg is None or pg is None or tg <= 0 or pg <= 0:
            continue          # 둘 다 늘어난 곳만 사례로 쓴다
        cands.append({
            'id': tid,
            'name': row['name'],
            'sigungu': short_name(row),
            'sido': row.get('sido') or '',
            'use': use,
            'r': round(r, 3),
            'traffic_cagr': round(tg * 100, 1),
            'price_cagr': round(pg * 100, 1),
            'years': [common[0], common[-1]],
            'traffic': index100([(y, tr[y]) for y in common]),
            'price': index100([(y, price[y]) for y in common]),
        })

    cands.sort(key=lambda c: -c['r'])
    picked, seen = [], set()
    for c in cands:
        key = (c['sido'], c['sigungu'])
        if key in seen:
            continue
        seen.add(key)
        picked.append(c)
        if len(picked) == CASES:
            break

    if len(picked) < CASES:
        print('사례가 %d 개뿐입니다 — 규칙을 확인하세요.' % len(picked), file=sys.stderr)
        return 1

    out = {
        'generated_at': meta.get('generated_at'),
        'cases': picked,
        'trust': {
            'trades': meta['counts']['trades_total'],
            'tollgates': meta['counts']['tollgates'],
            'regions': meta['counts']['regions'],
            'year_min': meta['year_min'],
            'year_max': meta['year_max'],
        },
        'series': {'traffic': '화물 통행량', 'price': '토지 실거래가'},
        # 고른 사례의 분모. 첫 화면에 이 숫자를 그대로 적는다 — 상위 셋만
        # 보여 주고 "다 이렇습니다" 라고 두면 광고가 된다. 게다가 "자리마다
        # 다르다" 는 것이 이 도구가 필요한 이유이기도 하다.
        'pool': {
            'n': len(pool),
            'rising': len(cands),
            'negative': sum(1 for r in pool if r < 0),
            'median_r': round(statistics.median(pool), 3) if pool else None,
        },
        'rule': {
            'freight_types': FREIGHT_TYPES,
            'uses': USES,
            'min_years': MIN_YEARS,
            'min_traffic': MIN_TRAFFIC,
            'endpoint_avg': ENDPOINT_AVG,
        },
        'note': '두 계열은 첫 공통 연도를 100 으로 맞춘 지수입니다. 같이 움직였다는 '
                '뜻이고, 교통량이 값을 올렸다는 증명은 아닙니다.',
    }
    path = os.path.join(DATA, 'why-traffic.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'))
        fh.write('\n')
    inject(out)
    for c in picked:
        print('%-10s %-8s r=%.3f 교통 %+.1f%%/년 가격 %+.1f%%/년 %d~%d %s'
              % (c['name'], c['sigungu'], c['r'], c['traffic_cagr'], c['price_cagr'],
                 c['years'][0], c['years'][1], c['use']))
    print('후보 %d 곳 중 %d 곳 → %s' % (len(cands), len(picked), os.path.relpath(path, ROOT)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
