"use client";

import { fr } from "@codegouvfr/react-dsfr";
import { Button } from "@codegouvfr/react-dsfr/Button";
import Image from "next/image";
import { AutoresizeTextarea } from "@/modules/common/AutoresizeTextarea";
import { AgreementSearchInput } from "../convention-collective/AgreementSearchInput";
import { Agreement } from "../convention-collective/search";
import justiceScales from "./justice-scales.svg";
import styles from "./Chat.module.css";

interface NewConversationViewProps {
  newMessage: string;
  setNewMessage: (message: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
  isDisabled: boolean;
  selectedAgreement: Agreement | undefined;
  setSelectedAgreement: (agreement: Agreement | undefined) => void;
}

export const NewConversationView = ({
  newMessage,
  setNewMessage,
  onSubmit,
  onKeyDown,
  isDisabled,
  selectedAgreement,
  setSelectedAgreement,
}: NewConversationViewProps) => {
  return (
    <div className={styles.composerScreen}>
      <div className={styles.composerHero}>
        <Image
          src={justiceScales}
          alt=""
          width={64}
          height={60}
          className={styles.composerHeroIcon}
          aria-hidden="true"
        />
        <h1 className={fr.cx("fr-h3", "fr-mb-1w")}>
          Préparez une réponse ou une recherche en droit du travail
        </h1>
        <p className={fr.cx("fr-text--lg", "fr-mb-0")}>
          Saisissez une demande usager ou une question juridique.
        </p>
      </div>

      <form onSubmit={onSubmit} className={styles.composerCard}>
        <AgreementSearchInput
          label={
            <span className={styles.composerFieldLabel}>
              Convention collective applicable
            </span>
          }
          hintText="À renseigner lorsque l’information est disponible, pour obtenir une réponse plus précise."
          placeholder="Rechercher par nom ou IDCC - ex. transport routier, 1486"
          onAgreementSelect={setSelectedAgreement}
          defaultAgreement={selectedAgreement}
          trackingActionName="chat"
        />

        <div className={styles.composerField}>
          <label className={fr.cx("fr-label")} htmlFor="composer-demande">
            <span className={styles.composerFieldLabel}>Votre demande</span>
            <span className="fr-hint-text">
              Collez la demande de l’usager ou reformulez-la si nécessaire.
            </span>
          </label>
          <div className={fr.cx("fr-input-group", "fr-mt-1w")}>
            <AutoresizeTextarea
              id="composer-demande"
              value={newMessage}
              onChange={setNewMessage}
              onKeyDown={onKeyDown}
              placeholder="Ex : Un salarié peut-il refuser une mutation géographique ? Quels sont ses droits en cas de licenciement ?"
              disabled={isDisabled}
              maxLines={10}
            />
          </div>
        </div>

        <div className={styles.composerActions}>
          <Button
            type="submit"
            iconId="fr-icon-send-plane-fill"
            iconPosition="right"
            disabled={isDisabled || !newMessage.trim()}
          >
            Générer une réponse
          </Button>
        </div>
      </form>

      <p className={styles.composerNotice}>
        <span
          className={fr.cx("fr-icon-info-fill", "fr-icon--sm")}
          aria-hidden="true"
        />
        La réponse proposée doit être vérifiée avant utilisation.
      </p>
    </div>
  );
};
