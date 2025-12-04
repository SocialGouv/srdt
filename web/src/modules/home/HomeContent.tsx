"use client";

import { useAuth } from "@/hooks/use-auth";
import { AuthVerification } from "@/modules/auth/AuthVerification";
import { Chat } from "@/modules/chat/Chat";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";

export function HomeContent() {
  const { isAuthenticated, isLoading } = useAuth();

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
    <LayoutWrapper>
      {isAuthenticated ? <Chat /> : <AuthVerification />}
    </LayoutWrapper>
  );
}
