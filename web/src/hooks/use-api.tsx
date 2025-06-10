"use client";

import { useState } from "react";
import { ApiResponse, AnalyzeResponse } from "@/types";

const useApi = () => {
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const generateAnswer = async (
    userQuestion: string,
    agreementId?: string,
    agreementTitle?: string
  ): Promise<ApiResponse<AnalyzeResponse>> => {
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

      const result: ApiResponse<AnalyzeResponse> = await response.json();
      setIsLoading(false);
      console.log(result);
      return result;
    } catch (error) {
      setIsLoading(false);
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
    onComplete: (result: ApiResponse<AnalyzeResponse>) => void,
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

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split("\n");

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6));

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
                console.warn("Failed to parse streaming data:", parseError);
              }
            }
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch (error) {
      setIsLoading(false);
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
    isLoading,
  };
};

export default useApi;
