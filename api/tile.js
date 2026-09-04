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

// 화면에 깔 수 있는 것. 목적지를 받지 않고 이 표에서만 고른다.
const LAYERS = {
  // 용도지역 네 장을 한 번에. 지적편집도에서 색으로 칠해지는 그 면이다.
  zoning: "lt_c_uq111,lt_c_uq112,lt_c_uq113,lt_c_uq114",
  // 필지 경계선. 색면 위에 얹으면 '이 필지' 를 눈으로 짚을 수 있다.
  cadastral: "lp_pa_cbnd_bubun",
};

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
async function callVworld(params) {
  const key = process.env.VWORLD_KEY;
  if (!key) return { keyMissing: true };
  // 브이월드 키는 '웹사이트' 유형으로 서비스URL 이 등록돼 있다. WMS 는
  // 요청이 그 도메인에서 왔는지를 Referer 로 본다. 서버에서 부르면
  // 브라우저처럼 Referer 가 안 붙으므로 등록된 주소를 실어 보낸다
  // (api/relay.js 가 같은 이유로 같은 값을 쓴다).
  const referer = process.env.VWORLD_REFERER || "https://sado-toji.vercel.app/";
  const url = `${VWORLD_WMS}?` + new URLSearchParams({ ...params, key });
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
  });
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

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return fail(res, 405, "GET 만 허용합니다");

  const layers = LAYERS[String(req.query.layer || "zoning")];
  if (!layers) return fail(res, 400, "그런 레이어가 없습니다");

  // 누른 자리의 이름을 묻는 요청. 같은 화이트리스트를 쓰고, 목적지도
  // 좌표계도 여기서 정한다 — 밖에서 받는 것은 위경도뿐이다.
  if (String(req.query.mode || "") === "info") {
    return featureInfo(req, res, layers);
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

  const out = await callVworld({
    SERVICE: "WMS", REQUEST: "GetMap", VERSION: "1.3.0",
    LAYERS: layers, STYLES: "",
    CRS: "EPSG:3857",              // SRS 로 보내면 빈 그림이 온다
    BBOX: mercBbox(z, x, y),
    WIDTH: "256", HEIGHT: "256",
    FORMAT: "image/png", TRANSPARENT: "true",
  });
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
};

// 검사가 bbox 계산을 직접 확인할 수 있게 내보낸다. 이 계산이 틀리면
// 그림은 오는데 땅이 어긋난다 — 눈으로는 잡기 어려운 종류다.
module.exports.mercBbox = mercBbox;
module.exports.LAYERS = LAYERS;
// 파서도 검사가 직접 확인한다. 응답 모양이 바뀌면 화면에 이름이
// 안 뜨는데, 오류가 아니라 빈 값으로 조용히 나타난다.
module.exports.parseInfo = parseInfo;
