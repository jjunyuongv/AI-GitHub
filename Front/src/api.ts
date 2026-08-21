/** 백엔드 호출에 공통으로 쓰는 값. App 과 Chat 이 서로를 import 하지 않도록 여기에 둔다. */

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export type ChatMessage = { role: "user" | "assistant"; content: string };

/** 코드 색인 진행 상황. completed 가 되기 전에는 답변에 코드가 쓰이지 않는다. */
export type IndexStatus = {
  status: "pending" | "running" | "completed" | "failed";
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
