"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { fr } from "@codegouvfr/react-dsfr";
import { Conversation } from "./types";
import useApi from "@/hooks/use-api";
import styles from "./Chat.module.css";
import { Agreement } from "../convention-collective/search";
import { ChatHistory } from "./ChatHistory";
import { ChatMessage } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import * as Sentry from "@sentry/nextjs";
import { push } from "@socialgouv/matomo-next";

const STORAGE_KEY = "chat-conversations";
const CURRENT_CONVERSATION_KEY = "current-conversation-id";

const MAX_CONVERSATIONS_TO_STORE = 30;

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
            // Clean up heavy data that's not needed for display
            lastApiResult: conv.lastApiResult
              ? {
                  ...conv.lastApiResult,
                  localSearchChunks: [], // Remove heavy chunks data
                }
              : null,
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
        // Prepare conversations for storage (remove heavy chunks)
        const conversationsToStore = storageConversations.map((conv) => ({
          ...conv,
          // Remove heavy localSearchChunks from API results before storing
          lastApiResult: conv.lastApiResult
            ? {
                ...conv.lastApiResult,
                localSearchChunks: [],
              }
            : conv.lastApiResult,
        }));

        try {
          localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify(conversationsToStore)
          );
        } catch (error) {
          console.error("Error saving conversations to localStorage:", error);
          // If quota exceeded, try with fewer conversations
          if (
            error instanceof DOMException &&
            error.name === "QuotaExceededError"
          ) {
            try {
              const reducedConversations = conversationsToStore.slice(0, 10);
              localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify(reducedConversations)
              );
              console.log(
                "Saved reduced set of conversations due to quota limit"
              );
            } catch (retryError) {
              console.error(
                "Failed to save even reduced conversations:",
                retryError
              );
            }
          }
        }
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
    // Check if current conversation is already empty (only has the initial assistant message)
    const currentConv = conversations.find(
      (c) => c.id === currentConversationId
    );
    const hasUserMessages = currentConv?.messages.some(
      (m) => m.role === "user"
    );

    // If current conversation is empty, don't create a new one
    if (!hasUserMessages) {
      return;
    }

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

    setConversations((prev) => {
      const newList = [newConversation, ...prev];
      // If we exceed the limit, trim to keep only the most recent ones
      if (newList.length > MAX_CONVERSATIONS_TO_STORE) {
        return newList.slice(0, MAX_CONVERSATIONS_TO_STORE);
      }
      return newList;
    });
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
          {messages.map((message, index) => (
            <ChatMessage
              key={index}
              message={message}
              index={index}
              isLastMessage={index === messages.length - 1}
              isLoading={isLoading}
              apiResult={apiResult}
              globalResponseTime={globalResponseTime}
              apiError={apiError}
              selectedAgreement={selectedAgreement}
            />
          ))}
        </div>

        <ChatInput
          newMessage={newMessage}
          setNewMessage={setNewMessage}
          onSubmit={handleSubmit}
          onKeyDown={handleKeyDown}
          isDisabled={isDisabled}
          messages={messages}
          currentConversation={currentConversation}
          selectedAgreement={selectedAgreement}
          setSelectedAgreement={setSelectedAgreement}
        />
      </div>
    </div>
  );
};
