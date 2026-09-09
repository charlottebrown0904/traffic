/* /api/relay — Cloudflare Pages 껍데기.
 *
 * 알맹이는 ../../api/relay.js 하나뿐이다. 여기서 하는 일은 모양을
 * 맞추는 것뿐이고, 로직은 한 줄도 없다. 중계 규칙(화이트리스트·토큰·
 * 키 지우기)을 고칠 일이 있으면 **저쪽 한 곳만** 고친다. */
import handler from "../../api/relay.js";
import { adapt } from "../_adapter.js";

export const onRequest = adapt(handler);
