"use client";

import { useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { AuthVerification } from "@/modules/auth/AuthVerification";
import { Chat } from "@/modules/chat/Chat";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";

export function HomeContent() {
  const { isAuthenticated, isLoading } = useAuth();
  const [conversationActive, setConversationActive] = useState(false);
  const [chatKey, setChatKey] = useState(0);

  // Reset to a fresh home screen (used when clicking the header brand).
  const goHome = () => {
    setConversationActive(false);
    setChatKey((k) => k + 1);
  };

  if (isLoading) {
    return (
      <LayoutWrapper>
        <div className="fr-container fr-my-6w">
          <div className="fr-grid-row fr-grid-row--center">
            <div className="fr-col-auto">
              <p>Chargement...</p>
            </div>
          </div>
        </div>
      </LayoutWrapper>
    );
  }

  return (
    <LayoutWrapper
      fullWidth={isAuthenticated}
      fillViewport={isAuthenticated && conversationActive}
      onGoHome={isAuthenticated ? goHome : undefined}
    >
      {isAuthenticated ? (
        <Chat key={chatKey} onConversationActiveChange={setConversationActive} />
      ) : (
        <AuthVerification />
      )}
    </LayoutWrapper>
  );
}
