import { fr } from "@codegouvfr/react-dsfr";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Feedback } from "@/modules/feedback/Feedback";
import styles from "./Chat.module.css";
import { ChatMessage as ChatMessageType } from "./types";
import { Agreement } from "../convention-collective/search";
import { AnswerResponse } from "@/types";
import React from "react";

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
}: ChatMessageProps) => {
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
        </div>
      </div>

      {apiResult && shouldShowFeedback && (
        <div
          className={`${styles.messageBubble} ${styles.messageBubbleAssistant}`}
        >
          <p className={fr.cx("fr-m-0", "fr-h1")}>
            Donnez votre avis sur cette réponse
          </p>
          <Feedback
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
          />
        </div>
      )}
    </div>
  );
};
