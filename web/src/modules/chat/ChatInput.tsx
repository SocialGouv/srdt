"use client";

import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { AutoresizeTextarea } from "@/modules/common/AutoresizeTextarea";
import { Conversation, ChatMessage } from "./types";
import styles from "./Chat.module.css";

interface ChatInputProps {
  newMessage: string;
  setNewMessage: (message: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  isDisabled: boolean;
  messages: ChatMessage[];
  currentConversation: Conversation | undefined;
  onNewConversation: () => void;
  onSuggestion: (text: string) => void;
}

// One-click follow-up suggestions. `label` is shown on the chip, `message` is
// the follow-up actually sent to the assistant.
const FOLLOWUP_SUGGESTIONS = [
  { label: "Résumer la réponse", message: "Résume la réponse de façon concise." },
  {
    label: "Rédiger un mail prêt à envoyer",
    message:
      "Rédige un mail synthétique reprenant les principaux points de la réponse. Le mail est à destination de l'usager qui a envoyé la question et répond à sa demande.",
  },
  {
    label: "Citer les textes de référence",
    message: "Cite les textes de référence applicables.",
  },
];

export const ChatInput = ({
  newMessage,
  setNewMessage,
  onSubmit,
  onKeyDown,
  isDisabled,
  messages,
  currentConversation,
  onNewConversation,
  onSuggestion,
}: ChatInputProps) => {
  const isGenerating =
    messages.length > 0 &&
    (messages[messages.length - 1].isLoading ||
      messages[messages.length - 1].isStreaming);

  const canFollowup = !!currentConversation?.isAwaitingFollowup && !isDisabled;

  const placeholder = isDisabled
    ? isGenerating
      ? "Génération de la réponse en cours…"
      : "Veuillez démarrer une nouvelle conversation pour poser une autre question."
    : "Posez une question de suivi ou démarrez une nouvelle conversation…";

  return (
    <div className={styles.followupCard}>
      <div className={styles.followupHeader}>
        <h2 className={fr.cx("fr-h5", "fr-m-0")}>Poursuivre l’échange</h2>
        <Button
          iconId="fr-icon-add-line"
          priority="secondary"
          size="small"
          onClick={onNewConversation}
        >
          Nouvelle conversation
        </Button>
      </div>

      {canFollowup && (
        <>
          <p className={styles.followupHint}>
            💡 Utilisez une suggestion ou posez une question complémentaire.
          </p>
          <div className={styles.suggestionChips}>
            {FOLLOWUP_SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.label}
                type="button"
                className={styles.suggestionChip}
                onClick={() => onSuggestion(suggestion.message)}
              >
                {suggestion.label}
              </button>
            ))}
          </div>
        </>
      )}

      <form onSubmit={onSubmit} className={styles.followupInputRow}>
        <div className={styles.followupTextareaWrap}>
          <AutoresizeTextarea
            value={newMessage}
            onChange={setNewMessage}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            disabled={isDisabled}
            maxLines={10}
          />
        </div>
        <Button
          iconId="fr-icon-send-plane-fill"
          type="submit"
          disabled={isDisabled || !newMessage.trim()}
        >
          Envoyer
        </Button>
      </form>
    </div>
  );
};
