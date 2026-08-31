/* Supabase 접속 설정.
   여기 있는 두 값은 브라우저에 노출되는 공개 값이다. 이것만으로는 데이터를
   마음대로 읽거나 쓸 수 없다 — 실제 권한은 데이터베이스의 RLS 정책이 정한다.
   service_role 키와 DB 비밀번호는 절대 이 파일에 넣지 않는다. */
window.SUPABASE = {
  url: "https://caykbxvnebpifcduqjre.supabase.co",
  key: "sb_publishable_S1otGjMvBab-ZtXUO_cM2Q_4VYxrdkQ",

  // 로그인 수단. 대시보드에서 켠 것만 실제로 동작한다.
  providers: ["google", "apple", "kakao"],
};
