import { NextRequest, NextResponse } from "next/server";
import { getAuthorizedSession } from "@/lib/auth/get-authorized-session";
import {
  saveConversation,
  updateConversationFollowup,
  updateConversationFeedback,
  isDatabaseAvailable,
} from "@/lib/db/conversations";
import { hashEmailForUserId } from "@/lib/db/hash-user";
import { ALLOWED_EMAIL_DOMAINS, DOMAIN_TO_DEPARTMENT } from "@/constants";
import * as Sentry from "@sentry/nextjs";

/**
 * Extract department from email address based on allowed domains
 */
function getDepartmentFromEmail(
  email: string | null | undefined
): string | null {
  if (!email) return null;

  const emailLower = email.toLowerCase();
  const domain = ALLOWED_EMAIL_DOMAINS.find((d) =>
    emailLower.endsWith(`@${d}`)
  );

  if (domain) {
    return DOMAIN_TO_DEPARTMENT[domain] || domain;
  }

  return null;
}

interface SaveInitialRequest {
  action: "save_initial";
  question: string;
  response: string;
  idcc?: string;
  modelName?: string;
}

interface SaveFollowupRequest {
  action: "save_followup";
  conversationId: string;
  followupQuestion: string;
  followupResponse: string;
}

interface SaveFeedbackRequest {
  action: "save_feedback";
  conversationId: string;
  feedbackType: "positive" | "negative";
  feedbackReasons?: string;
}

type RequestBody = SaveInitialRequest | SaveFollowupRequest | SaveFeedbackRequest;

export async function POST(request: NextRequest): Promise<NextResponse> {
  // Return early if database is not available (non-blocking)
  if (!isDatabaseAvailable()) {
    return NextResponse.json({
      success: false,
      error: "Database not available",
    });
  }

  try {
    // Get the authenticated and authorized user's session
    const session = await getAuthorizedSession();

    if (!session?.user?.email) {
      return NextResponse.json(
        { success: false, error: "Unauthorized" },
        { status: 401 }
      );
    }

    const body: RequestBody = await request.json();

    if (!body.action) {
      return NextResponse.json(
        { success: false, error: "Action is required" },
        { status: 422 }
      );
    }

    const userEmail = session.user.email;
    const userId = await hashEmailForUserId(userEmail);
    const department = getDepartmentFromEmail(userEmail);

    switch (body.action) {
      case "save_initial": {
        const { question, response, idcc, modelName } = body;

        if (!question || !response) {
          return NextResponse.json(
            { success: false, error: "Question and response are required" },
            { status: 422 }
          );
        }

        const conversationId = await saveConversation({
          user_id: userId,
          department,
          question,
          response,
          followup_question: null,
          followup_response: null,
          feedback_type: null,
          feedback_reasons: null,
          idcc: idcc ?? null,
          model_name: modelName ?? null,
        });

        return NextResponse.json({
          success: true,
          conversationId,
        });
      }

      case "save_followup": {
        const { conversationId, followupQuestion, followupResponse } = body;

        if (!conversationId || !followupQuestion || !followupResponse) {
          return NextResponse.json(
            {
              success: false,
              error:
                "conversationId, followupQuestion, and followupResponse are required",
            },
            { status: 422 }
          );
        }

        await updateConversationFollowup(
          conversationId,
          followupQuestion,
          followupResponse
        );

        return NextResponse.json({ success: true });
      }

      case "save_feedback": {
        const { conversationId, feedbackType, feedbackReasons } = body;

        if (!conversationId || !feedbackType) {
          return NextResponse.json(
            {
              success: false,
              error: "conversationId and feedbackType are required",
            },
            { status: 422 }
          );
        }

        if (feedbackType !== "positive" && feedbackType !== "negative") {
          return NextResponse.json(
            {
              success: false,
              error: "feedbackType must be 'positive' or 'negative'",
            },
            { status: 422 }
          );
        }

        await updateConversationFeedback(
          conversationId,
          feedbackType,
          feedbackReasons
        );

        return NextResponse.json({ success: true });

      }

      default:
        return NextResponse.json(
          { success: false, error: "Invalid action" },
          { status: 422 }
        );
    }
  } catch (error) {
    Sentry.captureException(error, {
      tags: {
        endpoint: "/api/conversations/save",
      },
    });

    console.error("Error saving conversation:", error);

    return NextResponse.json(
      { success: false, error: "Internal server error" },
      { status: 500 }
    );
  }
}
