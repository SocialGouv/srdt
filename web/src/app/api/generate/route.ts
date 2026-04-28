import { NextRequest } from "next/server";
import { generateAnswer } from "@/modules/api/process";
import { ApiResponse, AnswerResponse } from "@/types";
import { Config } from "@/constants";
import { getAuthorizedSession } from "@/lib/auth/get-authorized-session";
import { timingSafeEqual } from "crypto";
import * as Sentry from "@sentry/nextjs";

interface RequestBody {
  question: string;
  config?: Config;
  agreementId?: string;
  agreementTitle?: string;
}

function hasValidDebugToken(request: NextRequest): boolean {
  const expected = process.env.DEBUG_API_KEY;
  if (!expected) return false;

  const header = request.headers.get("authorization");
  if (!header?.startsWith("Bearer ")) return false;
  const provided = header.slice("Bearer ".length).trim();
  if (!provided) return false;

  const providedBuf = Buffer.from(provided);
  const expectedBuf = Buffer.from(expected);
  if (providedBuf.length !== expectedBuf.length) return false;
  return timingSafeEqual(providedBuf, expectedBuf);
}

export async function POST(request: NextRequest): Promise<Response> {
  const debugMode = hasValidDebugToken(request);

  if (!debugMode) {
    const session = await getAuthorizedSession();
    if (!session) {
      return new Response(
        JSON.stringify({ success: false, error: "Unauthorized" }),
        { status: 401, headers: { "Content-Type": "application/json" } }
      );
    }
  }

  let body: RequestBody | null = null;
  try {
    body = await request.json();
    const { question, config, agreementId, agreementTitle } =
      body as RequestBody;

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

    const result: ApiResponse<AnswerResponse> = await generateAnswer(
      question,
      config,
      agreementId,
      agreementTitle,
      debugMode
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
        debugMode,
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
