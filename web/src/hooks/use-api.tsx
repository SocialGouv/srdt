"use client";

import { useState } from "react";
import { ApiResponse, AnswerResponse } from "@/types";
import * as Sentry from "@sentry/nextjs";

const useApi = () => {
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const generateAnswer = async (
    userQuestion: string,
    agreementId?: string,
    agreementTitle?: string
  ): Promise<ApiResponse<AnswerResponse>> => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: userQuestion,
          agreementId,
          agreementTitle,
        }),
      });

      const result: ApiResponse<AnswerResponse> = await response.json();
      setIsLoading(false);
      console.log(result);
      return result;
    } catch (error) {
      setIsLoading(false);
      Sentry.captureException(error, {
        tags: {
          component: "useApi",
          method: "generateAnswer",
        },
        extra: {
          userQuestion: userQuestion,
          agreementId: agreementId,
          agreementTitle: agreementTitle,
        },
      });
      return {
        success: false,
        data: null,
        error: (error as Error).message,
      };
    }
  };

  const generateAnswerStream = async (
    userQuestion: string,
    onChunk: (chunk: string) => void,
    onComplete: (result: ApiResponse<AnswerResponse>) => void,
    agreementId?: string,
    agreementTitle?: string
  ): Promise<void> => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/generate/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: userQuestion,
          agreementId,
          agreementTitle,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
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
                const data = JSON.parse(jsonStr);

                switch (data.type) {
                  case "chunk":
                    if (data.content) {
                      onChunk(data.content);
                    }
                    break;
                  case "complete":
                    setIsLoading(false);
                    onComplete({
                      success: data.success,
                      data: data.data,
                      error: undefined,
                    });
                    return;
                  case "error":
                    setIsLoading(false);
                    onComplete({
                      success: false,
                      data: null,
                      error: data.error,
                    });
                    return;
                }
              } catch (parseError) {
                Sentry.captureException(parseError, {
                  tags: {
                    component: "useApi",
                    method: "generateAnswerStream",
                  },
                  extra: {
                    line: line,
                    userQuestion: userQuestion,
                    streamingStep: "parse_streaming_data",
                  },
                });
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
      setIsLoading(false);
      Sentry.captureException(error, {
        tags: {
          component: "useApi",
          method: "generateAnswerStream",
        },
        extra: {
          userQuestion: userQuestion,
          agreementId: agreementId,
          agreementTitle: agreementTitle,
        },
      });
      onComplete({
        success: false,
        data: null,
        error: (error as Error).message,
      });
    }
  };

  const generateFollowupAnswer = async (
    query1: string,
    answer1: string,
    query2: string,
    agreementId?: string,
    agreementTitle?: string,
    modelName?: string
  ): Promise<ApiResponse<AnswerResponse>> => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/generate/followup", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query1,
          answer1,
          query2,
          agreementId,
          agreementTitle,
          modelName,
        }),
      });

      const result: ApiResponse<AnswerResponse> = await response.json();
      setIsLoading(false);
      console.log(result);
      return result;
    } catch (error) {
      setIsLoading(false);
      Sentry.captureException(error, {
        tags: {
          component: "useApi",
          method: "generateFollowupAnswer",
        },
        extra: {
          query1: query1,
          query2: query2,
          agreementId: agreementId,
          agreementTitle: agreementTitle,
          modelName: modelName,
        },
      });
      return {
        success: false,
        data: null,
        error: (error as Error).message,
      };
    }
  };

  const generateFollowupAnswerStream = async (
    query1: string,
    answer1: string,
    query2: string,
    onChunk: (chunk: string) => void,
    onComplete: (result: ApiResponse<AnswerResponse>) => void,
    agreementId?: string,
    agreementTitle?: string,
    modelName?: string
  ): Promise<void> => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/generate/followup/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query1,
          answer1,
          query2,
          agreementId,
          agreementTitle,
          modelName,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
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
                const data = JSON.parse(jsonStr);

                switch (data.type) {
                  case "chunk":
                    if (data.content) {
                      onChunk(data.content);
                    }
                    break;
                  case "complete":
                    setIsLoading(false);
                    onComplete({
                      success: data.success,
                      data: data.data,
                      error: undefined,
                    });
                    return;
                  case "error":
                    setIsLoading(false);
                    onComplete({
                      success: false,
                      data: null,
                      error: data.error,
                    });
                    return;
                }
              } catch (parseError) {
                Sentry.captureException(parseError, {
                  tags: {
                    component: "useApi",
                    method: "generateFollowupAnswerStream",
                  },
                  extra: {
                    line: line,
                    query1: query1,
                    query2: query2,
                    streamingStep: "parse_streaming_data",
                    modelName: modelName,
                  },
                });
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
      setIsLoading(false);
      Sentry.captureException(error, {
        tags: {
          component: "useApi",
          method: "generateFollowupAnswerStream",
        },
        extra: {
          query1: query1,
          query2: query2,
          agreementId: agreementId,
          agreementTitle: agreementTitle,
          modelName: modelName,
        },
      });
      onComplete({
        success: false,
        data: null,
        error: (error as Error).message,
      });
    }
  };

  return {
    generateAnswer,
    generateAnswerStream,
    generateFollowupAnswer,
    generateFollowupAnswerStream,
    isLoading,
  };
};

export default useApi;
