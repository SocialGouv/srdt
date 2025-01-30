import {
  getRandomModel,
  PROMPT_INSTRUCTIONS_V1,
  SEARCH_OPTIONS_INTERNET,
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

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  userQuestion: string
): Promise<ApiResponse<AnalyzeResponse>> => {
  try {
    const model = getRandomModel();

    const anonymizeResult = await anonymize({
      model,
      user_question: userQuestion,
      anonymization_prompt: PROMPT_INSTRUCTIONS_V1.anonymisation,
    });

    if (anonymizeResult.error) {
      throw new Error(
        `Erreur lors de l'anonymisation: ${anonymizeResult.error}`
      );
    }

    const rephraseResult = await rephrase({
      model,
      question: anonymizeResult.data!.anonymized_question,
      rephrasing_prompt: PROMPT_INSTRUCTIONS_V1.reformulation,
      queries_splitting_prompt: PROMPT_INSTRUCTIONS_V1.split_multiple_queries,
    });

    if (rephraseResult.error) {
      throw new Error(
        `Erreur lors de la reformulation: ${rephraseResult.error}`
      );
    }

    const [localSearchResult, internetSearchResult] = await Promise.all([
      search({
        prompts: rephraseResult.data!.queries || [
          rephraseResult.data!.rephrased_question,
        ],
        options: SEARCH_OPTIONS_LOCAL,
      }),
      search({
        prompts: rephraseResult.data!.queries || [
          rephraseResult.data!.rephrased_question,
        ],
        options: SEARCH_OPTIONS_INTERNET,
      }),
    ]);

    if (localSearchResult.error || internetSearchResult.error) {
      throw new Error(
        `Erreur lors de la recherche: ${
          localSearchResult.error || internetSearchResult.error
        }`
      );
    }

    const generateResult = await generate({
      model,
      chat_history: [
        {
          role: "user",
          content: rephraseResult.data!.rephrased_question,
        },
      ],
      system_prompt: PROMPT_INSTRUCTIONS_V1.generate_instruction,
    });

    if (generateResult.error) {
      throw new Error(
        `Erreur lors de la génération de la réponse: ${generateResult.error}`
      );
    }

    if (
      !anonymizeResult.data ||
      !rephraseResult.data ||
      !localSearchResult.data ||
      !internetSearchResult.data ||
      !generateResult.data
    ) {
      throw new Error("Erreur lors de l'analyse de la question");
    }

    return {
      success: true,
      data: {
        anonymized: anonymizeResult.data,
        rephrased: rephraseResult.data,
        localSearch: localSearchResult.data,
        internetSearch: internetSearchResult.data,
        generated: generateResult.data,
        modelName: model.name,
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
