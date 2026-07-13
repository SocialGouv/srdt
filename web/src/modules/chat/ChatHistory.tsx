import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { push } from "@socialgouv/matomo-next";
import { Conversation } from "./types";
import { getSeenNouveautesVersion } from "@/modules/nouveautes/seen";
import styles from "./Chat.module.css";

interface ChatHistoryProps {
  conversations: Conversation[];
  currentConversationId: string;
  showHistory: boolean;
  onShowHistoryChange: (show: boolean) => void;
  onConversationSelect: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string, e: React.MouseEvent) => void;
  onNewConversation: () => void;
  /** Highlights a nav entry when the sidebar is shown on its own page. */
  activeItem?: "nouveautes" | "faq";
  /** Fingerprint of the Nouveautés content; drives the "unread" dot. */
  nouveautesVersion?: string;
}

export const ChatHistory: React.FC<ChatHistoryProps> = ({
  conversations,
  currentConversationId,
  showHistory,
  onShowHistoryChange,
  onConversationSelect,
  onDeleteConversation,
  onNewConversation,
  activeItem,
  nouveautesVersion,
}) => {
  // Get conversations that have actual user messages (not just the welcome message) and haven't failed
  const conversationsWithMessages = conversations.filter(
    (conv) =>
      conv.messages.some((msg) => msg.role === "user") && !conv.hasFailed
  );

  // Show a dot when the current content version differs from the last one the
  // user opened. Read from localStorage only after mount to avoid a hydration
  // mismatch (the server can't know what this browser has seen).
  const [seenVersion, setSeenVersion] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setSeenVersion(getSeenNouveautesVersion());
    setMounted(true);
  }, []);

  const hasUnseenNouveautes =
    mounted &&
    activeItem !== "nouveautes" &&
    !!nouveautesVersion &&
    seenVersion !== nouveautesVersion;

  const handleConversationClick = (conversationId: string) => {
    onConversationSelect(conversationId);
    push(["trackEvent", "history", "select conversation"]);
  };

  // Expand the collapsed sidebar (shared by the expand chevron and History icon).
  const handleExpand = () => {
    push(["trackEvent", "history", "show history"]);
    onShowHistoryChange(true);
  };

  if (!showHistory) {
    return (
      <div className={`${styles.sidebar} ${styles.sidebarCollapsed}`}>
        <Button
          iconId="fr-icon-arrow-right-s-line"
          priority="tertiary no outline"
          title="Afficher le panneau"
          onClick={handleExpand}
        />
        <Button
          iconId="fr-icon-add-circle-fill"
          priority="tertiary no outline"
          title="Nouvelle conversation"
          onClick={onNewConversation}
        />
        <span className={styles.sidebarDotAnchor}>
          <Button
            iconId="fr-icon-star-line"
            priority="tertiary no outline"
            title={
              hasUnseenNouveautes ? "Nouveautés (non lues)" : "Nouveautés"
            }
            linkProps={{ href: "/nouveautes" }}
          />
          {hasUnseenNouveautes && (
            <span className={styles.sidebarDotFloating} aria-hidden="true" />
          )}
        </span>
        <Button
          iconId="fr-icon-question-line"
          priority="tertiary no outline"
          title="Aide / FAQ"
          linkProps={{ href: "/faq" }}
        />
        <Button
          iconId="fr-icon-time-line"
          priority="tertiary no outline"
          title="Historique"
          onClick={handleExpand}
        />
      </div>
    );
  }

  return (
    <div className={`${styles.sidebar} ${styles.sidebarOpen}`}>
      <div className={styles.sidebarInner}>
        <div className={styles.sidebarToggleRow}>
          <Button
            iconId="fr-icon-arrow-left-s-line"
            priority="tertiary no outline"
            title="Réduire le panneau"
            onClick={() => onShowHistoryChange(false)}
          />
        </div>

        <button
          type="button"
          className={styles.sidebarRow}
          onClick={onNewConversation}
        >
          <span
            className={fr.cx("fr-icon-add-circle-fill", "fr-icon--sm")}
            aria-hidden="true"
          />
          Nouvelle conversation
        </button>

        <Link
          href="/nouveautes"
          className={`${styles.sidebarRow} ${
            activeItem === "nouveautes" ? styles.sidebarRowActive : ""
          }`}
          onClick={() => push(["trackEvent", "nouveautes", "open"])}
        >
          <span
            className={fr.cx("fr-icon-star-line", "fr-icon--sm")}
            aria-hidden="true"
          />
          Nouveautés
          {hasUnseenNouveautes && (
            <>
              <span className={styles.sidebarDot} aria-hidden="true" />
              <span className="fr-sr-only">(nouveautés non lues)</span>
            </>
          )}
        </Link>

        <Link
          href="/faq"
          className={`${styles.sidebarRow} ${
            activeItem === "faq" ? styles.sidebarRowActive : ""
          }`}
          onClick={() => push(["trackEvent", "faq", "open"])}
        >
          <span
            className={fr.cx("fr-icon-question-line", "fr-icon--sm")}
            aria-hidden="true"
          />
          Aide / FAQ
        </Link>

        <div className={`${styles.sidebarRow} ${styles.sidebarRowStatic}`}>
          <span
            className={fr.cx("fr-icon-time-line", "fr-icon--sm")}
            aria-hidden="true"
          />
          Historique
        </div>

        <div className={styles.sidebarList}>
          {conversationsWithMessages.length === 0 && (
            <div className={fr.cx("fr-mt-2v", "fr-px-1v")}>
              <p className={fr.cx("fr-text--sm")}>
                Vous n&apos;avez pas encore de conversations enregistrées.
              </p>
              <p className={fr.cx("fr-text--sm")}>
                <i>
                  Cliquez sur le bouton « Nouvelle conversation » pour en créer
                  une.
                </i>
              </p>
            </div>
          )}
          {conversationsWithMessages.map((conversation) => (
            <div
              key={conversation.id}
              className={fr.cx("fr-mb-1v")}
              style={{
                padding: "0.5rem",
                borderRadius: "4px",
                cursor: "pointer",
                backgroundColor:
                  conversation.id === currentConversationId
                    ? "var(--background-action-low-blue-france)"
                    : "transparent",
                border:
                  conversation.id === currentConversationId
                    ? "1px solid var(--border-action-high-blue-france)"
                    : "1px solid transparent",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
              }}
              onClick={() => handleConversationClick(conversation.id)}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: "0.875rem",
                    fontWeight:
                      conversation.id === currentConversationId ? "600" : "400",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    marginBottom: "0.125rem",
                  }}
                >
                  {conversation.title}
                </div>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "var(--text-mention-grey)",
                  }}
                >
                  {conversation.createdAt.toLocaleDateString("fr-FR")} à{" "}
                  {conversation.createdAt.toLocaleTimeString("fr-FR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
              </div>
              <Button
                iconId="fr-icon-delete-line"
                priority="tertiary no outline"
                size="small"
                title="Supprimer cette conversation"
                onClick={(e) => onDeleteConversation(conversation.id, e)}
                style={{ marginLeft: "0.5rem", flexShrink: 0 }}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
