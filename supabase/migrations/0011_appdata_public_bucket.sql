-- 화면 데이터를 배포에서 뺀다 (2026-09-14).
--
-- public/app/data 가 64MB 이고 그것이 Vercel 배포 하나의 98% 다. 배포마다
-- 그만큼이 쌓여 저장 한도를 넘겼다. 같은 파일을 여기에 두면 배포가
-- 1.5MB 가 된다.
--
-- **공개 버킷이다.** 이 자료는 이미 toji.fyi 에서 누구나 받던 것이라
-- 새로 열리는 것이 없다. 프리미엄 자료(격차율 표·표준지 조각)는 그대로
-- 비공개 버킷 'premium' 에 있고 여기 섞지 않는다.
insert into storage.buckets (id, name, public)
values ('appdata', 'appdata', true)
on conflict (id) do update set public = true;
