import { UserLLMMessage, AnswerResponse } from "@/types";

/**
 * Lightweight description of a document used to generate an answer. It is
 * persisted in localStorage with the message, so it deliberately carries only
 * what the sources panel displays: never the full document content.
 */
export interface MessageSource {
  /** Document id in the search index (cdtn_id). */
  id: string;
  title: string;
  url: string;
  /** Search collection the document comes from (see `Collection`). */
  source: string;
  /** Short plain-text preview of the document. */
  excerpt: string;
}

export interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
  isStreaming?: boolean;
  isFollowup?: boolean;
  /** Documents given to the LLM for this answer (assistant messages only). */
  sources?: MessageSource[];
}

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  lastApiResult?: AnswerResponse | null;
  lastResponseTime?: number;
  lastUserQuestion?: string;
  lastApiError?: string;
  hasFailed?: boolean;
  isAwaitingFollowup?: boolean;
  firstUserQuestion?: string;
  firstAssistantAnswer?: string;
  selectedModel?: string;
  /** Number of follow-up questions asked in this conversation */
  followupCount?: number;
  /** Database conversation ID for tracking (saved to PostgreSQL) */
  dbConversationId?: string;
}
