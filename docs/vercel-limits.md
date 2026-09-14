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
2. **사용자 몫**: 지난 배포 지우기. Vercel 대시보드 → 프로젝트 →
   Deployments 에서 오래된 것을 지우면 그만큼 바로 돌아온다. 26GB 중
   대부분이 지울 수 있는 것이다. (외부 계정 조작이라 내가 안 한다.)
3. **다음**: `public/app/data` 를 Supabase 버킷으로. 배포가 1.5MB 가 된다.
4. **그 다음**: 실거래 지역 조각(배율표 3단계)도 **처음부터 버킷에** 둔다.
   저장소에 커밋하면 지금 문제를 그대로 되풀이한다.

## 넘치면 무슨 일이 생기나

Hobby 요금제에서 한도를 넘기면 새 배포가 막힌다. 지금 사이트는 살아 있고
(마지막 배포가 READY), 막히는 것은 **다음 배포**다. 그래서 2번(지난 배포
지우기)이 급하다.
