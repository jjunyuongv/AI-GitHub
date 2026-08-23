import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import ReactMarkdown from "react-markdown";
import {
  API_BASE,
  errorMessage,
  fetchFileView,
  fetchIndexStatus,
  type ChatMessage,
  type Citation,
  type FileView,
  type IndexStatus,
} from "./api";
import { CITATION_ATTR, rehypeCitations } from "./citations";

type Props = {
  sessionId: string;
  initialMessages: ChatMessage[];
};

// 색인 진행 상황을 다시 물어보는 간격. 진행률은 배치(청크 32개, 20~30초) 단위로
// 올라가므로 이보다 촘촘히 물어봐도 같은 숫자만 돌아온다.
const INDEX_POLL_MS = 3000;

/** 답변을 기다리는 동안의 안내. */
function PendingNotice() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed(Date.now() - started), 500);
    return () => clearInterval(id);
  }, []);

  const seconds = Math.floor(elapsed / 1000);
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <p className="chat-pending" role="status" aria-live="polite">
      답변 생성 중… <span className="elapsed" aria-hidden>{clock}</span>
    </p>
  );
}

function remainingText(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 60) return " · 잠시 후 완료";
  return ` · 약 ${Math.ceil(seconds / 60)}분 남음`;
}

/** 코드 색인 상태 배너.
 *
 * 색인이 끝나기 전에는 백엔드가 코드를 검색하지 않고 요약만으로 답한다
 * (부분 인덱스로 검색하면 아직 읽지 않은 코드가 '없는 코드'처럼 보인다).
 * 그 사실과 남은 시간을 여기서 알린다. 끝났으면 아무것도 보여주지 않는다.
 */
function IndexNotice({ status }: { status: IndexStatus }) {
  if (status.status === "completed") return null;

  if (status.status === "failed") {
    return (
      <p className="chat-index failed" role="status">
        코드 색인에 실패해 요약을 근거로만 답합니다
        {status.error ? ` (${status.error})` : "."}
      </p>
    );
  }

  const { chunks_done: done, chunks_total: total } = status;
  const progress = total ? `${done.toLocaleString()} / ${total.toLocaleString()}개` : "준비 중";

  return (
    <p className="chat-index" role="status" aria-live="polite">
      이 저장소의 코드를 읽는 중입니다 ({progress}
      {remainingText(status.eta_seconds)}). 지금 물어보면 요약을 근거로만 답합니다.
    </p>
  );
}

/** 행 범위 표기. 한 줄이면 "17행", 여러 줄이면 "29-32행". */
function lineLabel(start: number, end: number) {
  return start === end ? `${start}행` : `${start}-${end}행`;
}

/** 인용이 가리킨 코드. **틀린 행 번호를 감추지 않는 것이 이 컴포넌트의 목적이다.**
 *
 * 실측 행 번호 정확도가 72.4% 라 넷 중 하나는 엉뚱한 줄을 짚는다. 그래서
 * - 인용 범위는 배경색으로만 표시하고 **여유 줄도 또렷하게 읽히게** 둔다(흐리게 하지 않는다).
 *   그래야 번호가 어긋났을 때 사용자가 근처에서 실제 위치를 찾을 수 있다
 * - 파일 밖을 가리킨 인용은 **빈 화면이 아니라 그 사실을 적는다**
 */
function CodeView({ view }: { view: FileView }) {
  const lines = view.numbered ? view.numbered.split("\n") : [];

  return (
    <div className="citation-code">
      <p className="citation-head">
        <code>{view.path}</code>{" "}
        <span className="cited">
          {lineLabel(view.requested_start, view.requested_end)}
        </span>{" "}
        <span className="shown">
          (전체 {view.total_lines.toLocaleString()}행
          {lines.length ? ` · ${lineLabel(view.start_line, view.end_line)} 표시` : ""})
        </span>
      </p>

      {lines.length === 0 ? (
        <p className="citation-missing">
          답변은 {lineLabel(view.requested_start, view.requested_end)}이라고 했지만 이 파일은{" "}
          {view.total_lines.toLocaleString()}행뿐입니다.
        </p>
      ) : (
        <pre>
          <code>
            {lines.map((line, i) => {
              const number = Number(line.slice(0, line.indexOf("|")));
              const cited =
                number >= view.requested_start && number <= view.requested_end;
              return (
                <span key={i} className={cited ? "line cited" : "line"}>
                  {line}
                  {"\n"}
                </span>
              );
            })}
          </code>
        </pre>
      )}

      {view.truncated && (
        <p className="citation-note">범위가 길어 앞부분만 보여줍니다.</p>
      )}
    </div>
  );
}

type OpenState = Record<string, FileView | "loading" | { error: string }>;

// 인라인 링크를 못 건 누적 건수. 렌더마다 초기화되면 빈도를 알 수 없어서 모듈에 둔다.
let missCount = 0;

export default function ChatPanel({ sessionId, initialMessages }: Props) {
  const [messages, setMessages] = useState(initialMessages);
  const [question, setQuestion] = useState("");
  // 전송 중인 질문. messages 에 미리 넣지 않는다 — 백엔드는 질문과 답변을 LLM 호출이
  // 성공한 뒤에 함께 저장하므로, 실패한 질문을 화면에 남기면 새로고침했을 때 사라진다.
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [index, setIndex] = useState<IndexStatus | null>(null);
  // 펼쳐 둔 인용. 키는 `메시지번호:인용번호` 다.
  //
  // **여러 개를 동시에 펼친다.** 하나만 열게 하면 A 를 열고 B 를 여는 순간 A 가 닫히는데,
  // 이 기능의 목적이 "행 번호가 맞는지 대조"라 대조 자체가 불가능해진다.
  //
  // **새 질문을 보내도 유지된다.** 메시지는 뒤에 붙기만 하므로 기존 블록의 번호가
  // 안 바뀐다 — 닫으면 방금 대조하려고 연 근거가 사라진다.
  const [opened, setOpened] = useState<OpenState>({});

  const endRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  // 색인이 끝날 때까지만 물어본다. 끝났거나(completed) 실패했으면 더 볼 게 없다.
  useEffect(() => {
    let stopped = false;
    let timer = 0;

    async function poll() {
      const status = await fetchIndexStatus(sessionId);
      if (stopped) return;
      setIndex(status);
      if (!status || status.status === "pending" || status.status === "running") {
        timer = window.setTimeout(poll, INDEX_POLL_MS);
      }
    }

    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [sessionId]);

  // 새 답변만 따라간다. 처음 그릴 때도 스크롤하면 이력을 복원했을 때
  // 요약을 지나쳐 대화 끝으로 튀어버린다.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages.length, pending]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = question.trim();
    if (!text || pending) return;

    setQuestion("");
    setPending(text);
    setError("");

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(errorMessage(body.detail, res.status, "답변을 받지 못했습니다"));
      }
      const { answer } = await res.json();
      setMessages((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: answer },
      ]);
    } catch (err) {
      // 저장되지 않은 질문은 입력창으로 되돌린다 (화면과 DB 가 어긋나지 않게).
      setQuestion(text);
      setError(err instanceof Error ? err.message : "알 수 없는 오류가 발생했습니다");
    } finally {
      setPending("");
    }
  }

  async function toggleCitation(key: string, cite: Citation) {
    if (opened[key]) {
      setOpened((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      return;
    }
    setOpened((prev) => ({ ...prev, [key]: "loading" }));
    try {
      const view = await fetchFileView(sessionId, cite);
      setOpened((prev) => ({ ...prev, [key]: view }));
    } catch (err) {
      setOpened((prev) => ({
        ...prev,
        [key]: { error: err instanceof Error ? err.message : "파일을 열지 못했습니다" },
      }));
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      e.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <section className="chat">
      <h3>대화</h3>

      {index && <IndexNotice status={index} />}

      {messages.length === 0 && !pending && (
        <p className="chat-empty">요약에서 더 알고 싶은 부분을 물어보세요.</p>
      )}

      {messages.map((m, i) => {
        if (m.role === "user") {
          return <div key={i} className="msg user">{m.content}</div>;
        }

        const cites = m.citations ?? [];
        // 인라인 링크를 못 건 인용. 아래 목록에는 그대로 남으므로 근거를 못 보게 되지는
        // 않는다. 빈도를 알아야 나중에 고칠지 정할 수 있어서 콘솔에 남긴다
        // (렌더 중에 불리므로 JSX 안이 아니라 콜백에서 남긴다).
        const plugin = rehypeCitations(cites, (c) => {
          missCount += 1;
          console.warn(
            `[citations] 인라인 링크 실패 ${missCount}건째 — 답변에서 "${c.marker}" 를 찾지 못했습니다`,
            c,
          );
        });

        return (
          <div key={i} className="msg assistant">
            <div className="markdown">
              <ReactMarkdown
                rehypePlugins={[plugin]}
                components={{
                  span(props) {
                    const { node, children, ...rest } = props;
                    const raw = node?.properties?.[CITATION_ATTR];
                    if (typeof raw !== "string") return <span {...rest}>{children}</span>;
                    const cite: Citation = JSON.parse(raw);
                    const key = `${i}:${cite.offset}`;
                    return (
                      <button
                        type="button"
                        className={`citation${opened[key] ? " open" : ""}`}
                        onClick={() => toggleCitation(key, cite)}
                        title={`${cite.path} ${lineLabel(cite.start_line, cite.end_line)} 열기`}
                      >
                        {children}
                      </button>
                    );
                  },
                }}
              >
                {m.content}
              </ReactMarkdown>
            </div>

            {cites.length > 0 && (
              <div className="citation-list">
                <p className="citation-list-head">근거</p>
                {cites.map((cite) => {
                  const key = `${i}:${cite.offset}`;
                  const state = opened[key];
                  return (
                    <div key={key}>
                      <button
                        type="button"
                        className={`citation-item${state ? " open" : ""}`}
                        onClick={() => toggleCitation(key, cite)}
                      >
                        {state ? "▾" : "▸"} {cite.path}{" "}
                        <span className="lines">
                          {lineLabel(cite.start_line, cite.end_line)}
                        </span>
                      </button>
                      {state === "loading" && <p className="citation-note">여는 중…</p>}
                      {state && typeof state === "object" && "error" in state && (
                        <p className="error">{state.error}</p>
                      )}
                      {state && typeof state === "object" && "numbered" in state && (
                        <CodeView view={state} />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {pending && (
        <>
          <div className="msg user">{pending}</div>
          <PendingNotice />
        </>
      )}

      <div ref={endRef} />

      {error && <p className="error">{error}</p>}

      <form onSubmit={send}>
        <textarea
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"
        />
        <button type="submit" disabled={!!pending || !question.trim()}>
          {pending ? "전송 중…" : "전송"}
        </button>
      </form>
    </section>
  );
}
