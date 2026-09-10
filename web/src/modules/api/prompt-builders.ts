import { Collection } from "@/constants";
import { ChunkResult } from "../../types";

// Judilibre indexe un titre = hiérarchie de titrage brute ("CONTRAT DE TRAVAIL, RUPTURE,...").
// Pour citer la décision dans le prompt generate, on préfère son numéro de pourvoi et sa date
// ("Arrêt numéro 21-12.345 du 10/05/2023") ; à défaut, on se rabat sur un libellé générique +
// l'identifiant de la décision. L'URL courdecassation reste le lien exact.
// Tolérant au runtime : decision_date / number peuvent être absents ou non-string
// dans le payload de l'API (ex. tableau pour des pourvois joints).
const formatDecisionDate = (raw?: unknown): string | null => {
  if (typeof raw !== "string" || !raw) return null;
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return raw;
  const [, year, month, day] = match;
  return `${day}/${month}/${year}`;
};

const chunkTitle = (chunk: ChunkResult) => {
  if (chunk.metadata.source !== Collection.JUDILIBRE) {
    return chunk.metadata.title;
  }
  const { number, decision_date } = chunk.metadata;
  const formattedDate = formatDecisionDate(decision_date);
  if (typeof number === "string" && number && formattedDate) {
    return `Arrêt numéro ${number} du ${formattedDate}`;
  }
  // Fallback : numéro/date absents de la base -> identifiant de la décision.
  // metadata.id = "<decision_id>-<index>" ; on privilégie initial_id (= decision_id)
  const decisionId =
    chunk.metadata.initial_id ?? chunk.metadata.id.replace(/-\d+$/, "");
  return `Arrêt de la Cour de cassation (réf. ${decisionId})`;
};

// Helper to format chunks for display
export const formatChunks = (chunks: ChunkResult[]) => {
  return chunks
    .map(
      (chunk) => `Source: ${chunk.metadata.source} (${chunk.metadata.url})
Titre: ${chunkTitle(chunk)}
Contenu: ${chunk.content}
---`
    )
    .join("\n");
};

// Helper to create knowledge base content for system prompt
export const createKnowledgeBaseContent = (
  fichesOfficiellesChunks: ChunkResult[],
  codeDuTravailChunks: ChunkResult[],
  idccChunks?: ChunkResult[],
  jurisprudenceChunks?: ChunkResult[]
) => {
  let content = `# Base de connaissance externe
Plusieurs types de documents sont ajoutés dans la base de connaissance externe

## Fiches officielles (1 à 10 extraits) :

Sources : Fiches des services publics, fiches du ministère du travail, contributions des pages du Code du travail numérique.

Caractéristiques : Ces articles sont rédigés ou validés par des professionnels du droit et offrent une synthèse fiable.

${formatChunks(fichesOfficiellesChunks)}

## Code du travail (1 à 5 extraits) :

Sources : Sections entières du Code du travail.

Caractéristiques : Textes légaux officiels.

${formatChunks(codeDuTravailChunks)}`;

  if (idccChunks && idccChunks.length > 0) {
    content += `

## Conventions collectives (1 à 5 extraits, si applicable) :

Sources : Pages du Code du travail numérique dédiées aux conventions collectives.

Caractéristiques : Spécifiques à la convention collective mentionnée par l'utilisateur (via son IDCC).

Utilisation : Utiliser ces sources uniquement si l'utilisateur a fourni l'IDCC de sa convention collective. Inclure un paragraphe dédié dans la réponse et un lien vers la convention collective dans la conclusion.

${formatChunks(idccChunks)}`;
  }

  if (jurisprudenceChunks && jurisprudenceChunks.length > 0) {
    content += `

## Jurisprudence (0 à 5 extraits) :

Sources : Décisions de la Cour de cassation, chambre sociale, publiées au bulletin (sommaires).

Caractéristiques : Décisions faisant autorité. Base **complémentaire** : la réponse se fonde d'abord sur les fiches officielles et le Code du travail. N'utiliser ces extraits que selon les règles de la section "⚖️ Jurisprudence" des instructions (contradiction, précision, ou seule source disponible). Sinon, ne pas les mentionner.

${formatChunks(jurisprudenceChunks)}`;
  }

  return content;
};

// Helper to create chat history for generation with separate source types
export const createChatHistory = (query: string) => [
  {
    role: "user" as const,
    content: query,
  },
];

// Helper to create IDCC-specific chat history with three source types
export const createIdccChatHistory = (query: string) => [
  {
    role: "user" as const,
    content: query,
  },
];

export interface ConversationHistoryEntry {
  question: string;
  answer: string;
}

// Helper to create follow-up chat history with full conversation context
export const createFollowupChatHistory = (
  conversationHistory: ConversationHistoryEntry[],
  newQuestion: string
) => {
  const messages: { role: "user" | "assistant"; content: string }[] = [];

  conversationHistory.forEach((entry, index) => {
    if (index === 0) {
      messages.push({
        role: "user" as const,
        content: `Contexte - Question initiale: "${entry.question}"`,
      });
      messages.push({
        role: "assistant" as const,
        content: `Première réponse: "${entry.answer}"`,
      });
    } else {
      messages.push({
        role: "user" as const,
        content: `Question de suivi: "${entry.question}"`,
      });
      messages.push({
        role: "assistant" as const,
        content: `Réponse: "${entry.answer}"`,
      });
    }
  });

  messages.push({
    role: "user" as const,
    content: `Nouvelle question ou retour: "${newQuestion}"`,
  });

  return messages;
};

// Helper to create follow-up IDCC chat history
export const createFollowupIdccChatHistory = (
  conversationHistory: ConversationHistoryEntry[],
  newQuestion: string
) => createFollowupChatHistory(conversationHistory, newQuestion);
