// 용도지역 지도 타일 — 네이버 지적편집도의 그 화면.
//
// 한국 **법정** 용도지역은 OSM 에 없다. 국토교통부 자료이고 브이월드에서
// 온다. 브라우저가 브이월드를 직접 부르면 인증키를 페이지에 적어야 하는데,
// 그 키는 실거래 지오코딩에 쓰는 하루 3만 건짜리 자원이고 이 프로젝트에서
// 가장 자주 병목이 된다. 누가 대신 써버리면 수집이 선다. 그래서 이 서버가
// 대신 받아온다.
//
// ── 어느 서비스로 받을지는 서버에 물어서 정했다 ──────────────────────
//
// 처음에는 WMTS 로 `LT_C_UQ111` 을 부르게 만들었다. 그 이름은 근거가 없는
// 추측이었고, 탐침(scripts/vworld_zoning.py)을 돌려보니 세 겹으로 틀렸다.
//
//   WMTS        캐패빌리티·타일 전부 404 — 브이월드 WMTS 로는 못 받는다
//   대문자      LT_C_UQ111 → text/xml 오류.  lt_c_uq111 → PNG 33KB
//               **레이어 이름은 소문자여야 한다**
//   uq111       이름이 '용도지역' 이 아니라 **'도시지역'** 이다
//
// 마지막이 가장 위험했다. 용도지역은 한 장이 아니라 국토계획법 대분류별로
// 넷이다. 우리 분석 필터(계획관리·생산관리·자연녹지)는 그중 **관리지역과
// 도시지역에 걸쳐** 있어서, uq111 만 깔면 정작 우리가 보는 땅이 안 나온다.
//
//   lt_c_uq111  도시지역          ← 자연녹지가 이 안
//   lt_c_uq112  관리지역          ← 계획관리·생산관리가 이 안
//   lt_c_uq113  농림지역
//   lt_c_uq114  자연환경보전지역
//
// 확인된 것 (2026-09-03 탐침)
//
//   LAYERS 쉼표   네 장을 한 요청에 겹쳐 준다 — 55,190B PNG.
//                 타일 한 장에 한 번만 부르면 된다.
//   EPSG:3857     `CRS` 로 보내면 온다. `SRS` 로 보내면 레이어가 달라도
//                 똑같이 1,784B — 빈 그림이다. SRS 는 WMS 1.1.1 것이고
//                 1.3.0 은 CRS 를 쓴다. 크기가 같은 것이 단서였다.
//   연속지적도    lp_pa_cbnd_bubun 로 필지 경계선을 받을 수 있다.
//
// Leaflet 의 타일 격자는 웹 머케이터다. 그래서 z/x/y 를 받아 머케이터
// bbox 로 바꿔 WMS 에 넘긴다. 주소가 z/x/y 로 고정되므로 CDN 이 반복
// 요청을 대신 받아준다 — bbox 를 그대로 받으면 주소가 매번 달라 캐시가
// 안 걸린다.

const VWORLD_WMS = "https://api.vworld.kr/req/wms";
// 토지특성(dt_d194) — 도로접·형상·지세·공시지가. WMS 가 아니라 WFS 다.
// 파이프라인은 이것을 칸 단위로 훑어 parcel 표에 담는데(collect/landchar),
// 전국이 아직 22.3% 뿐이라 **누른 그 필지 하나는 즉석에서 물어본다.**
// 미리 다 받아 둘 필요가 없다.
const VWORLD_WFS = "https://api.vworld.kr/req/wfs";
const PARCEL_TYPENAME = "dt_d194";
// 누른 점 둘레 몇 도를 볼 것인가.
//
// **0.0006도(≈60m)에 열 개만 달라고 하고 있었다.** 그것이 "정보가
// 확인 안 되는 토지가 있다" 의 원인이었다 (2026-09-10 실측,
// scripts/parcel_fields_probe.py):
//
//   광주 초월읍 지월리 14-1   그 네모 안에 이웃 20개
//   안성 공도읍 승두리 40      그 네모 안에 이웃 30개(상한에 걸림)
//
// 브이월드는 네모에 걸치는 필지를 주는데, 순서는 우리가 정하지
// 못한다. 스무 개 중 열 개만 받으면 **누른 그 필지가 안 올 수
// 있다.** 그러면 '필지를 못 찾았습니다' 가 뜨고, 사람은 그것을
// '이 땅은 정보가 없다' 로 읽는다. 자료는 있었다.
//
// 네모를 13m 로 줄이고 상한을 백으로 올린다. 둘 다 고친다 — 좁은
// 네모는 도심에서도 몇 개면 끝나고, 넉넉한 상한은 필지가 아주 잘게
// 쪼개진 곳에서 다시 같은 일이 나지 않게 한다.
const PARCEL_HALF_DEG = 0.00012;
// 열두 층을 한 요청에 담으므로 넉넉히 둔다.
const PARCEL_MAXFEATURES = "200";

// 필지 경계선을 **벡터로** 준다. 왜 그림이 아니라 도형인가:
//
//   브이월드 WMS 의 연속지적도는 1:1,703(z18) 아래로는 아무것도 안
//   그린다. z14~17 은 전부 '완전히 투명' 한 PNG 였다 (2026-09-10 실측,
//   scripts/cadastral_tile_probe.py). 게다가 그리기 시작하면 화소의
//   100% 를 칠한다 — 선이 아니라 면이라 배경으로 못 쓴다.
//
//   같은 자료를 WFS 로 받으면 도형이 온다. 그것을 Leaflet 이 선으로
//   그리면 얕은 배율에서도 나오고, 색도 우리가 정한다.
//
// **화면 단위가 아니라 타일 단위로 자른다.** 화면 하나를 통째로
// 부르면 조금만 움직여도 다시 받는다. 타일로 자르면 겹치는 칸은
// 엣지 캐시(s-maxage 이레)가 받아내고 새 칸만 나간다.
const PARCEL_VEC_TYPENAME = "lp_pa_cbnd_bubun";
const PARCEL_VEC_MIN_ZOOM = 16;
// 한 번에 받을 수 있는 상한. **600 은 도심에서 모자랐다** (2026-09-16,
// scripts/parcel_pix_probe.py):
//
//   대구 중구  z16 600개(상한) · z17 599개    ← 어느 배율로 봐도 걸린다
//   서울 중구  z16 600개(상한) · z17 142개
//   부산 중구  z16 577개       · z17 283개
//
// 걸리면 브이월드가 먼저 준 것만 오고 **나머지는 통째로 빠진다.** 화면은
// 빠진 자리에 선이 없으니 '경계가 지도와 안 맞는다' 로 보인다 — 받은
// 지시가 그것이었다("필지경계와 지도 틀어짐 발생 (대구)").
//
// 좌표가 밀린 것이 아니다. 같은 자리에서 브이월드가 칠한 그림과 우리가
// 찍은 선을 화소로 견줬더니 다섯 곳 모두 (0,0) 이 이겼다.
//
// 1000 은 브이월드 WFS 자신의 상한이다 — 더 불러도 안 준다. 그래서
// 그것으로도 모자라면 **칸을 넷으로 쪼개 다시 묻는다** (아래 gatherParcels).
const PARCEL_VEC_MAX = 1000;
// 쪼개기 깊이. 한 번 쪼개면 넷, 두 번이면 열여섯이다. 대구 중구가 z17
// 한 칸에 599개였으므로 z16 을 한 번만 쪼개도 조각마다 600 언저리 —
// 1000 아래로 떨어진다. 둘째 깊이는 보험이다.
const PARCEL_SPLIT_DEPTH = 2;
// 한 요청이 브이월드를 두드릴 수 있는 횟수 (1 + 4 + 16).
const PARCEL_CALL_BUDGET = 21;
// 우리가 쓰는 칸 이름. collect/landchar.FIELDS 와 같은 것을 본다 —
// 둘이 어긋나면 화면과 분석이 다른 땅을 말한다.
// dt_d194 는 서른 칸을 준다. 열 칸만 쓰고 있었다 (2026-09-10 실측).
// 요구사항: "토지의 기본 정보들 최대한 보여 줬으면 좋겠습니다."
const PARCEL_FIELDS = {
  pnu: "pnu",
  jimok: "lndcgr_code_nm",
  land_use: "prpos_area_1_nm",
  // 용도지역은 둘까지 지정된다. 하나만 보여주면 '자연녹지 + 개발제한'
  // 같은 겹침이 통째로 사라진다. 값이 '지정되지않음' 이면 화면이 뺀다.
  land_use2: "prpos_area_2_nm",
  use_situation: "lad_use_sittn_nm",
  area_m2: "lndpcl_ar",
  road_side: "road_side_code_nm",
  shape: "tpgrph_frm_code_nm",
  slope: "tpgrph_hg_code_nm",
  official_price: "pblntf_pclnd",
  stdr_year: "stdr_year",
  stdr_month: "stdr_mt",
  // '14-1답' 처럼 지번과 지목이 붙어 온다. 카드 머리에 그대로 쓴다.
  jibun_label: "lnm_lndcgr_smbol",
  // 1 = 토지대장 · 2 = 임야대장. 임야는 지번 앞에 '산' 이 붙는다.
  register: "regstr_se_code",
};

// 주소는 dt_d194 에 없다. 연속지적도가 addr 로 통째로 준다
// (실측: "경기도 광주시 초월읍 지월리 14-1").
const PARCEL_ADDR_FIELDS = {
  addr: "addr", sido: "ctp_nm", sigungu: "sig_nm",
  umd: "emd_nm", ri: "li_nm",
  // 그 표의 공시지가와 고시 시점. dt_d194 것과 기준이 달라 같이 안 섞는다.
  jiga: "jiga", gosi_year: "gosi_year", gosi_month: "gosi_month",
};
const PARCEL_ADDR_TYPENAME = "lp_pa_cbnd_bubun";

/* 필지에 겹친 **지구·구역** (요구사항 2026-09-10).
 *
 * 보고: "단순히 용도 지역으로만 토지를 평가하니 오류가 발생됩니다.
 * (농림지역의 농업진흥구역, 준보전산지, 개발제한구역 등)에 따라
 * 개발 방식이 달라짐"
 *
 * 맞는 말입니다. 무엇을 지을 수 있는지는 용도지역 위에 겹친 것들이
 * 정합니다. 상주 대조리 707-1 은 화면에 '계획관리 · 자연녹지' 만
 * 떴는데 실제로는 가축사육제한구역(절대제한)이 걸려 있었습니다.
 *
 * ## 왜 호출이 안 늘어나는가
 *
 * WFS 는 TYPENAME 에 쉼표로 여럿을 적을 수 있습니다. 토지특성까지
 * 한 요청에 담아 부르면 **클릭당 호출은 그대로 둘**입니다
 * (2026-09-10 실측, scripts/landuse_probe.py):
 *
 *   TYPENAME=dt_d194,lt_c_ud801,…(열둘)  → 200 · 14,837B
 *   층별 {'dt_d194': 1, 'lt_c_um000': 1}
 *
 * 어느 층에서 왔는지는 feature id 앞머리로 갈립니다
 * (lt_c_um000.57606).
 *
 * ## 못 주는 것
 *
 * **준보전산지와 접도구역은 브이월드 WFS 에 없습니다.** 목록을 훑어
 * 확인했습니다. 그 둘은 "국토교통부_토지이용계획정보" 에만 있고
 * 제공신청이 필요합니다. 그래서 화면에 '이것이 전부는 아니다' 라고
 * 적습니다 — 다 보여준 척하는 것이 안 보여주는 것보다 위험합니다.
 */
const PARCEL_ZONES = {
  lt_c_ud801: { label: "개발제한구역",
    note: "원칙적으로 신축이 안 됩니다. 기존 건축물 증축·용도변경도 따로 허가를 받습니다." },
  lt_c_agrixue101: { label: "농업진흥지역",
    note: "농업 관련 시설 외에는 어렵습니다. 진흥구역이 보호구역보다 더 엄합니다." },
  lt_c_um000: { label: "가축사육제한구역",
    note: "축사를 지을 수 없습니다. 제한 축종은 지자체 고시에 따릅니다." },
  lt_c_upisuq171: { label: "개발행위허가제한지역",
    note: "기간을 정해 개발행위 허가를 묶어 둔 곳입니다." },
  lt_c_uf151: { label: "산림보호구역",
    note: "입목 벌채와 형질변경이 제한됩니다." },
  lt_c_um710: { label: "상수원보호구역",
    note: "오수를 내는 시설이 막힙니다. 건축 자체가 크게 제한됩니다." },
  lt_c_uo101: { label: "교육환경보호구역",
    note: "학교 둘레라 제한 업종이 있습니다 (숙박·유흥 등)." },
  lt_c_uq121: { label: "경관지구",
    note: "높이·형태·색채에 제한이 붙습니다." },
  lt_c_uq124: { label: "방화지구",
    note: "건축물을 내화구조로 지어야 합니다." },
  lt_c_uq126: { label: "보호지구",
    note: "문화재·생태·시설 보호를 위해 행위가 제한됩니다." },
  lt_c_uq130: { label: "특정용도제한지구",
    note: "특정 용도의 건축물을 못 짓습니다." },
};
const PARCEL_ZONE_NAMES = Object.keys(PARCEL_ZONES);
// 그 구역의 세부 이름이 담기는 칸. 층마다 이름이 달라 순서대로 본다.
// (실측: 가축사육제한구역은 remark 에 "절대제한지역(전 축종)")
const ZONE_DETAIL_KEYS = ["remark", "alias", "dgm_nm", "name", "zone_nm"];
const VWORLD_ADDRESS = "https://api.vworld.kr/req/address";

// 화면에 깔 수 있는 것. 목적지를 받지 않고 이 표에서만 고른다.
const LAYERS = {
  // 용도지역 네 장을 한 번에. 지적편집도에서 색으로 칠해지는 그 면이다.
  zoning: "lt_c_uq111,lt_c_uq112,lt_c_uq113,lt_c_uq114",
  // 필지 경계선. 색면 위에 얹으면 '이 필지' 를 눈으로 짚을 수 있다.
  cadastral: "lp_pa_cbnd_bubun",

  // ── 개발 층 (요구사항 2026-09-14) ────────────────────────────────
  //
  // "산업단지 택지 지구 및 신규, 확장 도로 기차 노선은 지도에 색상
  //  구분해서 표기하면 좋을 것 같습니다 ('개발' 선택 시 표시)"
  //
  // 이름은 **추측하지 않았다.** WFS GetCapabilities 로 브이월드가 실제로
  // 열어 둔 177개 레이어를 받아 이름으로 걸렀다 (vworld-layers run 11·12).
  // 걸린 것을 그대로 쓴다:
  //
  //   lt_c_wgisiegug    국가산업단지
  //   lt_c_wgisieilban  일반산업단지
  //   lt_c_wgisiedosi   첨단산업단지
  //   lt_c_wgisienong   농공단지
  //   lt_c_lhzone       사업지구경계도   ← LH 택지개발지구가 여기
  //   lt_c_damdan       단지경계
  //   lt_c_upisuq151    도시계획(도로)   ← 신설·확장 계획도로
  //
  // **철도는 브이월드에 없다.** 두 번 훑어도 안 걸렸다. 대신 우리가
  // 자료를 갖고 있다 — rail_station 405곳과 rail_open 82건(2028년 예정
  // 개통까지). 철도는 우리 층으로 그린다 (app.js).
  //
  // 색은 브이월드 공식 스타일을 그대로 받는다. 용도지역 층에서 이미
  // 그렇게 했고, 지적편집도를 읽어온 사람에게는 설명이 필요 없다.
  // 네 갈래를 따로 둔 까닭은 **끌 수 있어야** 하기 때문이고, 다 켜면
  // develop 한 장으로 부른다 — 타일 한 칸에 함수 호출 한 번이다.
  industry: "lt_c_wgisiegug,lt_c_wgisieilban,lt_c_wgisiedosi,lt_c_wgisienong",
  // 갈래마다 따로도 부를 수 있어야 한다 (2026-09-16 지시: "산업단지도 …
  // 세부 선택 가능하도록").
  //
  // 산업단지는 **갈래가 곧 층**이라 층을 골라 부르면 그대로 걸러진다.
  // 그림으로 받아 놓고 나중에 거르는 길은 없다 — 브이월드가 이미 칠해서
  // 주기 때문이다. 그래서 거르기는 여기서, 부를 때 해야 한다.
  //
  // 넷을 다 켰을 때는 화면이 위의 industry 한 장으로 부른다. 타일 한 칸에
  // 함수 호출 한 번이 되도록 (api/tile 호출 수가 곧 요금이다).
  industry_gug: "lt_c_wgisiegug",
  industry_ilban: "lt_c_wgisieilban",
  industry_dosi: "lt_c_wgisiedosi",
  industry_nong: "lt_c_wgisienong",
  housing: "lt_c_lhzone,lt_c_damdan",
  planroad: "lt_c_upisuq151",
  develop: "lt_c_wgisiegug,lt_c_wgisieilban,lt_c_wgisiedosi,lt_c_wgisienong,"
    + "lt_c_lhzone,lt_c_damdan,lt_c_upisuq151",
};

/* 행정구역 경계 — 지역 태그를 누르면 그 구역이 드러나게 (2026-09-14).
 *
 * **코드로 묻지 않는다.** 브이월드 WFS 의 속성 이름(sig_cd 인지 emd_cd
 * 인지)을 모르는데, 틀린 이름으로 ATTRFILTER 를 걸면 0건이 오고 그것은
 * '그런 구역이 없다' 와 구별되지 않는다. 대신 **누른 자리를 감싸는 아주
 * 작은 상자**로 묻는다 — 그 안에 걸리는 폴리곤이 곧 그 자리가 속한
 * 행정구역이다. 추측이 한 개도 안 들어간다.
 */
const ADMIN_LAYERS = {
  sido: "lt_c_adsido",
  sigungu: "lt_c_adsigg",
  umd: "lt_c_ademd",
  // **리 경계는 있다** (2026-09-15, GetCapabilities 실측: `lt_c_adri  리`).
  // 여기 'lt_c_ademd' 를 넣고 "리 단위 경계는 없다" 고 적어 둔 것은 틀린
  // 단정이었다 — 그래서 리를 눌러도 면 전체가 잡혔다. 물어보니 177개
  // 레이어 안에 멀쩡히 있었다.
  ri: "lt_c_adri",
};

// 시에는 리가 없다 (조원동 같은 행정동·법정동). 그런 자리에서 리를 물으면
// 빈 답이 오므로 읍면동으로 한 번 물러난다 — 아래 adminShape 가 한다.
const ADMIN_FALLBACK = { ri: "umd" };

// ── 배경 지도 (요구사항 2026-09-09) ─────────────────────────────
//
// "배경 지도를 시인성 좋은 카카오맵이나 네이버맵을 받아올 수 있나요?"
//
// 카카오·네이버는 **타일이 아니라 자바스크립트 지도 SDK** 입니다.
// Leaflet 에 꽂을 타일 주소를 공개하지 않고, 타일을 뜯어 쓰는 것은
// 양쪽 약관이 금지합니다. 상업적 이용이 전제인 서비스에서 갈 길이
// 아닙니다. (네이버는 유료이기도 합니다.)
//
// 브이월드는 다릅니다 — **래스터 타일(WMTS)** 을 주고, 우리는 이미 그
// 키와 서울 중계기를 갖고 있습니다. 한국 지명·도로 체계에 위성까지
// 있습니다.
//
// 급소: WMTS 는 **키가 경로에 들어갑니다.**
//
//   https://api.vworld.kr/req/wmts/1.0.0/{키}/{레이어}/{z}/{y}/{x}.{확장자}
//
// 위의 WMS 는 키를 물음표 뒤에 붙입니다(callVworld). 그래서 같은 길로
// 못 보내고 따로 만듭니다. 확장자도 레이어마다 다릅니다 — 위성은
// 사진이라 jpeg 이고 나머지는 투명이 필요한 png 입니다. 여기서 틀리면
// 그림이 아예 안 옵니다.
//
// 다섯을 두드려 넷이 왔습니다 (점검 6-C, 2026-09-09 · z12/3495/1594):
//
//   base       200  20,792B  0.98s  ✓
//   midnight   200  14,414B  0.55s  ✓
//   satellite  200  22,161B  0.53s  ✓
//   hybrid     200  13,821B  0.38s  ✓
//   gray       ✗    브이월드가 그림 대신 XML 을 줬습니다
//
// **gray 는 뺐습니다.** 이름을 더 맞혀 볼 수는 있지만, 회색 배경은
// 지금도 OSM 을 CSS 로 채도를 낮춰 쓰고 있어 이미 있는 것이고
// (style.css .leaflet-tile-pane), 야간이 그 자리를 대신합니다. 목록에
// 올려 두고 눌렀을 때 안 나오면 그것은 고장으로 읽힙니다.
const BASEMAPS = {
  base: { name: "Base", ext: "png", label: "브이월드 일반" },
  midnight: { name: "midnight", ext: "png", label: "브이월드 야간" },
  satellite: { name: "Satellite", ext: "jpeg", label: "위성" },
  hybrid: { name: "Hybrid", ext: "png", label: "위성 위 지명" },
};
const VWORLD_WMTS = "https://api.vworld.kr/req/wmts/1.0.0";

// 웹 머케이터 격자의 한쪽 끝 (m). 타일 좌표를 bbox 로 바꾸는 데 쓴다.
const MERC_EDGE = 20037508.342789244;

// ── 누르면 이름이 뜨는 길 (GetFeatureInfo) ──────────────────────────
//
// 색면만 깔면 지적편집도가 아니라 색칠이다. 그 색이 무슨 뜻인지 알
// 방법이 있어야 한다.
//
// 길이 둘이었는데 **서버에 물어서** 하나로 좁혔다
// (scripts/vworld_featureinfo.py, 2026-09-04).
//
//   GetLegendGraphic   ✗ 브이월드가 안 준다.
//                        "유효한 파라미터 값의 범위 : [GetMap,
//                         GetFeatureInfo, GetCapabilities]"
//   GetFeatureInfo     ✓ 온다. INFO_FORMAT 네 가지가 다 응답했다.
//
// 형식은 text/plain 을 쓴다. 넷 중 가장 작고(466B) 파싱이 명확하다.
//
//   json  5,571B   MultiPolygon 좌표가 통째로 들어온다
//   xml   6,497B   같은 이유로 크다
//   html  1,473B   GeoServer 표 — 화면에 그대로 못 쓴다
//   plain   466B   key = value 한 줄씩          ← 이것
//
// 실제로 온 값 (용인 원삼 · 화성 향남)
//
//   uname = 농림지역 / 보전관리지역   ← 우리가 띄울 이름
//   ucode = UQC001 / UQB300           법정 용도지역 코드
//   sido_name·sigg_name·bon_bun·bu_bun
//   ag_geom = [GEOMETRY ...]          ← 버린다. 쓸 데가 없고 크다.
const INFO_FORMAT = "text/plain";
// 조회할 점 둘레로 만드는 사각형의 반지름(m). 너무 작으면 경계 근처에서
// 아무것도 안 잡히고, 너무 크면 옆 필지가 잡힌다.
const INFO_HALF_M = 30;
// 화면에 쓸 칸만 남긴다. 나머지는 사람이 볼 것이 아니다.
const INFO_FIELDS = ["uname", "ucode", "sido_name", "sigg_name",
                     "bon_bun", "bu_bun"];
// 좌표는 한반도 밖을 받지 않는다. 남의 서버에 헛일을 시킬 이유가 없다.
const KOREA = { latMin: 32.5, latMax: 39.5, lonMin: 124.0, lonMax: 132.5 };

/** 위경도 → 웹 머케이터 (m). */
function toMerc(lat, lon) {
  const x = (lon * MERC_EDGE) / 180;
  const y = Math.log(Math.tan(((90 + lat) * Math.PI) / 360)) / (Math.PI / 180);
  return [x, (y * MERC_EDGE) / 180];
}

/** 실수인지 본다. 빈 문자열·NaN·Infinity 를 통과시키면 안 된다. */
function decimal(value) {
  if (typeof value !== "string" || !/^-?\d{1,3}(\.\d{1,8})?$/.test(value)) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** GetFeatureInfo 의 text/plain 응답을 읽는다.
 *
 * 모양 (실제 응답)
 *
 *   Results for FeatureType 'https://www.vworld.kr:lt_c_uq113':
 *   --------------------------------------------
 *   uname = 농림지역
 *   ag_geom = [GEOMETRY (Polygon) with 3337 points]
 *   --------------------------------------------
 *
 * 네 장을 함께 물으므로 덩어리가 여럿 올 수 있다. **이름이 있는 첫
 * 덩어리**를 쓴다 — 한 점은 용도지역 대분류 하나에만 속한다.
 */
function parseInfo(text) {
  const blocks = String(text).split(/Results for FeatureType/).slice(1);
  for (const block of blocks) {
    const layer = (block.match(/:([a-z0-9_]+)'/) || [])[1] || null;
    const row = {};
    for (const line of block.split("\n")) {
      const m = line.match(/^\s*([a-z_]+)\s*=\s*(.*?)\s*$/);
      if (!m) continue;
      const [, k, v] = m;
      if (!INFO_FIELDS.includes(k) || v === "null" || v === "") continue;
      row[k] = v;
    }
    if (row.uname) return { ...row, layer };
  }
  return null;
}

const MAX_ZOOM = 19;
const TIMEOUT_MS = 10_000;
// 성공한 타일은 브라우저에 한 주, CDN 에 한 달 (+ 하루는 낡은 것을 주며
// 뒤에서 갱신). 용도지역·배경·경계선은 자주 바뀌는 자료가 아니다.
//
// **이 함수가 도는 횟수가 곧 돈이다** (Vercel Hobby: 함수 호출 월 100만).
// 실측(2026-09-11): 지도 한 번 움직임에 40장이 1초 안에 나가고 전부 MISS
// 였다. 엣지 캐시가 오래 붙들수록 두 번째 사람부터는 함수가 안 돈다.
// 실패는 짧게만 — 한도가 풀린 뒤에도 빈 화면이 오래 남으면 안 된다.
const CACHE_OK = "public, max-age=604800, s-maxage=2592000, stale-while-revalidate=86400";
const CACHE_BAD = "public, max-age=0, s-maxage=60";

function fail(res, code, message) {
  res.setHeader("cache-control", CACHE_BAD);
  res.status(code).json({ tileError: message });
}

/* ── 속도 제한 (요구사항 2026-09-10) ─────────────────────────────
 *
 * 왜 필요한가. 이 함수가 도는 것은 곧 브이월드를 부르는 것입니다.
 * 필지 경계선이 붙으면서 부를 수 있는 주소가 국토 전체 42만 칸으로
 * 늘었고, 필지 조회는 좌표가 소수점 여섯 자리라 **캐시가 아예 안
 * 먹습니다.** 훑는 프로그램 하나가 우리 브이월드 한도를 대신 태울 수
 * 있습니다.
 *
 * **여기가 정확한 자리입니다.** 엣지 캐시가 받아낸 요청은 이 함수를
 * 아예 안 부릅니다. 그러니 이 함수가 도는 횟수가 곧 브이월드로
 * 나갈 수 있는 횟수입니다.
 *
 * 한도는 사람의 사용을 막지 않을 만큼 넉넉합니다. 폰으로 지도를 한 번
 * 움직이면 경계선 칸이 최대 12장, 배경 타일이 스무 장쯤 한꺼번에
 * 나갑니다. 분당 240 이면 그것을 열 번 연속해도 안 걸립니다.
 *
 * 필지 조회는 따로, 더 좁게 봅니다. 캐시가 안 먹는 데다 한 번에
 * 브이월드를 두세 번 부르기 때문입니다. 사람은 1분에 예순 번 넘게
 * 필지를 누르지 않습니다.
 *
 * ## 한계를 분명히 적어 둡니다
 *
 * 이 셈은 **함수 인스턴스 안에서만** 삽니다. Vercel 은 부하에 따라
 * 인스턴스를 여럿 띄우므로, 전역으로 정확히 240 이 아니라 '인스턴스마다
 * 240' 입니다. 전역 한도를 세우려면 저장소(Redis 등)가 필요하고 그것은
 * 돈이 듭니다. 지금 필요한 것은 **폭주를 꺾는 것**이지 정밀한 계량이
 * 아니므로 이 정도로 둡니다.
 */
const RATE_WINDOW_MS = 60_000;
// 분당. 넉넉하게 잡습니다 — 이 제한의 일은 **폭주를 꺾는 것**이지
// 계량이 아닙니다.
//
// 넉넉해야 하는 이유가 하나 더 있습니다. 한국 이동통신은 여러 사용자가
// 주소 하나를 나눠 씁니다(CGNAT). 같은 IP 로 보이는 사람이 수십 명일
// 수 있어서, 사람 한 명 기준으로 좁게 잡으면 **애먼 사람이 막힙니다.**
// 600/분이면 한 IP 뒤에 스무 명이 동시에 지도를 굴려도 안 걸리고,
// 훑는 프로그램은 국토 42만 칸을 도는 데 열두 시간이 걸립니다.
const RATE_LIMIT = 600;
// 필지 조회는 따로 봅니다. 캐시가 안 먹고 한 번에 브이월드를 두세 번
// 부릅니다. 사람은 1분에 백 번 넘게 필지를 누르지 않습니다.
const RATE_LIMIT_PARCEL = 120;
// 이보다 많은 주소를 들고 있지 않는다. 넘으면 오래된 것부터 버린다.
// 없으면 훑는 쪽이 IP 를 바꿔 가며 우리 메모리를 불릴 수 있다.
const RATE_MAX_KEYS = 5000;
const rateHits = new Map();      // ip → number[] (요청 시각)

/** 요청을 보낸 쪽. Vercel 이 x-forwarded-for 를 덮어쓰므로 믿을 수 있다. */
function callerIp(req) {
  const h = req.headers || {};
  const xff = String(h["x-forwarded-for"] || "");
  return (xff.split(",")[0] || "").trim()
    || String(h["x-real-ip"] || "").trim()
    || "unknown";
}

/** 넘었으면 true. 넘지 않았으면 이번 요청을 세고 false. */
function overRate(req, limit) {
  const now = Date.now();
  const ip = callerIp(req);
  if (rateHits.size > RATE_MAX_KEYS) {
    // 통째로 비운다. 창이 1분이라 잃어봐야 1분어치다.
    rateHits.clear();
  }
  const seen = (rateHits.get(ip) || []).filter((t) => now - t < RATE_WINDOW_MS);
  if (seen.length >= limit) {
    rateHits.set(ip, seen);
    return true;
  }
  seen.push(now);
  rateHits.set(ip, seen);
  return false;
}

/** 너무 잦다고 답한다.
 *
 * **캐시하면 안 된다.** fail() 은 s-maxage=60 을 붙이는데, 그것을 쓰면
 * 훑는 쪽에게 준 429 가 엣지에 박혀 **같은 주소를 부른 다른 사람까지**
 * 1분간 막힙니다. no-store 로 못을 박습니다.
 */
function tooMany(res) {
  res.setHeader("cache-control", "no-store");
  res.setHeader("retry-after", String(RATE_WINDOW_MS / 1000));
  res.status(429).json({ tileError: "요청이 너무 잦습니다. 잠시 뒤 다시 시도해 주세요." });
}


/** 정수인지 본다. '01' · '1.5' · '1e3' · 음수를 통과시키면 안 된다. */
function whole(value) {
  if (typeof value !== "string" || !/^\d{1,7}$/.test(value)) return null;
  return Number(value);
}

/** 타일 z/x/y → 웹 머케이터 bbox "minX,minY,maxX,maxY".
 *
 * 투영좌표계라 축 순서가 easting,northing 이다. WMS 1.3.0 이 축 순서를
 * 뒤집는 것은 EPSG:4326 같은 **지리**좌표계뿐이다. */
function mercBbox(z, x, y) {
  const size = (MERC_EDGE * 2) / 2 ** z;
  const minX = -MERC_EDGE + x * size;
  const maxY = MERC_EDGE - y * size;
  return [minX, maxY - size, minX + size, maxY].join(",");
}

/** 브이월드를 부른다. 인증키는 여기서만 붙고 밖으로 안 나간다. */
async function callVworld(params, base, host) {
  const key = process.env.VWORLD_KEY;
  if (!key) return { keyMissing: true };
  // 브이월드 키는 '웹사이트' 유형으로 서비스URL 이 등록돼 있다. WMS 는
  // 요청이 그 도메인에서 왔는지를 Referer 로 본다. 서버에서 부르면
  // 브라우저처럼 Referer 가 안 붙으므로 등록된 주소를 실어 보낸다
  // (api/relay.js 가 같은 이유로 같은 값을 쓴다).
  // **주소를 코드에 박지 않는다.** 배포 주소가 바뀌면(2026-09-08 사도
  // 토지 → 토지 고고) 박아 둔 값이 그대로 남아 조용히 틀린 Referer 를
  // 보내게 된다. 환경변수가 있으면 그것을 쓰고, 없으면 지금 요청이 온
  // 그 호스트를 쓴다. 브이월드 콘솔에 등록된 주소와 맞아야 한다.
  const referer = process.env.VWORLD_REFERER
    || (host ? `https://${host}/` : "https://toji.fyi/");
  const url = `${base || VWORLD_WMS}?` + new URLSearchParams({ ...params, key });
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    const upstream = await fetch(url, {
      signal: stop.signal,
      redirect: "manual",
      headers: { "User-Agent": "redt-tile/1.0", Accept: "*/*", Referer: referer },
    });
    return { upstream };
  } catch (err) {
    return { timedOut: !!(err && err.name === "AbortError") };
  } finally {
    clearTimeout(timer);
  }
}

/** 배경 타일 한 장. WMTS 는 키가 **경로**에 들어가 WMS 와 길이 다르다. */
async function callWmts(spec, z, y, x, host) {
  const key = process.env.VWORLD_KEY;
  if (!key) return { keyMissing: true };
  const referer = process.env.VWORLD_REFERER
    || (host ? `https://${host}/` : "https://toji.fyi/");
  const url = `${VWORLD_WMTS}/${key}/${spec.name}/${z}/${y}/${x}.${spec.ext}`;
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    const upstream = await fetch(url, {
      signal: stop.signal,
      redirect: "manual",
      headers: { "User-Agent": "redt-tile/1.0", Accept: "image/*", Referer: referer },
    });
    return { upstream };
  } catch (err) {
    return { timedOut: !!(err && err.name === "AbortError") };
  } finally {
    clearTimeout(timer);
  }
}

/** 누른 자리의 용도지역 이름을 돌려준다. */
async function featureInfo(req, res, layers) {
  const lat = decimal(String(req.query.lat ?? ""));
  const lon = decimal(String(req.query.lon ?? ""));
  if (lat === null || lon === null) {
    return fail(res, 400, "lat·lon 이 필요합니다");
  }
  if (lat < KOREA.latMin || lat > KOREA.latMax ||
      lon < KOREA.lonMin || lon > KOREA.lonMax) {
    return fail(res, 400, "한반도 밖입니다");
  }

  const [cx, cy] = toMerc(lat, lon);
  const h = INFO_HALF_M;
  const out = await callVworld({
    SERVICE: "WMS", REQUEST: "GetFeatureInfo", VERSION: "1.3.0",
    LAYERS: layers, QUERY_LAYERS: layers, STYLES: "",
    CRS: "EPSG:3857",
    BBOX: [cx - h, cy - h, cx + h, cy + h].join(","),
    // 사각형 한가운데를 찍는다. 폭·높이는 픽셀 좌표의 기준일 뿐이다.
    WIDTH: "101", HEIGHT: "101", I: "50", J: "50",
    INFO_FORMAT, FEATURE_COUNT: "5",
  }, null, (req.headers || {}).host);
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`
                   : "브이월드 호출 실패");
  }
  const upstream = out.upstream;
  const type = upstream.headers.get("content-type") || "";
  const text = await upstream.text();
  // 한도 초과·키 오류는 text/plain 이 아니라 XML 로 온다. 본문을 그대로
  // 돌려주면 안 된다 — 우리가 보낸 요청 URL 이 오류에 실려 오는 경우가
  // 있고, 거기에는 인증키가 붙어 있다.
  if (!upstream.ok || /xml/i.test(type)) {
    return fail(res, 502, `브이월드가 정보를 주지 않았습니다 (HTTP ${upstream.status})`);
  }
  const info = parseInfo(text);
  res.setHeader("cache-control", info ? CACHE_OK : CACHE_BAD);
  // 없는 것도 200 으로 돌려준다. 빈 땅을 누른 것은 오류가 아니다 —
  // 화면이 "여기는 용도지역이 지정돼 있지 않습니다" 라고 말하면 된다.
  res.status(200).json(info ? { zoning: info } : { zoning: null });
}

/** 점이 다각형 안에 드는가 (광선 교차). 이웃 필지를 걸러낸다. */
function inRing(ring, lon, lat) {
  let inside = false;
  for (let i = 0, n = ring.length; i < n; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % n];
    if ((y1 > lat) !== (y2 > lat)) {
      const cut = x1 + ((lat - y1) * (x2 - x1)) / ((y2 - y1) || 1e-12);
      if (lon < cut) inside = !inside;
    }
  }
  return inside;
}

function hitsPoint(geom, lon, lat) {
  if (!geom) return false;
  const polys = geom.type === "MultiPolygon" ? geom.coordinates
              : geom.type === "Polygon" ? [geom.coordinates] : [];
  return polys.some((rings) => rings.length && inRing(rings[0], lon, lat));
}

/** 누른 자리의 **필지 특성**을 돌려준다 (도로접·형상·지세·공시지가). */
/** 타일 한 칸에 든 필지의 **선만** 준다. 지번·면적은 안 싣는다.
 *
 * 화면은 선 하나만 그린다. 지번·면적·소유 구분은 필지를 누른 뒤에
 * mode=parcel 이 따로 준다. 그것을 여기 같이 실으면 한 칸이 두 배로
 * 커진다 (실측: 속성을 버리면 838KB → 478KB, 좌표를 여섯 자리로
 * 깎으면 420KB).
 */
async function parcelLines(req, res) {
  const z = whole(String(req.query.z ?? ""));
  const y = whole(String(req.query.y ?? ""));
  const x = whole(String(req.query.x ?? ""));
  if (z === null || y === null || x === null) {
    return fail(res, 400, "z·y·x 가 0 이상의 정수여야 합니다");
  }
  if (z < PARCEL_VEC_MIN_ZOOM || z > MAX_ZOOM) {
    return fail(res, 400,
      `z 는 ${PARCEL_VEC_MIN_ZOOM}~${MAX_ZOOM} 이어야 합니다`);
  }
  const span = 2 ** z;
  if (y >= span || x >= span) return fail(res, 400, "그 배율의 격자 밖입니다");

  const [w, s, e, n] = degBbox(z, x, y);
  // 한반도 밖이면 브이월드에 헛일을 시키지 않는다. 바다·중국 쪽
  // 칸까지 부르면 한도만 축난다.
  if (n < KOREA.latMin || s > KOREA.latMax ||
      e < KOREA.lonMin || w > KOREA.lonMax) {
    return sendLines(res, [], true);
  }
  const got = await gatherParcels(req, [w, s, e, n], 0, { n: 0 });
  if (got.err === "key") {
    return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  }
  if (got.err === "timeout") {
    return fail(res, 504, `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`);
  }
  if (got.err === "call") return fail(res, 502, "브이월드 호출 실패");
  if (got.err === "notjson") {
    // 한도 초과·키 오류는 JSON 이 아니라 XML 로 온다. 그것을 빈
    // 목록인 척 돌려주면 '필지가 없는 동네' 로 읽힌다.
    return fail(res, 502, "브이월드가 필지 목록 대신 다른 것을 줬습니다");
  }
  // 쪼개서 물으면 경계에 걸친 필지가 두 조각 모두에 온다. 두 번 그리면
  // 선이 굵어 보이고 몸통도 커진다 — 첫 꼭짓점으로 같은 것을 걷어낸다.
  const seen = new Set();
  const geoms = [];
  for (const f of got.feats) {
    const g = round6((f || {}).geometry);
    if (!g) continue;
    // firstPoint 는 개발 층이 겹친 도형을 가릴 때 쓰는 그것을 그대로
    // 쓴다. 같은 이름의 함수를 하나 더 두면 **뒤에 선언한 것이 이긴다** —
    // 이 자리에서 실제로 그랬고, 겹친 필지가 안 걷혔다 (검사가 잡았다).
    const pt = firstPoint(g);
    const key = pt ? JSON.stringify(pt) : null;
    if (key && seen.has(key)) continue;
    if (key) seen.add(key);
    geoms.push(g);
  }
  return sendLines(res, geoms, !got.capped);
}


/** 상자 하나를 브이월드에 묻는다. 상한에 닿았는지도 같이 돌려준다. */
async function askParcelBox(req, [w, s, e, n]) {
  const out = await callVworld({
    // 1.1.0 한 길뿐이다 — parcelInfo 의 주석 참고.
    SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
    TYPENAME: PARCEL_VEC_TYPENAME,
    BBOX: [w, s, e, n].join(","),
    SRSNAME: "EPSG:4326",
    OUTPUT: "application/json",
    MAXFEATURES: String(PARCEL_VEC_MAX), RESULTTYPE: "results",
    DOMAIN: process.env.VWORLD_REFERER
      || `https://${(req.headers || {}).host || "toji.fyi"}/`,
  }, VWORLD_WFS, (req.headers || {}).host);
  if (out.keyMissing) return { err: "key" };
  if (!out.upstream) return { err: out.timedOut ? "timeout" : "call" };
  let body;
  try {
    body = await out.upstream.json();
  } catch (err) {
    return { err: "notjson" };
  }
  const feats = Array.isArray(body && body.features) ? body.features : [];
  return { feats, capped: feats.length >= PARCEL_VEC_MAX };
}

/** 상한에 걸리면 **칸을 넷으로 쪼개 다시 묻는다.**
 *
 * 상한에 걸린 칸을 그대로 그리면 필지가 빠진 채로 그려지는데, 화면에서
 * 그것은 '없는 것' 이 아니라 '틀어진 것' 으로 보인다. 빠지느니 한 번 더
 * 묻는 편이 낫다. 쪼개기는 **걸렸을 때만** 도므로 시골 칸은 그대로
 * 한 번이다 — 도심에서만 값을 치른다.
 */
async function gatherParcels(req, box, depth, budget) {
  budget.n += 1;
  const got = await askParcelBox(req, box);
  if (got.err) return got;
  if (!got.capped || depth >= PARCEL_SPLIT_DEPTH
      || budget.n + 4 > PARCEL_CALL_BUDGET) return got;
  const [w, s, e, n] = box;
  const mx = (w + e) / 2;
  const my = (s + n) / 2;
  const parts = await Promise.all([
    [w, s, mx, my], [mx, s, e, my], [w, my, mx, n], [mx, my, e, n],
  ].map((q) => gatherParcels(req, q, depth + 1, budget)));
  // 한 조각이라도 못 받으면 반쪽을 그리지 않는다 — 반쪽이 곧 틀어짐이다.
  const bad = parts.find((p) => p.err);
  if (bad) return bad;
  return {
    feats: parts.flatMap((p) => p.feats),
    capped: parts.some((p) => p.capped),
  };
}

/* 개발 층을 **도형으로** 준다 (2026-09-14 지시).
 *
 *   "계획도로는 확장인지, 신규인지 구분은 안될까요? 완공된 것은 표기
 *    안하는 것이 좋을 것 같습니다."
 *   "산업단지 택지사업지구의 색상은 의미가 있나요?"
 *
 * 두 물음의 답이 속성에 있었다 (vworld-render run 4):
 *
 *   lt_c_upisuq151  exc_nam  미집행 · 부분집행 · **집행완료**
 *                   atr_nam  광로2류 … 소로3류 (폭 등급)
 *                   pmi_nam  주간선도로 · 보조간선도로 · 집산도로 …
 *                   ※ 신설/확장을 가르는 칸은 **없다.** 도시계획도로는
 *                     '계획선' 이라 그 구분을 안 담는다. 대신 집행 단계가
 *                     그 자리를 대신한다 — 미집행이 아직 안 난 길이다.
 *   lt_c_lhzone     cat_nam  지구지정 · 개발계획 · 실시계획 · 부분준공 · **준공**
 *                   ※ 브이월드 색은 이 단계를 뜻한다. 의미가 있다.
 *
 * 그림(WMS)으로는 못 거른다 — 브이월드가 이미 칠해서 준다. 그래서 이
 * 둘만 도형(WFS)으로 받아 화면이 거르고 우리 색으로 그린다. 연속지적도
 * 에서 쓰던 길과 같다.
 */
const DEV_VEC = {
  planroad: {
    typename: "lt_c_upisuq151",
    keep: ["exc_nam", "atr_nam", "pmi_nam", "grad_se"],
  },
  zone: {
    typename: "lt_c_lhzone",
    keep: ["cat_nam", "zonename", "zonecode"],
  },
};
const DEV_VEC_MIN_ZOOM = 12;
const DEV_VEC_MAX = 600;

async function developShapes(req, res) {
  const want = String(req.query.kind || "");
  const spec = DEV_VEC[want];
  if (!spec) return fail(res, 400, "kind 는 planroad·zone 이어야 합니다");
  const z = whole(String(req.query.z ?? ""));
  const y = whole(String(req.query.y ?? ""));
  const x = whole(String(req.query.x ?? ""));
  if (z === null || y === null || x === null) {
    return fail(res, 400, "z·y·x 가 0 이상의 정수여야 합니다");
  }
  if (z < DEV_VEC_MIN_ZOOM || z > MAX_ZOOM) {
    return fail(res, 400, `z 는 ${DEV_VEC_MIN_ZOOM}~${MAX_ZOOM} 이어야 합니다`);
  }
  const span = 2 ** z;
  if (y >= span || x >= span) return fail(res, 400, "그 배율의 격자 밖입니다");
  const [w, s, e, n] = degBbox(z, x, y);
  if (n < KOREA.latMin || s > KOREA.latMax ||
      e < KOREA.lonMin || w > KOREA.lonMax) {
    return sendShapes(res, [], true);
  }
  const out = await callVworld({
    SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
    TYPENAME: spec.typename,
    BBOX: [w, s, e, n].join(","),
    SRSNAME: "EPSG:4326",
    OUTPUT: "application/json",
    MAXFEATURES: String(DEV_VEC_MAX), RESULTTYPE: "results",
    DOMAIN: process.env.VWORLD_REFERER
      || `https://${(req.headers || {}).host || "toji.fyi/"}`,
  }, VWORLD_WFS, (req.headers || {}).host);
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`
                   : "브이월드 호출 실패");
  }
  let body;
  try { body = await out.upstream.json(); }
  catch (err) { return fail(res, 502, "브이월드가 도형 대신 다른 것을 줬습니다"); }
  const feats = Array.isArray(body && body.features) ? body.features : [];
  const items = [];
  for (const f of feats) {
    const g = round6((f || {}).geometry);
    if (!g) continue;
    const src = (f || {}).properties || {};
    // **쓸 칸만 넘긴다.** 스물세 칸을 다 보내면 한 칸이 수백 KB 가 된다.
    const props = {};
    for (const k of spec.keep) {
      if (src[k] != null) props[k] = src[k];
    }
    // **도형 하나를 가리키는 이름표.**
    //
    // WFS 는 BBOX 에 '걸치는' 것을 전부 준다. 동탄2 처럼 큰 사업지구는
    // 칸 여러 개에 걸쳐 있어서 **칸마다 같은 도형이 한 번씩 온다.**
    // 화면이 그것을 그대로 그리면 같은 면이 여러 겹 쌓여, 반투명 채움이
    // 겹친 만큼 진해진다 (0.2 를 두 번 겹치면 0.36). 2026-09-16 보고:
    // "같은 부분준공인데 투명도 차이가 발생하는 이유?"
    //
    // 그래서 화면이 겹친 것을 골라낼 수 있도록 이름표를 같이 보낸다.
    // 브이월드가 주는 f.id 가 'lt_c_lhzone.123' 꼴로 도형마다 다르다.
    // 없으면 지구코드로, 그것도 없으면 첫 좌표로 대신한다 — 좌표는
    // 같은 도형이면 칸이 달라도 같은 값이 나온다(round6 이 먼저다).
    const k = (typeof f.id === 'string' && f.id) || src.zonecode
      || JSON.stringify(firstPoint(g));
    items.push({ k: String(k), g, p: props });
  }
  return sendShapes(res, items, feats.length < DEV_VEC_MAX);
}

/** 도형의 첫 좌표. 이름표가 없는 도형을 가릴 때만 쓴다. */
function firstPoint(g) {
  let c = g && g.coordinates;
  while (Array.isArray(c) && Array.isArray(c[0])) c = c[0];
  return Array.isArray(c) ? c : null;
}

function sendShapes(res, items, whole_) {
  res.setHeader("cache-control", CACHE_OK);
  return res.status(200).json({ n: items.length, whole: whole_, items });
}

/* 누른 자리가 속한 행정구역 한 덩이를 돌려준다.
 *
 * 아주 작은 상자로 물어 그 자리를 감싸는 폴리곤을 받는다. 경계선 바로
 * 위를 누르면 둘이 올 수 있는데, 그때는 **첫 번째**를 쓴다 — 어느 쪽이든
 * 사람이 누른 자리의 구역이고, 둘 중 하나를 고르려고 점-다각형 판정을
 * 여기서 다시 하는 것은 값에 비해 무겁다.
 *
 * 경계는 움직이지 않으므로 길게 캐시한다. 자리를 6자리로 끊어 물으면
 * 같은 동네의 다른 클릭이 같은 주소가 되어 엣지 캐시가 받아낸다.
 */
async function adminShape(req, res) {
  const level = String(req.query.level || "sigungu");
  if (!ADMIN_LAYERS[level]) {
    return fail(res, 400, "level 은 sido·sigungu·umd·ri 여야 합니다");
  }
  const lat = Number(req.query.lat);
  const lon = Number(req.query.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return fail(res, 400, "lat·lon 이 필요합니다");
  }
  if (lat < KOREA.latMin || lat > KOREA.latMax
      || lon < KOREA.lonMin || lon > KOREA.lonMax) {
    return fail(res, 400, "한반도 밖입니다");
  }
  // 약 10m 짜리 상자. 점 하나로 물으면 WFS 가 빈 상자로 읽는다.
  const d = 0.0001;
  const ask = (typename) => callVworld({
    SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
    TYPENAME: typename,
    BBOX: [lon - d, lat - d, lon + d, lat + d].join(","),
    SRSNAME: "EPSG:4326",
    OUTPUT: "application/json",
    MAXFEATURES: "4", RESULTTYPE: "results",
    DOMAIN: process.env.VWORLD_REFERER
      || `https://${(req.headers || {}).host || "toji.fyi"}/`,
  }, VWORLD_WFS, (req.headers || {}).host);

  let got = level;
  let out = await ask(ADMIN_LAYERS[level]);
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`
                   : "브이월드 호출 실패");
  }
  let body;
  try { body = await out.upstream.json(); }
  catch (err) {
    return fail(res, 502, "브이월드가 행정구역 대신 다른 것을 줬습니다");
  }
  let feats = Array.isArray(body && body.features) ? body.features : [];
  // 리가 없는 자리(시의 동)면 한 단계 물러나 읍면동을 준다. 빈 경계를
  // 주면 화면에서 '눌렀는데 아무 일도 안 난다' 가 된다.
  const back = ADMIN_FALLBACK[level];
  if (!feats.length && back && ADMIN_LAYERS[back]) {
    const out2 = await ask(ADMIN_LAYERS[back]);
    if (out2.upstream) {
      try {
        const body2 = await out2.upstream.json();
        const f2 = Array.isArray(body2 && body2.features) ? body2.features : [];
        if (f2.length) { feats = f2; got = back; }
      } catch (err) { /* 물러난 쪽이 안 와도 위의 빈 답을 그대로 준다 */ }
    }
  }
  const first = feats[0] || null;
  res.setHeader("cache-control", CACHE_OK);
  // 이름 칸은 실호출로 확인했다 (vworld-render run 1):
  //   시군구  sig_cd sig_kor_nm sig_eng_nm full_nm cat_cde cat_nam
  //   읍면동  emd_cd emd_kor_nm emd_eng_nm full_nm cat_cde cat_nam
  // full_nm 이 '경기도 평택시 안중읍' 처럼 통째로 온다. 그래도 속성은
  // **통째로** 넘긴다 — 여기서 하나만 골라 찍으면 다른 칸이 필요해질 때
  // 서버를 또 고쳐야 한다.
  return res.status(200).json({
    level,
    // 실제로 답한 단계. 리를 물었는데 동으로 물러났으면 여기서 갈린다 —
    // 화면이 '리 경계' 라고 말해 놓고 면을 그리는 일이 없게.
    got,
    n: feats.length,
    geom: first ? round6(first.geometry) : null,
    props: first ? (first.properties || {}) : null,
  });
}

/** 선 목록을 돌려준다. 빈 칸도 캐시한다 — 바다는 늘 비어 있다. */
/* ── 고속도로를 **선이 아니라 필지로** 그린다 (2026-09-16 지시) ──────────
 *
 *   "계획은 살려 놓고 실제로 표시는 계획 도로처럼 **필지 기준으로 선택**
 *    될 수 있도록 방법을 전환바랍니다."
 *
 * 두 문이 닫힌 것을 먼저 확인했다.
 *
 *   · 도시계획시설(lt_c_upisuq151)에 '고속' 을 가려낼 칸이 **없다**.
 *     안성 589개의 모든 칸을 세어 봤다 (scripts/road_kras_probe.py).
 *     토지이음에서 보이는 대로2류는 주간선·보조간선·집산도로다.
 *   · 브이월드 WFS 177개 층에 **도로구역도가 없다** (vworld-layers run 15).
 *
 * 그래서 남은 길로 간다 — **우리가 가진 선 둘레의 필지를 지적에서 고른다.**
 * 실측이 이 길을 열어 줬다 (scripts/road_parcel_probe.py):
 *
 *   서평택JCT-안산JCT   0.0m 448도 · 0.0m 446-1도 · 0.2m 964-1구
 *   읍내JCT-군위JCT     0.1m 305도 · 0.1m 308-1도 · 1.0m 산54-1도
 *   안성 서운면(신설)    0.4m 667장 · 0.9m 산138-22임 · 1.3m 산139임
 *
 * 세 가지가 한꺼번에 나왔다.
 *
 *   ① 우리 선이 도로 필지 위에 **0.0~2.2m** 로 놓인다.
 *   ② **지목이 지번에 붙어 온다** ('448도'). 따로 칸이 없어도 갈린다.
 *   ③ 신설 구간만 지목이 임야·공장용지다 — **아직 편입 전인 땅**이다.
 *      땅 주인에게 가장 중요한 것이 그것이므로 색을 나눠 그린다.
 *
 * 띠 너비도 쟀다. 10m 6~9개 · 20m 6~12개 · **30m 7~14개** · 50m 12~48개.
 * 30m 에서 깨끗이 끊기고 50m 부터 옆 필지가 딸려 온다. 고속도로 용지폭
 * (왕복 4차로 30m 안팎)과도 맞는다. 내가 고른 값이 아니라 잰 값이다.
 */
const ROAD_BAND_M = 30;
// 배율 15 아래로는 안 준다. 필지는 가까이서 보는 것이고, 멀리서는 선이
// 그 일을 한다. 아래로 열면 한 칸에 브이월드를 열 번씩 부르게 된다.
const ROAD_PARCEL_MIN_ZOOM = 15;
// 한 번 물을 때 덮는 선의 길이. 길면 네모가 넓어져 옆 필지가 딸려 오고,
// 짧으면 호출이 는다. 200m 면 네모가 200×200m 을 안 넘는다.
const ROAD_CHUNK_M = 200;
// 한 칸이 브이월드를 두드릴 수 있는 횟수. 고속도로가 지나는 칸만 낸다.
const ROAD_CHUNK_MAX = 6;
const ROAD_PARCEL_MAX = 300;
// 화면이 받는 그 주소를 우리도 쓴다 (app.js DATA_BUCKET).
const DATA_BUCKET = process.env.DATA_BUCKET
  || "https://caykbxvnebpifcduqjre.supabase.co/storage/v1/object/public/appdata";
const ROAD_TTL_MS = 60 * 60 * 1000;
let roadJson = null;
let roadJsonAt = 0;

/** road.json 을 버킷에서 받아 한 시간 들고 있는다. */
async function roadItems() {
  if (roadJson && Date.now() - roadJsonAt < ROAD_TTL_MS) return roadJson;
  try {
    const r = await fetch(`${DATA_BUCKET}/road.json`);
    if (!r.ok) return roadJson || [];
    const body = await r.json();
    roadJson = Array.isArray(body && body.items) ? body.items : [];
    roadJsonAt = Date.now();
  } catch (err) {
    return roadJson || [];        // 예전 것이라도 있으면 그것을 쓴다
  }
  return roadJson;
}

/** 가까운 두 점 사이 거리(m). 한반도 위도에서는 평면으로 봐도 된다. */
function metresBetween(aLat, aLon, bLat, bLon) {
  const k = Math.cos(((aLat + bLat) / 2) * Math.PI / 180);
  return Math.hypot((bLat - aLat) * 111320, (bLon - aLon) * 111320 * k);
}

/** 점에서 선분까지(m). 꼭짓점 거리만 재면 긴 선분 가운데가 멀게 나온다. */
function metresToSeg(lat, lon, a, b) {
  const k = Math.cos((lat * Math.PI) / 180);
  const px = lon * k; const py = lat;
  const ax = a[1] * k; const ay = a[0];
  const bx = b[1] * k; const by = b[0];
  const dx = bx - ax; const dy = by - ay;
  if (dx === 0 && dy === 0) return metresBetween(lat, lon, a[0], a[1]);
  let t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy);
  t = Math.max(0, Math.min(1, t));
  return Math.hypot((px - (ax + t * dx)) * 111320,
                    (py - (ay + t * dy)) * 111320);
}

/** 지번표기('448도' · '산54-1 도')의 **끝 글자가 지목**이다. */
function jimokOf(label) {
  const m = String(label || "").trim().match(/([가-힣]+)$/);
  return m ? m[1] : null;
}

/** 선분 묶음을 감싸는 네모를 띠만큼 넓힌다. */
function padBox(segs, band) {
  let s = 90; let w = 180; let n = -90; let e = -180;
  for (const [a, b] of segs) {
    s = Math.min(s, a[0], b[0]); n = Math.max(n, a[0], b[0]);
    w = Math.min(w, a[1], b[1]); e = Math.max(e, a[1], b[1]);
  }
  const dLat = band / 111320;
  const dLon = band / (111320 * Math.cos(((s + n) / 2) * Math.PI / 180) || 1);
  return [w - dLon, s - dLat, e + dLon, n + dLat];
}

/** 이 칸을 지나는 선분들을 200m 어치씩 묶는다. */
function roadChunks(items, box) {
  const [w, s, e, n] = box;
  const dLat = ROAD_BAND_M / 111320;
  const dLon = ROAD_BAND_M / (111320 * Math.cos(((s + n) / 2) * Math.PI / 180) || 1);
  const out = [];
  for (const it of items) {
    const path = it.path;
    if (!Array.isArray(path) || path.length < 2) continue;
    let cur = []; let len = 0;
    const flush = () => {
      if (cur.length) out.push({ it, segs: cur });
      cur = []; len = 0;
    };
    for (let i = 0; i + 1 < path.length; i += 1) {
      const a = path[i]; const b = path[i + 1];
      // 이 선분의 네모가 칸(띠만큼 넓힌)과 안 겹치면 건너뛴다.
      if (Math.max(a[0], b[0]) < s - dLat || Math.min(a[0], b[0]) > n + dLat
          || Math.max(a[1], b[1]) < w - dLon || Math.min(a[1], b[1]) > e + dLon) {
        flush();
        continue;
      }
      cur.push([a, b]);
      len += metresBetween(a[0], a[1], b[0], b[1]);
      if (len >= ROAD_CHUNK_M) flush();
    }
    flush();
  }
  return out;
}

/** 고속도로가 깔린(또는 깔릴) **필지**를 그 칸 몫만큼 돌려준다. */
async function roadParcels(req, res) {
  const z = whole(String(req.query.z ?? ""));
  const y = whole(String(req.query.y ?? ""));
  const x = whole(String(req.query.x ?? ""));
  if (z === null || y === null || x === null) {
    return fail(res, 400, "z·y·x 가 0 이상의 정수여야 합니다");
  }
  if (z < ROAD_PARCEL_MIN_ZOOM || z > MAX_ZOOM) {
    return fail(res, 400,
      `z 는 ${ROAD_PARCEL_MIN_ZOOM}~${MAX_ZOOM} 이어야 합니다`);
  }
  const span = 2 ** z;
  if (y >= span || x >= span) return fail(res, 400, "그 배율의 격자 밖입니다");
  const box = degBbox(z, x, y);
  const [w, s, e, n] = box;
  if (n < KOREA.latMin || s > KOREA.latMax
      || e < KOREA.lonMin || w > KOREA.lonMax) {
    return sendRoadParcels(res, [], true);
  }
  const items = await roadItems();
  const chunks = roadChunks(items, box);
  // 고속도로가 안 지나는 칸이면 브이월드를 아예 안 부른다. 화면은 칸마다
  // 부르므로 이 갈래가 대부분이다 — 여기서 값이 갈린다.
  if (!chunks.length) return sendRoadParcels(res, [], true);
  const use = chunks.slice(0, ROAD_CHUNK_MAX);
  const host = (req.headers || {}).host;
  const got = await Promise.all(use.map(async (c) => {
    const out = await callVworld({
      SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
      TYPENAME: PARCEL_VEC_TYPENAME,
      BBOX: padBox(c.segs, ROAD_BAND_M).join(","),
      SRSNAME: "EPSG:4326", OUTPUT: "application/json",
      MAXFEATURES: String(ROAD_PARCEL_MAX), RESULTTYPE: "results",
      DOMAIN: process.env.VWORLD_REFERER || `https://${host || "toji.fyi"}/`,
    }, VWORLD_WFS, host);
    if (out.keyMissing) return { err: "key" };
    if (!out.upstream) return { err: out.timedOut ? "timeout" : "call" };
    try {
      const body = await out.upstream.json();
      return { c, feats: Array.isArray(body && body.features) ? body.features : [] };
    } catch (err) {
      return { err: "notjson" };
    }
  }));
  const bad = got.find((g) => g.err);
  if (bad) {
    if (bad.err === "key") {
      return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
    }
    if (bad.err === "timeout") {
      return fail(res, 504, `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`);
    }
    return fail(res, bad.err === "call" ? 502 : 502,
      bad.err === "call" ? "브이월드 호출 실패"
                         : "브이월드가 필지 목록 대신 다른 것을 줬습니다");
  }
  const seen = new Set();
  const out = [];
  for (const g of got) {
    for (const f of g.feats) {
      const geom = round6((f || {}).geometry);
      if (!geom) continue;
      const ring = outerRing(geom);
      if (!ring.length) continue;
      // 띠 밖이면 버린다. 필지의 **가장 가까운 꼭짓점**으로 잰다 —
      // 가운데로 재면 길쭉한 도로 필지가 멀게 나온다.
      let near = Infinity;
      for (const c of ring) {
        for (const [a, b] of g.c.segs) {
          const d = metresToSeg(Number(c[1]), Number(c[0]), a, b);
          if (d < near) near = d;
          if (near <= ROAD_BAND_M) break;
        }
        if (near <= ROAD_BAND_M) break;
      }
      if (near > ROAD_BAND_M) continue;
      const src = (f || {}).properties || {};
      const label = src.lnm_lndcgr_smbol || src.jibun || "";
      const key = src.pnu || JSON.stringify(firstPoint(geom));
      if (seen.has(key)) continue;
      seen.add(key);
      const jimok = jimokOf(label);
      out.push({
        g: geom,
        b: String(label),
        j: jimok,
        // 지목이 '도' 면 이미 도로가 된 땅, 아니면 **아직 편입 전**이다.
        r: jimok === "도" ? 1 : 0,
        s: String(g.c.it.name || ""),
        t: String(g.c.it.stage || ""),
      });
    }
  }
  return sendRoadParcels(res, out, chunks.length <= ROAD_CHUNK_MAX);
}

/** 다각형의 바깥 고리. 구멍은 거리 재기에 안 쓴다. */
function outerRing(geom) {
  const t = (geom || {}).type;
  const cs = (geom || {}).coordinates || [];
  if (t === "Polygon") return cs[0] || [];
  if (t === "MultiPolygon") return (cs[0] || [])[0] || [];
  return [];
}

function sendRoadParcels(res, items, whole_) {
  res.setHeader("cache-control", CACHE_OK);
  return res.status(200).json({ n: items.length, whole: whole_, items });
}

function sendLines(res, geoms, whole_) {
  res.setHeader("cache-control", CACHE_OK);
  return res.status(200).json({ n: geoms.length, whole: whole_, geoms });
}

/** 타일 한 칸을 위경도 네모로. (서, 남, 동, 북) */
function degBbox(z, x, y) {
  const n = 2 ** z;
  const lon = (i) => (i / n) * 360 - 180;
  const lat = (j) => {
    const t = Math.PI * (1 - (2 * j) / n);
    return (Math.atan(Math.sinh(t)) * 180) / Math.PI;
  };
  return [lon(x), lat(y + 1), lon(x + 1), lat(y)];
}

async function parcelInfo(req, res) {
  const lat = decimal(String(req.query.lat ?? ""));
  const lon = decimal(String(req.query.lon ?? ""));
  if (lat === null || lon === null) return fail(res, 400, "lat·lon 이 필요합니다");
  if (lat < KOREA.latMin || lat > KOREA.latMax ||
      lon < KOREA.lonMin || lon > KOREA.lonMax) {
    return fail(res, 400, "한반도 밖입니다");
  }
  const h = PARCEL_HALF_DEG;
  const out = await callVworld({
    // **1.1.0 이다.** 2.0.0 으로 부르면 HTTP 400 이 온다 — 필지 조회가
    // 라이브에서 통째로 죽어 있었다 (2026-09-10 실측).
    //
    // 브이월드 WFS 는 GeoServer 이고 GetCapabilities 가 스스로
    // version="1.1.0" 이라고 말한다. 우리는 2.0.0 이라고 말하면서
    // 파라미터는 1.1.0 이름(TYPENAME·MAXFEATURES)으로 보내고 있었다.
    // GeoServer 가 그 조합에서 내부 오류를 낸다:
    //
    //   400  ows:ExceptionReport exceptionCode="NoApplicableCode"
    //        java.lang.Runti…
    //
    // 그렇다고 2.0.0 표준 철자(TYPENAMES·COUNT)로 바꿔도 안 된다.
    // 브이월드는 그 이름을 모른다:
    //
    //   PARAM_REQUIRED  필수 파라미터인 TYPENAME가 없어서…
    //
    // 즉 이 서비스에는 1.1.0 한 길뿐이다. (scripts/parcel_probe.py 로
    // 언제든 다시 잰다.)
    SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
    // 지구·구역을 **같은 요청에** 담는다. 따로 부르면 클릭당 호출이
    // 열둘이 된다 — 쉼표로 담으면 그대로 하나다.
    TYPENAME: [PARCEL_TYPENAME].concat(PARCEL_ZONE_NAMES).join(","),
    BBOX: [lon - h, lat - h, lon + h, lat + h].join(","),
    SRSNAME: "EPSG:4326",
    // GML 로 요청하면 중계기가 죽는다 (docs/land-price-fallback.md).
    OUTPUT: "application/json",
    MAXFEATURES: PARCEL_MAXFEATURES, RESULTTYPE: "results",
    DOMAIN: process.env.VWORLD_REFERER
      || `https://${(req.headers || {}).host || "toji.fyi"}/`,
  }, VWORLD_WFS, (req.headers || {}).host);
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`
                   : "브이월드 호출 실패");
  }
  const upstream = out.upstream;
  const type = upstream.headers.get("content-type") || "";
  const text = await upstream.text();
  // 한도 초과·키 오류는 JSON 이 아니라 XML 로 온다. 본문을 그대로 돌려주면
  // 안 된다 — 우리가 보낸 요청 URL 이 실려 오고 거기에 인증키가 붙어 있다.
  if (!upstream.ok || /xml/i.test(type)) {
    return fail(res, 502, `브이월드가 필지를 주지 않았습니다 (HTTP ${upstream.status})`);
  }
  let feats = [];
  try {
    feats = (JSON.parse(text) || {}).features || [];
  } catch (e) {
    return fail(res, 502, "브이월드 응답을 읽지 못했습니다");
  }
  // 어느 층에서 왔는지는 feature id 앞머리로 갈린다 (lt_c_um000.57606).
  const layerOf = (f) => String((f || {}).id || "").split(".")[0];
  // **누른 점을 품는 필지**를 고른다. bbox 로 부르면 이웃이 같이 온다.
  const hit = feats.find((f) => layerOf(f) === PARCEL_TYPENAME
                                && hitsPoint(f.geometry, lon, lat))
    // id 가 없는 응답도 있었다. 그때는 예전처럼 아무거나 품는 것을 쓴다.
    || feats.find((f) => hitsPoint(f.geometry, lon, lat)) || null;
  res.setHeader("cache-control", hit ? CACHE_OK : CACHE_BAD);
  if (!hit) return res.status(200).json({ parcel: null });
  const props = hit.properties || {};
  const parcel = {};
  for (const [ours, theirs] of Object.entries(PARCEL_FIELDS)) {
    const v = props[theirs];
    parcel[ours] = v === undefined || v === "" ? null : v;
  }
  for (const num of ["area_m2", "official_price"]) {
    const n = Number(parcel[num]);
    parcel[num] = Number.isFinite(n) ? n : null;
  }
  // **도형도 싣는다** (요구사항 2026-09-10 — 부동산플래닛처럼 윤곽).
  //
  // 예전에는 안 실었다. "응답이 수십 KB로 커지는데 화면은 쓰지 않는다"
  // 고 적어 뒀는데, 이제 화면이 그것을 그린다. 무겁던 이유는 도형 자체가
  // 아니라 **좌표의 소수점**이었다 — 브이월드는 15자리까지 준다.
  //
  //   127.123456789012345  →  20자
  //   127.123457           →  10자   (6자리 = 지상 약 11cm)
  //
  // 필지 하나가 꼭짓점 수십 개이므로 자리를 줄이면 절반 아래로 내려간다.
  // 11cm 보다 정밀한 윤곽은 화면에서 한 픽셀 안이라 뜻이 없다.
  // 주소와 지번은 이 표에 없다. 연속지적도가 addr 로 준다. 두 번째
  // 호출이지만 첫 호출이 성공한 뒤에만 하고, 실패해도 카드는 뜬다 —
  // 주소가 없다고 필지 정보를 통째로 버릴 이유는 없다.
  // 겹친 지구·구역. 같은 층이 여러 조각으로 와도 한 줄로 묶는다.
  const zones = [];
  const seen = new Set();
  for (const f of feats) {
    const layer = layerOf(f);
    const meta = PARCEL_ZONES[layer];
    if (!meta || seen.has(layer)) continue;
    if (!hitsPoint(f.geometry, lon, lat)) continue;
    seen.add(layer);
    const props = f.properties || {};
    const detail = ZONE_DETAIL_KEYS
      .map((k) => props[k]).find((v) => v !== undefined && v !== "") || null;
    zones.push({ label: meta.label, note: meta.note, detail });
  }

  const addr = await parcelAddress(req, lon, lat, parcel.jimok);
  res.status(200).json({ parcel, addr, zones, geom: round6(hit.geometry) });
}

/** 누른 자리의 주소. 지번은 늘, 도로명은 있으면.
 *
 * 도로명주소는 **건물이 있는 곳에만** 붙는다. 실측에서 두 곳 모두
 * type=ROAD 가 NOT_FOUND 였다 (광주 지월리 답, 안성 승두리 대).
 * 그래서 지번을 주인공으로 두고 도로명은 있을 때만 덧붙인다 —
 * 없는 것을 '조회 실패' 로 보여주면 고장으로 읽힌다.
 */
// 도로명주소가 붙는 땅. 건물이 서는 지목만이다.
//
// 실측(2026-09-10, scripts/parcel_fields_probe.py): 열 곳 중 두 곳
// (20%)만 도로명이 나왔고, 그 둘은 강남파이낸스센터와 네이버
// 그린팩토리였다. 답·전·임야·과수원은 전부 '없음' 이었다.
//
// 필지를 한 번 누를 때마다 브이월드를 세 번 부르는데 셋째가 이것이다.
// 여든 번은 헛걸음이었다. **나올 수 있는 땅에만 묻는다** — 관측된
// 두 건이 모두 '대' 였으므로 걸러도 놓치는 것이 없다.
const ROAD_JIMOK = new Set([
  "대", "공장용지", "창고용지", "학교용지", "주차장", "주유소용지",
  "종교용지", "의료용지", "체육용지", "수도용지", "철도용지",
]);

async function parcelAddress(req, lon, lat, jimok) {
  const host = (req.headers || {}).host;
  const domain = process.env.VWORLD_REFERER || `https://${host || "toji.fyi"}/`;
  const out = { jibun: null, road: null, sido: null, sigungu: null,
                umd: null, ri: null, jiga: null, gosi: null };

  const h = PARCEL_HALF_DEG;
  const [land, road] = await Promise.all([
    callVworld({
      SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
      TYPENAME: PARCEL_ADDR_TYPENAME,
      BBOX: [lon - h, lat - h, lon + h, lat + h].join(","),
      SRSNAME: "EPSG:4326", OUTPUT: "application/json",
      MAXFEATURES: PARCEL_MAXFEATURES, RESULTTYPE: "results", DOMAIN: domain,
    }, VWORLD_WFS, host),
    ROAD_JIMOK.has(String(jimok || "").trim())
      ? callVworld({
          service: "address", request: "getAddress", version: "2.0",
          crs: "epsg:4326", point: `${lon},${lat}`, type: "ROAD",
          format: "json", simple: "false",
        }, VWORLD_ADDRESS, host)
      : null,
  ]);

  try {
    if (land && land.upstream && land.upstream.ok) {
      const body = JSON.parse(await land.upstream.text()) || {};
      const hit = (body.features || [])
        .find((f) => hitsPoint(f.geometry, lon, lat));
      const p = (hit || {}).properties || {};
      for (const [ours, theirs] of Object.entries(PARCEL_ADDR_FIELDS)) {
        const v = p[theirs];
        if (v !== undefined && v !== "") out[ours === "addr" ? "jibun" : ours] = v;
      }
      if (out.gosi_year) {
        out.gosi = `${out.gosi_year}.${out.gosi_month || ""}`.replace(/\.$/, "");
      }
      delete out.gosi_year; delete out.gosi_month;
    }
  } catch (e) { /* 주소가 없어도 카드는 뜬다. */ }

  try {
    if (road && road.upstream && road.upstream.ok) {
      const body = JSON.parse(await road.upstream.text()) || {};
      const items = (((body.response || {}).result) || []);
      const one = items.find((i) => i && i.text);
      // NOT_FOUND 는 오류가 아니다 — 그 땅에 도로명이 안 붙었을 뿐이다.
      if (one) out.road = one.text;
    }
  } catch (e) { /* 위와 같다. */ }

  return out;
}

/** 좌표의 소수점을 여섯 자리로. 도형 구조는 그대로 둔다. */
function round6(geom) {
  if (!geom) return null;
  const cut = (v) => (Array.isArray(v) ? v.map(cut) : Math.round(v * 1e6) / 1e6);
  return { type: geom.type, coordinates: cut(geom.coordinates) };
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return fail(res, 405, "GET 만 허용합니다");

  // 속도 제한을 **맨 앞에** 둔다. 뒤에 두면 이미 브이월드를 부른
  // 뒤가 된다. 필지 조회는 캐시가 안 먹고 한 번에 두세 번 나가므로
  // 따로, 더 좁게 본다.
  const mode = String(req.query.mode || "");
  // 주소 → 좌표도 필지 조회와 같은 좁은 한도다 — 같은 브이월드 키의 하루
  // 한도(지오코딩 3만 건)를 쓴다.
  if (overRate(req, (mode === "parcel" || mode === "geocode" || mode === "pnu") ? RATE_LIMIT_PARCEL : RATE_LIMIT)) {
    return tooMany(res);
  }
  // 주소를 치면 그 필지로 간다 (요구사항 2026-09-11). 레이어와 무관하다.
  if (mode === "geocode") {
    return geocode(req, res);
  }
  // 지번 → PNU → 연속지적도에서 그 필지 하나. 지오코더가 모르는 땅도 찾는다.
  if (mode === "pnu") {
    return parcelByPnu(req, res);
  }

  const want = String(req.query.layer || "zoning");
  const layers = LAYERS[want];
  const basemap = BASEMAPS[want];
  if (!layers && !basemap) return fail(res, 400, "그런 레이어가 없습니다");
  // 어느 층이 함수를 돌리는지 세려고 한 줄 남긴다 (좌표는 안 적는다 —
  // 로그에 사람이 본 자리를 남길 이유가 없다). Vercel 로그 검색:
  // "tile kind=" 로 층별 호출 수를 센다.
  console.log(`tile kind=${mode || want} z=${String(req.query.z ?? "-")}`);

  // 누른 자리의 이름을 묻는 요청. 같은 화이트리스트를 쓰고, 목적지도
  // 좌표계도 여기서 정한다 — 밖에서 받는 것은 위경도뿐이다.
  if (mode === "info") {
    return featureInfo(req, res, layers);
  }
  // 누른 자리의 필지 특성. 레이어 화이트리스트와 무관한 다른 서비스라
  // 위의 layers 를 쓰지 않는다.
  if (mode === "parcel") {
    return parcelInfo(req, res);
  }
  // 화면에 미리 깔리는 경계선. 한 칸씩 준다.
  if (mode === "parcels") {
    return parcelLines(req, res);
  }
  // 누른 자리가 속한 행정구역 한 덩이.
  if (mode === "admin") {
    return adminShape(req, res);
  }
  // 개발 층을 도형으로 — 화면이 완공된 것을 걸러 낼 수 있게.
  if (mode === "devvec") {
    return developShapes(req, res);
  }
  // 고속도로를 선이 아니라 **필지**로 (2026-09-16 지시).
  if (mode === "roadparcels") {
    return roadParcels(req, res);
  }

  const z = whole(String(req.query.z ?? ""));
  const y = whole(String(req.query.y ?? ""));
  const x = whole(String(req.query.x ?? ""));
  if (z === null || y === null || x === null) {
    return fail(res, 400, "z·y·x 가 0 이상의 정수여야 합니다");
  }
  if (z > MAX_ZOOM) return fail(res, 400, `z 는 ${MAX_ZOOM} 이하여야 합니다`);
  // 배율 z 에서 격자는 한 변이 2^z 이다. 그 밖을 부르면 브이월드에
  // 헛일을 시키는 것이므로 여기서 끊는다.
  const span = 2 ** z;
  if (y >= span || x >= span) return fail(res, 400, "그 배율의 격자 밖입니다");

  if (basemap) return sendTile(res, await callWmts(
    basemap, z, y, x, (req.headers || {}).host));

  const out = await callVworld({
    SERVICE: "WMS", REQUEST: "GetMap", VERSION: "1.3.0",
    LAYERS: layers, STYLES: "",
    CRS: "EPSG:3857",              // SRS 로 보내면 빈 그림이 온다
    BBOX: mercBbox(z, x, y),
    WIDTH: "256", HEIGHT: "256",
    FORMAT: "image/png", TRANSPARENT: "true",
  }, null, (req.headers || {}).host);
  return sendTile(res, out);
};

/* ── 주소 → 좌표 (요구사항 2026-09-11: "주소 입력 시 해당 필지로 이동") ──
 *
 * 브이월드 지오코더(req/address getcoord). 지번(PARCEL)로 먼저 묻고 없으면
 * 도로명(ROAD)으로 다시 묻는다 — 사람은 둘을 섞어 친다. 수집 파이프라인
 * (src/redt/collect/geocode.py)과 같은 호출이라 응답 모양도 같다:
 *
 *   response.status  OK | NOT_FOUND | ERROR
 *   response.result.point.{x,y}   경도, 위도 (epsg:4326)
 *
 * 찾은 주소는 길게 캐시한다 — 주소는 움직이지 않는다. 못 찾은 것은 짧게.
 * 키는 응답에 싣지 않는다 (url 을 오류 문구에 넣지 않는다). */
const GEOCODE_MAX_LEN = 80;

async function geocode(req, res) {
  const q = String(req.query.q || "").replace(/\s+/g, " ").trim();
  if (!q || q.length > GEOCODE_MAX_LEN || /[<>\n\r\t]/.test(q)) {
    return fail(res, 400, `q(주소)가 필요합니다 (${GEOCODE_MAX_LEN}자 이내)`);
  }
  const host = (req.headers || {}).host;
  for (const type of ["PARCEL", "ROAD"]) {
    const out = await callVworld({
      service: "address", request: "getcoord", version: "2.0",
      crs: "epsg:4326", type, address: q, format: "json",
    }, VWORLD_ADDRESS, host);
    if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
    if (!out.upstream) {
      return fail(res, out.timedOut ? 504 : 502,
        out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)` : "브이월드 호출 실패");
    }
    let body;
    try { body = JSON.parse(await out.upstream.text()); }
    catch (err) { return fail(res, 502, "브이월드 지오코더가 JSON 을 주지 않았습니다"); }
    const r = (body || {}).response || {};
    if (r.status === "OK") {
      const pt = ((r.result || {}).point) || {};
      const lat = Number(pt.y);
      const lon = Number(pt.x);
      if (Number.isFinite(lat) && Number.isFinite(lon)) {
        res.setHeader("cache-control", CACHE_OK);
        return res.status(200).json({
          lat, lon, type,
          text: ((r.refined || {}).text) || q,
        });
      }
      return fail(res, 502, "OK 인데 좌표 칸을 못 읽었습니다 — 응답 모양 확인");
    }
    if (r.status !== "NOT_FOUND") {
      // ERROR — 한도 초과·인증·장애. 사용자 잘못이 아니다.
      const code = ((r.error || {}).code) || r.status || "?";
      return fail(res, 502, `브이월드 지오코더 오류 (${code})`);
    }
  }
  return fail(res, 404, "주소를 찾지 못했습니다 — 시·군과 읍·면·동을 함께 적어 주세요");
}

/* ── PNU 로 필지 하나 (요구사항 2026-09-11: 주소 → 그 필지) ──
 *
 * 지오코더(req/address)는 주소 DB 기반이라 **건물 없는 땅의 지번을 모른다**
 * (실측 2026-09-11: 건업리 140 → '140-1' 로 뭉개고, 없는 지번은 NOT_FOUND).
 * 땅을 보는 서비스에는 연속지적도가 원천이다. 화면이 법정동코드(명부)와
 * 지번으로 PNU 를 만들어 오면, 연속지적도(lp_pa_cbnd_bubun)를 **OGC 필터**로
 * 걸러 그 필지 하나를 받는다.
 *
 *   PNU = 법정동코드(10) + 대장구분(1: 토지 1 · 임야(산) 2) + 본번(4) + 부번(4)
 *
 * 탐침(scripts/pnu_probe.py, 2026-09-11 러너): FILTER(OGC PropertyIsEqualTo)만
 * 먹는다. CQL_FILTER 와 임의 파라미터는 조용히 무시되어 **엉뚱한 첫 다섯
 * 필지**가 온다 — 그 길로 만들면 늘 거창군 장기리가 나온다. FEATUREID 는
 * 0개. 그래서 FILTER 하나만 쓴다. 찾은 필지는 길게 캐시한다. */
const PNU_RE = /^\d{19}$/;

function geomCenter(geom) {
  // 좌표 전체의 경계상자 가운데. 필지는 작고 볼록한 편이라 이것으로 족하다
  // — 다음 단계(askParcel)가 이 점으로 필지를 다시 물어 카드를 연다.
  let w = Infinity; let s2 = Infinity; let e = -Infinity; let n = -Infinity;
  const walk = (v) => {
    if (!Array.isArray(v)) return;
    if (v.length >= 2 && typeof v[0] === "number" && typeof v[1] === "number") {
      w = Math.min(w, v[0]); e = Math.max(e, v[0]);
      s2 = Math.min(s2, v[1]); n = Math.max(n, v[1]);
      return;
    }
    v.forEach(walk);
  };
  walk((geom || {}).coordinates);
  if (!Number.isFinite(w) || !Number.isFinite(n)) return null;
  return { lat: (s2 + n) / 2, lon: (w + e) / 2 };
}

async function parcelByPnu(req, res) {
  const pnu = String(req.query.pnu || "").trim();
  if (!PNU_RE.test(pnu)) return fail(res, 400, "pnu 는 19자리 숫자여야 합니다");
  const host = (req.headers || {}).host;
  const out = await callVworld({
    SERVICE: "WFS", REQUEST: "GetFeature", VERSION: "1.1.0",
    TYPENAME: PARCEL_VEC_TYPENAME,
    FILTER: "<Filter><PropertyIsEqualTo><PropertyName>pnu</PropertyName>"
      + `<Literal>${pnu}</Literal></PropertyIsEqualTo></Filter>`,
    SRSNAME: "EPSG:4326", OUTPUT: "application/json",
    MAXFEATURES: "2", RESULTTYPE: "results",
    DOMAIN: process.env.VWORLD_REFERER || `https://${host || "toji.fyi"}/`,
  }, VWORLD_WFS, host);
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)` : "브이월드 호출 실패");
  }
  let body;
  try { body = await out.upstream.json(); }
  catch (err) { return fail(res, 502, "브이월드가 필지 대신 다른 것을 줬습니다"); }
  const feats = Array.isArray(body && body.features) ? body.features : [];
  // 필터가 무시되면 엉뚱한 필지가 온다 — pnu 가 같은 것만 믿는다.
  const hit = feats.find((f) => String(((f || {}).properties || {}).pnu || "") === pnu);
  if (!hit) return fail(res, 404, "그 지번의 필지가 연속지적도에 없습니다");
  const geom = round6(hit.geometry);
  const c = geomCenter(geom);
  if (!c) return fail(res, 502, "필지 도형을 읽지 못했습니다");
  res.setHeader("cache-control", CACHE_OK);
  return res.status(200).json({
    pnu, addr: (hit.properties || {}).addr || null,
    lat: Math.round(c.lat * 1e6) / 1e6, lon: Math.round(c.lon * 1e6) / 1e6, geom,
  });
}

/** 브이월드가 준 것을 그림으로 돌려준다. 배경도 용도지역도 여기를 지난다. */
async function sendTile(res, out) {
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    // 오류 문구에 url 을 넣지 않는다 — 인증키가 붙어 있어 그대로 새어나간다.
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`
                   : "브이월드 호출 실패");
  }
  const upstream = out.upstream;
  const type = upstream.headers.get("content-type") || "";
  // 한도 초과·키 오류는 PNG 가 아니라 XML 로 온다. 그것을 그림인 척
  // 돌려주면 지도에 깨진 이미지가 뜨고 원인을 알 수 없다.
  if (!upstream.ok || !/^image\//i.test(type)) {
    return fail(res, 502,
      `브이월드가 그림을 주지 않았습니다 (HTTP ${upstream.status}, ${type || "타입 없음"})`);
  }
  const buf = Buffer.from(await upstream.arrayBuffer());
  res.setHeader("content-type", type);
  res.setHeader("cache-control", CACHE_OK);
  res.status(200).send(buf);
}

// 검사가 bbox 계산을 직접 확인할 수 있게 내보낸다. 이 계산이 틀리면
// 그림은 오는데 땅이 어긋난다 — 눈으로는 잡기 어려운 종류다.
module.exports.mercBbox = mercBbox;
module.exports.LAYERS = LAYERS;
// 검사가 창을 비우고 시작할 수 있게. **여기여야 한다** — 위에 두면
// module.exports = handler 가 통째로 덮어써 사라진다.
module.exports.__resetRate = () => rateHits.clear();
// 검사가 버킷에서 받은 road.json 을 비운다. 안 비우면 앞 절이 받아 둔
// 것을 뒤 절이 그대로 써서, 고치지도 않은 검사가 갑자기 빨개진다.
module.exports.__resetRoad = () => { roadJson = null; roadJsonAt = 0; };
module.exports.jimokOf = jimokOf;
module.exports.BASEMAPS = BASEMAPS;
module.exports.hitsPoint = hitsPoint;
module.exports.PARCEL_FIELDS = PARCEL_FIELDS;
// 파서도 검사가 직접 확인한다. 응답 모양이 바뀌면 화면에 이름이
// 안 뜨는데, 오류가 아니라 빈 값으로 조용히 나타난다.
module.exports.parseInfo = parseInfo;
