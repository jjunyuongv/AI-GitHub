import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** 백엔드로 넘길 경로.
 *
 * **`nginx.conf` 의 정규식과 같은 집합이어야 한다.** 두 곳이 갈리면 로컬에서 되는
 * 것이 배포에서 404 가 되고, 그 404 는 SPA 폴백에 먹혀 200 으로 보인다.
 * 저쪽은 `^/(analyze|chat|health|auth)(/|$)` 다.
 */
const BACKEND_PATHS = ["/analyze", "/chat", "/health", "/auth"];

/** 개발 서버가 백엔드를 대신 불러 준다 — **출처를 하나로 만들기 위해서다.**
 *
 * 로그인 쿠키는 HttpOnly + SameSite=Lax 라, 프론트(5173)와 백엔드(8000)가 다른
 * 출처면 요청에 실리지 않는다. CORS 에 `allow_credentials` 를 여는 방법도 있지만
 * 그쪽은 **실제로 교차 출처 요청을 허용하는 것**이라 방어를 하나 내주는 일이고,
 * 배포(nginx 한 출처)와 구조도 달라진다. 프록시는 반대로 배포와 같은 모양을 만든다.
 *
 * 그래서 `src/api.ts` 의 `API_BASE` 기본값이 빈 문자열(상대 경로)이다 —
 * `/analyze`·`/chat` 도 이 프록시를 타야 쿠키가 함께 간다.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      BACKEND_PATHS.map((path) => [
        path,
        { target: "http://127.0.0.1:8000", changeOrigin: false },
      ]),
    ),
  },
});
