/**
 * Mia Home answers are plain text with line structure (Mia Home response quality, `ask-mia-home-v2`):
 * short paragraphs separated by a blank line and, to list several decisions, one line per decision
 * that starts with "- ". This turns that text into typed BLOCKS the UI renders as `<p>` / `<ul>`.
 *
 * It is deliberately NOT a Markdown renderer: nothing is interpreted (no bold, no links, no HTML,
 * no headings) and no character of the answer is ever dropped except the bullet marker itself and
 * the blank lines between blocks. The text still reaches the DOM only through React children, so it
 * is escaped like any other string. An answer with no line structure comes back as ONE paragraph,
 * i.e. exactly what the Home rendered before this existed.
 */
export type AnswerBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] };

// "- ", "• " and "* " at the start of a line (after optional indentation) mark a list item. The
// space is required, so a negative number ("-3 camere") or a dash inside a sentence is not a bullet.
const BULLET = /^\s*[-•*]\s+(.*\S)\s*$/u;

export function answerBlocksOf(answer: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];
  let items: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  const flushList = () => {
    if (items.length > 0) blocks.push({ kind: "list", items });
    items = [];
  };

  for (const rawLine of answer.replace(/\r\n?/gu, "\n").split("\n")) {
    const line = rawLine.trim();
    if (line === "") {
      flushParagraph();
      flushList();
      continue;
    }
    const bullet = BULLET.exec(rawLine);
    if (bullet !== null) {
      flushParagraph();
      items.push(bullet[1] as string);
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
