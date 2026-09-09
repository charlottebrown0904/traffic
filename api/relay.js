// 서울 리전(icn1) 중계기.
//
// 한국 공공 API 가 해외 IP 를 막는다 (docs/finding-geoblock.md).
// GitHub Actions 러너는 미국이라 직접 부를 수 없으므로, 서울에서 도는 이 함수가
// 대신 호출해 응답을 그대로 돌려준다.
//
// 인증키는 여기(Vercel 환경변수)에만 둔다. 호출하는 쪽은 키를 몰라도 되고,
// 알 필요도 없다.
//
// 열린 중계기가 되지 않도록 목적지 호스트를 화이트리스트로 못박고,
// 공유 토큰이 맞을 때만 응답한다.

const { timingSafeEqual } = require("node:crypto");

// param/env 가 있으면 인증키를 끼워 넣고, 없으면 그대로 통과시킨다.
// 통과 전용 호스트는 공개 페이지·파일을 읽기 위한 것으로, 키가 붙지 않는다.
const ALLOW = {
  "apis.data.go.kr": { param: "serviceKey", env: "DATA_GO_KR_KEY" },
  // 표준데이터(tn_pubr_public_*)는 s 가 없는 호스트다 — 위와 다른 곳이다.
  "api.data.go.kr":  { param: "serviceKey", env: "DATA_GO_KR_KEY" },
  "api.odcloud.kr":  { param: "serviceKey", env: "DATA_GO_KR_KEY" },
  // 브이월드 키는 '웹사이트' 유형으로 서비스URL 이 등록돼 있다. WMS/WFS 는
  // 요청이 그 도메인에서 왔는지를 Referer 로 본다. 중계기는 서버라 브라우저
  // 처럼 Referer 를 붙이지 않으므로, 등록된 주소를 직접 실어 보낸다.
  // 지오코더는 이것을 따지지 않아 지금까지 드러나지 않았다.
  // referer 는 **함수로 둔다.** 상수로 두면 이 파일을 읽는 순간
  // process.env 를 읽는데, Cloudflare Pages 에서는 그때 아직 환경변수가
  // 안 들어와 있다 (functions/_adapter.js 가 요청마다 부어 준다).
  // 상수로 두면 VWORLD_REFERER 를 아무리 넣어도 무시되고 아래 기본값이
  // 영원히 이긴다 — 그러면 브이월드가 Referer 를 보고 거절한다.
  "api.vworld.kr":   { param: "key",        env: "VWORLD_KEY",
                       referer: () => process.env.VWORLD_REFERER || DEFAULT_REFERER },
  "data.ex.co.kr":   { param: "key",        env: "EX_API_KEY" },
  "www.data.go.kr":  {},
  // 경매·공매 원천 확인용. 둘 다 키가 없는 공개 페이지라 통과만 시킨다.
  // 러너는 미국이고 두 곳 다 해외 IP 에서 응답이 없어(1차 탐침에서 전부
  // ConnectTimeout) 서울을 거치지 않으면 열려 있는지조차 알 수 없다.
  "openapi.onbid.co.kr":    {},
  "www.onbid.co.kr":        {},
  "www.courtauction.go.kr": {},
  // 표준지공시지가는 포털이 아니라 브이월드가 제공한다(링크 API). 어떤
  // 레이어 이름으로 열려 있는지는 목록 페이지에만 적혀 있다. 읽기만 하므로
  // 키를 붙이지 않는다.
  "www.vworld.kr":   {},
  // KOSIS 는 apiKey 를 쿼리로 받는다. 예전에는 {} 로 두어 키를 안 붙였는데,
  // 그러면 호출 측이 키를 들고 있어야 한다 — 키는 중계기에만 둔다는 원칙과
  // 어긋난다. env 를 지정하면 STRIP 이 들어온 키를 지우고 우리 것으로 덮는다.
  "kosis.kr":        { param: "apiKey",     env: "KOSIS_KEY" },
};

// 브이월드 콘솔에 등록된 서비스 주소. 환경변수(VWORLD_REFERER)가 있으면
// 그것이 이긴다 — 주소가 또 바뀔 때 코드를 안 고치기 위해서다.
const DEFAULT_REFERER = "https://toji.fyi/";

const STRIP = ["serviceKey", "key", "apiKey", "authKey", "accessKey"];
const TIMEOUT_MS = 25_000;

function deny(res, code, message) {
  res.status(code).json({ relayError: message });
}

// 길이가 달라도 시간이 새지 않도록 해시로 맞춘 뒤 비교한다.
function sameSecret(a, b) {
  const { createHash } = require("node:crypto");
  const h = (v) => createHash("sha256").update(String(v)).digest();
  return timingSafeEqual(h(a), h(b));
}

// 일부 공공 API 는 오류 응답에 요청 URL 을 그대로 되비춘다.
// 그 URL 에는 우리가 끼워 넣은 인증키가 붙어 있으므로, 돌려주기 전에 지운다.
function scrub(text, secret) {
  if (!secret) return text;
  const variants = [secret, encodeURIComponent(secret)];
  let out = text;
  for (const v of variants) {
    if (v) out = out.split(v).join("***");
  }
  return out;
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return deny(res, 405, "GET 만 허용합니다");

  const expected = process.env.RELAY_TOKEN;
  if (!expected) return deny(res, 500, "RELAY_TOKEN 이 설정되지 않았습니다");
  const given = req.headers["x-relay-token"];
  if (!given || !sameSecret(given, expected)) {
    return deny(res, 401, "토큰이 일치하지 않습니다");
  }

  const raw = req.query.target;
  if (!raw) return deny(res, 400, "target 파라미터가 없습니다");

  let target;
  try {
    target = new URL(raw);
  } catch {
    return deny(res, 400, "target 이 올바른 URL 이 아닙니다");
  }
  if (target.protocol !== "https:") return deny(res, 400, "https 만 허용합니다");

  const rule = ALLOW[target.hostname];
  if (!rule) return deny(res, 403, `허용되지 않은 목적지: ${target.hostname}`);

  let secret = null;
  if (rule.env) {
    secret = process.env[rule.env];
    if (!secret) return deny(res, 500, `${rule.env} 이 설정되지 않았습니다`);
    // 호출 측이 실수로 키 비슷한 것을 넣어 보냈어도 우리 것으로 덮어쓴다.
    for (const name of STRIP) target.searchParams.delete(name);
    target.searchParams.set(rule.param, secret);
  }

  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    const upstream = await fetch(target.toString(), {
      signal: stop.signal,
      // 리디렉션을 따라가면 인증키가 붙은 요청이 우리가 허용하지 않은 호스트로
      // 그대로 전달된다. 따라가지 않고 상태 코드만 돌려준다.
      redirect: "manual",
      headers: {
        "User-Agent": "redt-relay/1.0",
        Accept: "*/*",
        ...(rule.referer ? { Referer: rule.referer() } : {}),
      },
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      return deny(res, 502, `상류가 리디렉션을 요구했습니다 (${upstream.status}) — 따라가지 않았습니다`);
    }
    const type = upstream.headers.get("content-type") || "text/plain; charset=utf-8";
    const textual = /^text\/|json|xml|javascript|html/i.test(type);

    res.setHeader("cache-control", "no-store");
    if (textual) {
      res.setHeader("content-type", type);
      res.status(upstream.status).send(scrub(await upstream.text(), secret));
      return;
    }
    // zip·xlsx 같은 바이너리는 텍스트로 디코딩하면 깨진다. base64 로 감싸 보낸다.
    const buf = Buffer.from(await upstream.arrayBuffer());
    res.setHeader("content-type", "text/plain; charset=utf-8");
    res.setHeader("x-relay-encoding", "base64");
    res.setHeader("x-relay-content-type", type);
    res.setHeader("x-relay-bytes", String(buf.length));
    res.status(upstream.status).send(buf.toString("base64"));
  } catch (err) {
    const timedOut = err && err.name === "AbortError";
    // 오류 메시지에 target 을 넣지 않는다 — 키가 붙은 URL 이라 그대로 새어나간다.
    deny(res, timedOut ? 504 : 502,
         timedOut ? `상류 응답 없음 (${TIMEOUT_MS / 1000}초 초과)` : "상류 호출 실패");
  } finally {
    clearTimeout(timer);
  }
};
