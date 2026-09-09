/* /api/envcheck — **이름만** 알려주는 진단 창구.
 *
 * 변수가 함수까지 안 닿을 때 원인이 둘인데 밖에서는 구분이 안 된다.
 *
 *   (가) Cloudflare 가 안 붙여 줌     context.env 자체가 비어 있다
 *   (나) 어댑터가 못 옮김             context.env 엔 있는데 process.env 에 없다
 *
 * 둘을 나란히 찍으면 한 번에 갈린다. 추측으로 재배포를 반복하는 것보다
 * 요청 한 번이 싸다.
 *
 * **값은 절대 내보내지 않는다.** 이름과 참/거짓만 낸다. 이름은 이미
 * 공개 저장소와 문서에 적혀 있는 것들이라 새로 새는 것이 없다.
 * 길이조차 안 낸다 — 짧은 값은 길이만으로도 좁혀진다.
 */
const WANT = ["DATA_GO_KR_KEY", "VWORLD_KEY", "RELAY_TOKEN",
              "KOSIS_KEY", "EX_API_KEY", "VWORLD_REFERER"];

export async function onRequest(context) {
  const env = context.env || {};

  // 1) Cloudflare 가 준 것에 있는가
  const inContext = WANT.filter((k) => typeof env[k] === "string" && env[k] !== "");

  // 2) process.env 로 옮겨졌는가 (어댑터가 하는 일)
  let inProcess = [];
  let writable = null;
  let error = null;
  try {
    for (const [k, v] of Object.entries(env)) {
      if (typeof v === "string") process.env[k] = v;
    }
    inProcess = WANT.filter((k) => typeof process.env[k] === "string"
                                   && process.env[k] !== "");
    // process.env 가 읽기 전용이면 위 대입이 조용히 무시된다.
    // 그것이 (나) 의 정체이므로 직접 확인한다.
    const probe = "__envcheck_" + Date.now();
    process.env[probe] = "1";
    writable = process.env[probe] === "1";
    delete process.env[probe];
  } catch (e) {
    error = String((e && e.message) || e);
  }

  // **어디서 돌았는가.** 이것이 이사의 급소다.
  //
  // Vercel 함수는 regions:["icn1"] 로 서울에 고정돼 있었다. 한국 공공
  // API 가 해외 IP 를 막기 때문에(docs/finding-geoblock.md) 중계기가
  // 서울에서 돌아야만 했다.
  //
  // Cloudflare Workers 는 **요청자에게 가까운 곳**에서 돈다. 한국
  // 사용자가 열면 서울에서 돌지만, 미국 러너가 부르면 미국에서 돈다.
  // 그러면 수집 파이프라인의 중계기 노릇을 못 한다.
  const cf = context.request.cf || {};

  return new Response(JSON.stringify({
    ran_at: { colo: cf.colo || null, country: cf.country || null,
              city: cf.city || null, tz: cf.timezone || null },
    // Cloudflare 가 이 배포에 붙여 준 이름들
    context_has: inContext,
    // 우리 핸들러가 실제로 읽는 자리에 있는 이름들
    process_has: inProcess,
    // process.env 에 쓰기가 되는가 (false 면 어댑터 방식을 바꿔야 한다)
    process_env_writable: writable,
    // context.env 에 든 이름 **전부** (우리가 안 적은 것도 보인다)
    all_context_keys: Object.keys(env).sort(),
    error,
  }, null, 2), {
    status: 200,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-served-by": "cloudflare-pages",
    },
  });
}
