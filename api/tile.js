// 용도지역 지도 타일 중계 — 네이버 지적편집도의 그 화면.
//
// 한국 **법정** 용도지역(계획관리·생산관리·자연녹지…)은 OSM 에 없다.
// 국토교통부 자료이고 브이월드에서만 온다.
//
// 왜 브라우저가 브이월드를 직접 부르지 않는가
// -------------------------------------------
// 그러려면 인증키를 페이지에 적어야 한다. 그 키는 지금 실거래 지오코딩에
// 쓰는 **하루 3만 건짜리 자원**이고, 이 프로젝트에서 가장 자주 병목이
// 되는 것이다(오늘도 그것 때문에 수집이 한 번 멈췄다). 누가 대신 써버리면
// 수집이 선다. 키는 서버에만 둔다는 원칙을 여기서 깨지 않는다.
//
// relay.js 를 쓰지 않는 이유
// --------------------------
// 그쪽은 서버끼리 쓰는 창구다. 공유 토큰을 헤더로 요구하고, 바이너리를
// base64 로 감싸 보낸다. <img> 태그는 헤더를 붙일 수 없고 base64 문자열을
// 그림으로 읽지도 못한다. 그래서 브라우저용으로 따로 둔다.
//
// 열린 중계기가 되지 않게
// -----------------------
// target 을 받지 않는다. z/x/y 와 미리 정한 레이어 이름만 받아 주소를
// 우리가 만든다. 그래서 이 경로로는 브이월드의 그 레이어 말고 아무것도
// 부를 수 없다. relay.js 는 목적지를 받으므로 토큰이 필요했지만, 여기는
// 부를 수 있는 곳이 하나뿐이라 토큰 없이도 열린 중계기가 되지 않는다.
//
// 캐시
// ----
// 타일은 한 화면에 수십 장이 뜨고, 같은 자리를 다시 보면 같은 그림이다.
// 용도지역은 자주 바뀌는 자료가 아니므로 길게 캐시한다. Vercel CDN 이
// 반복 요청을 대신 받아주므로 함수 호출도, 브이월드 호출도 줄어든다.

const LAYERS = {
  // 용도지역. 지적편집도에서 색으로 칠해지는 그 면이다.
  zoning: "LT_C_UQ111",
};

const MAX_ZOOM = 19;
const TIMEOUT_MS = 10_000;
// 성공한 타일은 하루, CDN 에는 한 주. 실패는 짧게만 — 키를 넣거나
// 한도가 풀린 뒤에 빈 화면이 오래 남으면 안 된다.
const CACHE_OK = "public, max-age=86400, s-maxage=604800";
const CACHE_BAD = "public, max-age=0, s-maxage=60";

function fail(res, code, message) {
  res.setHeader("cache-control", CACHE_BAD);
  res.status(code).json({ tileError: message });
}

/** 정수인지 본다. '01' · '1.5' · '1e3' 같은 것을 통과시키면 안 된다. */
function whole(value) {
  if (typeof value !== "string" || !/^\d{1,7}$/.test(value)) return null;
  return Number(value);
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return fail(res, 405, "GET 만 허용합니다");

  const layer = LAYERS[String(req.query.layer || "zoning")];
  if (!layer) return fail(res, 400, "그런 레이어가 없습니다");

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

  const key = process.env.VWORLD_KEY;
  if (!key) return fail(res, 503, "VWORLD_KEY 가 설정되지 않았습니다");

  // 브이월드 키는 '웹사이트' 유형으로 서비스URL 이 등록돼 있다. 서버에서
  // 부르면 브라우저처럼 Referer 가 안 붙으므로 등록된 주소를 실어 보낸다
  // (relay.js 가 같은 이유로 같은 값을 쓴다).
  const referer = process.env.VWORLD_REFERER || "https://sado-toji.vercel.app/";
  const url = `https://api.vworld.kr/req/wmts/1.0.0/${encodeURIComponent(key)}`
            + `/${layer}/${z}/${y}/${x}.png`;

  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    const upstream = await fetch(url, {
      signal: stop.signal,
      redirect: "manual",
      headers: { "User-Agent": "redt-tile/1.0", Accept: "image/png,*/*", Referer: referer },
    });
    const type = upstream.headers.get("content-type") || "";
    // 한도 초과·키 오류는 PNG 가 아니라 JSON·HTML 로 온다. 그것을 그림인
    // 척 돌려주면 지도에 깨진 이미지가 뜨고 원인을 알 수 없다.
    if (!upstream.ok || !/^image\//i.test(type)) {
      return fail(res, 502,
        `브이월드가 그림을 주지 않았습니다 (HTTP ${upstream.status}, ${type || "타입 없음"})`);
    }
    const buf = Buffer.from(await upstream.arrayBuffer());
    res.setHeader("content-type", type);
    res.setHeader("cache-control", CACHE_OK);
    res.status(200).send(buf);
  } catch (err) {
    const timedOut = err && err.name === "AbortError";
    // 오류 문구에 url 을 넣지 않는다 — 인증키가 붙어 있어 그대로 새어나간다.
    fail(res, timedOut ? 504 : 502,
         timedOut ? `브이월드 응답 없음 (${TIMEOUT_MS / 1000}초 초과)` : "브이월드 호출 실패");
  } finally {
    clearTimeout(timer);
  }
};
