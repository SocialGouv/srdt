import {
  Config,
  getRandomModel,
  PROMPT_INSTRUCTIONS,
  SEARCH_OPTIONS_LOCAL,
  MAX_RERANK,
  K_RERANK,
  K_RERANK_IDCC,
  K_RERANK_FOLLOWUP_QUERY1,
  K_RERANK_FOLLOWUP_QUERY2,
  K_RERANK_IDCC_FOLLOWUP,
} from "@/constants";
import {
  AnonymizeResponse,
  RephraseResponse,
  ChunkResult,
  LLMModel,
  RerankResult,
  InstructionPrompts,
} from "../../types";
import * as Sentry from "@sentry/nextjs";
import {
  UseApiResponse,
  anonymize,
  getIdccChunks,
  search,
  rerank,
} from "./client";

export interface PreparedQuestionData {
  query: string;
  model: LLMModel;
  config: Config;
  instructions: {
    generate_instruction: string;
    generate_instruction_idcc: string;
    anonymisation?: string;
    reformulation?: string;
    split_multiple_queries?: string;
    generate_instruction_short_answer?: string;
    generate_instruction_idcc_short_answer?: string;
  };
  localSearchChunks: ChunkResult[];
  idccChunks: ChunkResult[];
  anonymizeResult?: UseApiResponse<AnonymizeResponse>;
  rephraseResult?: UseApiResponse<RephraseResponse>;
  answerType: "long" | "short";
}

export interface PreparedFollowupQuestionData {
  query1: string;
  query2: string;
  model: LLMModel;
  config: Config;
  instructions: InstructionPrompts;
  generalChunksQuery1: ChunkResult[];
  generalChunksQuery2: ChunkResult[];
  idccChunksQuery1: ChunkResult[];
  idccChunksQuery2: ChunkResult[];
}

// Helper function to merge chunks by document ID
const mergeChunksByDocumentId = (chunks: ChunkResult[]): ChunkResult[] => {
  const toRerankRecord = chunks
    .sort((a, b) => b.score - a.score)
    .reduce((acc: Record<string, ChunkResult>, curr: ChunkResult) => {
      const id = curr.metadata.document_id;
      if (!acc[id]) {
        acc[id] = curr;
      } else {
        acc[id].content = acc[id].content.concat("\n\n" + curr.content);
      }
      return acc;
    }, {} as Record<string, ChunkResult>);

  return Object.values(toRerankRecord);
};

// Common preprocessing logic for both streaming and non-streaming
export const prepareQuestionData = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
): Promise<PreparedQuestionData> => {
  const config = requiredConfig || Config.V1_15;
  const instructions = PROMPT_INSTRUCTIONS[config];
  const model = getRandomModel();

  let anonymizeResult: UseApiResponse<AnonymizeResponse> | undefined =
    undefined;

  // rephrased disabled teporarly
  // eslint-disable-next-line prefer-const
  let rephraseResult: UseApiResponse<RephraseResponse> | undefined = undefined;

  anonymizeResult = await anonymize({
    user_question: userQuestion,
  });

  if (anonymizeResult.error) {
    throw new Error(`Erreur lors de l'anonymisation: ${anonymizeResult.error}`);
  }

  if (!anonymizeResult.data) {
    throw new Error("Erreur lors de l'anonymisation");
  }

  const anonymized = anonymizeResult.data.anonymized_question;

  let rerankedIdcc: RerankResult[] = [];

  // retrieve all IDCC content then rerank them
  if (idcc) {
    const idccSearchResult = await getIdccChunks(idcc);

    if (idccSearchResult.error) {
      const searchError = new Error(
        `Erreur lors de la recherche IDCC: ${idccSearchResult.error}`
      );
      Sentry.captureException(searchError, {
        extra: {
          idcc: idcc,
          hasTopChunks: !!idccSearchResult.data?.top_chunks,
        },
      });
      console.error(`Erreur lors de la recherche: ${idccSearchResult.error}`);
    } else {
      const inputs = idccSearchResult.data?.top_chunks.slice(0, MAX_RERANK);
      const idccRerankResults = await rerank({
        prompt: userQuestion,
        inputs: inputs || [],
      });

      if (idccRerankResults.data) {
        rerankedIdcc = idccRerankResults.data.results;
      }
    }
  }

  const localSearchResult = await search({
    prompts: [anonymized],
    options: SEARCH_OPTIONS_LOCAL,
  });

  if (localSearchResult.error) {
    const localSearchError = new Error(
      `Erreur lors de la recherche locale: ${localSearchResult.error}`
    );
    Sentry.captureException(localSearchError, {
      extra: {
        query: anonymized,
        searchOptions: SEARCH_OPTIONS_LOCAL,
      },
    });
    console.error(`Erreur lors de la recherche: ${localSearchResult.error}`);
  }

  const localSearchChunks = localSearchResult.data?.top_chunks ?? [];

  if (localSearchChunks.length === 0) {
    Sentry.captureMessage("No search results found", {
      level: "warning",
      extra: {
        query: anonymized,
        userQuestion: userQuestion,
      },
    });
    console.warn("Aucun résultat de recherche trouvé");
  }

  // merge chunks if they come from the same document
  const toRerankChunks = mergeChunksByDocumentId(localSearchChunks).slice(
    0,
    MAX_RERANK
  );

  const searchRerankResults = await rerank({
    prompt: anonymized,
    inputs: toRerankChunks,
  });

  if (!searchRerankResults.data) {
    Sentry.captureMessage("No rerank results found", {
      level: "warning",
      extra: {
        userQuestion: anonymized,
        toRerankChunks: toRerankChunks.length,
      },
    });
    console.warn("Aucun résultat de recherche trouvé après le rerank");
  }

  const rerankedToChunk = ({
    chunk,
    rerank_score,
  }: RerankResult): ChunkResult => ({
    ...chunk,
    rerank_score,
  });

  // take top k rerank for the generate step (keep general chunks separate)
  const selectedGeneralChunks =
    searchRerankResults.data?.results.slice(0, K_RERANK).map(rerankedToChunk) ||
    [];

  const selectedIdccChunks =
    rerankedIdcc.slice(0, K_RERANK_IDCC).map(rerankedToChunk) || [];

  if (selectedGeneralChunks.length === 0 && selectedIdccChunks.length === 0) {
    Sentry.captureMessage("No chunks selected for generation", {
      level: "warning",
      extra: {
        userQuestion: anonymized,
        generalChunksLength: selectedGeneralChunks.length,
        idccChunksLength: selectedIdccChunks.length,
      },
    });
    console.warn("Aucun résultat de recherche trouvé");
  }

  const answerType = Math.random() < 0.5 ? "long" : "short";

  return {
    query: anonymized,
    model,
    config,
    instructions,
    localSearchChunks: selectedGeneralChunks,
    idccChunks: selectedIdccChunks,
    anonymizeResult,
    rephraseResult,
    answerType,
  };
};

// Prepare data for follow-up question analysis
export const prepareFollowupQuestionData = async (
  query1: string,
  query2: string,
  requiredConfig?: Config,
  idcc?: string,
  providedModel?: LLMModel
): Promise<PreparedFollowupQuestionData> => {
  const config = requiredConfig || Config.V1_15;
  const instructions = PROMPT_INSTRUCTIONS[config];
  const model = providedModel || getRandomModel(); // Use provided model or fallback to random

  // Search for query1 (top 5)
  const searchResultQuery1 = await search({
    prompts: [query1],
    options: SEARCH_OPTIONS_LOCAL,
  });

  if (searchResultQuery1.error) {
    console.error(
      `Erreur lors de la recherche query1: ${searchResultQuery1.error}`
    );
  }

  const localSearchChunksQuery1 = searchResultQuery1.data?.top_chunks ?? [];

  // Merge chunks from same document for query1
  const toRerankChunksQuery1 = mergeChunksByDocumentId(
    localSearchChunksQuery1
  ).slice(0, MAX_RERANK);

  // Rerank for query1
  const rerankResultQuery1 = await rerank({
    prompt: query1,
    inputs: toRerankChunksQuery1,
  });

  const rerankedQuery1 = rerankResultQuery1.data?.results || [];

  // Search for query2 (top 10)
  const searchResultQuery2 = await search({
    prompts: [query2],
    options: SEARCH_OPTIONS_LOCAL,
  });

  if (searchResultQuery2.error) {
    console.error(
      `Erreur lors de la recherche query2: ${searchResultQuery2.error}`
    );
  }

  const localSearchChunksQuery2 = searchResultQuery2.data?.top_chunks ?? [];

  // Merge chunks from same document for query2
  const toRerankChunksQuery2 = mergeChunksByDocumentId(
    localSearchChunksQuery2
  ).slice(0, MAX_RERANK);

  // Rerank for query2
  const rerankResultQuery2 = await rerank({
    prompt: query2,
    inputs: toRerankChunksQuery2,
  });

  const rerankedQuery2 = rerankResultQuery2.data?.results || [];

  // Convert rerank results to chunks
  const rerankedToChunk = ({
    chunk,
    rerank_score,
  }: RerankResult): ChunkResult => ({
    ...chunk,
    rerank_score,
  });

  const selectedGeneralChunksQuery1 = rerankedQuery1
    .slice(0, K_RERANK_FOLLOWUP_QUERY1)
    .map(rerankedToChunk);

  const selectedGeneralChunksQuery2 = rerankedQuery2
    .slice(0, K_RERANK_FOLLOWUP_QUERY2)
    .map(rerankedToChunk);

  // Handle IDCC chunks if applicable
  let selectedIdccChunksQuery1: ChunkResult[] = [];
  let selectedIdccChunksQuery2: ChunkResult[] = [];

  if (idcc) {
    // Get all IDCC content
    const idccSearchResult = await getIdccChunks(idcc);

    if (idccSearchResult.error) {
      console.error(
        `Erreur lors de la recherche IDCC: ${idccSearchResult.error}`
      );
    } else if (idccSearchResult.data?.top_chunks) {
      // Rerank IDCC chunks for query1
      const idccRerankResultQuery1 = await rerank({
        prompt: query1,
        inputs: idccSearchResult.data.top_chunks.slice(0, MAX_RERANK),
      });

      if (idccRerankResultQuery1.data) {
        selectedIdccChunksQuery1 = idccRerankResultQuery1.data.results
          .slice(0, K_RERANK_IDCC_FOLLOWUP)
          .map(rerankedToChunk);
      }

      // Rerank IDCC chunks for query2
      const idccRerankResultQuery2 = await rerank({
        prompt: query2,
        inputs: idccSearchResult.data.top_chunks.slice(0, MAX_RERANK),
      });

      if (idccRerankResultQuery2.data) {
        selectedIdccChunksQuery2 = idccRerankResultQuery2.data.results
          .slice(0, K_RERANK_IDCC_FOLLOWUP)
          .map(rerankedToChunk);
      }
    }
  }

  return {
    query1,
    query2,
    model,
    config,
    instructions,
    generalChunksQuery1: selectedGeneralChunksQuery1,
    generalChunksQuery2: selectedGeneralChunksQuery2,
    idccChunksQuery1: selectedIdccChunksQuery1,
    idccChunksQuery2: selectedIdccChunksQuery2,
  };
};
