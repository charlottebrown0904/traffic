/* 배포 환경별 설정. 이 파일만 바꾸면 앱 코드는 건드리지 않아도 된다.
   Vercel 같은 정적 호스팅에는 매물 API 가 없으므로 apiBase 가 비어 있고,
   앱은 매물 탭을 '준비 중'으로 표시한다. */
window.REDT_CONFIG = {
  // 매물 API 주소. 로컬 개발은 '/api', 정적 배포는 '' (비활성),
  // 나중에 Supabase / 별도 API 서버가 생기면 그 주소를 넣는다.
  apiBase: location.hostname === 'localhost' || location.hostname === '127.0.0.1'
    ? '/api' : '',
  // 프로모션 페이지 주소. 프로모션을 없애면 null 로 바꾸면 '홈으로' 가 사라진다.
  homeUrl: '/',
};
