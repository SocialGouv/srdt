import sql from "./postgres";

export interface ConversationRecord {
  id?: string;
  user_id: string;
  department: string | null;
  question: string;
  response: string;
  followup_question: string | null;
  followup_response: string | null;
  feedback_type: "positive" | "negative" | null;
  feedback_reasons: string | null;
  idcc: string | null;
  model_name: string | null;
  created_at?: Date;
  updated_at?: Date;
}

/**
 * Check if database is available
 */
export function isDatabaseAvailable(): boolean {
  return sql !== null;
}

/**
 * Save a new conversation (initial question + response)
 * Returns null if database is not available
 */
export async function saveConversation(
  conversation: Omit<ConversationRecord, "id" | "created_at" | "updated_at">
): Promise<string | null> {
  if (!sql) {
    console.warn("[conversations] Database not available, skipping save");
    return null;
  }

  const result = await sql<Array<{ id: string }>>`
    INSERT INTO conversations (
      user_id,
      department,
      question,
      response,
      followup_question,
      followup_response,
      feedback_type,
      feedback_reasons,
      idcc,
      model_name
    ) VALUES (
      ${conversation.user_id},
      ${conversation.department},
      ${conversation.question},
      ${conversation.response},
      ${conversation.followup_question},
      ${conversation.followup_response},
      ${conversation.feedback_type},
      ${conversation.feedback_reasons},
      ${conversation.idcc},
      ${conversation.model_name}
    )
    RETURNING id
  `;

  if (!result[0]?.id) {
    throw new Error("Failed to save conversation: no ID returned");
  }

  return result[0].id;
}

/**
 * Update a conversation with followup Q&A
 */
export async function updateConversationFollowup(
  id: string,
  followupQuestion: string,
  followupResponse: string
): Promise<void> {
  if (!sql) {
    console.warn("[conversations] Database not available, skipping update");
    return;
  }

  await sql`
    UPDATE conversations
    SET 
      followup_question = ${followupQuestion},
      followup_response = ${followupResponse},
      updated_at = NOW()
    WHERE id = ${id}
  `;
}

/**
 * Update a conversation with feedback
 */
export async function updateConversationFeedback(
  id: string,
  feedbackType: "positive" | "negative",
  feedbackReasons?: string
): Promise<void> {
  if (!sql) {
    console.warn("[conversations] Database not available, skipping update");
    return;
  }

  await sql`
    UPDATE conversations
    SET 
      feedback_type = ${feedbackType},
      feedback_reasons = ${feedbackReasons ?? null},
      updated_at = NOW()
    WHERE id = ${id}
  `;
}

/**
 * Get a conversation by ID
 */
export async function getConversation(
  id: string
): Promise<ConversationRecord | null> {
  if (!sql) {
    console.warn("[conversations] Database not available");
    return null;
  }

  const result = await sql<ConversationRecord[]>`
    SELECT * FROM conversations WHERE id = ${id}
  `;

  return result[0] ?? null;
}
