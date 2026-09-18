#!/usr/bin/env python3
"""공개 화면의 서술형 주석을 번호로 바꾸고, 원문은 비공개로 옮긴다.

지시(2026-09-17): "서비스 페이지에서 F12 누르면 우리의 대화와 지시 판단들이
들어 있습니다 … 간단한 단어들은 그냥 두고 서술형 대화들은 주석 번호를
부여하고 별도의 비밀 공간에 페이지 추가하여 주석 번호로 매칭하여 보는
형태로 관리해 주세요."

무엇을 남기고 무엇을 옮기나
  남긴다   한 줄짜리 짧은 말. 코드 바로 옆에서 뜻을 잡아 주는 이름표다.
  옮긴다   여러 줄 · 긴 글 · 날짜와 지시 인용 · 회의 결론 · 실측 수치 —
           읽으면 우리가 무엇을 어떻게 판단했는지가 드러나는 것들.

**문자열 안의 // 나 /* 를 주석으로 읽으면 코드가 깨진다.** 그래서 정규식이
아니라 한 글자씩 훑는다 — 홑·겹따옴표, 백틱(중괄호 중첩까지), 정규식 리터럴,
그리고 그 안의 이스케이프를 모두 따라간다.

  python scripts/strip_notes.py --scan    무엇이 옮겨질지만 센다 (파일 안 고침)
  python scripts/strip_notes.py --apply   실제로 바꾸고 notes.json 을 낸다
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, 'public')

# 옮길지 남길지. 짧은 이름표는 남기고, 글은 옮긴다.
MAX_KEEP_CHARS = 90          # 이보다 길면 글로 본다
MAX_KEEP_LINES = 1           # 두 줄부터는 글로 본다
# 짧아도 이 말이 들어 있으면 옮긴다 — 지시·날짜·인용은 곧 우리 대화다.
TELL = re.compile(r'지시|요구사항|보고된|회의|사용자가|2026-\d\d|2026\.\s?\d|"[^"]{10,}"|“|”')

# 기계가 찾는 표시는 글이 아니다. 지우면 그것을 찾는 스크립트가 죽는다.
KEEP = re.compile(r'why:start|why:end|sourceMappingURL|@license|noqa')


def _scan_js(src):
    """(시작, 끝, 종류) 목록. 종류는 'line' 또는 'block'."""
    out = []
    i, n = 0, len(src)
    # 정규식 리터럴인지 나누려면 앞의 의미 있는 글자를 봐야 한다.
    prev = ''
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n:
            nxt = src[i + 1]
            if nxt == '/':
                j = src.find('\n', i)
                j = n if j < 0 else j
                # **줄 주석이 여러 줄로 이어지면 한 덩이로 본다.** 한 줄씩
                # 따로 재면 긴 글의 앞줄만 남고 뒷줄이 번호로 바뀌어, 토막난
                # 문장이 화면에 그대로 남는다 (첫 판에서 실제로 그랬다).
                # 잇는 조건은 '그 줄에 코드 없이 // 로만 시작' 이다 —
                # 코드 뒤에 붙은 꼬리 주석까지 삼키면 안 된다.
                only = src.rfind('\n', 0, i) + 1
                if not src[only:i].strip():
                    k = j
                    while k < n:
                        nl = k + 1
                        e = src.find('\n', nl)
                        e = n if e < 0 else e
                        line = src[nl:e]
                        if line.strip().startswith('//'):
                            j = e
                            k = e
                            continue
                        break
                out.append((i, j, 'line'))
                i = j
                continue
            if nxt == '*':
                j = src.find('*/', i + 2)
                j = n if j < 0 else j + 2
                out.append((i, j, 'block'))
                i = j
                continue
            # 나눗셈이냐 정규식이냐. 앞 글자가 값이면 나눗셈이다.
            if prev and (prev.isalnum() or prev in ')]_$'):
                prev = c
                i += 1
                continue
            i = _skip_regex(src, i)
            prev = '/'
            continue
        if c in '"\'':
            i = _skip_quoted(src, i, c)
            prev = c
            continue
        if c == '`':
            i = _skip_template(src, i)
            prev = '`'
            continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def _skip_quoted(src, i, q):
    i += 1
    while i < len(src):
        if src[i] == '\\':
            i += 2
            continue
        if src[i] == q or src[i] == '\n':
            return i + 1
        i += 1
    return i


def _skip_regex(src, i):
    i += 1
    in_class = False
    while i < len(src):
        c = src[i]
        if c == '\\':
            i += 2
            continue
        if c == '[':
            in_class = True
        elif c == ']':
            in_class = False
        elif c == '/' and not in_class:
            return i + 1
        elif c == '\n':
            return i          # 정규식이 아니었다 — 되돌린다
        i += 1
    return i


def _skip_template(src, i):
    i += 1
    while i < len(src):
        c = src[i]
        if c == '\\':
            i += 2
            continue
        if c == '`':
            return i + 1
        if c == '$' and i + 1 < len(src) and src[i + 1] == '{':
            depth = 1
            i += 2
            while i < len(src) and depth:
                d = src[i]
                if d in '"\'':
                    i = _skip_quoted(src, i, d)
                    continue
                if d == '`':
                    i = _skip_template(src, i)
                    continue
                if d == '{':
                    depth += 1
                elif d == '}':
                    depth -= 1
                i += 1
            continue
        i += 1
    return i


def _scan_css(src):
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append((i, j, 'block'))
            i = j
            continue
        if c in '"\'':
            i = _skip_quoted(src, i, c)
            continue
        i += 1
    return out


def _scan_html(src):
    """<!-- --> 와 **안에 박힌 <script>·<style> 속 주석까지**.

    인라인 스크립트를 빼먹으면 화면마다 GA 설명 같은 글이 그대로 남는다 —
    F12 로 보이는 것은 파일이 아니라 **내려간 쪽 전체**이기 때문이다."""
    out = []
    i = 0
    while True:
        a = src.find('<!--', i)
        if a < 0:
            break
        b = src.find('-->', a + 4)
        b = len(src) if b < 0 else b + 3
        out.append((a, b, 'html'))
        i = b
    for tag, fn in (('script', _scan_js), ('style', _scan_css)):
        open_re = re.compile(r'<' + tag + r'\b[^>]*>', re.I)
        for m in open_re.finditer(src):
            # src= 가 붙은 태그는 속이 비어 있다.
            end = src.lower().find('</' + tag + '>', m.end())
            if end < 0:
                continue
            inner = src[m.end():end]
            for a2, b2, kind in fn(inner):
                out.append((m.end() + a2, m.end() + b2, kind))
    return sorted(out)


SCAN = {'.js': _scan_js, '.css': _scan_css, '.html': _scan_html}


def text_of(raw, kind):
    if kind == 'line':
        return '\n'.join(
            ln.strip().lstrip('/').strip() for ln in raw.split('\n')).strip()
    if kind == 'block':
        return raw[2:-2].strip() if raw.endswith('*/') else raw[2:].strip()
    return raw[4:-3].strip() if raw.endswith('-->') else raw[4:].strip()


def is_prose(raw, kind):
    t = text_of(raw, kind)
    if not t or KEEP.search(t):
        return False
    lines = [x for x in t.split('\n') if x.strip()]
    if len(lines) > MAX_KEEP_LINES:
        return True
    if len(t) > MAX_KEEP_CHARS:
        return True
    return bool(TELL.search(t))


def files():
    out = []
    for base, _dirs, names in os.walk(PUBLIC):
        if os.sep + 'data' in base or os.sep + 'brand' in base:
            continue
        for nm in sorted(names):
            ext = os.path.splitext(nm)[1]
            if ext in SCAN:
                out.append(os.path.join(base, nm))
    return sorted(out)


MARK = {'line': '// N%04d', 'block': '/* N%04d */', 'html': '<!-- N%04d -->'}


NOTES_JSON = os.path.join('data', 'private', 'code_notes.json')


def used_max():
    """이미 쓰인 가장 큰 번호. **다음 번호는 여기서 이어 붙인다.**

    파일 순서로 1부터 다시 매기면, 두 번째 실행에서 새 주석이 N0001 을 받아
    이미 옮겨 둔 글과 번호가 겹친다. 그러면 화면의 번호가 엉뚱한 글을
    가리키고, 그 어긋남은 아무 데서도 안 보인다."""
    mx = 0
    for path in files():
        for m in re.finditer(r'N(\d{4})', io.open(path, encoding='utf-8').read()):
            mx = max(mx, int(m.group(1)))
    prev = os.path.join(ROOT, NOTES_JSON)
    if os.path.exists(prev):
        for x in json.load(io.open(prev, encoding='utf-8')):
            mx = max(mx, int(x['n']))
    return mx


def apply_all():
    """새로 생긴 서술형 주석만 번호로 바꾸고, 원문 목록을 낸다.

    이미 번호가 붙은 자리는 짧아서 애초에 안 걸린다 — 그래서 다시 돌려도
    안전하다."""
    notes = []
    n = used_max()
    for path in files():
        src, hits = scan_file(path)
        if not hits:
            continue
        rel = os.path.relpath(path, ROOT)
        out = []
        last = 0
        for a, b, kind, raw in hits:
            n += 1
            notes.append({
                'n': n,
                'path': rel,
                'line': src.count('\n', 0, a) + 1,
                'kind': kind,
                'body': text_of(raw, kind),
            })
            out.append(src[last:a])
            out.append(MARK[kind] % n)
            last = b
        out.append(src[last:])
        io.open(path, 'w', encoding='utf-8').write(''.join(out))
    return notes


def write_csv(notes):
    """표 편집기에서 **파일로** 올릴 CSV.

    폰에서는 45만 자를 편집기에 붙여 넣는 것이 사실상 불가능하다 — 붙이는
    동안 편집기가 멈춘다. 표 편집기의 CSV 가져오기는 **파일 고르기**라
    손가락 세 번이면 끝난다. 그래서 같은 내용을 두 꼴로 낸다.

    줄바꿈이 든 글은 따옴표로 감싸 한 칸에 담는다 (csv 표준). 표의
    updated_at 은 기본값이 있으므로 싣지 않는다."""
    import csv
    out = os.path.join(ROOT, 'data', 'private', 'code_notes.csv')
    with io.open(out, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['n', 'path', 'line', 'kind', 'body'])
        for x in notes:
            w.writerow([x['n'], x['path'], x['line'], x['kind'], x['body']])
    return out


def write_sql(notes):
    """Supabase SQL 편집기에 한 번 붙여 넣을 파일을 만든다.

    **글을 여기 화면에 찍지 않는다** — 옮기는 까닭이 그것이기 때문이다.
    파일로만 낸다. 다시 돌려도 같은 결과가 되게 upsert 로 적는다."""
    out = os.path.join(ROOT, 'data', 'private', 'code_notes.sql')
    q = lambda v: "'" + str(v).replace("'", "''") + "'"
    lines = [
        '-- 공개 화면에서 걷어낸 서술형 주석 %d개. Supabase SQL 편집기에 붙여 넣고 실행합니다.' % len(notes),
        '-- 표는 0018_code_note.sql 이 만듭니다 (관리자만 읽습니다).',
        '-- 이 파일은 저장소에 커밋하지 않습니다 (data/private 은 gitignore).',
        '',
    ]
    for x in notes:
        lines.append(
            'insert into public.code_note (n, path, line, kind, body) values '
            '(%d, %s, %s, %s, %s) on conflict (n) do update set '
            'path = excluded.path, line = excluded.line, kind = excluded.kind, '
            'body = excluded.body, updated_at = now();'
            % (x['n'], q(x['path']), x['line'], q(x['kind']), q(x['body'])))
    io.open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    return out


def scan_file(path):
    src = io.open(path, encoding='utf-8').read()
    ext = os.path.splitext(path)[1]
    hits = []
    for a, b, kind in SCAN[ext](src):
        raw = src[a:b]
        if is_prose(raw, kind):
            hits.append((a, b, kind, raw))
    return src, hits


def main(argv):
    mode = argv[1] if len(argv) > 1 else '--scan'
    if mode == '--scan':
        tot = cnt = 0
        for p in files():
            _src, hits = scan_file(p)
            if hits:
                print('%5d개  %s' % (len(hits), os.path.relpath(p, ROOT)))
                cnt += len(hits)
                tot += sum(b - a for a, b, _k, _r in hits)
        print('---\n합계 %d개 · %d자' % (cnt, tot))
        return 0
    if mode == '--csv':
        notes = json.load(io.open(os.path.join(ROOT, NOTES_JSON), encoding='utf-8'))
        print(write_csv(notes))
        return 0
    if mode == '--sql':
        notes = json.load(io.open(os.path.join(ROOT, NOTES_JSON), encoding='utf-8'))
        print(write_sql(notes))
        return 0
    if mode == '--apply':
        fresh = apply_all()
        out = os.path.join(ROOT, NOTES_JSON)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        # **덮어쓰지 않고 잇는다.** 옛 글을 날리면 옛 번호가 가리킬 곳이 없다.
        old = json.load(io.open(out, encoding='utf-8')) if os.path.exists(out) else []
        notes = old + fresh
        io.open(out, 'w', encoding='utf-8').write(
            json.dumps(notes, ensure_ascii=False, indent=1))
        print('새로 옮긴 것 %d개 · 모두 %d개 → %s'
              % (len(fresh), len(notes), os.path.relpath(out, ROOT)))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
