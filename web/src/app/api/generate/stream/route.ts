import { NextRequest } from "next/server";
import { analyzeQuestionStream } from "@/modules/api/fetch";
import { Config } from "@/constants";

interface RequestBody {
  question: string;
  config?: Config;
  agreementId?: string;
  agreementTitle?: string;
}

export async function POST(request: NextRequest): Promise<Response> {
  try {
    const body: RequestBody = await request.json();
    const { question, config, agreementId, agreementTitle } = body;

    if (!question) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "Question is required",
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

    // Create a ReadableStream for the streaming response
    const stream = new ReadableStream({
      start(controller) {
        analyzeQuestionStream(
          question,
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
          agreementTitle
        ).catch((error) => {
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
