import { useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import AuthBar from "./Auth";
import ChatPanel from "./Chat";
import AnalyzeProgress from "./Progress";
import { API_BASE, errorMessage, type ChatMessage } from "./api";
import "./App.css";

type RepoMeta = {
  owner: string;
  name: string;
  description: string | null;
  primary_language: string | null;
  stars: number;
};

type AnalyzeResponse = {
  repo: RepoMeta;
  summary: string;
  // DB를 쓸 수 없으면 null이다. 그때는 요약만 볼 수 있다.
  session_id: string | null;
};

/** 화면에 띄울 대화. 복원한 세션일 수도, 방금 만들어진 세션일 수도 있다. */
type ChatState = { sessionId: string; messages: ChatMessage[] };

// session_id 를 브라우저에 보관해야 새로고침 후에도 대화를 이어갈 수 있다.
// **로그인해도 이 자리는 그대로다** — 로그인은 대화에 소유자를 붙일 뿐이고,
// 어느 대화를 이어갈지는 여전히 브라우저만 아는 정보다(익명 대화도 계속 생긴다).
const sessionKey = (repo: RepoMeta) =>
  `repodive:session:${repo.owner}/${repo.name}`.toLowerCase();

/** 저장된 대화 id. localStorage 를 못 쓰면(사생활 보호 모드 등) 없는 것으로 친다. */
function loadSession(repo: RepoMeta): string | null {
  try {
    return localStorage.getItem(sessionKey(repo));
  } catch {
    return null;
  }
}

/** 분석을 **보내기 전에** 찾아보는 세션 id.
 *
 * 서버는 이 값이 있어야 세션을 재사용하고, 없으면 분석마다 새로 만든다(그리고 아래
 * resolveChat 이 옛 세션을 복원하면 그 새 세션은 메시지 없이 버려진다).
 *
 * 이 시점에는 정식 표기를 모르므로 **입력 URL 에서 추정한 키**로 찾는다. 표기가 정식과
 * 다르면(저장소 이전 등) 못 찾을 뿐이고, 그때는 전과 똑같이 동작한다 — 나빠지지 않는다.
 */
function savedSessionForUrl(url: string): string | null {
  const m = url.trim().match(/github\.com\/([^/?#]+)\/([^/?#]+)/i);
  if (!m) return null;
  const key = `repodive:session:${m[1]}/${m[2].replace(/\.git$/i, "")}`.toLowerCase();
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function saveSession(repo: RepoMeta, sessionId: string) {
  try {
    localStorage.setItem(sessionKey(repo), sessionId);
  } catch {
    // 보관에 실패해도 이번 세션은 그대로 쓴다. 보관 장치가 기능을 막으면 안 된다.
  }
}

/** 이어갈 대화가 있으면 그것을, 없으면 방금 만들어진 세션을 쓴다.
 *
 * 키는 입력한 URL 이 아니라 응답의 정식 표기로 만든다 — 백엔드도 같은 기준으로 캐시 키를
 * 만들기 때문에(summary_cache), 저장소가 이전됐어도 같은 대화로 모인다.
 */
async function resolveChat(repo: RepoMeta, newSessionId: string): Promise<ChatState> {
  const saved = loadSession(repo);
  if (saved) {
    try {
      const res = await fetch(`${API_BASE}/chat/${saved}`);
      if (res.ok) {
        const body = await res.json();
        return { sessionId: saved, messages: body.messages };
      }
    } catch {
      // 이력을 못 불러오면 새 대화로 시작한다. 요약은 이미 화면에 있다.
    }
  }
  saveSession(repo, newSessionId);
  return { sessionId: newSessionId, messages: [] };
}

export default function App() {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [chat, setChat] = useState<ChatState | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResult(null);
    setChat(null);

    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // 이어갈 대화가 있으면 알려준다 — 서버는 localStorage 를 볼 수 없다.
        body: JSON.stringify({ github_url: url, session_id: savedSessionForUrl(url) }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(errorMessage(body.detail, res.status, "분석에 실패했습니다"));
      }
      const data: AnalyzeResponse = await res.json();
      setResult(data);
      // session_id 가 없으면 DB를 쓸 수 없는 상태다. 요약만 보여주고 대화는 숨긴다.
      if (data.session_id) setChat(await resolveChat(data.repo, data.session_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "알 수 없는 오류가 발생했습니다");
    } finally {
      setLoading(false);
    }
  }

  // 첫 화면과 상단 바가 같은 폼을 쓴다. 크기는 감싼 쪽(.landing / .topbar)이 정한다.
  const urlForm = (
    <form onSubmit={handleSubmit}>
      <input
        type="url"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://github.com/owner/repo"
        required
      />
      <button type="submit" disabled={loading || !url}>
        {loading ? "분석 중…" : "분석"}
      </button>
    </form>
  );

  // 아직 보여줄 결과가 없으면 링크 입력 하나만 남긴다 — 상단 바도 사이드바도 그리지 않는다.
  // 분석 중에는 그 자리에 진행 표시가 들어와 화면이 튀지 않는다.
  if (!result) {
    return (
      <main className="landing">
        <div className="landing-inner">
          <h1 className="brand brand-lg">
            <RepoIcon />
            RepoDive
          </h1>
          <p className="landing-lead">
            GitHub 레포지토리 링크를 넣으면 프로젝트 개요와 기술 스택을 정리해 드립니다.
          </p>

          {loading ? <AnalyzeProgress /> : urlForm}
          {error && <p className="error">{error}</p>}
          <AuthBar />
        </div>
      </main>
    );
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            <RepoIcon />
            RepoDive
          </span>
          {urlForm}
          <AuthBar />
        </div>
      </header>

      <div className="repo-head">
        <div className="repo-head-inner">
          <RepoIcon />
          <span className="owner">{result.repo.owner}</span>
          <span className="slash">/</span>
          <strong>{result.repo.name}</strong>
          <span className="badge">Public</span>
        </div>
      </div>

      <main>
        <div className="layout">
          <div className="main-col">
            <div className="markdown">
              <ReactMarkdown>{result.summary}</ReactMarkdown>
            </div>

            {chat && (
              <ChatPanel
                // 세션이 바뀌면 패널 내부 상태를 새로 시작한다.
                key={chat.sessionId}
                sessionId={chat.sessionId}
                initialMessages={chat.messages}
              />
            )}
          </div>

          <aside className="sidebar">
            <h3>About</h3>
            {result.repo.description ? (
              <p>{result.repo.description}</p>
            ) : (
              <p className="muted">No description provided.</p>
            )}
            <ul>
              {result.repo.primary_language && (
                <li>
                  <span className="lang-dot" />
                  {result.repo.primary_language}
                </li>
              )}
              <li>
                <StarIcon />
                {result.repo.stars.toLocaleString()} stars
              </li>
            </ul>
          </aside>
        </div>
      </main>
    </>
  );
}

function RepoIcon() {
  return (
    <svg className="octicon" viewBox="0 0 16 16" width="16" height="16" aria-hidden>
      <path d="M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8Z" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg className="octicon" viewBox="0 0 16 16" width="16" height="16" aria-hidden>
      <path d="M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z" />
    </svg>
  );
}
