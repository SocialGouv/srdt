"use client";

import { fr } from "@codegouvfr/react-dsfr";
import { createModal } from "@codegouvfr/react-dsfr/Modal";
import { useIsModalOpen } from "@codegouvfr/react-dsfr/Modal/useIsModalOpen";
import { AgreementSearchInput } from "./AgreementSearchInput";
import { Agreement } from "./search";
import styles from "./AgreementModal.module.css";

const modal = createModal({
  id: "agreement-modal",
  isOpenedByDefault: false,
});

/** Props for the button that opens the modal (DSFR wires the click). */
export const agreementModalButtonProps = modal.buttonProps;

type Props = {
  /** Called once the user has picked an agreement; the modal closes first. */
  onAgreementSelect: (agreement: Agreement) => void;
};

/**
 * Lets the user specify the collective agreement after an answer was given.
 * Picking one starts a new conversation (see the notice), so the modal closes
 * as soon as a suggestion is selected.
 */
export const AgreementModal = ({ onAgreementSelect }: Props) => {
  // The search field is only mounted while the modal is open so it starts
  // empty on every opening.
  const isOpen = useIsModalOpen(modal);

  return (
    <modal.Component
      title="Précisez et sélectionnez la convention collective"
      size="large"
      className={styles.modal}
      buttons={{ children: "Fermer", priority: "secondary" }}
    >
      {isOpen && (
        <AgreementSearchInput
          label="Nom de la convention collective ou son numéro d’identification IDCC (4 chiffres)"
          hintText="Ex : transport routier ou 1486"
          onAgreementSelect={(agreement) => {
            if (!agreement) return;
            modal.close();
            onAgreementSelect(agreement);
          }}
          trackingActionName="chat"
        />
      )}
      <p className={styles.notice}>
        <span
          className={fr.cx("fr-icon-info-fill", "fr-icon--sm")}
          aria-hidden="true"
        />
        Cette action lancera une nouvelle conversation et générera une nouvelle
        réponse tenant compte de la convention collective sélectionnée.
      </p>
    </modal.Component>
  );
};
