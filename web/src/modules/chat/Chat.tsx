"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { AnalyzeResponse, UserLLMMessage } from "@/types";
import useApi from "@/hooks/use-api";
import Markdown from "react-markdown";
import { Feedback } from "@/modules/feedback/Feedback";
import { AutoresizeTextarea } from "@/components/AutoresizeTextarea";
import styles from "./Chat.module.css";
import { Agreement } from "../convention-collective/search";
import { AgreementSearchInput } from "../convention-collective/AgreementSearchInput";
import * as Sentry from "@sentry/nextjs";

interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
  isStreaming?: boolean;
}

interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  lastApiResult?: AnalyzeResponse | null;
  lastResponseTime?: number;
  lastUserQuestion?: string;
  lastApiError?: string;
  hasFailed?: boolean;
}

const STORAGE_KEY = "chat-conversations";
const CURRENT_CONVERSATION_KEY = "current-conversation-id";

const initialConversationText =
  "Bonjour, je suis un assistant juridique spécialisé en droit du travail. Comment puis-je vous aider ?";

export const Chat = () => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] =
    useState<string>("");
  const [selectedAgreement, setSelectedAgreement] = useState<
    Agreement | undefined
  >(undefined);
  const [showHistory, setShowHistory] = useState(false);
  const [newMessage, setNewMessage] = useState("");
  const [isDisabled, setIsDisabled] = useState(false);
  const { generateAnswer, generateAnswerStream, isLoading } = useApi();
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const streamingMessageRef = useRef<string>("");
  const [messagesLength, setMessagesLength] = useState(0);

  // It was an option but it's not anymore since streaming works well
  const useStreaming = true;

  // Initialize conversations from localStorage and always start with new conversation
  useEffect(() => {
    const savedConversations = localStorage.getItem(STORAGE_KEY);

    if (savedConversations) {
      try {
        const parsed = JSON.parse(savedConversations).map(
          (conv: Omit<Conversation, "createdAt"> & { createdAt: string }) => ({
            ...conv,
            createdAt: new Date(conv.createdAt),
          })
        );

        // Create a new conversation and add it to the existing ones
        const newId = `conv_${Date.now()}`;
        const newConversation: Conversation = {
          id: newId,
          title: "Nouvelle conversation",
          messages: [
            {
              content: initialConversationText,
              role: "assistant",
            },
          ],
          createdAt: new Date(),
          hasFailed: false,
        };

        setConversations([newConversation, ...parsed]);
        setCurrentConversationId(newId);
      } catch (error) {
        Sentry.captureException(error, {
          tags: {
            component: "Chat",
            method: "loadConversations",
          },
          extra: {
            storageKey: STORAGE_KEY,
            errorStep: "parsing_saved_conversations",
          },
        });
        console.error("Error parsing saved conversations:", error);
        initializeDefaultConversation();
      }
    } else {
      initializeDefaultConversation();
    }
  }, []);

  // Save conversations to localStorage whenever they change, but exclude failed conversations
  useEffect(() => {
    if (conversations.length > 0) {
      // Filter out conversations that have failed responses (excluding the current one if it's being processed)
      const conversationsToSave = conversations.filter((conv) => {
        // Always keep the current conversation in memory for UI purposes
        if (conv.id === currentConversationId) {
          return true;
        }
        // Only save non-failed conversations to localStorage
        return !conv.hasFailed;
      });

      // Only save to localStorage if we have successful conversations or current conversation
      const storageConversations = conversationsToSave.filter(
        (conv) => conv.id !== currentConversationId || !conv.hasFailed
      );

      if (storageConversations.length > 0) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(storageConversations));
      }
    }
  }, [conversations, currentConversationId]);

  // Save current conversation ID to localStorage
  useEffect(() => {
    if (currentConversationId) {
      localStorage.setItem(CURRENT_CONVERSATION_KEY, currentConversationId);
    }
  }, [currentConversationId]);

  const initializeDefaultConversation = () => {
    const defaultConversation: Conversation = {
      id: "default",
      title: "Nouvelle conversation",
      messages: [{ content: initialConversationText, role: "assistant" }],
      createdAt: new Date(),
      hasFailed: false,
    };
    setConversations([defaultConversation]);
    setCurrentConversationId("default");
  };

  // Get current conversation
  const currentConversation = conversations.find(
    (c) => c.id === currentConversationId
  );
  const messages = useMemo(
    () => currentConversation?.messages || [],
    [currentConversation?.messages]
  );

  // Get conversation-specific state
  const userQuestion = currentConversation?.lastUserQuestion || "";
  const apiResult = currentConversation?.lastApiResult || null;
  const globalResponseTime = currentConversation?.lastResponseTime || 0;
  const apiError = currentConversation?.lastApiError;

  // Restored original scrolling behavior
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

  const updateCurrentConversation = (updates: Partial<Conversation>) => {
    setConversations((prev) =>
      prev.map((conv) =>
        conv.id === currentConversationId ? { ...conv, ...updates } : conv
      )
    );
  };

  const generateConversationTitle = (firstUserMessage: string): string => {
    // Take first 50 characters and add ellipsis if longer
    const title =
      firstUserMessage.length > 50
        ? firstUserMessage.substring(0, 50) + "..."
        : firstUserMessage;
    return title;
  };

  // Get conversations that have actual user messages (not just the welcome message) and haven't failed
  const conversationsWithMessages = conversations.filter(
    (conv) =>
      conv.messages.some((msg) => msg.role === "user") && !conv.hasFailed
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMessage.trim() || isDisabled) return;

    setIsDisabled(true);

    const userMessage = { content: newMessage, role: "user" as const };
    const currentMessages = [...messages, userMessage];

    // Update conversation title if this is the first user message
    const shouldUpdateTitle =
      messages.length === 1 && messages[0].role === "assistant";
    const conversationUpdates: Partial<Conversation> = {
      messages: currentMessages,
      lastUserQuestion: newMessage,
    };

    if (shouldUpdateTitle) {
      conversationUpdates.title = generateConversationTitle(newMessage);
    }

    updateCurrentConversation(conversationUpdates);
    setNewMessage("");

    const loadingMessage = {
      content: "",
      role: "assistant" as const,
      isLoading: !useStreaming,
      isStreaming: useStreaming,
    };

    updateCurrentConversation({
      messages: [...currentMessages, loadingMessage],
    });

    const startTime = performance.now();
    streamingMessageRef.current = "";

    if (useStreaming) {
      // Use streaming
      await generateAnswerStream(
        newMessage,
        (chunk: string) => {
          // Handle each streaming chunk
          streamingMessageRef.current += chunk;
          updateCurrentConversation({
            messages: currentMessages.concat([
              {
                content: streamingMessageRef.current,
                role: "assistant",
                isStreaming: true,
              },
            ]),
          });
        },
        (result) => {
          // Handle completion
          const endTime = performance.now();
          const responseTimeInSeconds = (endTime - startTime) / 1000;

          if (result.error || !result.success) {
            updateCurrentConversation({
              messages: currentMessages.concat([
                {
                  content: `Une erreur est survenue : ${result.error}`,
                  role: "assistant",
                  isError: true,
                },
              ]),
              lastApiError: result.error?.toString(),
              lastResponseTime: responseTimeInSeconds,
              hasFailed: true,
            });
          } else {
            updateCurrentConversation({
              messages: currentMessages.concat([
                {
                  content:
                    result.data?.generated?.text ?? streamingMessageRef.current,
                  role: "assistant",
                },
              ]),
              lastApiResult: result.data,
              lastResponseTime: responseTimeInSeconds,
              lastApiError: undefined,
              hasFailed: false,
            });
          }
        },
        selectedAgreement?.id,
        selectedAgreement?.title
      );
    } else {
      // Use traditional non-streaming approach
      const result = await generateAnswer(
        newMessage,
        selectedAgreement?.id,
        selectedAgreement?.title
      );
      const endTime = performance.now();
      const responseTimeInSeconds = (endTime - startTime) / 1000;

      if (result.error || !result.success) {
        updateCurrentConversation({
          messages: currentMessages.concat([
            {
              content: `Une erreur est survenue : ${result.error}`,
              role: "assistant",
              isError: true,
            },
          ]),
          lastApiError: result.error?.toString(),
          lastResponseTime: responseTimeInSeconds,
          hasFailed: true,
        });
      } else {
        updateCurrentConversation({
          messages: currentMessages.concat([
            {
              content:
                result.data?.generated?.text ??
                "Désolé, je n'ai pas pu générer de réponse.",
              role: "assistant",
            },
          ]),
          lastApiResult: result.data,
          lastResponseTime: responseTimeInSeconds,
          lastApiError: undefined,
          hasFailed: false,
        });
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleNewConversation = () => {
    const newId = `conv_${Date.now()}`;
    const newConversation: Conversation = {
      id: newId,
      title: "Nouvelle conversation",
      messages: [{ content: initialConversationText, role: "assistant" }],
      createdAt: new Date(),
      hasFailed: false,
    };

    setConversations((prev) => [newConversation, ...prev]);
    setCurrentConversationId(newId);
    setNewMessage("");
    setIsDisabled(false);
    setSelectedAgreement(undefined);
    streamingMessageRef.current = "";
  };

  const handleConversationSelect = (conversationId: string) => {
    setCurrentConversationId(conversationId);
    setNewMessage("");
    setIsDisabled(true);
    streamingMessageRef.current = "";
  };

  const handleDeleteConversation = (
    conversationId: string,
    e: React.MouseEvent
  ) => {
    e.stopPropagation();

    if (conversations.length === 1) {
      // If it's the last conversation, reset it instead of deleting
      handleNewConversation();
      return;
    }

    const filteredConversations = conversations.filter(
      (c) => c.id !== conversationId
    );
    setConversations(filteredConversations);

    // If we deleted the current conversation, switch to the first available one
    if (conversationId === currentConversationId) {
      setCurrentConversationId(filteredConversations[0].id);
    }
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
              idcc={selectedAgreement?.id}
            />
          </div>
        )}
      </div>
    );
  };

  const renderConversationHistory = () => {
    return (
      <div
        style={{
          width: showHistory ? "300px" : "0px",
          transition: "width 0.3s ease",
          overflow: "hidden",
          borderRight: showHistory
            ? "1px solid var(--background-alt-blue-france)"
            : "none",
          backgroundColor: "var(--background-alt-grey)",
          marginRight: "1rem",
        }}
      >
        {showHistory && (
          <div style={{ padding: "1rem", width: "300px" }}>
            <div
              className={fr.cx("fr-mb-2w")}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <h3 className={fr.cx("fr-h6", "fr-m-0")}>Historique</h3>
              <Button
                iconId="fr-icon-close-line"
                priority="tertiary no outline"
                size="small"
                title="Fermer l'historique"
                onClick={() => setShowHistory(false)}
              />
            </div>

            <div style={{ maxHeight: "calc(80vh - 200px)", overflowY: "auto" }}>
              {conversationsWithMessages.length === 0 && (
                <div className={fr.cx("fr-mt-4v", "fr-px-1v")}>
                  <p className={fr.cx("fr-text--sm")}>
                    Vous n&apos;avez pas encore de conversations enregistrées.
                  </p>
                  <p className={fr.cx("fr-text--sm")}>
                    <i>
                      Cliquez sur le bouton « Nouvelle conversation » pour en
                      créer une.
                    </i>
                  </p>
                </div>
              )}
              {conversationsWithMessages.map((conversation) => (
                <div
                  key={conversation.id}
                  className={fr.cx("fr-mb-1v")}
                  style={{
                    padding: "0.75rem",
                    borderRadius: "4px",
                    cursor: "pointer",
                    backgroundColor:
                      conversation.id === currentConversationId
                        ? "var(--background-action-low-blue-france)"
                        : "transparent",
                    border:
                      conversation.id === currentConversationId
                        ? "1px solid var(--border-action-high-blue-france)"
                        : "1px solid transparent",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                  }}
                  onClick={() => handleConversationSelect(conversation.id)}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: "0.875rem",
                        fontWeight:
                          conversation.id === currentConversationId
                            ? "600"
                            : "400",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        marginBottom: "0.25rem",
                      }}
                    >
                      {conversation.title}
                    </div>
                    <div
                      style={{
                        fontSize: "0.75rem",
                        color: "var(--text-mention-grey)",
                      }}
                    >
                      {conversation.createdAt.toLocaleDateString("fr-FR")} à{" "}
                      {conversation.createdAt.toLocaleTimeString("fr-FR", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </div>
                  </div>
                  <Button
                    iconId="fr-icon-delete-line"
                    priority="tertiary no outline"
                    size="small"
                    title="Supprimer cette conversation"
                    onClick={(e) =>
                      handleDeleteConversation(conversation.id, e)
                    }
                    style={{ marginLeft: "0.5rem", flexShrink: 0 }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: "flex", height: "80vh" }}>
      {renderConversationHistory()}

      <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
        <div
          className={`chat-messages`}
          style={{
            display: "flex",
            flexDirection: "column",
            height: "calc(80vh - 20px)",
            overflowY: "auto",
            gap: "1rem",
            marginBottom: "1rem",
          }}
        >
          <div
            className={fr.cx("fr-my-2w")}
            style={{ display: "flex", gap: "1rem", alignItems: "center" }}
          >
            <Button
              onClick={() => setShowHistory(!showHistory)}
              iconId={
                // showHistory ? "fr-icon-close-line" : "fr-icon-menu-fill"
                "fr-icon-menu-fill"
              }
              priority="tertiary no outline"
              title={
                showHistory ? "Masquer l'historique" : "Afficher l'historique"
              }
            />

            <Button
              onClick={handleNewConversation}
              iconId="fr-icon-add-line"
              priority="secondary"
            >
              Nouvelle conversation
            </Button>
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
          {!isDisabled && (
            <div className={fr.cx("fr-col-11")}>
              <AgreementSearchInput
                onAgreementSelect={(agreement) => {
                  console.log("agreement", agreement);
                  setSelectedAgreement(agreement);
                }}
                defaultAgreement={undefined}
                trackingActionName="chat"
              />
            </div>
          )}
        </form>
      </div>
    </div>
  );
};
