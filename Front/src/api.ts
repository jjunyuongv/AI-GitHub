/** 백엔드 호출에 공통으로 쓰는 값. App 과 Chat 이 서로를 import 하지 않도록 여기에 둔다. */

/** **빈 문자열 = 같은 출처**다. 개발은 Vite proxy 가, 배포는 nginx 가 백엔드로 넘긴다.
 *
 * 전에는 `http://127.0.0.1:8000` 이 기본값이라 개발에서 API 호출이 **교차 출처**로
 * 나갔다. 그러면 HttpOnly + SameSite=Lax 인 로그인 쿠키가 실리지 않아, 로그인해도
 * `/chat` 이 익명 요청으로 도착한다 — 오류 없이 소유자 검사만 조용히 빗나간다.
 */
export const API_BASE = import.meta.env.VITE_API_BASE ?? "";

/** 답변이 짚은 근거 한 건.
 *
 * **행 번호는 검증되지 않은 값이다** — 실측 정확도가 72.4% 다. 서버도 화면도 맞았는지
 * 판정하지 않는다. 틀린 것을 감추면 고칠 수가 없다.
 *
 * `offset` 은 답변 문자열 안에서 `marker` 가 시작하는 위치다. 마크다운 렌더러가 줄 앞뒤
 * 공백을 지워서 offset 산술만으로는 어긋나므로, offset 으로 **노드를 고르고**
 * `marker` 로 **노드 안 위치를 정한다** (`citations.ts`).
 */
export type Citation = {
  path: string;
  start_line: number;
  end_line: number;
  marker: string;
  offset: number;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  /** 사용자 메시지에는 없다. 보관 소스가 없는 스냅샷에서도 빈 배열이다. */
  citations?: Citation[];
};

/** 인용이 가리킨 파일 조각. 요청 범위와 실제 반환 범위를 둘 다 준다. */
export type FileView = {
  path: string;
  /** 실제로 담긴 범위 (앞뒤 여유가 붙어 있다). */
  start_line: number;
  end_line: number;
  /** 인용이 요청한 범위. 파일 밖을 가리켰어도 그대로 온다. */
  requested_start: number;
  requested_end: number;
  total_lines: number;
  truncated: boolean;
  /** `12|코드` 형식. 도구의 read_file 과 같은 형식이다. */
  numbered: string;
};

export async function fetchFileView(
  sessionId: string,
  cite: Citation,
): Promise<FileView> {
  const params = new URLSearchParams({
    path: cite.path,
    start: String(cite.start_line),
    end: String(cite.end_line),
  });
  const res = await fetch(`${API_BASE}/chat/${sessionId}/file?${params}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(errorMessage(body.detail, res.status, "파일을 열지 못했습니다"));
  }
  return res.json();
}

/** 코드 색인 진행 상황. completed 가 되기 전에는 답변에 코드가 쓰이지 않는다. */
export type IndexStatus = {
  /** skipped 는 실패가 아니라 **만들지 않기로 정한 것**이다 (청크 수가 상한 초과).
   *  그때 chunks_total 은 실제로 나온 청크 수이고 error 에 사유가 들어간다. */
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  chunks_total: number;
  chunks_done: number;
  /** 남은 예상 시간(초). 진행이 없어 계산할 수 없으면 null. */
  eta_seconds: number | null;
  error: string | null;
};

export async function fetchIndexStatus(sessionId: string): Promise<IndexStatus | null> {
  try {
    const res = await fetch(`${API_BASE}/chat/${sessionId}/index`);
    return res.ok ? await res.json() : null;
  } catch {
    // 상태를 못 읽어도 질문은 할 수 있다. 안내만 생략한다.
    return null;
  }
}

/** 백엔드 에러 메시지. FastAPI 본문 검증만 detail이 배열이고, 나머지는 문자열이다. */
export function errorMessage(detail: unknown, status: number, fallback: string): string {
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === "string");
    return messages.length ? messages.join(", ") : "입력 형식이 올바르지 않습니다";
  }

  return `${fallback} (${status})`;
}
