"use client";

import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { AutoresizeTextarea } from "@/modules/common/AutoresizeTextarea";
import { Agreement } from "../convention-collective/search";
import { AgreementSearchInput } from "../convention-collective/AgreementSearchInput";
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
  selectedAgreement: Agreement | undefined;
  setSelectedAgreement: (agreement: Agreement | undefined) => void;
}

export const ChatInput = ({
  newMessage,
  setNewMessage,
  onSubmit,
  onKeyDown,
  isDisabled,
  messages,
  currentConversation,
  selectedAgreement,
  setSelectedAgreement,
}: ChatInputProps) => {
  return (
    <form
      onSubmit={onSubmit}
      className={`${fr.cx("fr-grid-row", "fr-grid-row--gutters")} ${
        styles.chatForm
      }`}
    >
      <div className={fr.cx("fr-col-11")}>
        <AutoresizeTextarea
          value={newMessage}
          onChange={setNewMessage}
          onKeyDown={onKeyDown}
          placeholder={
            isDisabled
              ? // Check if we're actively generating (last message is loading/streaming) vs conversation is complete
                messages.length > 0 &&
                (messages[messages.length - 1].isLoading ||
                  messages[messages.length - 1].isStreaming)
                ? "Génération de la réponse en cours...\nVous pourrez ensuite poser une question de suivi ou démarrer une nouvelle conversation."
                : "Veuillez démarrer une nouvelle conversation pour poser une autre question.\nPour cela, remontez en haut de la page et cliquez sur le bouton « Nouvelle conversation »."
              : currentConversation?.isAwaitingFollowup
              ? "Posez une question de suivi ou démarrez une nouvelle conversation...\nEx. : « Fais-en un mail », « Cite tous les textes applicables », « Synthétise la réponse »..."
              : "Saisissez votre message"
          }
          disabled={isDisabled}
          maxLines={10}
        />
      </div>
      <div className={`${fr.cx("fr-col-1")} ${styles.submitButtonContainer}`}>
        <Button
          iconId="fr-icon-send-plane-fill"
          title={
            isDisabled
              ? // Check if we're actively generating (last message is loading/streaming) vs conversation is complete
                messages.length > 0 &&
                (messages[messages.length - 1].isLoading ||
                  messages[messages.length - 1].isStreaming)
                ? "Génération en cours, patientez..."
                : "Démarrez une nouvelle conversation pour poser une autre question"
              : currentConversation?.isAwaitingFollowup
              ? "Envoyer votre question de suivi"
              : "Envoyer votre message"
          }
          type="submit"
          className={fr.cx("fr-cell--center")}
          disabled={isDisabled}
        />
      </div>
      {!isDisabled && !currentConversation?.firstUserQuestion && (
        <div className={fr.cx("fr-col-11")}>
          <AgreementSearchInput
            onAgreementSelect={(agreement) => {
              setSelectedAgreement(agreement);
            }}
            defaultAgreement={selectedAgreement}
            trackingActionName="chat"
          />
        </div>
      )}
      {currentConversation?.isAwaitingFollowup && !isDisabled && (
        <div className={fr.cx("fr-col-12", "fr-mt-1w")}>
          <div className={styles.followupInfo}>
            💡 Vous pouvez poser une question de suivi pour approfondir cette
            réponse, ou démarrer une nouvelle conversation.
          </div>
        </div>
      )}
    </form>
  );
};
