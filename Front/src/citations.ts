/** 답변 안의 인용 표기(`26-91행`)를 클릭 가능한 span 으로 바꾸는 rehype 플러그인.
 *
 * **여기서 정규식을 다시 짜지 않는다.** 인용을 뽑는 규칙은 백엔드 하나뿐이고
 * (`app/services/citations.py`), 화면은 그것이 준 offset·marker 로 자리만 찾는다.
 * 파서가 둘이 되면 "테스트가 채점하는 인용"과 "화면에 링크로 뜨는 인용"이 다른 집합이 된다.
 *
 * ## 왜 offset 만으로는 안 되는가
 *
 * remark 는 mdast/hast 노드에 원본 offset(`position`)을 남기고 react-markdown 은 그것을
 * 지우지 않는다 — 그래서 **어느 노드인지는 offset 으로 정확히 고를 수 있다.**
 * 그런데 `mdast-util-to-hast` 의 텍스트 핸들러가 `trimLines()` 로 줄 앞뒤 공백을 지우므로
 * **노드 안 인덱스는 offset 산술로 못 구한다.** 그래서 marker 문자열로 다시 찾는다.
 *
 * ## 못 찾으면 링크를 만들지 않는다
 *
 * 억지로 만들면 엉뚱한 글자에 링크가 걸린다 — **죽은 링크보다 나쁘다.**
 * 대신 `onMiss` 로 알려 빈도를 셀 수 있게 한다. 인라인이 빠져도 답변 아래 근거 목록에는
 * 남으므로 사용자가 근거를 못 보게 되지는 않는다.
 */

import type { Citation } from "./api";

type HastNode = {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
  position?: { start: { offset?: number }; end: { offset?: number } };
};

export const CITATION_ATTR = "dataCitation";

/** 이 텍스트 노드가 담고 있는 인용들. 원본 offset 으로 고른다. */
function citationsIn(node: HastNode, citations: Citation[]): Citation[] {
  const from = node.position?.start?.offset;
  const to = node.position?.end?.offset;
  if (from === undefined || to === undefined) return [];
  return citations.filter((c) => c.offset >= from && c.offset < to);
}

/** 노드 값 안에서 marker 의 위치. 없으면 -1.
 *
 * 같은 marker 가 한 노드에 둘 이상 있으면 offset 으로 계산한 근사 위치에서 가까운 쪽을
 * 고른다 — 노드는 이미 offset 으로 정확히 골랐으므로 그 안에서는 근사로 충분하다.
 */
function locate(value: string, marker: string, approx: number): number {
  let best = -1;
  let bestDistance = Infinity;
  for (let at = value.indexOf(marker); at !== -1; at = value.indexOf(marker, at + 1)) {
    const distance = Math.abs(at - approx);
    if (distance < bestDistance) {
      best = at;
      bestDistance = distance;
    }
  }
  return best;
}

function split(
  node: HastNode,
  citations: Citation[],
  onMiss: (cite: Citation) => void,
): HastNode[] | null {
  const value = node.value ?? "";
  const start = node.position!.start.offset!;

  const hits: { at: number; cite: Citation }[] = [];
  for (const cite of citations) {
    const at = locate(value, cite.marker, cite.offset - start);
    if (at === -1) {
      // **억지로 만들지 않는다.** 여기서 근사 위치에 그냥 걸면 엉뚱한 글자가 링크가 된다.
      onMiss(cite);
      continue;
    }
    hits.push({ at, cite });
  }
  if (!hits.length) return null;

  hits.sort((a, b) => a.at - b.at);

  const out: HastNode[] = [];
  let cursor = 0;
  for (const { at, cite } of hits) {
    // 앞 인용과 겹치면 건너뛴다 (같은 글자에 링크 둘을 걸 수 없다).
    if (at < cursor) continue;
    if (at > cursor) out.push({ type: "text", value: value.slice(cursor, at) });
    out.push({
      type: "element",
      tagName: "span",
      properties: {
        className: ["citation"],
        [CITATION_ATTR]: JSON.stringify(cite),
      },
      children: [{ type: "text", value: cite.marker }],
    });
    cursor = at + cite.marker.length;
  }
  if (cursor < value.length) out.push({ type: "text", value: value.slice(cursor) });
  return out;
}

/** react-markdown 의 `rehypePlugins` 에 넣는다. */
export function rehypeCitations(
  citations: Citation[],
  onMiss: (cite: Citation) => void,
) {
  return () => (tree: HastNode) => {
    if (!citations.length) return;

    const walk = (node: HastNode) => {
      const children = node.children;
      if (!children) return;
      // **뒤에서부터 돈다.** 앞에서부터 splice 하면 뒤 인덱스가 밀린다.
      for (let i = children.length - 1; i >= 0; i -= 1) {
        const child = children[i];
        if (child.type === "text") {
          const mine = citationsIn(child, citations);
          if (!mine.length) continue;
          const replacement = split(child, mine, onMiss);
          if (replacement) children.splice(i, 1, ...replacement);
        } else {
          walk(child);
        }
      }
    };

    walk(tree);
  };
}
