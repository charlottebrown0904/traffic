# 브랜드 — 토지 고고

## 이름

**토지 고고**. 도메인은 `toji.fyi`. 화면·문서·manifest 가 모두 이 이름입니다.
옛 이름(`사도 토지` · `사도될까`)은 폐기했습니다 — 새 문구에 다시 쓰지 마세요.

## 색

부드러운 파스텔톤 브라운 계열입니다. 파스텔은 배경에, 진한 갈색은 글자·버튼에 씁니다.
파스텔 톤 위에 흰 글씨를 얹으면 명도 대비가 모자라 읽히지 않기 때문입니다.

| 쓰임 | 값 | 비고 |
|---|---|---|
| accent (글자·버튼·링크) | `#8A6547` | 흰 배경 대비 5.2:1 — WCAG AA 통과 |
| accent-soft (배경) | `#F4E9DD` | |
| 다크모드 accent | `#D8B18C` | 어두운 배경 대비 8.7:1 |
| 다크모드 accent-soft | `#2A2019` | |
| theme-color (브라우저 주소창·PWA) | `#FAF7F3` / 어두울 때 `#12100D` | 머리띠 색과 같게 (2026-09-12) |
| brand-warm (점·띠 장식) | `#C9A47C` | 예전 theme-color |
| 히어로 그라데이션 | `#9C7454` → `#7C5A3D` | 160deg |
| 아이콘 배경 그라데이션 | `#F0E2D0` → `#CFAE8A` | |
| 아이콘 필지 | `#FFF8F0` | |
| 아이콘 도로 | `#8A6547` | |

**토큰은 `public/lib/theme.css` 한 곳에 있습니다** (2026-09-12). 랜딩·가이드·
게시판·계정·지도앱이 전부 이 파일을 부릅니다. 어두운 값은 `--d-*` 로 한 번만
적고, 미디어쿼리와 `[data-theme="dark"]` 는 그것을 옮겨 담기만 합니다 — 그래서
한쪽만 고쳐 어긋날 일이 없습니다.

지도앱의 **자료색**(용도지역·거래 종류·교통량 구간·거리 밴드)만
`public/app/style.css` 에 남습니다. 그 색들은 서로 구별되는 것이 임무라
브랜드와 같이 움직이면 안 됩니다.

## 마크

위에서 내려다본 **필지**(밝은 마름모, 분할선 있음)를 **도로**가 가로질러
오른쪽 위로 뻗어 나갑니다. 도로가 곧 화살표입니다 — 교통량이 곧 미래가치라는
이 서비스의 가설을 그대로 그린 것입니다.

## 파일

| 파일 | 용도 |
|---|---|
| `public/icon.svg` | 마스터. 모서리 둥근 512 정사각 |
| `public/favicon.svg` | 16px 용 단순화판 (분할선 제거, 도로 굵게, 대비 강화) |
| `public/favicon.ico` | 16/32/48 멀티사이즈 |
| `public/apple-touch-icon.png` | 180px. iOS 가 직접 깎으므로 모서리·투명도 없음 |
| `public/brand/icon-192.png`, `icon-512.png` | PWA |
| `public/brand/icon-maskable-512.png` | 안드로이드 maskable. 내용을 76% 로 축소해 안전영역 확보 |
| `public/brand/icon-square.svg`, `icon-maskable.svg` | 위 PNG 의 원본 |
| `public/site.webmanifest` | PWA 매니페스트 |

## 다시 만들 때

이 컨테이너에는 ImageMagick 도 cairosvg 도 없습니다. SVG 는 Chromium 으로 찍고
`.ico` 는 Pillow 로 묶었습니다.

```bash
node scratchpad/render.js '[{"svg":"public/icon.svg","out":"out.png","size":512}]'
python3 -c "from PIL import Image; Image.open('out.png').convert('RGBA').save('public/favicon.ico', sizes=[(16,16),(32,32),(48,48)])"
```

SVG 를 고쳤으면 파생 PNG 를 **전부** 다시 뽑아야 합니다.
`scripts/test_web.py` 4번 검사가 파일 존재와 `<head>` 태그는 봐주지만,
PNG 안의 그림이 SVG 와 같은지까지는 보지 못합니다.
