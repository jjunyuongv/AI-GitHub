import { useEffect, useState } from "react";
import { API_BASE } from "./api";

type AuthUser = { login: string; avatar_url: string | null };
type AuthStatus = { enabled: boolean; user: AuthUser | null };

/** 로그인 줄. **꺼져 있으면 아무것도 그리지 않는다.**
 *
 * 켜짐 여부를 프론트 설정이 아니라 서버에 묻는다 — 켜는 곳이 백엔드의 환경변수
 * 하나여야 하고, 두 곳에 적으면 "화면에는 버튼이 있는데 누르면 404" 가 된다.
 *
 * 상태를 못 읽으면(네트워크 실패 등) 꺼진 것으로 친다. 로그인은 부가 기능이라
 * 이것 때문에 화면이 깨지면 안 된다.
 *
 * **`fetch` 로 로그인을 시작하지 않는다.** `<a>` 와 `<form>` 으로 진짜 이동을 만든다 —
 * OAuth 는 GitHub 으로 갔다 돌아오는 흐름이고, 돌아오는 길에 `SameSite=Lax` 쿠키가
 * 실리려면 그것이 **최상위 이동**이어야 한다.
 */
export default function AuthBar() {
  const [status, setStatus] = useState<AuthStatus | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/auth/me`);
        if (!res.ok) return;
        const body: AuthStatus = await res.json();
        if (alive) setStatus(body);
      } catch {
        // 꺼진 것으로 둔다.
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (!status?.enabled) return null;

  if (!status.user) {
    return (
      <a className="auth-link" href={`${API_BASE}/auth/login`}>
        GitHub 로그인
      </a>
    );
  }

  return (
    <span className="auth-user">
      {status.user.avatar_url && (
        <img src={status.user.avatar_url} alt="" width={20} height={20} />
      )}
      <span>{status.user.login}</span>
      <form method="post" action={`${API_BASE}/auth/logout`}>
        <button type="submit" className="auth-link">
          로그아웃
        </button>
      </form>
    </span>
  );
}
