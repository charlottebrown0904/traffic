/* /api/tile — Cloudflare Pages 껍데기. 알맹이는 ../../api/tile.js.
 *
 * **여기가 이사의 성패를 가르는 자리다.** Vercel 은 s-maxage 를 보고
 * CDN 이 알아서 캐시해 주지만, Cloudflare 는 Functions 응답을 저절로
 * 캐시하지 않는다. 그대로 옮기면 타일 한 장 한 장이 매번 브이월드까지
 * 갔다 온다 — 느려지고, 브이월드 한도도 같이 태운다.
 *
 * 그래서 Cache API 를 직접 쓴다. 다만 **캐시에 맞아도 Worker 는 돈다** —
 * 무료 10만 요청/일은 캐시로 줄지 않는다. 줄어드는 것은 브이월드 호출과
 * 응답 시간이지 호출 수가 아니다. 이 구분을 흐리면 '캐시 걸었으니
 * 괜찮겠지' 로 잘못 판단하게 된다. */
import handler from "../../api/tile.js";
import { adapt } from "../_adapter.js";

const inner = adapt(handler);

export async function onRequest(context) {
  const { request } = context;
  // GET 이 아니면 캐시를 건드리지 않는다.
  if (request.method !== "GET") return inner(context);

  const cache = caches.default;
  const hit = await cache.match(request);
  if (hit) {
    const marked = new Response(hit.body, hit);
    marked.headers.set("x-tile-cache", "hit");
    return marked;
  }

  const fresh = await inner(context);
  fresh.headers.set("x-tile-cache", "miss");
  // 성공만 담는다. 실패를 담으면 한도가 풀린 뒤에도 빈 화면이 남는다
  // (api/tile.js 의 CACHE_BAD 가 같은 이유로 60초짜리다).
  if (fresh.ok && /max-age=\d/.test(fresh.headers.get("cache-control") || "")) {
    context.waitUntil(cache.put(request, fresh.clone()));
  }
  return fresh;
}
