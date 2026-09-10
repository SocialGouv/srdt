import { UserLLMMessage, AnswerResponse } from "@/types";

/**
 * Lightweight description of a document used to generate an answer. It is
 * persisted in localStorage with the message, so it deliberately carries only
 * what the sources panel displays: never the full document content.
 */
export interface MessageSource {
  /** Document id (cdtn_id), Legifrance article id, or the URL as a fallback. */
  id: string;
  title: string;
  url: string;
  /** Short plain-text preview; empty when the document was not retrieved. */
  excerpt: string;
  /** False when the linked page (fiche, contribution…) was not among the documents given to the LLM. */
  inContext?: boolean;
}

export interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
  isStreaming?: boolean;
  isFollowup?: boolean;
  /** Links of this answer, enriched from the documents given to the LLM (assistant messages only). */
  sources?: MessageSource[];
  /** Links the API stripped from the answer because they could not be verified. */
  removedLinks?: number;
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
