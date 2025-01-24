"use client";

import { useState, useEffect } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { Input } from "@codegouvfr/react-dsfr/Input";
import { fr } from "@codegouvfr/react-dsfr";
import { UserLLMMessage } from "@/types";

export const Chat = () => {
  const [messages, setMessages] = useState<UserLLMMessage[]>([
    { content: "Bonjour, comment puis-je vous aider ?", role: "assistant" },
    { content: "J'ai une question concernant mes démarches", role: "user" },
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

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div className={fr.cx("fr-card", "fr-my-3w")}>
        <div className={fr.cx("fr-card__body")}>
          <h1 className={fr.cx("fr-card__title")}>Assistant conversationnel</h1>
          <p className={fr.cx("fr-card__desc")}>
            Notre assistant conversationnel en droit du travail vous offre des
            réponses rapides, fiables et conformes à la législation en vigueur.
          </p>
        </div>
      </div>

      <div
        className={`${fr.cx("fr-p-3w")} chat-messages`}
        style={{
          display: "flex",
          flexDirection: "column",
          height: "calc(100vh - 250px)",
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
          <Input
            label="Votre message"
            nativeInputProps={{
              placeholder: "Saisissez votre message",
              value: newMessage,
              onChange: (e) => setNewMessage(e.target.value),
            }}
            hideLabel
          />
        </div>
        <div
          className={fr.cx("fr-col-1")}
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "flex-end",
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
