import type { ChunkResult } from "@/types";
import type { MessageSource } from "./types";

/** Characters kept for a source preview (about two lines in the panel). */
export const SOURCE_EXCERPT_MAX_LENGTH = 140;
/** Upper bound on the sources persisted with a single message. */
export const MAX_SOURCES_PER_MESSAGE = 25;

// ---- Categories (product spec) --------------------------------------------

export type SourceCategory =
  | "fiches"
  | "articles"
  | "conventions"
  | "cassation"
  | "autres";

/** Panel groups, in display order, with an optional explanation line. */
export const SOURCE_CATEGORIES: {
  key: SourceCategory;
  label: string;
  description?: string;
}[] = [
  { key: "fiches", label: "Fiches pratiques" },
  {
    key: "articles",
    label: "Articles de loi",
    // Article numbers mostly come from the LLM's own knowledge (the indexed
    // fiches carry none), so the excerpt is the only positive proof that the
    // text was in the documents it was given.
    // Not used currently.
    // description: "Articles cités par l’assistant avec un lien vérifié vers Légifrance (un extrait indique que le texte figurait dans les documents de référence).",
  },
  { key: "conventions", label: "Conventions collectives" },
  { key: "cassation", label: "Arrêts de la Cour de cassation" },
  { key: "autres", label: "Autres liens" },
];

// "https://www.code.travail.gouv.fr/x/" → "code.travail.gouv.fr/x/"
const stripOrigin = (url: string): string =>
  url
    .trim()
    .replace(/^https?:\/\//i, "")
    .replace(/^www\./i, "")
    .toLowerCase();

/**
 * Category of a link, from its URL:
 * - Fiches pratiques: code.travail.gouv.fr pages, except agreement pages;
 * - Articles de loi: legifrance.gouv.fr/codes;
 * - Conventions collectives: agreement-specific contribution pages (slug
 *   prefixed by the IDCC number), agreement pages, legifrance.gouv.fr/conv_coll;
 * - Arrêts: courdecassation.fr.
 * A generic contribution page (no IDCC prefix) answers for every agreement,
 * so it reads as a fiche pratique.
 */
export const getSourceCategory = (url: string): SourceCategory => {
  const path = stripOrigin(url);
  if (path.startsWith("code.travail.gouv.fr/")) {
    const isAgreementPage =
      /^code\.travail\.gouv\.fr\/contribution\/\d+-/.test(path) ||
      path.startsWith("code.travail.gouv.fr/convention-collective/");
    return isAgreementPage ? "conventions" : "fiches";
  }
  if (path.startsWith("legifrance.gouv.fr/codes")) return "articles";
  if (path.startsWith("legifrance.gouv.fr/conv_coll")) return "conventions";
  if (path.startsWith("courdecassation.fr/")) return "cassation";
  return "autres";
};

/** Small label shown above a source title: the site or collection it comes from. */
export const getSourceLabel = (url: string): string => {
  const path = stripOrigin(url);
  if (path.startsWith("code.travail.gouv.fr/")) {
    if (path.includes("/fiche-service-public/")) return "Service Public";
    if (path.includes("/fiche-ministere-travail/")) return "Travail emploi";
    if (path.includes("/code-du-travail/")) return "Code du travail";
    return "Code du travail numérique";
  }
  if (path.startsWith("legifrance.gouv.fr/")) return "Légifrance";
  if (path.startsWith("courdecassation.fr/")) return "Cour de cassation";
  return path.split("/")[0] || url;
};

/** Sources grouped by category in display order; empty groups are dropped. */
export const groupSourcesByCategory = (sources: MessageSource[]) =>
  SOURCE_CATEGORIES.map((category) => ({
    ...category,
    sources: sources.filter(
      (source) => getSourceCategory(source.url) === category.key
    ),
  })).filter((group) => group.sources.length > 0);

// ---- Links of an answer ---------------------------------------------------

// Loose URL comparison: the answer may link to a section (#anchor) or omit
// the trailing slash while the index stores the canonical page URL.
const normalizeUrl = (url: string): string =>
  stripOrigin(url)
    .replace(/[#?].*$/, "")
    .replace(/\/+$/, "");

export interface AnswerLink {
  /** Link description as written in the answer. */
  text: string;
  url: string;
}

// The API post-processing leaves plain "[text](url)" links only: validated
// code.travail.gouv.fr pages and Legifrance article links rebuilt from the
// article numbers of the text.
const LINK_PATTERN = /\[([^\]]+)\]\(\s*(https?:\/\/[^)\s]+)\s*\)/g;

/** Links of an answer in order of appearance, one per URL. */
export const extractLinks = (markdown: string): AnswerLink[] => {
  const links = new Map<string, AnswerLink>();
  const pattern = new RegExp(LINK_PATTERN.source, "g");
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(markdown)) !== null) {
    const [, text, url] = match;
    const key = normalizeUrl(url);
    if (!links.has(key)) links.set(key, { text: text.trim(), url });
  }
  return [...links.values()];
};

/**
 * Links the API stripped from the answer because they could not be verified:
 * present in the raw LLM output (the streamed chunks) and absent from the
 * cleaned final text.
 */
export const countRemovedLinks = (
  rawAnswer: string,
  cleanedAnswer: string
): number => {
  const kept = new Set(
    extractLinks(cleanedAnswer).map((link) => normalizeUrl(link.url))
  );
  return extractLinks(rawAnswer).filter(
    (link) => !kept.has(normalizeUrl(link.url))
  ).length;
};

// ---- Code du travail articles ---------------------------------------------

const articleIdFromUrl = (url: string): string | undefined =>
  /legifrance\.gouv\.fr\/codes\/article_lc\/(LEGIARTI\d+)/i.exec(url)?.[1];

/** "L. 1226-1", "l1226-1", "Article L1226-1" → "L1226-1". */
export const normalizeArticleNum = (text: string): string =>
  text
    .replace(/^\s*articles?\s+/i, "")
    .replace(/[.\s]/g, "")
    .toUpperCase();

/**
 * Text of one article inside an ingested Code du travail section, which reads
 * "…\nArticle L1226-1 \n <texte> \n \nArticle L1226-1-1 \n …". The number may
 * be written with a dot or a space after the letter. Returns undefined when
 * the article is not in this chunk.
 */
export const findArticleText = (
  content: string,
  num: string
): string | undefined => {
  const letter = num.charAt(0);
  const digits = num.slice(1).replace(/[^\d-]/g, "");
  if (!letter || !digits) return undefined;
  const pattern = new RegExp(
    `Article\\s+${letter}\\.?\\s?${digits}(?![\\d-])\\s*([\\s\\S]*?)(?=\\n\\s*Article\\s+[LRD]|$)`
  );
  const text = content.match(pattern)?.[1]?.trim();
  return text || undefined;
};

// ---- Retrieved documents --------------------------------------------------

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

interface RetrievedDocument {
  id: string;
  title: string;
  url: string;
  /** Contents of every retrieved chunk of this document, in rank order. */
  contents: string[];
}

// The search returns chunks; several may belong to the same document.
const groupByDocument = (chunks: ChunkResult[]): RetrievedDocument[] => {
  const documents = new Map<string, RetrievedDocument>();
  for (const chunk of chunks) {
    const { id, title, url } = chunk.metadata;
    const key = id || url;
    if (!key) continue;
    const existing = documents.get(key);
    if (existing) {
      existing.contents.push(chunk.content ?? "");
    } else {
      documents.set(key, { id, title, url, contents: [chunk.content ?? ""] });
    }
  }
  return [...documents.values()];
};

// Pages of the indexed collections: the ones the LLM can only know by having
// been given them. Agreement pages and the site root are navigational links
// the prompt itself asks for, so they are never flagged.
const isIndexedDocumentUrl = (url: string): boolean =>
  /^code\.travail\.gouv\.fr\/(fiche-service-public|fiche-ministere-travail|information|contribution|code-du-travail)\//.test(
    stripOrigin(url)
  );

// ---- Message sources ------------------------------------------------------

/**
 * Build the lightweight sources persisted with an assistant message: the
 * links of the (cleaned) answer, enriched with the chunks that were given to
 * the LLM. A link matching a retrieved document gets its title and an
 * excerpt; a Legifrance article link gets the article text when it sits in a
 * retrieved Code du travail chunk (articles are never flagged: their numbers
 * mostly come from the LLM's own knowledge, the excerpt is the positive proof).
 * `inContext` is set to false when the LLM linked an indexed page that was
 * not among the documents it was given. Full document contents never reach
 * localStorage.
 */
export const toMessageSources = (
  chunks: ChunkResult[],
  answer: string
): MessageSource[] => {
  const documents = groupByDocument(chunks);
  const byUrl = new Map(documents.map((d) => [normalizeUrl(d.url), d]));
  const contents = documents.flatMap((d) => d.contents);

  const sources: MessageSource[] = [];

  for (const link of extractLinks(answer)) {
    const articleId = articleIdFromUrl(link.url);

    if (articleId) {
      const num = normalizeArticleNum(link.text);
      const text = contents
        .map((content) => findArticleText(content, num))
        .find(Boolean);
      sources.push({
        id: articleId,
        title: /^\s*article/i.test(link.text)
          ? link.text
          : `Article ${link.text}`,
        url: link.url,
        excerpt: text ? toExcerpt(text) : "",
      });
    } else {
      const document = byUrl.get(normalizeUrl(link.url));
      sources.push({
        id: document?.id ?? link.url,
        title: document?.title ?? link.text,
        url: link.url,
        excerpt: document ? toExcerpt(document.contents[0]) : "",
        ...(!document && isIndexedDocumentUrl(link.url)
          ? { inContext: false }
          : {}),
      });
    }

    if (sources.length >= MAX_SOURCES_PER_MESSAGE) break;
  }

  return sources;
};
