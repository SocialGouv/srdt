import { Conversation } from "./types";

export const STORAGE_KEY = "chat-conversations";
export const CURRENT_CONVERSATION_KEY = "current-conversation-id";
/** Set by other screens (e.g. Nouveautés) to ask the chat to open a given
 *  conversation when it next mounts. */
export const OPEN_CONVERSATION_KEY = "open-conversation-id";

/** Read the persisted conversation list (used by screens outside of <Chat/>). */
export function loadStoredConversations(): Conversation[] {
  if (typeof window === "undefined") return [];
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return [];
  try {
    const parsed = JSON.parse(saved) as (Omit<Conversation, "createdAt"> & {
      createdAt: string;
    })[];
    return parsed.map(
      (conv) =>
        ({
          ...conv,
          createdAt: new Date(conv.createdAt),
        } as Conversation)
    );
  } catch {
    return [];
  }
}

export function persistConversations(conversations: Conversation[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
}
