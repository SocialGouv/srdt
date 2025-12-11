"use client";

import { useState } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { Checkbox } from "@codegouvfr/react-dsfr/Checkbox";
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
  const [selectedReasons, setSelectedReasons] = useState<Set<string>>(
    new Set()
  );
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

  const toggleReason = (reason: string) => {
    setSelectedReasons((prev) => {
      const newReasons = new Set(prev);
      if (newReasons.has(reason)) {
        newReasons.delete(reason);
      } else {
        newReasons.add(reason);
      }
      return newReasons;
    });
  };

  const handleSubmitNegativeFeedback = () => {
    const reasons = Array.from(selectedReasons);
    // If "other" is selected, replace it with the actual text
    const finalReasons = reasons.map((r) => (r === "other" ? otherReason : r));

    // Track negative feedback with all reasons in Matomo
    // Join multiple reasons with a separator
    const reasonsString = finalReasons.join(" | ");
    push(["trackEvent", "feedback", "negative", reasonsString]);

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
          Pour quelle(s) raison(s) la réponse n’est pas satisfaisante ?
        </p>
        <Checkbox
          options={[
            {
              label: "La réponse est fausse",
              nativeInputProps: {
                checked: selectedReasons.has("false"),
                onChange: () => toggleReason("false"),
              },
            },
            {
              label: "La réponse est incomplète",
              nativeInputProps: {
                checked: selectedReasons.has("incomplete"),
                onChange: () => toggleReason("incomplete"),
              },
            },
            {
              label:
                "La réponse de l'assistant n'est pas suffisamment compréhensible",
              nativeInputProps: {
                checked: selectedReasons.has("not_understandable"),
                onChange: () => toggleReason("not_understandable"),
              },
            },
            {
              label: "Autre (préciser)",
              nativeInputProps: {
                checked: selectedReasons.has("other"),
                onChange: () => toggleReason("other"),
              },
            },
          ]}
        />
        {selectedReasons.has("other") && (
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
            selectedReasons.size === 0 ||
            (selectedReasons.has("other") && !otherReason.trim())
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
