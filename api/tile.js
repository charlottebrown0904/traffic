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
const PARCEL_MAXFEATURES = "100";

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
// 한 칸에 이보다 많으면 자른다. z16 한 칸은 한 변 600m 남짓이라
// 도심이라도 이 안에서 끝난다. 상한이 없으면 서울 한복판에서
// 한 칸이 수백 KB 가 된다.
const PARCEL_VEC_MAX = 600;
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
const VWORLD_ADDRESS = "https://api.vworld.kr/req/address";

// 화면에 깔 수 있는 것. 목적지를 받지 않고 이 표에서만 고른다.
const LAYERS = {
  // 용도지역 네 장을 한 번에. 지적편집도에서 색으로 칠해지는 그 면이다.
  zoning: "lt_c_uq111,lt_c_uq112,lt_c_uq113,lt_c_uq114",
  // 필지 경계선. 색면 위에 얹으면 '이 필지' 를 눈으로 짚을 수 있다.
  cadastral: "lp_pa_cbnd_bubun",
};

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
// 성공한 타일은 하루, CDN 에는 한 주. 용도지역은 자주 바뀌는 자료가 아니다.
// 실패는 짧게만 — 한도가 풀린 뒤에도 빈 화면이 오래 남으면 안 된다.
const CACHE_OK = "public, max-age=86400, s-maxage=604800";
const CACHE_BAD = "public, max-age=0, s-maxage=60";

function fail(res, code, message) {
  res.setHeader("cache-control", CACHE_BAD);
  res.status(code).json({ tileError: message });
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
  if (out.keyMissing) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");
  if (!out.upstream) {
    return fail(res, out.timedOut ? 504 : 502,
      out.timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)`
                   : "브이월드 호출 실패");
  }
  let body;
  try {
    body = await out.upstream.json();
  } catch (err) {
    // 한도 초과·키 오류는 JSON 이 아니라 XML 로 온다. 그것을 빈
    // 목록인 척 돌려주면 '필지가 없는 동네' 로 읽힌다.
    return fail(res, 502, "브이월드가 필지 목록 대신 다른 것을 줬습니다");
  }
  const feats = Array.isArray(body && body.features) ? body.features : [];
  const geoms = [];
  for (const f of feats) {
    const g = round6((f || {}).geometry);
    if (g) geoms.push(g);
  }
  return sendLines(res, geoms, feats.length < PARCEL_VEC_MAX);
}

/** 선 목록을 돌려준다. 빈 칸도 캐시한다 — 바다는 늘 비어 있다. */
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
    TYPENAME: PARCEL_TYPENAME,
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
  // **누른 점을 품는 필지**를 고른다. bbox 로 부르면 이웃이 같이 온다.
  const hit = feats.find((f) => hitsPoint(f.geometry, lon, lat)) || null;
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
  const addr = await parcelAddress(req, lon, lat);
  res.status(200).json({ parcel, addr, geom: round6(hit.geometry) });
}

/** 누른 자리의 주소. 지번은 늘, 도로명은 있으면.
 *
 * 도로명주소는 **건물이 있는 곳에만** 붙는다. 실측에서 두 곳 모두
 * type=ROAD 가 NOT_FOUND 였다 (광주 지월리 답, 안성 승두리 대).
 * 그래서 지번을 주인공으로 두고 도로명은 있을 때만 덧붙인다 —
 * 없는 것을 '조회 실패' 로 보여주면 고장으로 읽힌다.
 */
async function parcelAddress(req, lon, lat) {
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
    callVworld({
      service: "address", request: "getAddress", version: "2.0",
      crs: "epsg:4326", point: `${lon},${lat}`, type: "ROAD",
      format: "json", simple: "false",
    }, VWORLD_ADDRESS, host),
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

  const want = String(req.query.layer || "zoning");
  const layers = LAYERS[want];
  const basemap = BASEMAPS[want];
  if (!layers && !basemap) return fail(res, 400, "그런 레이어가 없습니다");

  // 누른 자리의 이름을 묻는 요청. 같은 화이트리스트를 쓰고, 목적지도
  // 좌표계도 여기서 정한다 — 밖에서 받는 것은 위경도뿐이다.
  if (String(req.query.mode || "") === "info") {
    return featureInfo(req, res, layers);
  }
  // 누른 자리의 필지 특성. 레이어 화이트리스트와 무관한 다른 서비스라
  // 위의 layers 를 쓰지 않는다.
  if (String(req.query.mode || "") === "parcel") {
    return parcelInfo(req, res);
  }
  // 화면에 미리 깔리는 경계선. 한 칸씩 준다.
  if (String(req.query.mode || "") === "parcels") {
    return parcelLines(req, res);
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
module.exports.BASEMAPS = BASEMAPS;
module.exports.hitsPoint = hitsPoint;
module.exports.PARCEL_FIELDS = PARCEL_FIELDS;
// 파서도 검사가 직접 확인한다. 응답 모양이 바뀌면 화면에 이름이
// 안 뜨는데, 오류가 아니라 빈 값으로 조용히 나타난다.
module.exports.parseInfo = parseInfo;
