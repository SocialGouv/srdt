"use client";

import { Alert } from "@codegouvfr/react-dsfr/Alert";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { signOut, useSession } from "next-auth/react";
import { buildProConnectLogoutUrl } from "@/lib/auth/proconnect-logout";
import { ALLOWED_EMAIL_DOMAINS } from "@/constants";

export const AccessDeniedContent = () => {
  const { data: session } = useSession();

  const handleSignOut = async () => {
    try {
      const idToken = session?.idToken;

      if (idToken) {
        // Full ProConnect logout with id_token
        const postLogoutRedirectUri = window.location.origin;
        const proconnectLogoutUrl = buildProConnectLogoutUrl(
          idToken,
          postLogoutRedirectUri
        );

        await signOut({ redirect: false });
        window.location.href = proconnectLogoutUrl;
      } else {
        // Fallback if no id_token
        await signOut({ callbackUrl: "/" });
      }
    } catch (error) {
      console.error("Error signing out:", error);
      await signOut({ callbackUrl: "/" });
    }
  };

  return (
    <div className="fr-container fr-my-6w">
      <div className="fr-grid-row fr-grid-row--center">
        <div className="fr-col-12 fr-col-md-8 fr-col-lg-7">
          <Alert
            severity="error"
            title="Accès non autorisé"
            description={
              session?.user?.email
                ? `L'adresse email ${session.user.email} n'est pas autorisée à accéder à cette application. Seuls les agents des domaines gouvernementaux autorisés peuvent se connecter.`
                : "Votre adresse email n'est pas autorisée à accéder à cette application. Seuls les agents des domaines gouvernementaux autorisés peuvent se connecter."
            }
            className="fr-mb-4w"
          />

          <div className="fr-callout fr-mb-4w">
            <h3 className="fr-callout__title">Domaines autorisés</h3>
            <ul>
              {ALLOWED_EMAIL_DOMAINS.map((domain) => (
                <li key={domain}>{domain}</li>
              ))}
            </ul>
          </div>

          <p className="fr-text--sm fr-mb-4w">
            Si vous pensez que votre domaine devrait être autorisé, veuillez
            contacter l&apos;administrateur de l&apos;application.
          </p>

          <Button onClick={handleSignOut} priority="primary">
            Se déconnecter et retourner à l&apos;accueil
          </Button>
        </div>
      </div>
    </div>
  );
};
