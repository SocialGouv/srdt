import React from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { push } from "@socialgouv/matomo-next";
import { Conversation } from "./types";
import styles from "./Chat.module.css";

interface ChatHistoryProps {
  conversations: Conversation[];
  currentConversationId: string;
  showHistory: boolean;
  onShowHistoryChange: (show: boolean) => void;
  onConversationSelect: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string, e: React.MouseEvent) => void;
  onNewConversation: () => void;
}

export const ChatHistory: React.FC<ChatHistoryProps> = ({
  conversations,
  currentConversationId,
  showHistory,
  onShowHistoryChange,
  onConversationSelect,
  onDeleteConversation,
  onNewConversation,
}) => {
  // Get conversations that have actual user messages (not just the welcome message) and haven't failed
  const conversationsWithMessages = conversations.filter(
    (conv) =>
      conv.messages.some((msg) => msg.role === "user") && !conv.hasFailed
  );

  const handleConversationClick = (conversationId: string) => {
    onConversationSelect(conversationId);
    push(["trackEvent", "history", "select conversation"]);
  };

  if (!showHistory) {
    return (
      <div className={`${styles.sidebar} ${styles.sidebarCollapsed}`}>
        <Button
          iconId="fr-icon-arrow-right-s-line"
          priority="tertiary no outline"
          title="Afficher le panneau"
          onClick={() => {
            push(["trackEvent", "history", "show history"]);
            onShowHistoryChange(true);
          }}
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
