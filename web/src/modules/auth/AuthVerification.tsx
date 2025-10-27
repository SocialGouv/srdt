"use client";

import { ProConnectButton } from "@codegouvfr/react-dsfr/ProConnectButton";
import { signIn } from "next-auth/react";

export const AuthVerification = () => {
  const handleSignIn = async () => {
    try {
      await signIn("proconnect", { callbackUrl: "/" });
    } catch (error) {
      console.error("Error signing in:", error);
    }
  };

  return (
    <div className="fr-container fr-my-6w">
      <div className="fr-grid-row fr-grid-row--center">
        <div className="fr-col-12 fr-col-md-8 fr-col-lg-6">
          <div className="fr-card">
            <div className="fr-card__body">
              <div className="fr-card__content">
                <h1 className="fr-card__title">
                  Bienvenue sur l&apos;expérimentation SRDT IA
                </h1>
                <p className="fr-card__desc">
                  Pour accéder à l&apos;application, veuillez vous connecter
                  avec ProConnect, le service d&apos;authentification des
                  professionnels français.
                </p>
                <div className="fr-mt-4w">
                  <ProConnectButton onClick={handleSignIn} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
