/* Supabase 접속 설정.
   여기 있는 두 값은 브라우저에 노출되는 공개 값이다. 이것만으로는 데이터를
   마음대로 읽거나 쓸 수 없다 — 실제 권한은 데이터베이스의 RLS 정책이 정한다.
   service_role 키와 DB 비밀번호는 절대 이 파일에 넣지 않는다. */
window.SUPABASE = {
  url: "https://caykbxvnebpifcduqjre.supabase.co",
  key: "sb_publishable_S1otGjMvBab-ZtXUO_cM2Q_4VYxrdkQ",

  // 로그인 수단. 대시보드에서 켠 것만 실제로 동작한다.
  // 애플은 유료 개발자 계정(연 $99)이 필요해 뒤로 미뤘다.
  // 아이폰 사용자도 구글·카카오로 로그인된다.
  providers: ["google", "kakao"],
};

/* 방문 통계(GA4) 측정 ID. **비어 있으면 GA 를 아예 안 붙인다**
   (public/lib/track.js).

   측정 ID(G-...)는 공개 값이다 — 브라우저가 그것으로 구글에 보내는 것이
   본래 하는 일이라 숨길 수 없고 숨길 이유도 없다. service_role 키와는
   성격이 다르다.

   구글 애널리틱스에서 속성을 만들고 받은 'G-' 로 시작하는 값을 여기
   넣으면 그 순간부터 쌓이기 시작한다. 그 전까지는 UTM(유입 경로)만
   우리 자료로 쌓인다 — 그쪽은 구글 없이도 돈다. */
window.ANALYTICS = {
  // 스트림 '토지랩' · https://toji.fyi · 스트림 ID 15788843540 (2026-09-16)
  // **초기화는 각 쪽의 <head> 인라인이 한다.** 이 값은 화면이 상태를 표시할 때
  // (어드민의 'GA 켜져 있음') 쓰는 사본이다.
  ga4: "G-RW6MCG84SF",
};
