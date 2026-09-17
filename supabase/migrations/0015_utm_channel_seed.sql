-- utm_channel 시드값을 마이그레이션으로 고정한다 (2026-09-17, "여기에 기타 항목 추가").
--
-- 왜 필요한가. utm_channel 의 여덟 행(네이버 검색광고 · 네이버 블로그 ·
-- 부동산 카페 글 · 네이버 밴드 · 카카오 채널·DM · 유튜브 설명란 ·
-- 메타 유료 광고 · 명함·전단 QR)은 0013_links_audit.sql 을 적용할 때
-- 함께 넣었는데, 그 insert 문 자체가 저장소 파일에는 없다 — DB 에는
-- 있고 git 에는 없는 값이었다(admin_link_stats(p_days) 때와 같은
-- 종류의 드리프트, 0014 가 그건 닫았지만 이건 놓쳤다). 이 마이그레이션이
-- 그 자리를 메운다 — 여덟 행을 그대로 옮기고 아홉째로 '기타'를 더한다.
--
-- on conflict(code) 로 이미 있는 행은 값만 맞추고 새로 만들지 않는다.
-- 다시 실행해도 안전하다.

insert into public.utm_channel
  (code, name, source, medium, content_mode, content_prefix, note, sort, active)
values
  ('naver-cpc', '네이버 검색광고', 'naver',    'cpc',   'free',   null,   '키워드는 utm_term 에 넣는다', 10, true),
  ('naver-blog','네이버 블로그',   'naver',    'blog',  'serial', 'post', '글마다 새 번호',              20, true),
  ('naver-cafe','부동산 카페 글',  'naver',    'cafe',  'serial', 'post', '카페 게시글·댓글',            30, true),
  ('band',      '네이버 밴드',     'band',     'post',  'date',   null,   '올린 날짜가 코드',            40, true),
  ('kakao',     '카카오 채널·DM',  'kakao',    'dm',    'none',   null,   '카카오톡 채널 메시지·1:1 공유', 50, true),
  ('youtube',   '유튜브 설명란',   'youtube',  'video', 'serial', 'ep',   '영상 설명란·고정 댓글',        60, true),
  ('meta-ads',  '메타 유료 광고',  'meta-ads', 'paid',  'free',   null,   '광고 소재명을 코드로',        70, true),
  ('offline',   '명함·전단 QR',    'offline',  'qr',    'free',   null,   '인쇄물마다 다른 코드',        80, true),
  -- 새로 추가하는 아홉째 — 위 여덟 갈래에 안 걸리는 채널을 담는 자리.
  -- content_mode 를 'free' 로 둬 소재란에 무엇이든 직접 적을 수 있게 한다
  -- (예: '지인 공유', '오픈채팅', '문자'). 정렬은 맨 뒤(90).
  ('etc',       '기타',            'etc',      'etc',   'free',   null,   '위 목록에 없는 채널 — 소재란에 직접 적는다', 90, true)
on conflict (code) do update set
  name           = excluded.name,
  source         = excluded.source,
  medium         = excluded.medium,
  content_mode   = excluded.content_mode,
  content_prefix = excluded.content_prefix,
  note           = excluded.note,
  sort           = excluded.sort,
  active         = excluded.active;
