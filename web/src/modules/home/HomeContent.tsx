"use client";

import { Notice } from "@codegouvfr/react-dsfr/Notice";
import { useAuth } from "@/hooks/use-auth";
import { AuthVerification } from "@/modules/auth/AuthVerification";
import { Chat } from "@/modules/chat/Chat";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";

const feedbackNotice = (
  <Notice
    title={
      <>
        Merci par avance de partager vos retours sur{" "}
        <a
          href="https://tally.so/r/jaG2jR"
          target="_blank"
          rel="noopener noreferrer"
        >
          ce questionnaire d&apos;évaluation
        </a>{" "}
        avant le 18 mai. Ces retours sont précieux pour donner les bonnes
        orientations post-expérimentation à ce projet !
      </>
    }
  />
);

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
    <LayoutWrapper notice={isAuthenticated ? feedbackNotice : undefined}>
      {isAuthenticated ? <Chat /> : <AuthVerification />}
    </LayoutWrapper>
  );
}
