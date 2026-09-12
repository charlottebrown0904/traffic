#!/usr/bin/env python3
"""캡쳐를 첫 화면에 걸 크기로 다듬는다 (scripts/build_shots.js 다음에 돈다).

하는 일은 셋뿐이다 — **자르기 · 줄이기 · 다시 저장**. 그림 안의 무엇도
고치지 않는다. 지우거나 덧그리면 그것은 화면 캡쳐가 아니다.

  * 자르기: 화면보다 긴 칸(필지 카드·산출표)의 아래쪽, 그리고 오른쪽
    패널의 꼬리말처럼 첫 화면에서 뜻이 없는 부분.
  * 줄이기: 폭 1100px (2배 화면에서도 또렷하고, 첫 화면이 무거워지지
    않는다).
  * 저장: WebP. PNG 그대로 두면 넷이 1.2MB 다 — 첫 화면에서 그 무게는
    이야기를 읽기 전에 사람을 놓친다.

왜 원본을 저장소에 안 남기나: 같은 그림이 두 벌 있으면 어느 것이 화면에
걸린 것인지 알 수 없다. 다시 필요하면 `node scripts/build_shots.js` 가
다시 찍는다.
"""
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, 'public', 'brand', 'shots')
WIDTH = 1100
QUALITY = 80

# 이름: (아래쪽을 원본 높이의 몇 %까지 남길지, 무엇을 자르는 이유)
CROP = {
    'map':    (1.00, None),
    'region': (1.00, None),
    'rank':   (1.00, None),
    'trend':  (0.82, '오른쪽 패널 꼬리말(공시지가 원천 설명)은 첫 화면에서 뜻이 없다'),
    'parcel': (1.00, None),
    # 산출표는 **일부만** 싣는다. 뒤쪽(개별요인 격차율·그 밖의 요인·결정단가)
    # 은 회원 화면의 몫이다 — 첫 화면은 '이런 표가 나온다' 까지만 보인다.
    'value':  (0.42, '뒤쪽은 회원 화면의 몫 (격차율·결정단가)'),
}


def main():
    if not os.path.isdir(SHOTS):
        print('캡쳐가 없습니다 — 먼저 node scripts/build_shots.js', file=sys.stderr)
        return 1
    made = 0
    for name in sorted(os.listdir(SHOTS)):
        if not name.endswith('.png'):
            continue
        key = name[:-4]
        keep, why = CROP.get(key, (1.00, None))
        src = os.path.join(SHOTS, name)
        im = Image.open(src).convert('RGB')
        w, h = im.size
        if keep < 1.0:
            im = im.crop((0, 0, w, int(h * keep)))
        if im.width > WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
        out = os.path.join(SHOTS, key + '.webp')
        im.save(out, 'WEBP', quality=QUALITY, method=6)
        os.remove(src)
        kb = round(os.path.getsize(out) / 1024)
        print('  %-8s %4dx%-4d %3dKB%s'
              % (key + '.webp', im.width, im.height, kb, '  — ' + why if why else ''))
        made += 1
    print('%d장 다듬었습니다.' % made)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
