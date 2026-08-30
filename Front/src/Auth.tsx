import { API_BASE, type AuthStatus } from "./api";

/** 로그인 줄. **꺼져 있으면 아무것도 그리지 않는다.**
 *
 * 켜짐 여부를 프론트 설정이 아니라 서버에 묻는다 — 켜는 곳이 백엔드의 환경변수
 * 하나여야 하고, 두 곳에 적으면 "화면에는 버튼이 있는데 누르면 404" 가 된다.
 * 상태는 `App` 이 `/auth/me` 로 한 번 읽어 내려준다(저장소 목록도 같은 값을 본다).
 * 못 읽었으면(null) 꺼진 것으로 친다.
 *
 * **`fetch` 로 로그인을 시작하지 않는다.** `<a>` 와 `<form>` 으로 진짜 이동을 만든다 —
 * OAuth 는 GitHub 으로 갔다 돌아오는 흐름이고, 돌아오는 길에 `SameSite=Lax` 쿠키가
 * 실리려면 그것이 **최상위 이동**이어야 한다.
 */
export default function AuthBar({ status }: { status: AuthStatus | null }) {
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
