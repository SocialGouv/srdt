"use client";

import { Header as DsfrHeader } from "@codegouvfr/react-dsfr/Header";
import { Footer as DsfrFooter } from "@codegouvfr/react-dsfr/Footer";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import { ReactNode } from "react";
import { headerFooterDisplayItem } from "@codegouvfr/react-dsfr/Display";
import { fr } from "@codegouvfr/react-dsfr";
import { useAuth } from "@/hooks/use-auth";
import { signOut } from "next-auth/react";
import { buildProConnectLogoutUrl } from "@/lib/auth/proconnect-logout";
import { AuthorizationCheck } from "@/modules/auth/AuthorizationCheck";

type Props = {
  children: ReactNode;
};

export const LayoutWrapper = ({ children }: Props) => {
  const { isAuthenticated, user, session } = useAuth();

  const handleSignOut = async () => {
    try {
      console.log("🔓 Logout initiated from header");
      console.log("  Session exists:", !!session);
      console.log("  ID Token available:", !!session?.idToken);

      // Get the ID token from the session
      const idToken = session?.idToken;

      // Build ProConnect logout URL (without trailing slash to match ProConnect config)
      const postLogoutRedirectUri = window.location.origin;
      const proconnectLogoutUrl = buildProConnectLogoutUrl(
        idToken || "",
        postLogoutRedirectUri
      );

      // Clear NextAuth session first
      await signOut({ redirect: false });

      // Then redirect to ProConnect logout
      console.log("  Redirecting to ProConnect logout:", proconnectLogoutUrl);
      window.location.href = proconnectLogoutUrl;
    } catch (error) {
      console.error("❌ Error signing out:", error);
      // Fallback: still try to sign out
      await signOut({ callbackUrl: "/" });
    }
  };

  return (
    <>
      <AuthorizationCheck />
      <DsfrHeader
        brandTop={
          <>
            RÉPUBLIQUE
            <br />
            FRANÇAISE
          </>
        }
        homeLinkProps={{
          href: "/",
          title: "Accueil - Experimentation SRDT IA",
        }}
        serviceTitle={
          <>
            Experimentation SRDT IA{" "}
            <Badge as="span" noIcon severity="success">
              Beta
            </Badge>
          </>
        }
        serviceTagline="Direction générale du travail"
        quickAccessItems={
          isAuthenticated
            ? [
                {
                  iconId: "fr-icon-account-circle-line",
                  text: user?.name || user?.email || "Mon compte",
                  buttonProps: {
                    onClick: handleSignOut,
                  },
                  linkProps: undefined,
                },
                headerFooterDisplayItem,
              ]
            : [headerFooterDisplayItem]
        }
      />
      <main className={fr.cx("fr-container", "fr-mb-5w")}>{children}</main>
      <DsfrFooter
        accessibility="non compliant"
        bottomItems={[headerFooterDisplayItem]}
      />
    </>
  );
};
