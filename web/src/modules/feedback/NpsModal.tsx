"use client";

import { useEffect, useId, useRef, useState } from "react";
import { fr } from "@codegouvfr/react-dsfr";
import { createModal } from "@codegouvfr/react-dsfr/Modal";
import { useIsModalOpen } from "@codegouvfr/react-dsfr/Modal/useIsModalOpen";
import { push } from "@socialgouv/matomo-next";
import { NPS_MAX, NPS_MIN, NpsTrigger } from "./indicators";
import {
  hasNpsBeenShown,
  markNpsShown,
  NPS_REQUEST_EVENT,
  requestNps,
} from "./nps";
import { saveIndicator } from "./save-indicator";
import styles from "./Indicators.module.css";

const modal = createModal({
  id: "nps-modal",
  isOpenedByDefault: false,
});

const SCORES = Array.from(
  { length: NPS_MAX - NPS_MIN + 1 },
  (_, i) => NPS_MIN + i
);

type Props = {
  /**
   * Also open when the pointer leaves the window through the top (desktop
   * only), e.g. once the user has received an answer.
   */
  openOnExitIntent: boolean;
};

/**
 * NPS modal ("Recommanderiez-vous l'assistant IA à un collègue ?", 0 to 10),
 * shown once per browser. It opens on requestNps() (copying an answer) and on
 * exit intent.
 */
export const NpsModal = ({ openOnExitIntent }: Props) => {
  const id = useId();
  const [score, setScore] = useState<number | null>(null);
  const triggerRef = useRef<NpsTrigger | null>(null);
  const submittedRef = useRef(false);
  const isOpenRef = useRef(false);
  // Still once per page when localStorage is unavailable.
  const shownRef = useRef(false);

  useIsModalOpen(modal, {
    // Recorded once DSFR has actually opened the modal: asked too early (DSFR
    // not ready yet), modal.open() does nothing and a later trigger may retry.
    onDisclose: () => {
      isOpenRef.current = true;
      shownRef.current = true;
      markNpsShown();
      if (triggerRef.current) {
        push(["trackEvent", "nps", "display", triggerRef.current]);
      }
    },
    onConceal: () => {
      isOpenRef.current = false;
      if (!submittedRef.current && triggerRef.current) {
        push(["trackEvent", "nps", "dismiss", triggerRef.current]);
      }
    },
  });

  useEffect(() => {
    const open = (event: Event) => {
      if (isOpenRef.current || shownRef.current || hasNpsBeenShown()) return;
      triggerRef.current = (event as CustomEvent<NpsTrigger>).detail;
      modal.open();
    };
    window.addEventListener(NPS_REQUEST_EVENT, open);
    return () => window.removeEventListener(NPS_REQUEST_EVENT, open);
  }, []);

  useEffect(() => {
    if (!openOnExitIntent) return;
    // Leaving through the top of the window means nothing with a finger.
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
      return;
    }
    const onMouseOut = (event: MouseEvent) => {
      // No relatedTarget: the pointer left the page; clientY <= 0: through
      // the top (towards the tabs or the address bar).
      if (event.relatedTarget || event.clientY > 0) return;
      requestNps("exit_intent");
    };
    document.addEventListener("mouseout", onMouseOut);
    return () => document.removeEventListener("mouseout", onMouseOut);
  }, [openOnExitIntent]);

  const handleSubmit = () => {
    if (score === null || submittedRef.current) return;
    submittedRef.current = true;
    push(["trackEvent", "nps", "submit", triggerRef.current, score]);
    void saveIndicator({
      action: "save_nps",
      score,
      trigger: triggerRef.current,
    });
    modal.close();
  };

  return (
    <modal.Component
      title="Donnez votre avis"
      size="large"
      buttons={[
        { children: "Ne pas répondre", priority: "secondary" },
        {
          children: "Valider",
          onClick: handleSubmit,
          disabled: score === null,
          // Closed by handleSubmit, once the answer is recorded (otherwise
          // the closing could be tracked as a dismissal).
          doClosesModal: false,
        },
      ]}
    >
      <fieldset
        className={fr.cx("fr-fieldset", "fr-mb-0")}
        aria-labelledby={`${id}-legend`}
      >
        <legend id={`${id}-legend`} className={fr.cx("fr-fieldset__legend")}>
          Recommanderiez-vous l’assistant IA à un collègue&nbsp;?
          <span className={fr.cx("fr-hint-text")}>
            0&nbsp;: pas du tout, 10&nbsp;: absolument
          </span>
        </legend>
        <div className={fr.cx("fr-fieldset__element")}>
          <div className={styles.npsScale}>
            {SCORES.map((value) => (
              <div key={value} className={styles.npsOption}>
                <input
                  type="radio"
                  id={`${id}-${value}`}
                  name={`${id}-score`}
                  value={value}
                  checked={score === value}
                  onChange={() => setScore(value)}
                  className={styles.npsInput}
                />
                <label htmlFor={`${id}-${value}`} className={styles.npsLabel}>
                  {value}
                </label>
              </div>
            ))}
          </div>
        </div>
      </fieldset>
    </modal.Component>
  );
};
