// 변수가 함수까지 닿았는지 — **이름과 참·거짓만** 낸다.
//
// 왜 필요한가. 키가 안 붙었을 때 증상이 '키를 안 넣었다' 와 '넣었는데
// 배포에 안 실렸다' 와 '이름을 잘못 적었다' 가 **글자 하나까지
// 똑같다.** 그러면 대시보드만 들여다보며 넣었다 지웠다를 반복하게
// 된다. 2026-09-09 에 Cloudflare 쪽에서 그 고리를 한 번 돌았다.
//
// **값은 절대 내보내지 않는다.** 길이조차 안 낸다 — 짧은 값은 길이
// 만으로도 좁혀진다. 이름은 이미 공개 저장소와 문서에 있는 것들이다.
//
// 그래도 아무나 부를 수 있게 두지 않는다. 중계기와 같은 토큰을
// 요구한다 — 우리 배포의 속살을 굳이 세상에 열어 둘 이유가 없다.
const { createHash, timingSafeEqual } = require("node:crypto");

const WANT = ["DATA_GO_KR_KEY", "VWORLD_KEY", "RELAY_TOKEN",
              "KOSIS_KEY", "EX_API_KEY", "VWORLD_REFERER"];

function sameSecret(a, b) {
  const h = (v) => createHash("sha256").update(String(v)).digest();
  return timingSafeEqual(h(a), h(b));
}

module.exports = async function handler(req, res) {
  const expected = process.env.RELAY_TOKEN;
  if (!expected) {
    return res.status(500).json({ envError: "RELAY_TOKEN 이 설정되지 않았습니다" });
  }
  const given = req.headers["x-relay-token"];
  if (!given || !sameSecret(given, expected)) {
    return res.status(401).json({ envError: "토큰이 일치하지 않습니다" });
  }

  const have = WANT.filter((k) => typeof process.env[k] === "string"
                                  && process.env[k] !== "");
  res.setHeader("cache-control", "no-store");
  res.status(200).json({
    platform: "vercel",
    // 배포된 함수가 실제로 도는 리전. 이 제품이 도는 이유가 여기 있다 —
    // 한국 공공 API 가 해외 IP 를 막는다(docs/finding-geoblock.md).
    region: process.env.VERCEL_REGION || null,
    has: have,
    missing: WANT.filter((k) => !have.includes(k)),
    // 브이월드에 어떤 Referer 로 나가는지. 값이 아니라 '무엇을 쓰는지'다.
    referer_source: process.env.VWORLD_REFERER ? "환경변수" : "요청 호스트에서 유추",
  });
};
