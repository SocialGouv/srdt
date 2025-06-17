import {
  ALBERT_LLM,
  Config,
  getFamilyModel,
  getRandomModel,
  PROMPT_INSTRUCTIONS,
  SEARCH_OPTIONS_LOCAL,
  PROMPT_INSTRUCTIONS_GENERATE_IDCC,
  MAX_RERANK,
  K_RERANK,
  K_RERANK_IDCC,
} from "@/constants";
import {
  AnonymizeRequest,
  AnonymizeResponse,
  RephraseRequest,
  RephraseResponse,
  SearchRequest,
  SearchResponse,
  GenerateRequest,
  GenerateResponse,
  ChunkResult,
  LLMModel,
  RerankRequest,
  RerankResponse,
  RerankResult,
} from "../../types";
import { ApiResponse, AnalyzeResponse } from "@/types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

interface UseApiResponse<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

interface StreamChunk {
  type: "start" | "chunk" | "end" | "error";
  content?: string;
  time?: number;
  text?: string;
  nb_token_input?: number;
  nb_token_output?: number;
  error?: string;
}

interface PreparedQuestionData {
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
  anonymizeResult?: UseApiResponse<AnonymizeResponse>;
  rephraseResult?: UseApiResponse<RephraseResponse>;
}

const fetchApi = async <T>(
  endpoint: string,
  options: RequestInit
): Promise<T> => {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${process.env.AUTH_API_KEY}`,
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Une erreur est survenue");
  }

  return response.json();
};

const anonymize = async (
  request: AnonymizeRequest
): Promise<UseApiResponse<AnonymizeResponse>> => {
  try {
    const data = await fetchApi<AnonymizeResponse>("/api/v1/anonymize", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

const rephrase = async (
  request: RephraseRequest
): Promise<UseApiResponse<RephraseResponse>> => {
  try {
    const data = await fetchApi<RephraseResponse>("/api/v1/rephrase", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

const getIdccChunks = async (
  idcc: string
): Promise<UseApiResponse<SearchResponse>> => {
  try {
    const data = await fetchApi<SearchResponse>(`/api/v1/idcc/${idcc}`, {
      method: "GET",
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

const search = async (
  request: SearchRequest
): Promise<UseApiResponse<SearchResponse>> => {
  try {
    const data = await fetchApi<SearchResponse>("/api/v1/search", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

const rerank = async (
  request: RerankRequest
): Promise<UseApiResponse<RerankResponse>> => {
  try {
    const data = await fetchApi<RerankResponse>("/api/v1/rerank", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

const generate = async (
  request: GenerateRequest
): Promise<UseApiResponse<GenerateResponse>> => {
  try {
    const data = await fetchApi<GenerateResponse>("/api/v1/generate", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

const generateStream = async (
  request: GenerateRequest,
  onChunk: (chunk: string) => void,
  onStart?: (data: { time: number; nb_token_input: number }) => void,
  onEnd?: (data: {
    time: number;
    text: string;
    nb_token_input: number;
    nb_token_output: number;
  }) => void,
  onError?: (error: string) => void
): Promise<void> => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/generate/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.AUTH_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Une erreur est survenue");
    }

    if (!response.body) {
      throw new Error("No response body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = ""; // Buffer to accumulate incomplete lines

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;

        // Split by newlines but keep the last potentially incomplete line in buffer
        const lines = buffer.split("\n");
        buffer = lines.pop() || ""; // Keep the last (potentially incomplete) line in buffer

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const jsonStr = line.slice(6);
              const data: StreamChunk = JSON.parse(jsonStr);

              switch (data.type) {
                case "start":
                  if (
                    onStart &&
                    data.time !== undefined &&
                    data.nb_token_input !== undefined
                  ) {
                    onStart({
                      time: data.time,
                      nb_token_input: data.nb_token_input,
                    });
                  }
                  break;
                case "chunk":
                  if (data.content) {
                    onChunk(data.content);
                  }
                  break;
                case "end":
                  if (
                    onEnd &&
                    data.time !== undefined &&
                    data.text !== undefined &&
                    data.nb_token_input !== undefined &&
                    data.nb_token_output !== undefined
                  ) {
                    onEnd({
                      time: data.time,
                      text: data.text,
                      nb_token_input: data.nb_token_input,
                      nb_token_output: data.nb_token_output,
                    });
                  }
                  break;
                case "error":
                  if (onError && data.error) {
                    onError(data.error);
                  }
                  break;
              }
            } catch (parseError) {
              console.warn(
                "Failed to parse streaming data:",
                parseError,
                "Line:",
                line
              );
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  } catch (error) {
    if (onError) {
      onError((error as Error).message);
    }
    throw error;
  }
};

// Common preprocessing logic for both streaming and non-streaming
const prepareQuestionData = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
): Promise<PreparedQuestionData> => {
  const config = requiredConfig || Config.V1_1;
  const instructions = PROMPT_INSTRUCTIONS[config];
  const model = getRandomModel();

  let query = userQuestion;
  let anonymizeResult: UseApiResponse<AnonymizeResponse> | undefined =
    undefined;
  let rephraseResult: UseApiResponse<RephraseResponse> | undefined = undefined;

  // A/B testing : if v1_0 we run the rephrase otherwise we ignore it
  if (config == Config.V1_0) {
    anonymizeResult = await anonymize({
      model: ALBERT_LLM,
      user_question: userQuestion,
      anonymization_prompt: instructions.anonymisation,
    });

    if (anonymizeResult.error) {
      throw new Error(
        `Erreur lors de l'anonymisation: ${anonymizeResult.error}`
      );
    }

    if (!anonymizeResult.data) {
      throw new Error("Erreur lors de l'anonymisation");
    }

    rephraseResult = await rephrase({
      model,
      question: anonymizeResult.data.anonymized_question,
      rephrasing_prompt: instructions.reformulation,
      queries_splitting_prompt: instructions.split_multiple_queries,
    });

    if (rephraseResult.error) {
      throw new Error(
        `Erreur lors de la reformulation: ${rephraseResult.error}`
      );
    }

    if (!rephraseResult.data) {
      throw new Error("Erreur lors de la reformulation");
    }
    query = rephraseResult.data.rephrased_question;
  }

  let rerankedIdcc: RerankResult[] = [];

  // retrieve all IDCC content then rerank them
  if (idcc) {
    const idccSearchResult = await getIdccChunks(idcc);

    if (idccSearchResult.error && idccSearchResult.data?.top_chunks) {
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
    prompts: [query],
    options: SEARCH_OPTIONS_LOCAL,
  });

  if (localSearchResult.error) {
    console.error(`Erreur lors de la recherche: ${localSearchResult.error}`);
  }

  const localSearchChunks = localSearchResult.data?.top_chunks ?? [];

  if (localSearchChunks.length === 0) {
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
    prompt: userQuestion,
    inputs: toRerankChunks,
  });

  if (!searchRerankResults.data) {
    console.warn("Aucun résultat de recherche trouvé après le rerank");
  }

  // take top k rerank for the generate step
  const selectedRerankedChunked =
    searchRerankResults.data?.results
      .slice(0, K_RERANK)
      .map(({ chunk }) => chunk) || [];

  selectedRerankedChunked.push(
    ...rerankedIdcc.slice(0, K_RERANK_IDCC).map(({ chunk }) => chunk)
  );

  if (selectedRerankedChunked.length === 0) {
    console.warn("Aucun résultat de recherche trouvé");
  }

  return {
    query,
    model,
    config,
    instructions,
    localSearchChunks: selectedRerankedChunked,
    anonymizeResult,
    rephraseResult,
  };
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

        ${localSearchChunks
          .map(
            (chunk) => `Source: ${chunk.metadata.source} (${chunk.metadata.url})
                  Contenu: ${chunk.content}
                  ---`
          )
          .join("\n")}`,
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
  localSearchChunks: preparedData.localSearchChunks,
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
});

export const analyzeQuestion = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string,
  agreementTitle?: string
): Promise<ApiResponse<AnalyzeResponse>> => {
  try {
    const preparedData = await prepareQuestionData(
      userQuestion,
      requiredConfig,
      idcc
    );

    const chatHistory = createChatHistory(
      preparedData.query,
      preparedData.localSearchChunks
    );

    const generateResult = await generate({
      model: preparedData.model,
      chat_history: chatHistory,
      system_prompt:
        idcc && agreementTitle
          ? PROMPT_INSTRUCTIONS_GENERATE_IDCC.replace(
              "[Titre de la convention collective]",
              agreementTitle
            )
          : preparedData.instructions.generate_instruction,
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
  idcc?: string,
  agreementTitle?: string
): Promise<void> => {
  try {
    const preparedData = await prepareQuestionData(
      userQuestion,
      requiredConfig,
      idcc
    );

    const chatHistory = createChatHistory(
      preparedData.query,
      preparedData.localSearchChunks
    );

    await generateStream(
      {
        model: preparedData.model,
        chat_history: chatHistory,
        system_prompt:
          idcc && agreementTitle
            ? PROMPT_INSTRUCTIONS_GENERATE_IDCC.replace(
                "[Titre de la convention collective]",
                agreementTitle
              )
            : preparedData.instructions.generate_instruction,
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
