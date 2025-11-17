"use client";

import { Alert } from "@codegouvfr/react-dsfr/Alert";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { signOut, useSession } from "next-auth/react";
import { buildProConnectLogoutUrl } from "@/lib/auth/proconnect-logout";

export const AccessDeniedContent = () => {
  const { data: session } = useSession();

  const handleSignOut = async () => {
    try {
      console.log("🔓 Logout initiated from access-denied page");
      console.log("  Session exists:", !!session);
      console.log("  ID Token available:", !!session?.idToken);

      // Get the ID token from the session
      const idToken = session?.idToken;

      if (idToken) {
        // User has a valid session with id_token - do full ProConnect logout
        console.log("  Using id_token_hint for full ProConnect logout");
        const postLogoutRedirectUri = window.location.origin;
        const proconnectLogoutUrl = buildProConnectLogoutUrl(
          idToken,
          postLogoutRedirectUri
        );

        // Clear NextAuth session first
        await signOut({ redirect: false });

        // Then redirect to ProConnect logout
        console.log("  Redirecting to ProConnect logout:", proconnectLogoutUrl);
        window.location.href = proconnectLogoutUrl;
      } else {
        // No id_token - should not happen with new flow, but handle gracefully
        console.warn("  No id_token available - using fallback logout");
        await signOut({ callbackUrl: "/" });
      }
    } catch (error) {
      console.error("❌ Error signing out:", error);
      // Fallback: still try to sign out
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
              <li>pyrenees-atlantiques.gouv.fr</li>
              <li>seine-maritime.gouv.fr</li>
              <li>correze.gouv.fr</li>
              <li>dreets.gouv.fr</li>
              <li>travail.gouv.fr</li>
              <li>fabrique.social.gouv.fr</li>
              <li>sg.social.gouv.fr</li>
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

