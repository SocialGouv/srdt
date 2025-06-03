import {
  ALBERT_LLM,
  Config,
  getFamilyModel,
  getRandomModel,
  MAX_SOURCE_COUNT,
  PROMPT_INSTRUCTIONS,
  SEARCH_OPTIONS_LOCAL,
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
} from "../../types";
import { ApiResponse, AnalyzeResponse } from "@/types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

interface UseApiResponse<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
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

export const analyzeQuestion = async (
  userQuestion: string,
  requiredConfig?: Config
): Promise<ApiResponse<AnalyzeResponse>> => {
  try {
    const config = requiredConfig || Config.V1_1;

    const instructions = PROMPT_INSTRUCTIONS[config];

    const model = getRandomModel();

    let query = userQuestion;

    let anonymizeResult: UseApiResponse<AnonymizeResponse> | undefined =
      undefined;

    let rephraseResult: UseApiResponse<RephraseResponse> | undefined =
      undefined;

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

    const localSearchResult = await search({
      prompts: [query], // Passer l'IDCC
      options: SEARCH_OPTIONS_LOCAL,
    });

    if (localSearchResult.error) {
      console.error(`Erreur lors de la recherche: ${localSearchResult.error}`);
    }

    const localSearchChunks = localSearchResult.data?.top_chunks ?? [];

    if (localSearchChunks.length === 0) {
      console.warn("Aucun résultat de recherche trouvé");
    }

    localSearchChunks
      .sort((a, b) => b.score - a.score)
      .slice(0, MAX_SOURCE_COUNT);

    const generateResult = await generate({
      model,
      chat_history: [
        {
          role: "user",
          content: query,
        },
        {
          role: "user",
          content: `Voici les sources pertinentes pour répondre à la question:

              ${localSearchChunks
                .map(
                  (
                    chunk
                  ) => `Source: ${chunk.metadata.source} (${chunk.metadata.url})
                        Contenu: ${chunk.content}
                        ---`
                )
                .join("\n")}`,
        },
      ],
      system_prompt: instructions.generate_instruction,
    });

    if (generateResult.error) {
      throw new Error(
        `Erreur lors de la génération de la réponse: ${generateResult.error}. Pour information, le model utilisé lors de la génération est ${model.name}`
      );
    }

    if (!generateResult.data) {
      throw new Error(
        `Erreur lors de la génération de la réponse. Pour information, le model utilisé lors de la génération est ${model.name}`
      );
    }

    return {
      success: true,
      data: {
        config: config.toString(),
        anonymized: anonymizeResult?.data || null,
        rephrased: rephraseResult?.data || null,
        localSearchChunks,
        generated: generateResult.data,
        modelName: model.name,
        modelFamily: getFamilyModel(model),
      },
    };
  } catch (error) {
    return {
      success: false,
      data: null,
      error: (error as Error).message,
    };
  }
};
