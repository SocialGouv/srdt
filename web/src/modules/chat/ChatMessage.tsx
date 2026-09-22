import { fr } from "@codegouvfr/react-dsfr";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FeedbackSelector } from "@/modules/feedback/FeedbackSelector";
import styles from "./Chat.module.css";
import { ChatMessage as ChatMessageType } from "./types";
import { Agreement } from "../convention-collective/search";
import { AnswerResponse } from "@/types";
import React, { useRef } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import Image from "next/image";
import { SOURCES_PANEL_ID } from "./SourcesPanel";
import marianne from "./marianne.png";
import addCc from "./add-cc.svg";
import { agreementModalButtonProps } from "../convention-collective/AgreementModal";
import { CopyAnswerMenu } from "./CopyAnswerMenu";

// Custom markdown components to handle links properly
const markdownComponents = {
  a: ({ ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
};

const LINK_PLACEHOLDER_TEXT = "Génération du lien en cours\u2026";

/**
 * During streaming, replaces complete and partial markdown links with a
 * styled placeholder. This prevents showing incorrect/shifting links while
 * the backend hasn't yet post-corrected them.
 */
function processStreamingLinks(content: string): string {
  // 1. Replace complete markdown links [text](url)
  let processed = content.replace(
    /\[[^\]]*\]\([^)]*\)/g,
    `*${LINK_PLACEHOLDER_TEXT}*`
  );

  // 2. Replace partial markdown link at end of streaming content
  //    Matches: [text](partial…  |  [text](  |  [text]  |  [partial_text
  processed = processed.replace(
    /\[[^\]]*(?:\](?:\([^)]*)?)?$/,
    `*${LINK_PLACEHOLDER_TEXT}*`
  );

  return processed;
}

// Markdown components used during streaming: adds special rendering for link placeholders
const streamingMarkdownComponents = {
  a: ({ ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
  em: ({
    children,
    ...props
  }: React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }) => {
    const childArray = React.Children.toArray(children);
    const isPlaceholder =
      childArray.length === 1 &&
      typeof childArray[0] === "string" &&
      childArray[0] === LINK_PLACEHOLDER_TEXT;

    if (isPlaceholder) {
      return <span className={styles.linkPlaceholder}>{children}</span>;
    }
    return <em {...props}>{children}</em>;
  },
};

interface ChatMessageProps {
  message: ChatMessageType;
  index: number;
  isLastMessage: boolean;
  isLoading: boolean;
  apiResult: AnswerResponse | null;
  globalResponseTime: number;
  apiError?: string;
  /** Collective agreement the conversation was started with, if any */
  agreement?: Agreement;
  /** Database conversation ID for saving feedback */
  dbConversationId?: string;
  /** Opens (or closes) the sources side panel for this message. */
  onShowSources?: () => void;
  /** Whether the sources panel currently shows this message's sources. */
  isSourcesOpen?: boolean;
}

export const ChatMessage = ({
  message,
  index,
  isLastMessage,
  isLoading,
  apiResult,
  globalResponseTime,
  apiError,
  agreement,
  dbConversationId,
  onShowSources,
  isSourcesOpen = false,
}: ChatMessageProps) => {
  const contentRef = useRef<HTMLDivElement>(null);

  const bubbleClasses = [
    styles.messageBubble,
    message.role === "user"
      ? styles.messageBubbleUser
      : styles.messageBubbleAssistant,
    message.isError ? styles.messageBubbleError : "",
  ]
    .filter(Boolean)
    .join(" ");

  // Check if this is the last assistant message and should show feedback
  const isLastAssistantMessage =
    message.role === "assistant" &&
    isLastMessage &&
    !message.isLoading &&
    !message.isStreaming &&
    !message.isError;

  const hasSources = (message.sources?.length ?? 0) > 0;

  // Always show feedback for the last assistant message
  // This naturally handles: show after first → hide when follow-up starts → show after follow-up
  const shouldShowFeedback = isLastAssistantMessage;

  return (
    <div key={index}>
      <div
        className={`${fr.cx(
          "fr-my-1w",
          message.role === "user" ? "fr-ml-auto" : "fr-mr-auto"
        )} ${styles.messageWrapper} ${
          message.role === "user"
            ? styles.messageWrapperUser
            : styles.messageWrapperAssistant
        }`}
      >
        <div className={bubbleClasses}>
          {message.role === "assistant" && index !== 0 && (
            <div className={styles.conventionBadgeContainer}>
              <Badge
                as="span"
                noIcon
                severity="info"
                className={styles.conventionBadge}
              >
                {agreement ? (
                  <>
                    <span
                      className={styles.conventionBadgeTitle}
                      title={`${agreement.shortTitle} (IDCC ${agreement.num})`}
                    >
                      Convention collective&nbsp;: {agreement.shortTitle}
                    </span>
                    <span className={styles.conventionBadgeIdcc}>
                      &nbsp;(IDCC {agreement.num})
                    </span>
                  </>
                ) : (
                  <span className={styles.conventionBadgeTitle}>
                    Convention collective&nbsp;: non renseignée
                  </span>
                )}
              </Badge>
              {/* Restarts with the first question only, so not on follow-ups */}
              {!agreement && !message.isFollowup && (
                <Button
                  priority="secondary"
                  nativeButtonProps={agreementModalButtonProps}
                  disabled={isLoading}
                  className={styles.addAgreementButton}
                >
                  <Image
                    src={addCc}
                    alt=""
                    width={23}
                    height={27}
                    aria-hidden="true"
                    className={styles.addAgreementIcon}
                  />
                  Préciser la convention collective
                </Button>
              )}
            </div>
          )}
          <div
            ref={contentRef}
            className={
              !message.isLoading && !message.isStreaming
                ? styles.messageContent
                : ""
            }
          >
            <Markdown
              remarkPlugins={[remarkGfm]}
              components={
                message.isStreaming
                  ? streamingMarkdownComponents
                  : markdownComponents
              }
            >
              {message.isStreaming
                ? processStreamingLinks(message.content)
                : message.content}
            </Markdown>
            {(message.isLoading || message.isStreaming) && (
              <div className={fr.cx("fr-mt-1w")}>
                {isLoading && (
                  <div>
                    {message.isStreaming
                      ? "Génération en cours..."
                      : "Génération de la réponse..."}
                    {message.isStreaming && (
                      <span className={styles.streamingCursor}>▋</span>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
          {message.role === "assistant" &&
            !message.isLoading &&
            !message.isStreaming &&
            index !== 0 && (
              <div className={styles.messageActions}>
                {hasSources && onShowSources && (
                  <Button
                    onClick={onShowSources}
                    priority="tertiary no outline"
                    size="small"
                    title="Afficher les sources de la réponse"
                    className={styles.copyButton}
                    nativeButtonProps={{
                      "aria-expanded": isSourcesOpen,
                      "aria-controls": SOURCES_PANEL_ID,
                    }}
                  >
                    <Image
                      src={marianne}
                      alt=""
                      unoptimized
                      width={20}
                      height={20}
                      aria-hidden="true"
                      className={`${styles.marianneIcon} ${styles.sourcesButtonIcon}`}
                    />
                    Sources
                  </Button>
                )}
                <CopyAnswerMenu
                  contentRef={contentRef}
                  fallbackText={message.content}
                />
              </div>
            )}
        </div>
      </div>

      {apiResult && shouldShowFeedback && (
        <div
          className={`${styles.messageBubble} ${styles.messageBubbleAssistant}`}
        >
          <p className={fr.cx("fr-m-0", "fr-h3")}>
            Donnez votre avis sur cette réponse
          </p>
          <FeedbackSelector
            modelName={apiResult?.modelName}
            familyModel={apiResult?.modelFamily}
            scenarioVersion={apiResult?.config}
            inputNbTokens={apiResult?.anonymized?.nb_token_input}
            outputNbTokens={apiResult?.generated.nb_token_output}
            globalResponseTime={globalResponseTime}
            userQuestion={apiResult?.anonymized?.anonymized_question}
            llmResponse={apiResult?.generated.text}
            errorMessage={apiError}
            idcc={agreement?.id}
            isFollowupResponse={message.isFollowup}
            dbConversationId={dbConversationId}
          />
        </div>
      )}
    </div>
  );
};
