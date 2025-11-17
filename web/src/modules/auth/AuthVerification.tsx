"use client";

import { ProConnectButton } from "@codegouvfr/react-dsfr/ProConnectButton";
import { Alert } from "@codegouvfr/react-dsfr/Alert";
import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";

export const AuthVerification = () => {
  const searchParams = useSearchParams();
  const error = searchParams.get("error");

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
        <div className="fr-col-12 fr-col-md-8 fr-col-lg-7">
          {error === "AccessDenied" && (
            <Alert
              severity="error"
              title="Accès non autorisé"
              description="Votre adresse email n'est pas autorisée à accéder à cette application. Seuls les agents des domaines gouvernementaux autorisés peuvent se connecter."
              className="fr-mb-4w"
            />
          )}
          {error === "OAuthSignin" && (
            <Alert
              severity="error"
              title="Erreur de connexion"
              description="Une erreur est survenue lors de la connexion avec ProConnect. Veuillez réessayer."
              className="fr-mb-4w"
            />
          )}
          <h1 className="fr-h4">
            Bienvenue sur l&apos;expérimentation SRDT&nbsp;IA
          </h1>
          <div className="fr-mt-4w">
            <ProConnectButton onClick={handleSignIn} />
          </div>
          <div className="fr-text--sm">
            <strong>Domaines autorisés :</strong> pyrenees-atlantiques.gouv.fr,
            seine-maritime.gouv.fr, correze.gouv.fr, dreets.gouv.fr,
            travail.gouv.fr, fabrique.social.gouv.fr, sg.social.gouv.fr
          </div>
        </div>
      </div>
    </div>
  );
};
