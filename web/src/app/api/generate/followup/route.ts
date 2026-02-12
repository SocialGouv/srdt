import { NextRequest } from "next/server";
import { generateFollowupAnswer } from "@/modules/api/process";
import { ApiResponse, AnswerResponse } from "@/types";
import { Config, getModelByName } from "@/constants";
import { getAuthorizedSession } from "@/lib/auth/get-authorized-session";
import * as Sentry from "@sentry/nextjs";

interface FollowupRequestBody {
  query1: string;
  answer1: string;
  query2: string;
  config?: Config;
  agreementId?: string;
  modelName?: string;
}

export async function POST(request: NextRequest): Promise<Response> {
  const session = await getAuthorizedSession();
  if (!session) {
    return new Response(
      JSON.stringify({ success: false, error: "Unauthorized" }),
      { status: 401, headers: { "Content-Type": "application/json" } }
    );
  }

  let body: FollowupRequestBody | null = null;
  try {
    body = await request.json();
    const { query1, answer1, query2, config, agreementId, modelName } =
      body as FollowupRequestBody;

    if (!query1 || !answer1 || !query2) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "query1, answer1, and query2 are required",
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
          error: `Wrong config : available values are ${Object.values(Config)}`,
        } as ApiResponse<never>),
        {
          status: 422,
          headers: {
            "Content-Type": "application/json",
          },
        }
      );
    }

    // Get the model by name if provided
    let providedModel = undefined;
    if (modelName) {
      providedModel = getModelByName(modelName);
      if (!providedModel) {
        return new Response(
          JSON.stringify({
            success: false,
            error: `Invalid model name: ${modelName}`,
          } as ApiResponse<never>),
          {
            status: 422,
            headers: {
              "Content-Type": "application/json",
            },
          }
        );
      }
    }

    const result: ApiResponse<AnswerResponse> = await generateFollowupAnswer(
      query1,
      answer1,
      query2,
      config,
      agreementId,
      providedModel
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
        endpoint: "/api/generate/followup",
      },
      extra: {
        method: "POST",
        hasQuery1: !!body?.query1,
        hasAnswer1: !!body?.answer1,
        hasQuery2: !!body?.query2,
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
