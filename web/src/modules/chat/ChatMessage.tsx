import { fr } from "@codegouvfr/react-dsfr";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FeedbackSelector } from "@/modules/feedback/FeedbackSelector";
import styles from "./Chat.module.css";
import { ChatMessage as ChatMessageType } from "./types";
import { Agreement } from "../convention-collective/search";
import { AnswerResponse } from "@/types";
import React, { useState, useRef } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";

// Custom markdown components to handle links properly
const markdownComponents = {
  a: ({ ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
};

interface ChatMessageProps {
  message: ChatMessageType;
  index: number;
  isLastMessage: boolean;
  isLoading: boolean;
  apiResult: AnswerResponse | null;
  globalResponseTime: number;
  apiError?: string;
  selectedAgreement?: Agreement;
  /** Database conversation ID for saving feedback */
  dbConversationId?: string;
}

export const ChatMessage = ({
  message,
  index,
  isLastMessage,
  isLoading,
  apiResult,
  globalResponseTime,
  apiError,
  selectedAgreement,
  dbConversationId,
}: ChatMessageProps) => {
  const [copySuccess, setCopySuccess] = useState(false);
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

  // Always show feedback for the last assistant message
  // This naturally handles: show after first → hide when follow-up starts → show after follow-up
  const shouldShowFeedback = isLastAssistantMessage;

  // Handle copy to clipboard with formatted HTML
  const handleCopyToClipboard = async () => {
    try {
      if (!contentRef.current) return;

      // Get the HTML content from the rendered markdown
      const htmlContent = contentRef.current.innerHTML;
      const plainText = contentRef.current.innerText;

      // Check if ClipboardItem is supported (not in Firefox)
      if (typeof ClipboardItem !== "undefined") {
        const clipboardItem = new ClipboardItem({
          "text/html": new Blob([htmlContent], { type: "text/html" }),
          "text/plain": new Blob([plainText], { type: "text/plain" }),
        });
        await navigator.clipboard.write([clipboardItem]);
      } else {
        // Fallback for Firefox: use plain text
        await navigator.clipboard.writeText(plainText);
      }

      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (err) {
      console.error("Failed to copy text:", err);
      // Final fallback to plain text
      try {
        await navigator.clipboard.writeText(message.content);
        setCopySuccess(true);
        setTimeout(() => setCopySuccess(false), 2000);
      } catch (fallbackErr) {
        console.error("Fallback copy also failed:", fallbackErr);
      }
    }
  };

  return (
    <div key={index}>
      <div
        className={`${fr.cx(
          "fr-my-1w",
          message.role === "user" ? "fr-ml-auto" : "fr-mr-auto"
        )} ${styles.messageWrapper}`}
      >
        <div className={bubbleClasses}>
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
              components={markdownComponents}
            >
              {message.content}
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
              <div className={styles.copyButtonContainer}>
                <Button
                  onClick={handleCopyToClipboard}
                  iconId={
                    copySuccess
                      ? "fr-icon-check-line"
                      : "fr-icon-file-text-line"
                  }
                  priority="tertiary no outline"
                  size="small"
                  title="Copier la réponse"
                  className={styles.copyButton}
                >
                  {copySuccess ? "Copié !" : "Copier la réponse"}
                </Button>
              </div>
            )}
        </div>
      </div>

      {apiResult && shouldShowFeedback && (
        <div
          className={`${styles.messageBubble} ${styles.messageBubbleAssistant}`}
        >
          <p className={fr.cx("fr-m-0", "fr-h1")}>
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
            idcc={selectedAgreement?.id}
            isFollowupResponse={message.isFollowup}
            dbConversationId={dbConversationId}
          />
        </div>
      )}
    </div>
  );
};
