"use client";

import { useEffect, useMemo, useRef } from "react";
import Image from "next/image";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import styles from "./Chat.module.css";
import { MessageSource } from "./types";
import { getSourceLabel, groupSourcesByCategory } from "./sources";
import marianne from "./marianne.png";

/** DOM id of the panel, referenced by the "Sources" buttons (aria-controls). */
export const SOURCES_PANEL_ID = "sources-panel";

interface SourcesPanelProps {
  sources: MessageSource[];
  /** Links the API stripped from the answer because they could not be verified. */
  removedLinks?: number;
  onClose: () => void;
}

const SourceItem = ({ source }: { source: MessageSource }) => (
  <li className={styles.sourceItem}>
    <p className={styles.sourceKind}>
      <Image
        src={marianne}
        alt=""
        unoptimized
        width={18}
        height={18}
        aria-hidden="true"
        className={styles.marianneIcon}
      />
      {getSourceLabel(source.url)}
      {source.inContext === false && (
        <Badge as="span" small noIcon severity="info">
          À vérifier
        </Badge>
      )}
    </p>
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className={styles.sourceTitle}
    >
      {source.title}
    </a>
    {source.excerpt && <p className={styles.sourceExcerpt}>{source.excerpt}</p>}
    {source.inContext === false && (
      <p className={styles.sourceNote}>
        Page citée par l’assistant sans figurer dans ses documents de
        référence pour cette réponse.
      </p>
    )}
  </li>
);

/**
 * Right-hand overlay listing the links of an answer, grouped by category in
 * a fixed order (fiches pratiques, articles de loi, conventions collectives,
 * arrêts de la Cour de cassation).
 */
export const SourcesPanel = ({
  sources,
  removedLinks = 0,
  onClose,
}: SourcesPanelProps) => {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const groups = useMemo(() => groupSourcesByCategory(sources), [sources]);

  useEffect(() => {
    // preventScroll: the page must not jump when the panel opens from the
    // bottom of a long answer.
    closeButtonRef.current?.focus({ preventScroll: true });
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <aside
      id={SOURCES_PANEL_ID}
      className={styles.sourcesPanel}
      aria-labelledby={`${SOURCES_PANEL_ID}-title`}
    >
      <div className={styles.sourcesPanelHeader}>
        <h2 id={`${SOURCES_PANEL_ID}-title`} className="fr-sr-only">
          Sources de la réponse
        </h2>
        <Button
          ref={closeButtonRef}
          iconId="fr-icon-close-line"
          priority="tertiary no outline"
          size="small"
          title="Fermer le panneau des sources"
          onClick={onClose}
        />
      </div>

      {groups.map((group) => (
        <section key={group.key} className={styles.sourcesGroup}>
          <h3 className={styles.sourcesGroupTitle}>{group.label}</h3>
          {group.description && (
            <p className={styles.sourcesGroupDescription}>
              {group.description}
            </p>
          )}
          <ul className={styles.sourcesList}>
            {group.sources.map((source) => (
              <SourceItem key={source.id || source.url} source={source} />
            ))}
          </ul>
        </section>
      ))}

      {removedLinks > 0 && (
        <p className={styles.sourcesFooter}>
          {removedLinks > 1
            ? `${removedLinks} liens ont été retirés de la réponse car ils n’ont pas pu être vérifiés.`
            : "Un lien a été retiré de la réponse car il n’a pas pu être vérifié."}
        </p>
      )}
    </aside>
  );
};
