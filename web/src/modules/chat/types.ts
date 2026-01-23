import { UserLLMMessage, AnswerResponse } from "@/types";

export interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
  isStreaming?: boolean;
  isFollowup?: boolean;
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
  /** Database conversation ID for tracking (saved to PostgreSQL) */
  dbConversationId?: string;
}
