import { NextRequest } from "next/server";
import { analyzeQuestion } from "@/modules/api/fetch";
import { ApiResponse, AnalyzeResponse } from "@/types";

interface RequestBody {
  question: string;
}

export async function POST(request: NextRequest): Promise<Response> {
  try {
    const body: RequestBody = await request.json();
    const { question } = body;

    if (!question) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "Question is required",
        } as ApiResponse<never>),
        {
          status: 400,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }

    const result: ApiResponse<AnalyzeResponse> = await analyzeQuestion(
      question
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
