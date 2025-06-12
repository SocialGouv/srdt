"use client";

import { useState, useEffect, useRef } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { AnalyzeResponse, UserLLMMessage } from "@/types";
import useApi from "@/hooks/use-api";
import Markdown from "react-markdown";
import { Feedback } from "@/modules/feedback/Feedback";
import { AutoresizeTextarea } from "@/components/AutoresizeTextarea";
import styles from "./Chat.module.css";

interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
  isStreaming?: boolean;
}

export const Chat = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { content: "Bonjour, comment puis-je vous aider ?", role: "assistant" },
  ]);
  const [userQuestion, setUserQuestion] = useState<string>("");
  const [newMessage, setNewMessage] = useState("");
  const [isDisabled, setIsDisabled] = useState(false);
  const { generateAnswer, generateAnswerStream, isLoading } = useApi();
  const [apiResult, setApiResult] = useState<AnalyzeResponse | null>(null);
  const [globalResponseTime, setGlobalResponseTime] = useState<number>(0);
  const [apiError, setApiError] = useState<string | undefined>(undefined);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const streamingMessageRef = useRef<string>("");
  const [messagesLength, setMessagesLength] = useState(messages.length);

  // It was an option but it's not anymore since streaming works well
  const useStreaming = true;

  useEffect(() => {
    // Only auto-scroll when a new message is added (array length changes),
    // not when existing message content is updated during streaming
    if (messages.length !== messagesLength) {
      setMessagesLength(messages.length);
      if (lastMessageRef.current) {
        lastMessageRef.current.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    }
  }, [messages, messagesLength]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMessage.trim() || isDisabled) return;

    setIsDisabled(true);
    setUserQuestion(newMessage);

    const userMessage = { content: newMessage, role: "user" as const };
    setMessages((prev) => [...prev, userMessage]);
    setNewMessage("");

    const loadingMessage = {
      content: "",
      role: "assistant" as const,
      isLoading: !useStreaming,
      isStreaming: useStreaming,
    };
    setMessages((prev) => [...prev, loadingMessage]);

    const startTime = performance.now();
    streamingMessageRef.current = "";

    if (useStreaming) {
      // Use streaming
      await generateAnswerStream(
        newMessage,
        (chunk: string) => {
          // Handle each streaming chunk
          streamingMessageRef.current += chunk;
          setMessages((prev) => {
            const newMessages = [...prev];
            const lastMessage = newMessages[newMessages.length - 1];
            if (lastMessage && lastMessage.isStreaming) {
              lastMessage.content = streamingMessageRef.current;
            }
            return newMessages;
          });
        },
        (result) => {
          // Handle completion
          const endTime = performance.now();
          const responseTimeInSeconds = (endTime - startTime) / 1000;

          setGlobalResponseTime(responseTimeInSeconds);
          setApiResult(result.data);

          setMessages((prev) => {
            const newMessages = prev.filter(
              (msg) => !msg.isLoading && !msg.isStreaming
            );

            if (result.error || !result.success) {
              setApiError(result.error?.toString());
              return [
                ...newMessages,
                {
                  content: `Une erreur est survenue : ${result.error}`,
                  role: "assistant",
                  isError: true,
                },
              ];
            }

            return [
              ...newMessages,
              {
                content:
                  result.data?.generated?.text ?? streamingMessageRef.current,
                role: "assistant",
              },
            ];
          });
        }
      );
    } else {
      // Use traditional non-streaming approach
      const result = await generateAnswer(newMessage);
      const endTime = performance.now();
      const responseTimeInSeconds = (endTime - startTime) / 1000;

      setGlobalResponseTime(responseTimeInSeconds);
      setApiResult(result.data);
      setMessages((prev) => prev.filter((msg) => !msg.isLoading));

      if (result.error || !result.success) {
        setApiError(result.error?.toString());
        setMessages((prev) => [
          ...prev,
          {
            content: `Une erreur est survenue : ${result.error}`,
            role: "assistant",
            isError: true,
          },
        ]);
        return;
      }

      setMessages((prev) => [
        ...prev,
        {
          content:
            result.data?.generated?.text ??
            "Désolé, je n'ai pas pu générer de réponse.",
          role: "assistant",
        },
      ]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleReset = () => {
    setMessages([
      { content: "Bonjour, comment puis-je vous aider ?", role: "assistant" },
    ]);
    setNewMessage("");
    setUserQuestion("");
    setIsDisabled(false);
    setApiResult(null);
    setGlobalResponseTime(0);
    setApiError(undefined);
    streamingMessageRef.current = "";
  };

  const renderMessage = (message: ChatMessage, index: number) => {
    const backgroundColor =
      message.role === "user"
        ? "var(--text-action-high-blue-france)"
        : "var(--background-default-grey-hover)";

    const textColor = message.isError
      ? "var(--text-default-error)"
      : message.role === "user"
      ? "white"
      : "inherit";

    const bubbleMessageStyle = {
      backgroundColor,
      color: textColor,
      borderRadius: "8px",
      padding: "1rem",
    };

    const isLastAssistantMessage =
      message.role === "assistant" &&
      index === messages.length - 1 &&
      !message.isLoading &&
      !message.isStreaming &&
      !message.isError;

    const isLastMessage = index === messages.length - 1;

    return (
      <div
        key={index}
        ref={isLastMessage && messages.length > 1 ? lastMessageRef : null}
      >
        <div
          className={fr.cx(
            "fr-my-1w",
            message.role === "user" ? "fr-ml-auto" : "fr-mr-auto"
          )}
          style={{ maxWidth: "70%", minWidth: "200px" }}
        >
          <div style={bubbleMessageStyle}>
            <div
              style={
                !message.isLoading && !message.isStreaming
                  ? { marginBottom: "-1.5rem" }
                  : {}
              }
            >
              <Markdown>{message.content}</Markdown>
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

        {apiResult && isLastAssistantMessage && (
          <div style={bubbleMessageStyle}>
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
              userQuestion={userQuestion}
              llmResponse={apiResult?.generated.text}
              errorMessage={apiError}
            />
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "80vh" }}>
      <div
        className={`chat-messages`}
        style={{
          display: "flex",
          flexDirection: "column",
          height: "calc(80vh - 20px)", // Ajusté la hauteur car on n'a plus d'éléments au-dessus
          overflowY: "auto",
          gap: "1rem",
          marginBottom: "1rem",
        }}
      >
        <div
          className={fr.cx("fr-mt-2w")}
          style={{ display: "flex", gap: "1rem", alignItems: "center" }}
        >
          <Button
            onClick={handleReset}
            iconId="fr-icon-refresh-line"
            priority="secondary"
          >
            Nouvelle conversation
          </Button>
        </div>
        <div className={fr.cx("fr-card", "fr-mt-2w")}>
          <div className={fr.cx("fr-card__body")}>
            <h1 className={fr.cx("fr-card__title")}>
              Assistant conversationnel
            </h1>
            <p className={fr.cx("fr-card__desc")}>
              Je suis un assistant juridique spécialisé en droit du travail. Mon
              rôle est de proposer une réponse à la question que vous me posez
              ci-dessous. Je m&apos;appuie principalement sur des sites publics
              (service-public, code du travail numérique, travail-emploi, ...)
              pour générer ma réponse, et je détaille à chaque fois les sources
              que j&apos;utilise. Cependant, je suis encore en formation et mes
              réponses ne sont pas parfaites. Aussi et pendant cette phase
              d&apos;expérimentation, je vous demande de prendre le temps de
              noter ma réponse via le formulaire qui se déroule sous ma réponse.
              Cela sera précieux pour m&apos;améliorer !
            </p>
          </div>
        </div>
        {messages.map((message, index) => renderMessage(message, index))}
      </div>

      <form
        onSubmit={handleSubmit}
        className={fr.cx("fr-grid-row", "fr-grid-row--gutters")}
        style={{
          backgroundColor: "var(--background-default-grey)",
          borderTop: "1px solid var(--background-alt-blue-france)",
        }}
      >
        <div className={fr.cx("fr-col-11")}>
          <AutoresizeTextarea
            value={newMessage}
            onChange={setNewMessage}
            onKeyDown={handleKeyDown}
            placeholder={
              isDisabled
                ? "Veuillez démarrer une nouvelle conversation pour poser une autre question.\nPour cela, remontez en haut de la page et cliquez sur le bouton « Nouvelle conversation »."
                : "Saisissez votre message"
            }
            disabled={isDisabled}
            maxLines={10}
          />
        </div>
        <div
          className={fr.cx("fr-col-1")}
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "flex-start",
          }}
        >
          <Button
            iconId="fr-icon-send-plane-fill"
            title={
              isDisabled
                ? "Démarrez une nouvelle conversation pour poser une autre question"
                : "Envoyer votre message"
            }
            type="submit"
            className={fr.cx("fr-cell--center")}
            disabled={isDisabled}
          />
        </div>
      </form>
    </div>
  );
};
