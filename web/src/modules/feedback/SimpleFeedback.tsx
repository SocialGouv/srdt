"use client";

import { useState } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { RadioButtons } from "@codegouvfr/react-dsfr/RadioButtons";
import { Input } from "@codegouvfr/react-dsfr/Input";
import { fr } from "@codegouvfr/react-dsfr";
import { push } from "@socialgouv/matomo-next";

type SimpleFeedbackProps = {
  modelName?: string;
  familyModel?: string;
  scenarioVersion?: string;
  globalResponseTime?: number;
  inputNbTokens?: number;
  outputNbTokens?: number;
  userQuestion?: string;
  llmResponse?: string;
  errorMessage?: string;
  idcc?: string;
  isFollowupResponse?: boolean;
};

export const SimpleFeedback = (props: SimpleFeedbackProps) => {
  const [showQuestionnaire, setShowQuestionnaire] = useState(false);
  const [selectedReason, setSelectedReason] = useState<string>("");
  const [otherReason, setOtherReason] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handlePositiveFeedback = () => {
    setSubmitted(true);

    // Track positive feedback in Matomo
    push([
      "trackEvent",
      "feedback",
      "positive",
      props.isFollowupResponse ? "followup" : "initial",
    ]);
  };

  const handleNegativeFeedback = () => {
    setShowQuestionnaire(true);
  };

  const handleSubmitNegativeFeedback = () => {
    const reason = selectedReason === "other" ? otherReason : selectedReason;

    // Track negative feedback with reason in Matomo
    push(["trackEvent", "feedback", "negative", reason]);

    setSubmitted(true);
  };

  if (submitted) {
    return (
      <div className={fr.cx("fr-mt-2w", "fr-mb-2w")}>
        <p className={fr.cx("fr-text--sm", "fr-m-0")}>
          Merci pour votre retour !
        </p>
      </div>
    );
  }

  if (showQuestionnaire) {
    return (
      <div className={fr.cx("fr-mt-2w")}>
        <p className={fr.cx("fr-text--bold", "fr-mb-1w")}>
          Pour quelle(s) raison(s) la réponse n'est pas satisfaisante ?
        </p>
        <RadioButtons
          options={[
            {
              label: "La réponse est fausse",
              nativeInputProps: {
                value: "false",
                checked: selectedReason === "false",
                onChange: () => setSelectedReason("false"),
              },
            },
            {
              label: "La réponse est incomplète",
              nativeInputProps: {
                value: "incomplete",
                checked: selectedReason === "incomplete",
                onChange: () => setSelectedReason("incomplete"),
              },
            },
            {
              label: "Autre (préciser)",
              nativeInputProps: {
                value: "other",
                checked: selectedReason === "other",
                onChange: () => setSelectedReason("other"),
              },
            },
          ]}
        />
        {selectedReason === "other" && (
          <Input
            label=""
            nativeInputProps={{
              value: otherReason,
              onChange: (e) => setOtherReason(e.target.value),
              placeholder: "Précisez la raison...",
            }}
            className={fr.cx("fr-mt-1w")}
          />
        )}
        <Button
          onClick={handleSubmitNegativeFeedback}
          disabled={
            !selectedReason ||
            (selectedReason === "other" && !otherReason.trim())
          }
          className={fr.cx("fr-mt-2w")}
        >
          Envoyer
        </Button>
      </div>
    );
  }

  return (
    <div className={fr.cx("fr-mt-2w")}>
      <div style={{ display: "flex", gap: "1rem" }}>
        <Button
          onClick={handlePositiveFeedback}
          iconId="fr-icon-thumb-up-line"
          priority="secondary"
          title="Cette réponse est satisfaisante"
        >
          Réponse satisfaisante
        </Button>
        <Button
          onClick={handleNegativeFeedback}
          iconId="fr-icon-thumb-down-line"
          priority="secondary"
          title="Cette réponse n'est pas satisfaisante"
        >
          Réponse non satisfaisante
        </Button>
      </div>
    </div>
  );
};
