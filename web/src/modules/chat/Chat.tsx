"use client";

import { useState, useEffect } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { UserLLMMessage } from "@/types";
import useApi from "@/hooks/use-api";
import Markdown from "react-markdown";

interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
}

export const Chat = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { content: "Bonjour, comment puis-je vous aider ?", role: "assistant" },
  ]);
  const [newMessage, setNewMessage] = useState("");
  const [isDisabled, setIsDisabled] = useState(false);
  const { generateAnswer, isLoading } = useApi();

  useEffect(() => {
    const chatContainer = document.querySelector(".chat-messages");
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMessage.trim() || isDisabled) return;

    setIsDisabled(true);

    const userMessage = { content: newMessage, role: "user" as const };
    setMessages((prev) => [...prev, userMessage]);
    setNewMessage("");

    const loadingMessage = {
      content: "",
      role: "assistant" as const,
      isLoading: true,
    };
    setMessages((prev) => [...prev, loadingMessage]);

    const result = await generateAnswer(newMessage);

    setMessages((prev) => prev.filter((msg) => !msg.isLoading));

    if (result.error || !result.success) {
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
    const localSources =
      result.data?.localSearchChunks.map((v) => v.metadata.url) ?? [];
    const internetSources =
      result.data?.internetSearchChunks.map((v) => v.metadata.url) ?? [];
    const sourceList = [...localSources, ...internetSources];

    setMessages((prev) => [
      ...prev,
      {
        content:
          (result.data?.generated?.text ??
            "Désolé, je n'ai pas pu générer de réponse.") +
          (sourceList.length > 0
            ? "\n\n*Sources utilisées pour générer cette réponse :*\n" +
              sourceList.map((source) => `- [${source}](${source})`).join("\n")
            : ""),
        role: "assistant",
      },
    ]);
    setIsDisabled(false);
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
    setIsDisabled(false);
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

    return (
      <div
        key={index}
        className={fr.cx(
          "fr-my-1w",
          message.role === "user" ? "fr-ml-auto" : "fr-mr-auto"
        )}
        style={{ maxWidth: "70%", minWidth: "200px" }}
      >
        <div
          style={{
            backgroundColor,
            color: textColor,
            borderRadius: "8px",
            padding: "1rem",
            whiteSpace: "pre-wrap",
          }}
        >
          <div>
            <Markdown>{message.content}</Markdown>
            {message.isLoading && (
              <div className={fr.cx("fr-mt-1w")}>
                {isLoading && <div>Génération de la réponse...</div>}
              </div>
            )}
          </div>
        </div>
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
        }}
      >
        <Button
          onClick={handleReset}
          iconId="fr-icon-refresh-line"
          priority="secondary"
          className={fr.cx("fr-mt-2w")}
        >
          Nouvelle conversation
        </Button>
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
          <textarea
            className={fr.cx("fr-input")}
            placeholder={
              isDisabled
                ? "Veuillez démarrer une nouvelle conversation pour poser une autre question"
                : "Saisissez votre message"
            }
            value={newMessage}
            onChange={(e) => setNewMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isDisabled}
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
