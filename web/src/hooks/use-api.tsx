"use client";

import { useState } from "react";
import { ApiResponse, AnalyzeResponse } from "@/types";

const useApi = () => {
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const generateAnswer = async (
    userQuestion: string,
    agreementId?: string
  ): Promise<ApiResponse<AnalyzeResponse>> => {
    setIsLoading(true);
    try {
      const response = await fetch("/api/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ question: userQuestion, agreementId }),
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

  return {
    generateAnswer,
    isLoading,
  };
};

export default useApi;
