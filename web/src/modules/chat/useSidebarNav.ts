"use client";

import { useState, useEffect, type MouseEvent } from "react";
import { useRouter } from "next/navigation";
import { Conversation } from "./types";
import {
  loadStoredConversations,
  persistConversations,
  OPEN_CONVERSATION_KEY,
} from "./conversation-storage";

/**
 * Sidebar wiring shared by the standalone pages (Nouveautés, FAQ) that reuse
 * <ChatHistory/> outside of <Chat/>. Conversation actions route back to the
 * chat screen, handing off the requested conversation via sessionStorage.
 * The returned keys match <ChatHistory/>'s props so they can be spread.
 */
export function useSidebarNav() {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showHistory, setShowHistory] = useState(true);

  useEffect(() => {
    setConversations(loadStoredConversations());
  }, []);

  const onNewConversation = () => {
    // Drop any stale "open this conversation" request so we really start fresh.
    sessionStorage.removeItem(OPEN_CONVERSATION_KEY);
    router.push("/");
  };

  const onConversationSelect = (conversationId: string) => {
    sessionStorage.setItem(OPEN_CONVERSATION_KEY, conversationId);
    router.push("/");
  };

  const onDeleteConversation = (conversationId: string, e: MouseEvent) => {
    e.stopPropagation();
    setConversations((prev) => {
      const next = prev.filter((c) => c.id !== conversationId);
      persistConversations(next);
      return next;
    });
  };

  return {
    conversations,
    showHistory,
    onShowHistoryChange: setShowHistory,
    onNewConversation,
    onConversationSelect,
    onDeleteConversation,
  };
}
