/**
 * HTML 에서 글자만 뽑는다 — 마이페이지 목록의 한두 줄 요약용(레퍼런스 lib/html-text.ts 와 같은 규칙).
 *
 * 결과는 React 가 텍스트로 그리므로(자동 이스케이프) 정화가 필요 없다. 그래서 sanitize-html 을 부르는
 * lib/sanitize.ts 대신 이것을 쓴다 — 목록 화면 번들에 HTML 파서가 들어가지 않게.
 * 결과를 dangerouslySetInnerHTML 에 넣지 말 것.
 */

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
};

function decodeEntity(entity: string, body: string): string {
  if (body.startsWith("#")) {
    const code = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
    return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : entity;
  }
  return NAMED_ENTITIES[body.toLowerCase()] ?? entity;
}

export function htmlToText(html: string | null | undefined): string {
  return (html ?? "")
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, decodeEntity)
    .replace(/\s+/g, " ")
    .trim();
}

const HTML_TAG = /<\/?[a-z][^>]*>/i;

/**
 * 후기 · 문의 본문 보이기용 — 에디터 HTML 이면 글자만 뽑고(태그를 글자로 찍지 않게),
 * 글자로 쓴 본문은 그대로 둬서 whitespace-pre-wrap 의 줄바꿈이 남는다.
 */
export function contentText(value: string | null | undefined): string {
  const text = value ?? "";
  return HTML_TAG.test(text) ? htmlToText(text) : text;
}
