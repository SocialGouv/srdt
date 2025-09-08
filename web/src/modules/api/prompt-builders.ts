import { ChunkResult } from "../../types";

// Helper to format chunks for display
export const formatChunks = (chunks: ChunkResult[]) => {
  return chunks
    .map(
      (chunk) => `Source: ${chunk.metadata.source} (${chunk.metadata.url})
Contenu: ${chunk.content}
---`
    )
    .join("\n");
};

// Helper to create knowledge base content for system prompt
export const createKnowledgeBaseContent = (
  fichesOfficiellesChunks: ChunkResult[],
  codeDuTravailChunks: ChunkResult[],
  idccChunks?: ChunkResult[]
) => {
  let content = `# Base de connaissance externe
3 types de documents sont ajoutés dans la base de connaissance externe

## Fiches officielles (1 à 10 extraits) :

Sources : Fiches des services publics, fiches du ministère du travail, contributions des pages du Code du travail numérique.

Caractéristiques : Ces articles sont rédigés ou validés par des professionnels du droit et offrent une synthèse fiable.

${formatChunks(fichesOfficiellesChunks)}

## Code du travail (1 à 5 extraits) :

Sources : Sections entières du Code du travail.

Caractéristiques : Textes légaux officiels.

Utilisation : Citer explicitement la référence de l'article (ex. : « Article L. 1234-1 ») et l'extrait pertinent dans la réponse. Inclure la source dans la section « Références » avec le titre, l'extrait et l'URL.

${formatChunks(codeDuTravailChunks)}`;

  if (idccChunks && idccChunks.length > 0) {
    content += `

## Conventions collectives (1 à 5 extraits, si applicable) :

Sources : Pages du Code du travail numérique dédiées aux conventions collectives.

Caractéristiques : Spécifiques à la convention collective mentionnée par l'utilisateur (via son IDCC).

Utilisation : Utiliser ces sources uniquement si l'utilisateur a fourni l'IDCC de sa convention collective. Inclure un paragraphe dédié dans la réponse et un lien vers la convention collective dans la conclusion.

${formatChunks(idccChunks)}`;
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

// Helper to create follow-up chat history with context from previous conversation
export const createFollowupChatHistory = (
  query1: string,
  answer1: string,
  query2: string
) => [
  {
    role: "user" as const,
    content: `Contexte - Question initiale: "${query1}"`,
  },
  {
    role: "assistant" as const,
    content: `Première réponse: "${answer1}"`,
  },
  {
    role: "user" as const,
    content: `Nouvelle question ou retour: "${query2}"`,
  },
];

// Helper to create follow-up IDCC chat history
export const createFollowupIdccChatHistory = (
  query1: string,
  answer1: string,
  query2: string
) => [
  {
    role: "user" as const,
    content: `Contexte - Question initiale: "${query1}"`,
  },
  {
    role: "assistant" as const,
    content: `Première réponse: "${answer1}"`,
  },
  {
    role: "user" as const,
    content: `Nouvelle question ou retour: "${query2}"`,
  },
];
