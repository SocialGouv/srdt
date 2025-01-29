"use client";

import { useState, useEffect } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { UserLLMMessage } from "@/types";

export const Chat = () => {
  const [messages, setMessages] = useState<UserLLMMessage[]>([
    { content: "Bonjour, comment puis-je vous aider ?", role: "assistant" },
  ]);

  const [newMessage, setNewMessage] = useState("");

  useEffect(() => {
    const chatContainer = document.querySelector(".chat-messages");
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newMessage.trim()) {
      setMessages([...messages, { content: newMessage, role: "user" }]);
      setNewMessage("");
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
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "70vh" }}>
      <Button
        onClick={handleReset}
        iconId="fr-icon-refresh-fill"
        priority="secondary"
        className={fr.cx("fr-mt-2w")}
      >
        Nouvelle conversation
      </Button>
      <div className={fr.cx("fr-card", "fr-mt-2w")}>
        <div className={fr.cx("fr-card__body")}>
          <h1 className={fr.cx("fr-card__title")}>Assistant conversationnel</h1>
          <p className={fr.cx("fr-card__desc")}>
            Je suis un assistant juridique spécialisé en droit du travail. Mon
            rôle est de proposer une réponse à la question que vous me posez
            ci-dessous. Je m&apos;appuie principalement sur des sites publics
            (service-public, code du travail numérique, travail-emploi, ...)
            pour générer ma réponse, et je détaille à chaque fois les sources
            que j&apos;utilise. Cependant, je suis encore en formation et mes
            réponses ne sont pas parfaites. Aussi et pendant cette phase
            d&apos;expérimentation, je vous demande de prendre le temps de noter
            ma réponse via le formulaire qui se déroule sous ma réponse. Cela
            sera précieux pour m&apos;améliorer !
          </p>
        </div>
      </div>

      <div
        className={`chat-messages`}
        style={{
          display: "flex",
          flexDirection: "column",
          height: "calc(70vh - 250px)",
          overflowY: "auto",
          gap: "1rem",
        }}
      >
        {messages.map((message, index) => (
          <div
            key={index}
            className={fr.cx(
              "fr-my-1w",
              message.role === "user" ? "fr-ml-auto" : "fr-mr-auto"
            )}
            style={{
              maxWidth: "70%",
              minWidth: "200px",
            }}
          >
            <div
              style={{
                backgroundColor:
                  message.role === "user"
                    ? "var(--text-action-high-blue-france)"
                    : "var(--background-default-grey-hover)",
                color: message.role === "user" ? "white" : "inherit",
                borderRadius: "8px",
                padding: "1rem",
                whiteSpace: "pre-wrap",
              }}
            >
              {message.content}
            </div>
          </div>
        ))}
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
            placeholder="Saisissez votre message"
            value={newMessage}
            onChange={(e) => setNewMessage(e.target.value)}
            onKeyDown={handleKeyDown}
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
            title="Envoyer votre message"
            type="submit"
            className={fr.cx("fr-cell--center")}
          />
        </div>
      </form>
    </div>
  );
};
