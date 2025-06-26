import {
  Config,
  PROMPT_INSTRUCTIONS,
  getRandomModel,
  MAX_RERANK,
  SEARCH_OPTIONS_LOCAL,
  K_RERANK,
  K_RERANK_IDCC,
  getFamilyModel,
  PROMPT_INSTRUCTIONS_GENERATE_IDCC,
} from "@/constants";
import {
  AnonymizeResponse,
  RephraseResponse,
  RerankResult,
  ChunkResult,
  GenerateResponse,
  AnalyzeResponse,
  ApiResponse,
  LLMModel,
} from "@/types";
import * as Sentry from "@sentry/nextjs";
import {
  UseApiResponse,
  anonymize,
  getIdccChunks,
  rerank,
  search,
  retrieveDocs,
  generate,
  generateStream,
} from "./client";

export interface StreamChunk {
  type: "start" | "chunk" | "end" | "error";
  content?: string;
  time?: number;
  text?: string;
  nb_token_input?: number;
  nb_token_output?: number;
  error?: string;
}

export interface PreparedQuestionData {
  query: string;
  model: LLMModel;
  config: Config;
  instructions: {
    generate_instruction: string;
    anonymisation?: string;
    reformulation?: string;
    split_multiple_queries?: string;
  };
  localSearchChunks: ChunkResult[];
  idccChunks: ChunkResult[];
  anonymizeResult: UseApiResponse<AnonymizeResponse>;
  rephraseResult?: UseApiResponse<RephraseResponse>;
}

// Common preprocessing logic for both streaming and non-streaming
const prepareQuestionData = async (
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

    if (idccSearchResult.error && idccSearchResult.data?.top_chunks) {
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
      const idccRerankResults = await rerank({
        prompt: userQuestion,
        inputs: idccSearchResult.data?.top_chunks.slice(
          0,
          MAX_RERANK
        ) as ChunkResult[],
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
  const toRerankRecord = localSearchChunks
    .sort((a, b) => b.score - a.score)
    .reduce((acc: Record<string, ChunkResult>, curr: ChunkResult) => {
      const id = curr.metadata.document_id;
      if (!acc[id]) {
        acc[id] = curr;
      } else {
        acc[id].content.concat(" /n/n " + curr.content);
      }
      return acc;
    }, {} as Record<string, ChunkResult>);

  const toRerankChunks = Object.values(toRerankRecord).slice(0, MAX_RERANK);

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

  const selectedDocumentsIds = [
    ...localSearchChunks,
    ...selectedIdccChunks,
  ].map((c) => c.metadata.id);

  const retrieveResponse = await retrieveDocs(selectedDocumentsIds);

  const selectedDocuments = retrieveResponse.data?.contents || [];

  if (retrieveResponse.error) {
    const retrieveError = new Error(
      `Erreur lors de l'accès aux documents : ${retrieveResponse.error}`
    );
    Sentry.captureException(retrieveError, {
      extra: {
        query: anonymized,
        searchOptions: SEARCH_OPTIONS_LOCAL,
      },
    });
    console.error(
      `Erreur lors de l'accès aux documents : ${retrieveResponse.error}`
    );
  }

  if (retrieveResponse.data?.contents.length === 0) {
    Sentry.captureMessage("Aucun document trouvé", {
      level: "warning",
      extra: {
        userQuestion: anonymized,
        generalChunksLength: selectedGeneralChunks.length,
        idccChunksLength: selectedIdccChunks.length,
      },
    });
    console.warn("Aucun document trouvé");
  }

  return {
    query: anonymized,
    model,
    config,
    instructions,
    localSearchChunks: selectedDocuments
      .filter((s) => s.metadata.idcc === undefined)
      .slice(0, 7)
      .map((s) => ({ ...s, score: 0, id_chunk: 0 })),
    idccChunks: selectedDocuments
      .filter((s) => s.metadata.idcc !== undefined)
      .slice(0, 3)
      .map((s) => ({ ...s, score: 0, id_chunk: 0 })),
    anonymizeResult,
    rephraseResult,
  };
};

// Helper to format chunks for display
const formatChunks = (chunks: ChunkResult[]) => {
  return chunks
    .map(
      (chunk) => `Source: ${chunk.metadata.source} (${chunk.metadata.url})
                Contenu: ${chunk.content}
                ---`
    )
    .join("\n");
};

// Helper to create chat history for generation
const createChatHistory = (query: string, localSearchChunks: ChunkResult[]) => [
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
const createIdccChatHistory = (
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

// Helper to create final response
const createAnalyzeResponse = (
  preparedData: PreparedQuestionData,
  generatedData: GenerateResponse
): AnalyzeResponse => ({
  config: preparedData.config.toString(),
  anonymized: preparedData.anonymizeResult?.data || null,
  rephrased: preparedData.rephraseResult?.data || null,
  localSearchChunks: [
    ...preparedData.localSearchChunks,
    ...preparedData.idccChunks,
  ],
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
});

export const analyzeQuestion = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
): Promise<ApiResponse<AnalyzeResponse>> => {
  try {
    const preparedData = await prepareQuestionData(
      userQuestion,
      requiredConfig,
      idcc
    );

    // Determine chat history and system prompt based on whether IDCC is provided
    const { chatHistory, systemPrompt } = idcc
      ? {
          chatHistory: createIdccChatHistory(
            preparedData.query,
            preparedData.localSearchChunks,
            preparedData.idccChunks
          ),
          systemPrompt: PROMPT_INSTRUCTIONS_GENERATE_IDCC.replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`
          ),
        }
      : {
          chatHistory: createChatHistory(
            preparedData.query,
            preparedData.localSearchChunks
          ),
          systemPrompt: preparedData.instructions.generate_instruction,
        };

    const generateResult = await generate({
      model: preparedData.model,
      chat_history: chatHistory,
      system_prompt: systemPrompt,
    });

    if (generateResult.error) {
      throw new Error(
        `Erreur lors de la génération de la réponse: ${generateResult.error}. Pour information, le model utilisé lors de la génération est ${preparedData.model.name}`
      );
    }

    if (!generateResult.data) {
      throw new Error(
        `Erreur lors de la génération de la réponse. Pour information, le model utilisé lors de la génération est ${preparedData.model.name}`
      );
    }

    return {
      success: true,
      data: createAnalyzeResponse(preparedData, generateResult.data),
    };
  } catch (error) {
    return {
      success: false,
      data: null,
      error: (error as Error).message,
    };
  }
};

export const analyzeQuestionStream = async (
  userQuestion: string,
  onChunk: (chunk: string) => void,
  onComplete: (result: ApiResponse<AnalyzeResponse>) => void,
  requiredConfig?: Config,
  idcc?: string
): Promise<void> => {
  try {
    const preparedData = await prepareQuestionData(
      userQuestion,
      requiredConfig,
      idcc
    );

    // Determine chat history and system prompt based on whether IDCC is provided
    const { chatHistory, systemPrompt } = idcc
      ? {
          chatHistory: createIdccChatHistory(
            preparedData.query,
            preparedData.localSearchChunks,
            preparedData.idccChunks
          ),
          systemPrompt: PROMPT_INSTRUCTIONS_GENERATE_IDCC.replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`
          ),
        }
      : {
          chatHistory: createChatHistory(
            preparedData.query,
            preparedData.localSearchChunks
          ),
          systemPrompt: preparedData.instructions.generate_instruction,
        };

    await generateStream(
      {
        model: preparedData.model,
        chat_history: chatHistory,
        system_prompt: systemPrompt,
      },
      onChunk,
      undefined, // onStart
      (endData) => {
        // onEnd - call completion callback with full result
        const generatedData: GenerateResponse = {
          time: endData.time,
          text: endData.text,
          nb_token_input: endData.nb_token_input,
          nb_token_output: endData.nb_token_output,
        };

        onComplete({
          success: true,
          data: createAnalyzeResponse(preparedData, generatedData),
        });
      },
      (error) => {
        // onError
        onComplete({
          success: false,
          data: null,
          error,
        });
      }
    );
  } catch (error) {
    onComplete({
      success: false,
      data: null,
      error: (error as Error).message,
    });
  }
};
