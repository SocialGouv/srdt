import { NextRequest } from "next/server";
import { analyzeFollowupQuestionStream } from "@/modules/api/process";
import { Config, getModelByName } from "@/constants";
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
  try {
    const body: FollowupRequestBody = await request.json();
    const { query1, answer1, query2, config, agreementId, modelName } = body;

    if (!query1 || !answer1 || !query2) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "query1, answer1, and query2 are required",
        }),
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
        }),
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
          }),
          {
            status: 422,
            headers: {
              "Content-Type": "application/json",
            },
          }
        );
      }
    }

    // Create a ReadableStream for the streaming response
    const stream = new ReadableStream({
      start(controller) {
        analyzeFollowupQuestionStream(
          query1,
          answer1,
          query2,
          (chunk: string) => {
            // Send each chunk as Server-Sent Events
            const data = JSON.stringify({ type: "chunk", content: chunk });
            controller.enqueue(`data: ${data}\n\n`);
          },
          (result) => {
            // Send the final result
            if (result.success) {
              const data = JSON.stringify({
                type: "complete",
                success: true,
                data: result.data,
              });
              controller.enqueue(`data: ${data}\n\n`);
            } else {
              const data = JSON.stringify({
                type: "error",
                success: false,
                error: result.error,
              });
              controller.enqueue(`data: ${data}\n\n`);
            }
            controller.close();
          },
          config,
          agreementId,
          providedModel
        ).catch((error) => {
          Sentry.captureException(error, {
            tags: {
              endpoint: "/api/generate/followup/stream",
            },
            extra: {
              method: "POST",
              hasQuery1: !!query1,
              hasAnswer1: !!answer1,
              hasQuery2: !!query2,
              config: config,
              agreementId: agreementId,
            },
          });
          const data = JSON.stringify({
            type: "error",
            success: false,
            error: error.message,
          });
          controller.enqueue(`data: ${data}\n\n`);
          controller.close();
        });
      },
    });

    return new Response(stream, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  } catch (error) {
    Sentry.captureException(error, {
      tags: {
        endpoint: "/api/generate/followup/stream",
      },
      extra: {
        method: "POST",
        errorType: "outer_catch",
      },
    });
    return new Response(
      JSON.stringify({
        success: false,
        error: (error as Error).message,
      }),
      {
        status: 500,
        headers: {
          "Content-Type": "application/json",
        },
      }
    );
  }
}
