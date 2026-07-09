"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";
import { ChatHistory } from "@/modules/chat/ChatHistory";
import { Conversation } from "@/modules/chat/types";
import {
  loadStoredConversations,
  persistConversations,
  OPEN_CONVERSATION_KEY,
} from "@/modules/chat/conversation-storage";
import { markNouveautesSeen } from "./seen";
import chatStyles from "@/modules/chat/Chat.module.css";
import styles from "./Nouveautes.module.css";

type BadgeSeverity = "info" | "warning" | "success";

// Inline-code keywords that render as DSFR badges (see src/content/nouveautes.md).
const BADGES: Record<string, BadgeSeverity> = {
  NOUVEAU: "info",
  CORRECTION: "warning",
  AMÉLIORATION: "success",
  AMELIORATION: "success",
};

const markdownComponents = {
  // Only external links open in a new tab; internal/relative links behave normally.
  a: ({ href, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
    const isExternal = typeof href === "string" && /^https?:\/\//.test(href);
    return (
      <a
        href={href}
        {...props}
        {...(isExternal
          ? { target: "_blank", rel: "noopener noreferrer" }
          : {})}
      />
    );
  },
  // Inline code whose text matches a keyword becomes a DSFR badge.
  code: ({
    className,
    children,
    ...props
  }: React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }) => {
    const text = typeof children === "string" ? children.trim() : "";
    const severity = !className ? BADGES[text.toUpperCase()] : undefined;

    if (severity) {
      return (
        <Badge as="span" noIcon severity={severity} className={styles.badge}>
          {text}
        </Badge>
      );
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
};

type Props = {
  markdown: string;
  /** Fingerprint of this content; recorded as "seen" when the page opens. */
  version: string;
};

export function NouveautesContent({ markdown, version }: Props) {
  const router = useRouter();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showHistory, setShowHistory] = useState(true);

  useEffect(() => {
    setConversations(loadStoredConversations());
    // Opening the page counts as reading the latest updates: clear the dot.
    markNouveautesSeen(version);
    // Land at the top of the page (the previous screen's scroll can carry over).
    window.scrollTo(0, 0);
  }, [version]);

  // The sidebar actions live on the chat screen — route back to it, asking it
  // to open the requested conversation when relevant.
  const handleNewConversation = () => router.push("/");

  const handleConversationSelect = (conversationId: string) => {
    sessionStorage.setItem(OPEN_CONVERSATION_KEY, conversationId);
    router.push("/");
  };

  const handleDeleteConversation = (
    conversationId: string,
    e: React.MouseEvent
  ) => {
    e.stopPropagation();
    const next = conversations.filter((c) => c.id !== conversationId);
    setConversations(next);
    persistConversations(next);
  };

  return (
    <LayoutWrapper fullWidth>
      <div
        className={`${chatStyles.chatContainer} ${chatStyles.chatContainerEmpty}`}
      >
        <ChatHistory
          conversations={conversations}
          currentConversationId=""
          showHistory={showHistory}
          onShowHistoryChange={setShowHistory}
          onConversationSelect={handleConversationSelect}
          onDeleteConversation={handleDeleteConversation}
          onNewConversation={handleNewConversation}
          activeItem="nouveautes"
          nouveautesVersion={version}
        />

        <div className={chatStyles.chatMainContent}>
          <div className={styles.card}>
            <h1 className={styles.title}>Quoi de neuf dans l&apos;outil&nbsp;?</h1>
            <p className={styles.intro}>
              Découvrez les dernières fonctionnalités et améliorations de
              l&apos;assistant.
            </p>
            <article className={styles.markdownBody}>
              <Markdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {markdown}
              </Markdown>
            </article>
          </div>
        </div>
      </div>
    </LayoutWrapper>
  );
}
