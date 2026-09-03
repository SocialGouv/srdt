import { ChunkResult } from "@/types";
import { MessageSource } from "./types";

/** Characters kept for a source preview (about two lines in the panel). */
export const SOURCE_EXCERPT_MAX_LENGTH = 140;
/** Upper bound on the sources persisted with a single message. */
export const MAX_SOURCES_PER_MESSAGE = 25;

/** Panel label for each search collection (see `Collection` in constants). */
const SOURCE_LABELS: Record<string, string> = {
  contributions: "Code du travail numérique",
  contributions_idcc: "Code du travail numérique",
  information: "Code du travail numérique",
  fiches_service_public: "Service Public",
  page_fiche_ministere_travail: "Travail emploi",
  code_du_travail: "Code du travail",
};

// Every indexed document is served by the Code du travail numérique, so it is
// the safe default when a collection has no dedicated label.
export const getSourceLabel = (source: string): string =>
  SOURCE_LABELS[source] ?? "Code du travail numérique";

// Plain-text preview: collapse whitespace, drop markdown markers, cut on a
// word boundary.
const toExcerpt = (content: string): string => {
  const text = content
    .replace(/[#*`]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length <= SOURCE_EXCERPT_MAX_LENGTH) return text;
  const cut = text.slice(0, SOURCE_EXCERPT_MAX_LENGTH);
  const lastSpace = cut.lastIndexOf(" ");
  const clean =
    lastSpace > SOURCE_EXCERPT_MAX_LENGTH / 2 ? cut.slice(0, lastSpace) : cut;
  return `${clean}…`;
};

/**
 * Reduce the search chunks given to the LLM to the lightweight, deduplicated
 * list stored with the assistant message. Only what the sources panel shows
 * is kept: the full document contents never reach localStorage.
 */
export const toMessageSources = (chunks: ChunkResult[]): MessageSource[] => {
  const seen = new Set<string>();
  const sources: MessageSource[] = [];

  for (const chunk of chunks) {
    const { id, title, url, source } = chunk.metadata;
    const key = id || url;
    if (!key || seen.has(key)) continue;
    seen.add(key);

    sources.push({
      id,
      title,
      url,
      source,
      excerpt: toExcerpt(chunk.content ?? ""),
    });

    if (sources.length >= MAX_SOURCES_PER_MESSAGE) break;
  }

  return sources;
};

// Loose URL comparison: the answer may link to a section (#anchor) or omit
// the trailing slash while the index stores the canonical page URL.
const normalizeUrl = (url: string): string =>
  url
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/^www\./i, "")
    .replace(/[#?].*$/, "")
    .replace(/\/+$/, "")
    .toLowerCase();

/** Normalized URLs of every markdown link in an answer. */
export const extractLinkedUrls = (markdown: string): Set<string> => {
  const urls = new Set<string>();
  const linkPattern = /\]\(\s*(https?:\/\/[^)\s]+)\s*\)/g;
  let match: RegExpExecArray | null;
  while ((match = linkPattern.exec(markdown)) !== null) {
    urls.add(normalizeUrl(match[1]));
  }
  return urls;
};

/**
 * Split the sources between those the answer links to ("cited") and the
 * other documents the LLM was given, preserving the original order.
 */
export const splitSourcesByCitation = (
  sources: MessageSource[],
  answer: string
): { cited: MessageSource[]; others: MessageSource[] } => {
  const linked = extractLinkedUrls(answer);
  const cited: MessageSource[] = [];
  const others: MessageSource[] = [];

  for (const source of sources) {
    (linked.has(normalizeUrl(source.url)) ? cited : others).push(source);
  }

  return { cited, others };
};
