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

const ALLOW = {
  "apis.data.go.kr": { param: "serviceKey", env: "DATA_GO_KR_KEY" },
  "api.vworld.kr":   { param: "key",        env: "VWORLD_KEY" },
  "data.ex.co.kr":   { param: "key",        env: "EX_API_KEY" },
};

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

  const secret = process.env[rule.env];
  if (!secret) return deny(res, 500, `${rule.env} 이 설정되지 않았습니다`);

  // 호출 측이 실수로 키 비슷한 것을 넣어 보냈어도 우리 것으로 덮어쓴다.
  for (const name of STRIP) target.searchParams.delete(name);
  target.searchParams.set(rule.param, secret);

  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    const upstream = await fetch(target.toString(), {
      signal: stop.signal,
      // 리디렉션을 따라가면 인증키가 붙은 요청이 우리가 허용하지 않은 호스트로
      // 그대로 전달된다. 따라가지 않고 상태 코드만 돌려준다.
      redirect: "manual",
      headers: { "User-Agent": "redt-relay/1.0", Accept: "*/*" },
    });
    if (upstream.status >= 300 && upstream.status < 400) {
      return deny(res, 502, `상류가 리디렉션을 요구했습니다 (${upstream.status}) — 따라가지 않았습니다`);
    }
    const body = scrub(await upstream.text(), secret);
    const type = upstream.headers.get("content-type") || "text/plain; charset=utf-8";
    res.setHeader("content-type", type);
    res.setHeader("cache-control", "no-store");
    res.status(upstream.status).send(body);
  } catch (err) {
    const timedOut = err && err.name === "AbortError";
    // 오류 메시지에 target 을 넣지 않는다 — 키가 붙은 URL 이라 그대로 새어나간다.
    deny(res, timedOut ? 504 : 502,
         timedOut ? `상류 응답 없음 (${TIMEOUT_MS / 1000}초 초과)` : "상류 호출 실패");
  } finally {
    clearTimeout(timer);
  }
};
