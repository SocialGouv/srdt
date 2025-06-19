import { NextRequest } from "next/server";
import { analyzeQuestion } from "@/modules/api/fetch";
import { ApiResponse, AnalyzeResponse } from "@/types";
import { Config } from "@/constants";

interface RequestBody {
  question: string;
  config?: Config;
  agreementId?: string;
}

export async function POST(request: NextRequest): Promise<Response> {
  try {
    const body: RequestBody = await request.json();
    const { question, config, agreementId } = body;

    if (!question) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "Question is required",
        } as ApiResponse<never>),
        {
          status: 422,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }

    if (config && !Object.values(Config).includes(config)) {
      return new Response(
        JSON.stringify({
          success: false,
          error: `Wrong config : avalaible values are ${Object.values(Config)}`,
        } as ApiResponse<never>),
        {
          status: 422,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }

    const result: ApiResponse<AnalyzeResponse> = await analyzeQuestion(
      question,
      config,
      agreementId
    );

    if (!result.success) {
      return new Response(
        JSON.stringify({ success: false, error: result.error }),
        {
          status: 500,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }

    return new Response(JSON.stringify({ success: true, data: result.data }), {
      status: 200,
      headers: {
        "Content-Type": "application/json",
      },
    });
  } catch (error) {
    return new Response(
      JSON.stringify({ success: false, error: (error as Error).message }),
      {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
  }
}
