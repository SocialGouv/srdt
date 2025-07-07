import React from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { push } from "@socialgouv/matomo-next";
import { Conversation } from "./types";

interface ChatHistoryProps {
  conversations: Conversation[];
  currentConversationId: string;
  showHistory: boolean;
  onShowHistoryChange: (show: boolean) => void;
  onConversationSelect: (conversationId: string) => void;
  onDeleteConversation: (conversationId: string, e: React.MouseEvent) => void;
}

export const ChatHistory: React.FC<ChatHistoryProps> = ({
  conversations,
  currentConversationId,
  showHistory,
  onShowHistoryChange,
  onConversationSelect,
  onDeleteConversation,
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

  return (
    <div
      style={{
        width: showHistory ? "300px" : "0px",
        transition: "width 0.3s ease",
        overflow: "hidden",
        borderRight: showHistory
          ? "1px solid var(--background-alt-blue-france)"
          : "none",
        backgroundColor: "var(--background-alt-grey)",
        marginRight: "1rem",
      }}
    >
      {showHistory && (
        <div style={{ padding: "1rem", width: "300px" }}>
          <div
            className={fr.cx("fr-mb-2w")}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <h3 className={fr.cx("fr-h6", "fr-m-0")}>Historique</h3>
            <Button
              iconId="fr-icon-close-line"
              priority="tertiary no outline"
              size="small"
              title="Fermer l'historique"
              onClick={() => onShowHistoryChange(false)}
            />
          </div>

          <div style={{ maxHeight: "calc(80vh - 200px)", overflowY: "auto" }}>
            {conversationsWithMessages.length === 0 && (
              <div className={fr.cx("fr-mt-4v", "fr-px-1v")}>
                <p className={fr.cx("fr-text--sm")}>
                  Vous n&apos;avez pas encore de conversations enregistrées.
                </p>
                <p className={fr.cx("fr-text--sm")}>
                  <i>
                    Cliquez sur le bouton « Nouvelle conversation » pour en
                    créer une.
                  </i>
                </p>
              </div>
            )}
            {conversationsWithMessages.map((conversation) => (
              <div
                key={conversation.id}
                className={fr.cx("fr-mb-1v")}
                style={{
                  padding: "0.75rem",
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
                        conversation.id === currentConversationId
                          ? "600"
                          : "400",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      marginBottom: "0.25rem",
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
      )}
    </div>
  );
};
