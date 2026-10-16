import * as Sentry from "@sentry/nextjs";
import { JURISPRUDENCE_FILTER_LLM } from "@/constants";
import { ChunkResult } from "../../types";
import { generate } from "./client";
import { JURISPRUDENCE_FILTER_INSTRUCTION } from "@/prompts";
import { formatChunks } from "./prompt-builders";

// Lit le verdict du LLM : true pour OUI, false pour NON, null si la réponse ne
// commence ni par l'un ni par l'autre.
export const parseVerdict = (text: string): boolean | null => {
  const verdict = text.trim().match(/^\W*(OUI|NON)\b/i);
  return verdict ? verdict[1].toUpperCase() === "OUI" : null;
};

const isRelevant = async (
  question: string,
  chunk: ChunkResult
): Promise<boolean> => {
  const request = {
    model: JURISPRUDENCE_FILTER_LLM,
    system_prompt: JURISPRUDENCE_FILTER_INSTRUCTION,
    chat_history: [
      {
        role: "user" as const,
        content: `Question : ${question}\n\nArrêt :\n${formatChunks([chunk])}\n\nRépondez uniquement par OUI ou NON.`,
      },
    ],
  };

  let result = await generate(request);
  if (result.error || !result.data) {
    result = await generate(request);
  }

  if (result.error || !result.data) {
    Sentry.captureException(
      new Error(
        `Erreur lors du filtre jurisprudence: ${result.error ?? "réponse vide"}`
      ),
      { extra: { query: question, url: chunk.metadata.url } }
    );
    return true;
  }

  const verdict = parseVerdict(result.data.text);
  if (verdict === null) {
    Sentry.captureMessage(
      `Réponse invalide du filtre jurisprudence: ${result.data.text.slice(0, 200)}`,
      { extra: { query: question, url: chunk.metadata.url } }
    );
    return false;
  }
  return verdict;
};

// Filtre LLM des jurisprudences : un appel par arrêt (en parallèle), le LLM répond
// OUI/NON selon que l'arrêt permet ou non de répondre à la question. On ne garde que
// les OUI. En cas d'erreur d'appel, on réessaie une fois ; si l'erreur persiste,
// l'arrêt est conservé (comme si la réponse était OUI). Une réponse qui ne commence
// ni par OUI ni par NON est signalée à Sentry et l'arrêt est écarté.
export const filterJurisprudence = async (
  question: string,
  chunks: ChunkResult[]
): Promise<ChunkResult[]> => {
  const verdicts = await Promise.all(
    chunks.map((chunk) => isRelevant(question, chunk))
  );
  return chunks.filter((_, i) => verdicts[i]);
};
