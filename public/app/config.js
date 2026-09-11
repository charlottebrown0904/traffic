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
  // 표준지 조각(stdland-NNNNN.json, 252개 138MB)은 Vercel 에 싣지 않는다.
  // 배포마다 전체 사본이 저장돼 Hobby 저장 한도(10GB)를 넘겼다(2026-09-11:
  // 20.88GB, 배포가 멈춤). 공개 저장소의 파일을 jsDelivr 가 그대로 내어 주므로
  // 거기서 받는다. 로컬은 같은 자리에서. 실패하면 앱이 같은 자리로 되돌아간다.
  stdlandBase: location.hostname === 'localhost' || location.hostname === '127.0.0.1'
    ? '' : 'https://cdn.jsdelivr.net/gh/charlottebrown0904/traffic@main/public/app/data',
};

/* 브이월드 인증키는 **여기에 두지 않습니다.**
 *
 * 용도지역 배경(지적편집도)은 우리 서버가 대신 받아옵니다 — api/tile.js.
 * 브라우저는 /api/tile?... 을 부르고, 키는 Vercel 환경변수(VWORLD_KEY)
 * 에만 있습니다.
 *
 * 페이지에 키를 적는 길도 있지만 택하지 않았습니다. 그 키는 실거래
 * 지오코딩에 쓰는 하루 3만 건짜리 자원이고, 이 프로젝트에서 가장 자주
 * 병목이 되는 것입니다. 누가 대신 써버리면 수집이 섭니다.
 */
