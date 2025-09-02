import {
  Config,
  getRandomModel,
  PROMPT_INSTRUCTIONS,
  SEARCH_OPTIONS_CONTENT,
  MAX_RERANK,
  K_RERANK,
  K_RERANK_IDCC,
  K_RERANK_FOLLOWUP_QUERY1,
  K_RERANK_FOLLOWUP_QUERY2,
  K_RERANK_IDCC_FOLLOWUP,
  SEARCH_OPTIONS_CODE,
  K_RERANK_CODE,
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
  };
  fichesOfficiellesChunks: ChunkResult[];
  codeDuTravailChunks: ChunkResult[];
  idccChunks: ChunkResult[];
  anonymizeResult?: UseApiResponse<AnonymizeResponse>;
  rephraseResult?: UseApiResponse<RephraseResponse>;
}

export interface PreparedFollowupQuestionData {
  query1: string;
  query2: string;
  model: LLMModel;
  config: Config;
  instructions: InstructionPrompts;
  fichesOfficiellesChunksQuery1: ChunkResult[];
  fichesOfficiellesChunksQuery2: ChunkResult[];
  codeDuTravailChunksQuery1: ChunkResult[];
  codeDuTravailChunksQuery2: ChunkResult[];
  idccChunksQuery1: ChunkResult[];
  idccChunksQuery2: ChunkResult[];
}

// Helper function to merge chunks by document ID
const mergeChunksByDocumentId = (chunks: ChunkResult[]): ChunkResult[] => {
  const toRerankRecord = chunks
    .sort((a, b) => b.score - a.score)
    .reduce((acc: Record<string, ChunkResult>, curr: ChunkResult) => {
      const id = curr.metadata.id;
      if (!acc[id]) {
        acc[id] = curr;
      } else {
        acc[id].content = acc[id].content.concat("\n\n" + curr.content);
      }
      return acc;
    }, {} as Record<string, ChunkResult>);

  return Object.values(toRerankRecord);
};

const rerankedToChunk = ({
  chunk,
  rerank_score,
}: RerankResult): ChunkResult => ({
  ...chunk,
  rerank_score,
});

const searchTextContent = async (anonymized: string) => {
  // call search for 256 chunks
  // merge them by source document
  // run rerank on two 64 batches of these merged chunks
  // merge results and take 10 best
  // return full content for these 10

  const localSearchResult = await search({
    prompts: [anonymized],
    options: SEARCH_OPTIONS_CONTENT,
  });

  if (localSearchResult.error) {
    const localSearchError = new Error(
      `Erreur lors de la recherche locale: ${localSearchResult.error}`
    );
    Sentry.captureException(localSearchError, {
      extra: {
        query: anonymized,
        searchOptions: SEARCH_OPTIONS_CONTENT,
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
      },
    });
    console.warn("Aucun résultat de recherche trouvé");
  }

  const mergedChunks = mergeChunksByDocumentId(localSearchChunks).sort(
    (a, b) => b.score - a.score
  );

  const rerankBatch1 = await rerank({
    prompt: anonymized,
    inputs: mergedChunks.slice(0, MAX_RERANK) || [],
  });

  const rerankBatch2 = await rerank({
    prompt: anonymized,
    inputs: mergedChunks.slice(MAX_RERANK, MAX_RERANK * 2) || [],
  });

  if (
    !rerankBatch1.data?.results.length ||
    !rerankBatch2.data?.results.length
  ) {
    Sentry.captureMessage("No rerank results found", {
      level: "warning",
      extra: {
        userQuestion: anonymized,
        toRerankChunks: localSearchChunks,
      },
    });
    console.warn("Aucun résultat de recherche trouvé après le rerank");
  }

  const allReranked = [
    ...(rerankBatch1.data?.results || []),
    ...(rerankBatch2.data?.results || []),
  ].sort((a, b) => b.rerank_score - a.rerank_score);

  return allReranked.slice(0, K_RERANK).map(rerankedToChunk);
};

// get all idcc content and run rerank using user question
// return best 5
const searchIDCC = async (idcc: string, anonymized: string) => {
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

    if (inputs?.length) {
      const idccRerankResults = await rerank({
        prompt: anonymized,
        inputs: inputs,
      });

      if (idccRerankResults.data) {
        return idccRerankResults.data.results
          .slice(0, K_RERANK_IDCC)
          .map(rerankedToChunk);
      }
    }
  }

  return [];
};

const searchArticles = async (anonymized: string) => {
  // call search
  const codeSearchResult = await search({
    prompts: [anonymized],
    options: SEARCH_OPTIONS_CODE,
  });

  // run rerank
  const reranked = await rerank({
    prompt: anonymized,
    inputs: codeSearchResult.data?.top_chunks.slice(0, MAX_RERANK) || [],
  });

  return (
    reranked.data?.results?.slice(0, K_RERANK_CODE).map(rerankedToChunk) || []
  );
};

// Common preprocessing logic for both streaming and non-streaming
export const prepareQuestionData = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
): Promise<PreparedQuestionData> => {
  const config = requiredConfig || Config.V1_16;
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

  let selectedIdccChunks: ChunkResult[] = [];

  if (idcc) {
    // retrieve all IDCC content then rerank them
    selectedIdccChunks = await searchIDCC(idcc, anonymized);
  }

  const selectedFichesOfficiellesChunks = await searchTextContent(anonymized);

  const selectedCodeDuTravailChunks = await searchArticles(anonymized);

  if (
    selectedFichesOfficiellesChunks.length === 0 &&
    selectedCodeDuTravailChunks.length === 0 &&
    selectedIdccChunks.length === 0
  ) {
    Sentry.captureMessage("No chunks selected for generation", {
      level: "warning",
      extra: {
        userQuestion: anonymized,
        fichesOfficiellesChunksLength: selectedFichesOfficiellesChunks.length,
        codeDuTravailChunksLength: selectedCodeDuTravailChunks.length,
        idccChunksLength: selectedIdccChunks.length,
      },
    });
    console.warn("Aucun résultat de recherche trouvé");
  }

  return {
    query: anonymized,
    model,
    config,
    instructions,
    fichesOfficiellesChunks: selectedFichesOfficiellesChunks,
    codeDuTravailChunks: selectedCodeDuTravailChunks,
    idccChunks: selectedIdccChunks,
    anonymizeResult,
    rephraseResult,
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
  const config = requiredConfig || Config.V1_16;
  const instructions = PROMPT_INSTRUCTIONS[config];
  const model = providedModel || getRandomModel(); // Use provided model or fallback to random

  // Search for query1 (top 5)
  const searchResultQuery1 = await search({
    prompts: [query1],
    options: SEARCH_OPTIONS_CONTENT,
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
    options: SEARCH_OPTIONS_CONTENT,
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

  const selectedFichesOfficiellesChunksQuery1 = rerankedQuery1
    .slice(0, K_RERANK_FOLLOWUP_QUERY1)
    .map(rerankedToChunk);

  const selectedFichesOfficiellesChunksQuery2 = rerankedQuery2
    .slice(0, K_RERANK_FOLLOWUP_QUERY2)
    .map(rerankedToChunk);

  // For follow-up questions, we currently don't search Code du Travail articles
  // This could be added in the future if needed
  const selectedCodeDuTravailChunksQuery1: ChunkResult[] = [];
  const selectedCodeDuTravailChunksQuery2: ChunkResult[] = [];

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
    fichesOfficiellesChunksQuery1: selectedFichesOfficiellesChunksQuery1,
    fichesOfficiellesChunksQuery2: selectedFichesOfficiellesChunksQuery2,
    codeDuTravailChunksQuery1: selectedCodeDuTravailChunksQuery1,
    codeDuTravailChunksQuery2: selectedCodeDuTravailChunksQuery2,
    idccChunksQuery1: selectedIdccChunksQuery1,
    idccChunksQuery2: selectedIdccChunksQuery2,
  };
};
