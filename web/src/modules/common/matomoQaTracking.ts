"use client";

import { push } from "@socialgouv/matomo-next";

export type QaMatomoPayload = {
  date: string; // ISO8601
  userHash?: string;
  familyModel?: string;
  modelName?: string;
  scenarioVersion?: string;
  globalResponseTime?: number;
  inputNbTokens?: number;
  outputNbTokens?: number;
  userQuestion?: string;
  llmResponse?: string;
  errorMessage?: string;
  idcc?: string;
  isFollowupResponse?: boolean;
};

function generateInteractionId(): string {
  // Prefer UUID when available (modern browsers); otherwise fallback.
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `qa_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function chunkText(text: string, chunkSize: number): string[] {
  const chunks: string[] = [];
  for (let i = 0; i < text.length; i += chunkSize) {
    chunks.push(text.slice(i, i + chunkSize));
  }
  return chunks;
}

function safeJsonStringify(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return '{"error":"json_stringify_failed"}';
  }
}

function trackTextChunks(params: {
  category: string;
  action: string;
  interactionId: string;
  text?: string;
  chunkSize?: number;
  maxChunks?: number;
}) {
  const {
    category,
    action,
    interactionId,
    text,
    chunkSize = 2800,
    maxChunks = 20,
  } = params;
  if (!text) return;

  const chunks = chunkText(text, chunkSize);
  const total = Math.min(chunks.length, maxChunks);

  for (let i = 0; i < total; i += 1) {
    const prefix = `${interactionId} ${i + 1}/${total} `;
    push(["trackEvent", category, action, prefix + chunks[i]]);
  }

  if (chunks.length > maxChunks) {
    push([
      "trackEvent",
      category,
      `${action}_truncated`,
      `${interactionId} total_chunks=${chunks.length} max_chunks=${maxChunks}`,
    ]);
  }
}

/**
 * Tracks a full Q/A exchange in Matomo as:
 * - one "meta" event (small JSON)
 * - multiple "question" chunk events
 * - multiple "response" chunk events
 */
export function trackAnswerReceived(payload: QaMatomoPayload): string {
  const interactionId = generateInteractionId();

  const { userQuestion, llmResponse, ...meta } = payload;

  push([
    "trackEvent",
    "llm",
    "answer_meta",
    `${interactionId} ${safeJsonStringify(meta)}`,
  ]);

  trackTextChunks({
    category: "llm",
    action: "answer_question",
    interactionId,
    text: userQuestion,
  });

  trackTextChunks({
    category: "llm",
    action: "answer_response",
    interactionId,
    text: llmResponse,
  });

  if (payload.errorMessage) {
    push([
      "trackEvent",
      "llm",
      "answer_error",
      `${interactionId} ${payload.errorMessage}`,
    ]);
  }

  return interactionId;
}
