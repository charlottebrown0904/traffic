# Vercel 무료 한도 — 무엇이 넘쳤고 왜인가 (2026-09-14)

사용자가 사용량 화면을 올려 검토를 지시했다. 넘친 것은 **하나**고, 그
하나가 다른 둘을 같이 밀어 올리고 있다.

## 지금 자리

| 항목 | 쓴 것 | 한도 | |
|---|---|---|---|
| **Deployment Storage** | **26.76 GB** | 10 GB | **268% · 넘침** |
| Edge Requests | 797 K | 1 M | 80% |
| Fast Origin Transfer | 7.22 GB | 10 GB | 72% |
| Function Invocations | 531 K | 1 M | 53% |
| Fluid Active CPU | 1h 38m | 4h | 41% |
| Edge Request CPU | 3m 36s | 1h | 6% |
| Fast Data Transfer | 5.92 GB | 100 GB | 6% |
| Fluid Provisioned | 16.3 GB-Hrs | 360 GB-Hrs | 5% |
| Functions Storage | 11.26 MB | 10 GB | 0.1% |
| ISR Reads | 10 | 1 M | 0% |

## 먼저, 앞서 적은 것이 틀렸다 (2026-09-14 정정)

아래 '산수가 딱 맞는다' 는 **틀린 계산이다.** 26.76GB 를 toji-gogo 한
프로젝트로 나눠 '배포 422개분' 이라고 했는데, 실제로 세어 보니
**toji-gogo 의 배포는 86개**다 (약 5.6GB). 주간 정리(vercel-cleanup.yml)가
이미 돌고 있어서 그렇다.

**사용량 화면은 프로젝트가 아니라 팀 전체다.** 이 팀에는 프로젝트가 다섯
있다 — toji-gogo · rokaf-lmp · quant · first · chart. 26.76GB 는 그 다섯의
합이고, toji-gogo 는 그중 5.6GB 쯤이다.

숫자가 맞아떨어진다고 원인을 찾은 것이 아니다. 65MB × 422 가 26.76GB 와
맞은 것은 **우연**이었고, 나는 그 우연을 근거로 삼았다. 세어 보고 나서야
갈렸다.

아래 배포 크기 이야기(65MB 중 64MB 가 데이터)와 헛배포 83% 는 **그대로
맞다** — 다만 그것이 설명하는 것은 26.76GB 전부가 아니라 toji-gogo 몫이다.

## (아래는 toji-gogo 한 프로젝트 이야기다)

## 넘친 까닭 — 산수가 딱 맞는다

배포 하나의 크기를 쟀다.

    public/                     65 MB
      └ public/app/data/        64 MB   ← 98%
    public/ 에서 data 를 빼면   1.5 MB
    api/ + functions/           116 KB

그리고 **푸시마다 배포가 하나씩 남는다.** Vercel 은 지난 배포를 지우지
않으므로 65MB 가 계속 쌓인다.

    26.76 GB ÷ 65 MB ≈ 배포 422 개분

실제로 커밋은 740개이고, 배포 목록을 열어 보니 두 시간 남짓에 스무 개가
찍혀 있었다. 맞는 계산이다.

## 그런데 그 배포의 83% 는 헛것이었다

최근 백 커밋을 세어 봤다.

    public / api / vercel.json 을 건드린 것       17
    안 건드린 것 (docs/ · src/ · scripts/ 만)     83

곧 **여든세 번은 사이트가 한 글자도 안 바뀌는데 65MB 짜리 배포를 새로
남겼다.** 26.76GB 중 **22.2GB** 가 그것이다.

## 한 줄로 막는다

`vercel.json` 에 `ignoreCommand` 를 둔다.

    git diff --quiet HEAD^ HEAD -- public api vercel.json

바뀐 것이 없으면 0(건너뜀), 있으면 1(짓는다). 첫 배포처럼 `HEAD^` 가
없으면 git 이 실패해 0 이 아닌 값을 주므로 **짓는 쪽으로 넘어진다** —
안전한 쪽이 기본값이다.

이것만으로 앞으로 쌓이는 속도가 **6분의 1**이 된다.

## 그래도 남는 것 — 64MB 를 배포에 싣지 않는다

`ignoreCommand` 는 **앞으로**를 막을 뿐, 배포 하나가 65MB 인 사실은 그대로다.
데이터를 배포에서 빼면 배포가 **1.5MB** 가 된다 — 43분의 1이다.

큰 것부터:

    series.json        4.0 MB
    parcelstats.json   3.1 MB
    places.json        2.0 MB
    trades-*.json      27 MB  (스무 해)
    landprice-*.json   24 MB

이것을 **Supabase 공개 버킷**으로 옮기고 화면이 그 주소에서 받게 한다.
프리미엄 자료가 이미 그 길로 간다 (`premium` 버킷).

**이것이 세 항목을 한꺼번에 내린다.**

  · Deployment Storage — 배포마다 64MB 가 빠진다
  · Fast Origin Transfer (7.22GB) — 지금 그 파일을 Vercel 이 내보내고 있다
  · Edge Requests — 데이터 요청이 Vercel 을 안 거친다

## 순서

1. **지금**: `ignoreCommand` (넣었다). 앞으로 쌓이는 것이 6분의 1.
2. ~~사용자 몫: 지난 배포 지우기~~ → **내가 한다.** `vercel-cleanup.yml`
   이 이미 있고 토큰은 GitHub 시크릿(VERCEL_TOKEN)에만 있다. 손으로 수백
   개를 누를 일이 아니다.
   · `sizes=1` 로 프로젝트마다 배포 수를 센다 (아무것도 안 지움)
   · `dry_run=1` 로 지울 목록을 본다
   · `dry_run=0` 으로 지운다 — **지금 toji.fyi 가 가리키는 배포와 최근
     production 몇 개는 스크립트가 지키고 지운다**
3. **다음**: `public/app/data` 를 Supabase 버킷으로. 배포가 1.5MB 가 된다.
4. **그 다음**: 실거래 지역 조각(배율표 3단계)도 **처음부터 버킷에** 둔다.
   저장소에 커밋하면 지금 문제를 그대로 되풀이한다.

## 넘치면 무슨 일이 생기나

Hobby 요금제에서 한도를 넘기면 새 배포가 막힌다. 지금 사이트는 살아 있고
(마지막 배포가 READY), 막히는 것은 **다음 배포**다. 그래서 2번(지난 배포
지우기)이 급하다.


## 실제로 지웠다 (2026-09-14 13:48 UTC)

`vercel-cleanup.yml` 을 dry_run=0 · keep=3 으로 돌렸다.

    toji-gogo 배포  86개 → **3개**  (83개 지움)

스크립트가 지금 toji.fyi 가 가리키는 배포를 API 로 직접 확인해서 지키고,
최근 production 셋을 남겼다. 사이트는 그대로 살아 있다.

**그런데 가장 최근 배포가 ERROR 다.** `bd5d276` (main) 이 그것이고,
빌드 로그가 **한 줄도 없다** — 빌드가 시작조차 안 했다는 뜻이다. 그
커밋은 `public/app/app.js` 와 `vercel.json` 을 건드렸으므로 ignoreCommand
는 제대로 '짓는다' 를 골랐다. 곧 내가 넣은 그 한 줄 탓이 아니고,
**한도를 넘겨 배포가 막힌 바로 그 증상**이다.

그래서 지금 toji.fyi 가 내보내는 것은 그 앞의 READY 배포(`9940536`)다.
**배율표(z14 부터 실거래 전부)는 아직 배포에 안 올라갔다.** 자리를
비웠으니 다음에 public/ 을 건드리는 푸시가 올라가는지로 확인한다.

## 남은 의문 — 26.76GB 는 어디서 오나

팀 전체 배포가 **122개**였다 (toji-gogo 86 · chart 15 · first 8 ·
rokaf-lmp 8 · quant 5). toji-gogo 가 배포당 65MB 이고 나머지는 더 작으니
다 합쳐야 6GB 대다. **122개로는 26.76GB 가 안 된다.**

그러므로 그 수치는 지금 남아 있는 배포의 합이 아니다. 남는 설명은 둘이다.

  · Vercel 사용량 표시가 **삭제를 늦게 반영한다**
  · 그 수치가 현재 보관량이 아니라 **청구 기간 누적**이다

주간 정리가 어제(일요일) 돌았으니 그 전에 쌓였던 것이 아직 수치에 남아
있는 쪽이 그럴듯하다. **어느 쪽이든 더 지워서 내릴 수 있는 것이 아니다** —
근본은 배포 하나를 65MB 에서 1.5MB 로 줄이는 것(데이터를 버킷으로)이다.


## 옮겼다 (2026-09-14 14:11 UTC)

    올림   435개 · 65.1MB  →  Supabase 공개 버킷 appdata
    확인   열쇠 없이 공개 주소로 다시 받음
             meta.json 4KB · chart.json 415KB
             trades-2025.json 1,463KB · places.json 2,004KB

**올리기가 200 을 주는 것과 브라우저가 받는 것은 다른 말**이라 반드시
열쇠 없이 다시 받아 본다 (`web_store.verify`). 그것이 통과한 뒤에 저장소
사본을 지웠다 — 순서를 바꾸면 확인 전에 물러설 자리가 사라진다.

    배포에 실리는 것   65MB → **1.5MB**   (43분의 1)

주소: `https://caykbxvnebpifcduqjre.supabase.co/storage/v1/object/public/appdata/<이름>.json`

다시 만들려면 `redt export-web && redt web-upload`. analyze.yml 이 이제
커밋하지 않고 그 길로 올린다.

**작업 폴더에는 파일이 남는다** — git 이 안 따라갈 뿐이다. 지역에서
`make web` 으로 만든 것을 그대로 열어 볼 수 있다.


## 배포가 막힌 진짜 까닭 — **내가 vercel.json 을 깨뜨렸다** (정정)

앞에서 "가장 최근 배포가 ERROR 이고 빌드 로그가 한 줄도 없다 … 한도를
넘겨 배포가 막힌 그 증상이다" 라고 적었다. **틀렸다.** 배포 상세를 열어
보니 까닭이 또렷하게 적혀 있었다.

    The `vercel.json` schema validation failed with the following message:
    should NOT have additional property `_ignoreCommand`

`vercel.json` 에 `ignoreCommand` 를 넣으면서 **까닭을 `_ignoreCommand`
라는 배열로 같이 적어 뒀다.** JSON 에는 주석이 없으니 밑줄 붙인 열쇠를
주석 삼은 것인데, **vercel.json 은 스키마가 엄격해서 모르는 속성이 하나만
있어도 배포를 통째로 거절한다.**

그래서 700401a 이후 main 으로 간 배포가 전부 ERROR 였다. 한도와는 **아무
상관이 없었다.** 빌드 로그가 비어 있던 것도 그 때문이다 — 설정을 읽다
막혔으니 빌드가 시작조차 안 했다.

**배운 것 둘.**

1. `vercel.json` 에는 **주석을 넣을 자리가 없다.** 까닭은 문서에만 둔다.
2. '빌드 로그가 없는 ERROR' 를 보고 원인을 짐작하지 말고 **배포 상세의
   `errorMessage` 를 읽는다.** 거기 한 줄로 적혀 있었는데, 나는 그것을
   안 읽고 '한도 탓' 이라는 그럴듯한 이야기를 먼저 만들었다. 앞서 26.76GB
   산수를 우연으로 맞춘 것과 같은 잘못이다.
