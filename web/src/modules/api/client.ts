import {
  AnonymizeRequest,
  AnonymizeResponse,
  RephraseRequest,
  RephraseResponse,
  SearchRequest,
  SearchResponse,
  GenerateRequest,
  GenerateResponse,
  RerankRequest,
  RerankResponse,
  RetrieveResponse,
} from "../../types";
import * as Sentry from "@sentry/nextjs";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export interface UseApiResponse<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

export interface StreamChunk {
  type: "start" | "chunk" | "end" | "error";
  content?: string;
  time?: number;
  text?: string;
  nb_token_input?: number;
  nb_token_output?: number;
  error?: string;
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

export const anonymize = async (
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

export const rephrase = async (
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

export const getIdccChunks = async (
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

export const search = async (
  request: SearchRequest
): Promise<UseApiResponse<SearchResponse>> => {
  try {
    const data = await fetchApi<SearchResponse>("/api/v1/search_es", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

export const retrieveDocs = async (ids: string[]) => {
  try {
    const data = await fetchApi<RetrieveResponse>("/api/v1/docs/retrieve", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    return { data, error: null, loading: false };
  } catch (error) {
    return { data: null, error: (error as Error).message, loading: false };
  }
};

export const rerank = async (
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

export const generate = async (
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

export const generateStream = async (
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
              const errorMessage = "Failed to parse streaming data";
              const parseErrorWithContext = new Error(
                `${errorMessage}: ${parseError}`
              );
              Sentry.captureException(parseErrorWithContext, {
                extra: {
                  line: line,
                  originalError: parseError,
                },
              });
              console.warn(errorMessage, parseError, "Line:", line);
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
