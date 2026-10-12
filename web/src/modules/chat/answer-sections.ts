/**
 * Splits a rendered answer into its sections so that one of them can be
 * copied on its own. The LLM is asked (see constants.ts) to structure its
 * answers with numbered headings ("### 1. Reformulation", "### 2. Réponse
 * générale", "### 5. Conclusion"…), so the sections are read from the
 * headings of the rendered markdown. What precedes the first heading is not
 * a section: it is only part of the full answer.
 */
export interface AnswerSection {
  /** Heading text without its numbering, e.g. "Réponse générale". */
  label: string;
  /** Rendered elements of the section body, heading excluded. */
  elements: HTMLElement[];
}

/** Longest text still taken as a title when it is only a bold line. */
const MAX_BOLD_TITLE_LENGTH = 80;

const isHeading = (el: Element) => /^H[1-6]$/.test(el.tagName);

/** A line such as `**Réponse générale**` renders as a paragraph holding only a <strong>. */
const isBoldLine = (el: Element) =>
  el.tagName === "P" &&
  el.childNodes.length === 1 &&
  el.firstElementChild?.tagName === "STRONG" &&
  (el.textContent ?? "").trim().length <= MAX_BOLD_TITLE_LENGTH;

/** "2. Réponse générale :" → "Réponse générale" */
function toLabel(text: string): string {
  return text
    .replace(/^\s*\d+\s*[.)\-–:]\s*/, "")
    .replace(/\s*:\s*$/, "")
    .trim();
}

export function getAnswerSections(root: HTMLElement): AnswerSection[] {
  const children = Array.from(root.children) as HTMLElement[];
  // Bold-only lines count as titles only when the answer has no real heading.
  const isTitle = children.some(isHeading) ? isHeading : isBoldLine;

  const sections: AnswerSection[] = [];
  let current: AnswerSection | null = null;
  for (const el of children) {
    if (isTitle(el)) {
      current = { label: toLabel(el.textContent ?? ""), elements: [] };
      sections.push(current);
    } else if (current) {
      current.elements.push(el);
    }
  }
  return sections.filter(
    (section) => section.label !== "" && section.elements.length > 0
  );
}
