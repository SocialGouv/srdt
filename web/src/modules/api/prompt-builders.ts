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

// Helper to create chat history for generation
export const createChatHistory = (
  query: string,
  localSearchChunks: ChunkResult[]
) => [
  {
    role: "user" as const,
    content: query,
  },
  {
    role: "user" as const,
    content: `Voici les sources pertinentes pour répondre à la question:

        ${formatChunks(localSearchChunks)}`,
  },
];

// Helper to create IDCC-specific chat history with both general and IDCC chunks
export const createIdccChatHistory = (
  query: string,
  generalChunks: ChunkResult[],
  idccChunks: ChunkResult[]
) => [
  {
    role: "user" as const,
    content: query,
  },
  {
    role: "user" as const,
    content: ` 2 types de documents sont ajoutées dans la base de connaissance externe :

### Documents généralistes :
${formatChunks(generalChunks)}

### Documents spécifiques à la convention collective renseignée :
${formatChunks(idccChunks)}`,
  },
];

// Helper to create follow-up chat history with context from previous conversation
export const createFollowupChatHistory = (
  query1: string,
  answer1: string,
  query2: string,
  generalChunks: ChunkResult[]
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
  {
    role: "user" as const,
    content: `Voici les sources pertinentes pour répondre à la nouvelle question:

        ${formatChunks(generalChunks)}`,
  },
];

// Helper to create follow-up IDCC chat history
export const createFollowupIdccChatHistory = (
  query1: string,
  answer1: string,
  query2: string,
  generalChunks: ChunkResult[],
  idccChunks: ChunkResult[]
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
  {
    role: "user" as const,
    content: ` 2 types de documents sont ajoutées dans la base de connaissance externe :

### Documents généralistes :
${formatChunks(generalChunks)}

### Documents spécifiques à la convention collective renseignée :
${formatChunks(idccChunks)}`,
  },
];
