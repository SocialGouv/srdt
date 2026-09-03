"use client";

import { useEffect, useMemo, useRef } from "react";
import Image from "next/image";
import { Button } from "@codegouvfr/react-dsfr/Button";
import styles from "./Chat.module.css";
import { MessageSource } from "./types";
import { getSourceLabel, splitSourcesByCitation } from "./sources";
import marianne from "./marianne.png";

/** DOM id of the panel, referenced by the "Sources" buttons (aria-controls). */
export const SOURCES_PANEL_ID = "sources-panel";

interface SourcesPanelProps {
  sources: MessageSource[];
  /** Markdown of the answer, used to tell cited sources from consulted ones. */
  answer: string;
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
      {getSourceLabel(source.source)}
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
  </li>
);

const SourceList = ({ sources }: { sources: MessageSource[] }) => (
  <ul className={styles.sourcesList}>
    {sources.map((source) => (
      <SourceItem key={source.id || source.url} source={source} />
    ))}
  </ul>
);

/**
 * Right-hand overlay listing the documents behind an answer: the ones the
 * answer links to first, the other consulted documents in a collapsed block.
 */
export const SourcesPanel = ({ sources, answer, onClose }: SourcesPanelProps) => {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  const { cited, others } = useMemo(
    () => splitSourcesByCitation(sources, answer),
    [sources, answer]
  );

  // When no link could be matched (e.g. the answer cites without URLs), show
  // everything as one flat list rather than an empty "cited" section.
  const mainSources = cited.length > 0 ? cited : others;
  const otherSources = cited.length > 0 ? others : [];

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

      <SourceList sources={mainSources} />

      {otherSources.length > 0 && (
        <details className={styles.sourcesOthers}>
          <summary className={styles.sourcesOthersSummary}>
            Autres documents consultés ({otherSources.length})
          </summary>
          <SourceList sources={otherSources} />
        </details>
      )}
    </aside>
  );
};
