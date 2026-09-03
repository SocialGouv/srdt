import type { AnswerReference, ChunkResult } from "@/types";
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

/** Panel groups, in display order. */
export const SOURCE_CATEGORIES: { key: SourceCategory; label: string }[] = [
  { key: "fiches", label: "Fiches pratiques" },
  { key: "articles", label: "Articles de loi" },
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
 * - Fiches pratiques: code.travail.gouv.fr pages, except the contribution
 *   pages dedicated to one agreement;
 * - Articles de loi: legifrance.gouv.fr/codes;
 * - Conventions collectives: agreement-specific contribution pages (slug
 *   prefixed by the IDCC number) and legifrance.gouv.fr/conv_coll;
 * - Arrêts: courdecassation.fr.
 * A generic contribution page (no IDCC prefix) answers for every agreement,
 * so it reads as a fiche pratique.
 */
export const getSourceCategory = (url: string): SourceCategory => {
  const path = stripOrigin(url);
  if (path.startsWith("code.travail.gouv.fr/")) {
    return /^code\.travail\.gouv\.fr\/contribution\/\d+-/.test(path)
      ? "conventions"
      : "fiches";
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

// ---- Helpers --------------------------------------------------------------

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

// Loose URL comparison: the answer may link to a section (#anchor) or omit
// the trailing slash while the index stores the canonical page URL.
const normalizeUrl = (url: string): string =>
  stripOrigin(url)
    .replace(/[#?].*$/, "")
    .replace(/\/+$/, "");

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

const articleIdFromUrl = (url: string): string | undefined =>
  /(LEGIARTI\d+)/.exec(url)?.[1];

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

// ---- Message sources ------------------------------------------------------

/**
 * Build the lightweight sources persisted with an assistant message from the
 * links the API reports in the answer (`references`), enriched with the
 * documents that were given to the LLM (`chunks`): title and excerpt when a
 * link matches a retrieved document, the article text when a rebuilt Code du
 * travail link sits in a retrieved section. Removed links are only counted
 * (see `countRemovedLinks`). Full document contents never reach localStorage.
 */
export const toMessageSources = (
  chunks: ChunkResult[],
  references: AnswerReference[]
): MessageSource[] => {
  const documents = groupByDocument(chunks);
  const byUrl = new Map(documents.map((d) => [normalizeUrl(d.url), d]));
  const byId = new Map(documents.map((d) => [d.id, d]));

  const seen = new Set<string>();
  const sources: MessageSource[] = [];

  for (const reference of references) {
    if (reference.status === "removed") continue;
    const key = normalizeUrl(reference.url);
    if (!key || seen.has(key)) continue;
    seen.add(key);

    if (reference.status === "rebuilt") {
      // Article link rebuilt by the API from an article number. Its excerpt
      // is the article text, looked up in the section the API points to (or
      // in every retrieved document when it does not say).
      const section = reference.section_id
        ? byId.get(reference.section_id)
        : undefined;
      const candidates = section ? [section] : documents;
      const num = reference.num;
      const text = num
        ? candidates
            .flatMap((d) => d.contents)
            .map((content) => findArticleText(content, num))
            .find(Boolean)
        : undefined;

      sources.push({
        id: articleIdFromUrl(reference.url) ?? reference.url,
        title: /^\s*article/i.test(reference.text)
          ? reference.text.trim()
          : `Article ${reference.text.trim()}`,
        url: reference.url,
        excerpt: text ? toExcerpt(text) : "",
        ...(reference.in_context === false ? { inContext: false } : {}),
      });
    } else {
      const document = byUrl.get(key);
      sources.push({
        id: document?.id ?? reference.url,
        title: document?.title ?? reference.text.trim(),
        url: reference.url,
        excerpt: document ? toExcerpt(document.contents[0]) : "",
      });
    }

    if (sources.length >= MAX_SOURCES_PER_MESSAGE) break;
  }

  return sources;
};

/** Links the API stripped from the answer because they could not be verified. */
export const countRemovedLinks = (references: AnswerReference[]): number =>
  references.filter((reference) => reference.status === "removed").length;
