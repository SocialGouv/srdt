"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { ChatMessage, Conversation } from "./types";
import useApi from "@/hooks/use-api";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Feedback } from "@/modules/feedback/Feedback";
import { AutoresizeTextarea } from "@/components/AutoresizeTextarea";
import styles from "./Chat.module.css";
import { Agreement } from "../convention-collective/search";
import { AgreementSearchInput } from "../convention-collective/AgreementSearchInput";
import { ChatHistory } from "./ChatHistory";
import * as Sentry from "@sentry/nextjs";
import { push } from "@socialgouv/matomo-next";

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
              answerType={apiResult?.answerType}
              isFollowupResponse={message.isFollowup}
            />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={styles.chatContainer}>
      <ChatHistory
        conversations={conversations}
        currentConversationId={currentConversationId}
        showHistory={showHistory}
        onShowHistoryChange={setShowHistory}
        onConversationSelect={handleConversationSelect}
        onDeleteConversation={handleDeleteConversation}
      />

      <div className={styles.chatMainContent}>
        {/* Fixed header with buttons - always visible */}
        <div className={`${fr.cx("fr-mt-2w")} ${styles.chatHeader}`}>
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
          className={`chat-messages ${styles.chatMessagesContainer}`}
        >
          {messages.map((message, index) => renderMessage(message, index))}
        </div>

        <form
          onSubmit={handleSubmit}
          className={`${fr.cx("fr-grid-row", "fr-grid-row--gutters")} ${
            styles.chatForm
          }`}
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
            className={`${fr.cx("fr-col-1")} ${styles.submitButtonContainer}`}
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
              <div className={styles.followupInfo}>
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
