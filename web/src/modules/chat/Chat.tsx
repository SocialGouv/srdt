"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { AnalyzeResponse, UserLLMMessage } from "@/types";
import useApi from "@/hooks/use-api";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Feedback } from "@/modules/feedback/Feedback";
import { AutoresizeTextarea } from "@/components/AutoresizeTextarea";
import styles from "./Chat.module.css";
import { Agreement } from "../convention-collective/search";
import { AgreementSearchInput } from "../convention-collective/AgreementSearchInput";
import * as Sentry from "@sentry/nextjs";
import { push } from "@socialgouv/matomo-next";

interface ChatMessage extends UserLLMMessage {
  isError?: boolean;
  isLoading?: boolean;
  isStreaming?: boolean;
  isFollowup?: boolean;
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
  isAwaitingFollowup?: boolean;
  firstUserQuestion?: string;
  firstAssistantAnswer?: string;
  selectedModel?: string;
}

const STORAGE_KEY = "chat-conversations";
const CURRENT_CONVERSATION_KEY = "current-conversation-id";

const initialConversationText =
  "Bonjour, je suis un assistant juridique spécialisé en droit du travail. Comment puis-je vous aider ?";

// Custom markdown components to handle links properly
const markdownComponents = {
  a: ({ ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
};

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
  const { generateAnswerStream, generateFollowupAnswerStream, isLoading } =
    useApi();
  const chatMessagesRef = useRef<HTMLDivElement>(null);
  const streamingMessageRef = useRef<string>("");
  const [messagesLength, setMessagesLength] = useState(0);

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
          isAwaitingFollowup: false,
          selectedModel: undefined,
        };

        // Ensure backward compatibility by adding missing fields to loaded conversations
        const compatibleParsed = parsed.map(
          (conv: Partial<Conversation>) =>
            ({
              ...conv,
              isAwaitingFollowup: conv.isAwaitingFollowup ?? false,
              firstUserQuestion: conv.firstUserQuestion ?? undefined,
              firstAssistantAnswer: conv.firstAssistantAnswer ?? undefined,
              selectedModel: conv.selectedModel ?? undefined,
            } as Conversation)
        );

        setConversations([newConversation, ...compatibleParsed]);
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
      isAwaitingFollowup: false,
      selectedModel: undefined,
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
  const apiResult = currentConversation?.lastApiResult || null;
  const globalResponseTime = currentConversation?.lastResponseTime || 0;
  const apiError = currentConversation?.lastApiError;

  // Scroll within the chat messages container only
  useEffect(() => {
    // Only auto-scroll when a new message is added (array length changes),
    // not when existing message content is updated during streaming
    if (messages.length !== messagesLength) {
      setMessagesLength(messages.length);
      if (chatMessagesRef.current) {
        // Scroll to bottom of the chat messages container with smooth behavior
        chatMessagesRef.current.scrollTo({
          top: chatMessagesRef.current.scrollHeight,
          behavior: "smooth",
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

    const userMessage = {
      content: newMessage,
      role: "user" as const,
      isFollowup: currentConversation?.isAwaitingFollowup || false,
    };
    const currentMessages = [...messages, userMessage];

    // Check if this is a follow-up question
    const isFollowupQuestion =
      currentConversation?.isAwaitingFollowup &&
      currentConversation?.firstUserQuestion &&
      currentConversation?.firstAssistantAnswer;

    push([
      "trackEvent",
      "chat",
      isFollowupQuestion ? "send message followup" : "send message initial",
    ]);

    // Update conversation title if this is the first user message
    const shouldUpdateTitle =
      messages.length === 1 && messages[0].role === "assistant";
    const conversationUpdates: Partial<Conversation> = {
      messages: currentMessages,
      lastUserQuestion: newMessage,
    };

    if (shouldUpdateTitle) {
      conversationUpdates.title = generateConversationTitle(newMessage);
      // Store the first question for potential follow-up
      conversationUpdates.firstUserQuestion = newMessage;
    }

    // If this is a follow-up, clear the awaiting state
    if (isFollowupQuestion) {
      conversationUpdates.isAwaitingFollowup = false;
    }

    updateCurrentConversation(conversationUpdates);
    setNewMessage("");

    const loadingMessage = {
      content: "",
      role: "assistant" as const,
      isLoading: false,
      isStreaming: true,
      isFollowup: !!isFollowupQuestion,
    };

    updateCurrentConversation({
      messages: [...currentMessages, loadingMessage],
    });

    const startTime = performance.now();
    streamingMessageRef.current = "";

    if (isFollowupQuestion) {
      // Use follow-up streaming
      await generateFollowupAnswerStream(
        currentConversation.firstUserQuestion!,
        currentConversation.firstAssistantAnswer!,
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
                isFollowup: true,
              },
            ]),
          });
        },
        (result) => {
          // Handle completion for follow-up
          const endTime = performance.now();
          const responseTimeInSeconds = (endTime - startTime) / 1000;

          if (result.error || !result.success) {
            updateCurrentConversation({
              messages: currentMessages.concat([
                {
                  content: `Une erreur est survenue : ${result.error}`,
                  role: "assistant",
                  isError: true,
                  isFollowup: true,
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
                  isFollowup: true,
                },
              ]),
              lastApiResult: result.data,
              lastResponseTime: responseTimeInSeconds,
              lastApiError: undefined,
              hasFailed: false,
              isAwaitingFollowup: false, // Followup is complete, no more follow-ups
              firstAssistantAnswer:
                result.data?.generated?.text ?? streamingMessageRef.current,
              selectedModel: result.data?.modelName,
            });
          }
          setIsDisabled(true); // Disable after follow-up is complete (max 2 questions per conversation)
        },
        selectedAgreement?.id,
        selectedAgreement?.title,
        currentConversation.selectedModel
      );
    } else {
      // Use regular streaming for initial question
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
          // Handle completion for initial question
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
              isAwaitingFollowup: true, // Set flag to allow follow-up
              firstAssistantAnswer:
                result.data?.generated?.text ?? streamingMessageRef.current,
              selectedModel: result.data?.modelName,
            });
          }
          setIsDisabled(false); // Re-enable for potential follow-up
        },
        selectedAgreement?.id,
        selectedAgreement?.title
      );
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
      isAwaitingFollowup: false, // Ensure new conversations are not awaiting follow-up
      selectedModel: undefined,
    };

    setConversations((prev) => [newConversation, ...prev]);
    setCurrentConversationId(newId);
    setNewMessage("");
    setIsDisabled(false);
    setSelectedAgreement(undefined);
    streamingMessageRef.current = "";

    push(["trackEvent", "chat", "new conversation"]);
  };

  const handleConversationSelect = (conversationId: string) => {
    setCurrentConversationId(conversationId);
    setNewMessage("");
    // Don't disable if the conversation is awaiting a follow-up
    const selectedConversation = conversations.find(
      (c) => c.id === conversationId
    );
    setIsDisabled(!selectedConversation?.isAwaitingFollowup);
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

    // Check if this is the last assistant message and should show feedback
    const isLastAssistantMessage =
      message.role === "assistant" &&
      index === messages.length - 1 &&
      !message.isLoading &&
      !message.isStreaming &&
      !message.isError;

    // Always show feedback for the last assistant message
    // This naturally handles: show after first → hide when follow-up starts → show after follow-up
    const shouldShowFeedback = isLastAssistantMessage;

    return (
      <div key={index}>
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
              userQuestion={apiResult?.anonymized?.anonymized_question}
              llmResponse={apiResult?.generated.text}
              errorMessage={apiError}
              idcc={selectedAgreement?.id}
              answerType={apiResult?.answerType}
              isFollowupResponse={message.isFollowup}
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
                      Cliquez sur le bouton « Nouvelle conversation » pour en
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
                  onClick={() => {
                    handleConversationSelect(conversation.id);
                    push(["trackEvent", "history", "select conversation"]);
                  }}
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
        {/* Fixed header with buttons - always visible */}
        <div
          className={fr.cx("fr-mt-2w")}
          style={{
            display: "flex",
            gap: "1rem",
            alignItems: "center",
            flexShrink: 0,
            paddingBottom: "1rem",
            borderBottom: "1px solid var(--background-alt-blue-france)",
          }}
        >
          <Button
            onClick={() => {
              if (!showHistory) {
                push(["trackEvent", "history", "show history"]);
              }
              setShowHistory(!showHistory);
            }}
            iconId={"fr-icon-menu-fill"}
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

        {/* Scrollable messages area */}
        <div
          ref={chatMessagesRef}
          className={`chat-messages`}
          style={{
            display: "flex",
            flexDirection: "column",
            flex: 1,
            overflowY: "auto",
            gap: "1rem",
            marginBottom: "1rem",
            paddingTop: "1rem",
          }}
        >
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
                  ? // Check if we're actively generating (last message is loading/streaming) vs conversation is complete
                    messages.length > 0 &&
                    (messages[messages.length - 1].isLoading ||
                      messages[messages.length - 1].isStreaming)
                    ? "Génération de la réponse en cours...\nVous pourrez ensuite poser une question de suivi ou démarrer une nouvelle conversation."
                    : "Veuillez démarrer une nouvelle conversation pour poser une autre question.\nPour cela, remontez en haut de la page et cliquez sur le bouton « Nouvelle conversation »."
                  : currentConversation?.isAwaitingFollowup
                  ? "Posez une question de suivi ou démarrez une nouvelle conversation..."
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
                  ? // Check if we're actively generating (last message is loading/streaming) vs conversation is complete
                    messages.length > 0 &&
                    (messages[messages.length - 1].isLoading ||
                      messages[messages.length - 1].isStreaming)
                    ? "Génération en cours, patientez..."
                    : "Démarrez une nouvelle conversation pour poser une autre question"
                  : currentConversation?.isAwaitingFollowup
                  ? "Envoyer votre question de suivi"
                  : "Envoyer votre message"
              }
              type="submit"
              className={fr.cx("fr-cell--center")}
              disabled={isDisabled}
            />
          </div>
          {!isDisabled && !currentConversation?.firstUserQuestion && (
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
          {currentConversation?.isAwaitingFollowup && !isDisabled && (
            <div className={fr.cx("fr-col-12", "fr-mt-1w")}>
              <div
                style={{
                  fontSize: "0.875rem",
                  color: "var(--text-mention-grey)",
                  padding: "0.5rem",
                  backgroundColor: "var(--background-alt-grey)",
                  borderRadius: "4px",
                  borderLeft: "3px solid var(--border-action-high-blue-france)",
                }}
              >
                💡 Vous pouvez poser une question de suivi pour approfondir
                cette réponse, ou démarrer une nouvelle conversation.
              </div>
            </div>
          )}
        </form>
      </div>
    </div>
  );
};
