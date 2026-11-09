"use client";

import { useEffect, useId, useRef, useState } from "react";
import { fr } from "@codegouvfr/react-dsfr";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { push } from "@socialgouv/matomo-next";
import { TimeSavedAnswer } from "./indicators";
import { saveIndicator } from "./save-indicator";
import { TIME_SAVED_QUESTION_DELAY_MS, TimeSavedSurvey } from "./time-saved";
import styles from "./Indicators.module.css";

const OPTIONS: { value: TimeSavedAnswer; label: string }[] = [
  { value: "yes", label: "Oui" },
  { value: "no", label: "Non" },
  { value: "dont_know", label: "Je ne sais pas" },
];

type Props = {
  survey: TimeSavedSurvey;
  onSurveyChange: (survey: TimeSavedSurvey) => void;
  /** Database conversation ID, to save the answer */
  dbConversationId?: string;
  isFollowupResponse?: boolean;
};

/**
 * "Did the answer save you time?" question. It shows up
 * TIME_SAVED_QUESTION_DELAY_MS after the answer was displayed (right away if
 * that time has already passed, e.g. when coming back to the conversation).
 */
export const TimeSavedQuestion = ({
  survey,
  onSurveyChange,
  dbConversationId,
  isFollowupResponse,
}: Props) => {
  const questionId = useId();
  // Thanks are only shown right after answering, not when coming back later.
  const [hasJustAnswered, setHasJustAnswered] = useState(false);
  const responseKind = isFollowupResponse ? "followup" : "initial";
  const { messageIndex, answerDisplayedAt, status } = survey;

  // Latest callback, so the chat re-rendering doesn't restart the timer.
  const onSurveyChangeRef = useRef(onSurveyChange);
  useEffect(() => {
    onSurveyChangeRef.current = onSurveyChange;
  });

  useEffect(() => {
    if (status !== "pending") return;
    const timeout = setTimeout(() => {
      push(["trackEvent", "time_saved", "display", responseKind]);
      onSurveyChangeRef.current({
        messageIndex,
        answerDisplayedAt,
        status: "shown",
      });
    }, Math.max(0, answerDisplayedAt + TIME_SAVED_QUESTION_DELAY_MS - Date.now()));
    return () => clearTimeout(timeout);
  }, [status, messageIndex, answerDisplayedAt, responseKind]);

  const handleAnswer = (answer: TimeSavedAnswer) => {
    push(["trackEvent", "time_saved", answer, responseKind]);
    if (dbConversationId) {
      void saveIndicator({
        action: "save_time_saved",
        conversationId: dbConversationId,
        timeSaved: answer,
      });
    }
    setHasJustAnswered(true);
    onSurveyChange({ ...survey, status: "answered" });
  };

  return (
    // Live region present from the start, so the question is announced when
    // it shows up.
    <div aria-live="polite">
      {status === "shown" && (
        <div
          role="group"
          aria-labelledby={questionId}
          className={styles.timeSaved}
        >
          <p id={questionId} className={fr.cx("fr-text--bold", "fr-mb-2w")}>
            Diriez-vous que la réponse de l’assistant IA vous a fait gagner du
            temps&nbsp;?
          </p>
          <div className={styles.timeSavedButtons}>
            {OPTIONS.map((option) => (
              <Button
                key={option.value}
                priority="secondary"
                onClick={() => handleAnswer(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>
      )}
      {status === "answered" && hasJustAnswered && (
        <p className={`${styles.timeSaved} ${fr.cx("fr-text--sm", "fr-mb-0")}`}>
          Merci pour votre réponse&nbsp;!
        </p>
      )}
    </div>
  );
};
