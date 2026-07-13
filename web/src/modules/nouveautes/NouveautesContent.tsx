"use client";

import React, { useEffect } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";
import { ChatHistory } from "@/modules/chat/ChatHistory";
import { useSidebarNav } from "@/modules/chat/useSidebarNav";
import { externalLinkComponents } from "@/modules/common/markdownComponents";
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
  ...externalLinkComponents,
  // Inline code whose text matches a keyword becomes a DSFR badge.
  code: ({
    className,
    children,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    node: _node,
    ...props
  }: React.HTMLAttributes<HTMLElement> & {
    children?: React.ReactNode;
    node?: unknown;
  }) => {
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
  const sidebar = useSidebarNav();

  // Land at the top of the page (the previous screen's scroll can carry over).
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  // Opening the page counts as reading the latest updates: clear the dot.
  useEffect(() => {
    markNouveautesSeen(version);
  }, [version]);

  return (
    <LayoutWrapper fullWidth>
      <div
        className={`${chatStyles.chatContainer} ${chatStyles.chatContainerEmpty}`}
      >
        <ChatHistory
          {...sidebar}
          currentConversationId=""
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
