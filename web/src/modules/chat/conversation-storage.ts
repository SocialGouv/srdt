import { Conversation } from "./types";
import { MAX_HISTORY_CONVERSATIONS } from "@/constants";

export const STORAGE_KEY = "chat-conversations";
export const CURRENT_CONVERSATION_KEY = "current-conversation-id";
/** Set by other screens (e.g. Nouveautés) to ask the chat to open a given
 *  conversation when it next mounts. */
export const OPEN_CONVERSATION_KEY = "open-conversation-id";

/** A conversation the user actually started (at least one question) that
 *  didn't fail: the ones listed in the sidebar and counted against the cap. */
export function isHistoryConversation(conv: Conversation): boolean {
  return conv.messages.some((msg) => msg.role === "user") && !conv.hasFailed;
}

/** Keep only the MAX_HISTORY_CONVERSATIONS most recent history conversations
 *  (the list is newest first). Conversations that aren't listed (empty or
 *  failed) pass through untouched, so the current one is never dropped. */
export function trimHistory(conversations: Conversation[]): Conversation[] {
  let kept = 0;
  return conversations.filter(
    (conv) => !isHistoryConversation(conv) || kept++ < MAX_HISTORY_CONVERSATIONS
  );
}

/** Shape the list for localStorage: exactly what the sidebar lists (capped, no
 *  empty or failed conversation — the chat recreates a fresh one on mount),
 *  without the heavy search chunks so a caller can't accidentally bloat
 *  localStorage and trigger a QuotaExceededError. */
export function prepareForStorage(conversations: Conversation[]) {
  return trimHistory(conversations)
    .filter(isHistoryConversation)
    .map((conv) => ({
      ...conv,
      lastApiResult: conv.lastApiResult
        ? { ...conv.lastApiResult, localSearchChunks: [] }
        : conv.lastApiResult,
    }));
}

/** Read the persisted conversation list (used by screens outside of <Chat/>). */
export function loadStoredConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return [];
  try {
    const parsed = JSON.parse(saved) as (Omit<Conversation, "createdAt"> & {
      createdAt: string;
    })[];
    return trimHistory(
      parsed.map(
        (conv) =>
          ({
            ...conv,
            createdAt: new Date(conv.createdAt),
          } as Conversation)
      )
    );
  } catch {
    return [];
  }
}

export function persistConversations(conversations: Conversation[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(prepareForStorage(conversations))
  );
}
