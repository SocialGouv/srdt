import { NextRequest } from "next/server";
import { analyzeQuestion } from "@/modules/api/process";
import { ApiResponse, AnalyzeResponse } from "@/types";
import { Config } from "@/constants";
import * as Sentry from "@sentry/nextjs";

interface RequestBody {
  question: string;
  config?: Config;
  agreementId?: string;
}

export async function POST(request: NextRequest): Promise<Response> {
  let body: RequestBody | null = null;
  try {
    body = await request.json();
    const { question, config, agreementId } = body as RequestBody;

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
    Sentry.captureException(error, {
      tags: {
        endpoint: "/api/generate",
      },
      extra: {
        method: "POST",
        hasQuestion: !!body?.question,
        config: body?.config,
        agreementId: body?.agreementId,
      },
    });
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
