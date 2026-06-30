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
import { MatomoUserTracking } from "@/modules/common/MatomoUserTracking";
import styles from "./LayoutWrapper.module.css";

type Props = {
  children: ReactNode;
  /** When true, `main` spans the full width instead of the centered DSFR container. */
  fullWidth?: boolean;
  /**
   * When true, header + main fill the viewport (app-shell) and the footer is
   * pushed below the fold — used on the conversation screen to free reading space.
   */
  fillViewport?: boolean;
  /** When set, clicking the header brand resets to the home screen instead of navigating. */
  onGoHome?: () => void;
};

export const LayoutWrapper = ({
  children,
  fullWidth = false,
  fillViewport = false,
  onGoHome,
}: Props) => {
  const { isAuthenticated, user, session } = useAuth();

  const mainClassName = fillViewport
    ? styles.appMain
    : fullWidth
    ? ""
    : fr.cx("fr-container", "fr-mb-5w");

  const handleSignOut = async () => {
    try {
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
      <MatomoUserTracking />
      <div className={fillViewport ? styles.appShell : styles.contents}>
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
            title: "Accueil - L’assistant IA des SRDT",
            ...(onGoHome
              ? {
                  onClick: (e: React.MouseEvent<HTMLAnchorElement>) => {
                    // Let the browser handle modifier-clicks (open in a new tab/window).
                    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                    e.preventDefault();
                    onGoHome();
                  },
                }
              : {}),
          }}
          serviceTitle={
            <>
              L’assistant IA des SRDT{" "}
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
                    buttonProps: undefined,
                    linkProps: {
                      href: "#",
                      onClick: (e: React.MouseEvent) => e.preventDefault(),
                    },
                  },

                  {
                    iconId: "fr-icon-questionnaire-line",
                    text: "Support",
                    linkProps: {
                      href: "https://tally.so/r/jao5z4",
                      target: "_blank",
                      rel: "noopener noreferrer",
                    },
                  },
                  headerFooterDisplayItem,
                  {
                    iconId: "fr-icon-logout-box-r-line",
                    text: "Se déconnecter",
                    buttonProps: {
                      onClick: handleSignOut,
                    },
                    linkProps: undefined,
                  },
                ]
              : [
                  {
                    iconId: "fr-icon-questionnaire-line",
                    text: "Support",
                    linkProps: {
                      href: "https://tally.so/r/jao5z4",
                      target: "_blank",
                      rel: "noopener noreferrer",
                    },
                  },
                  headerFooterDisplayItem,
                ]
          }
        />
        <main className={mainClassName}>{children}</main>
      </div>
      <DsfrFooter
        accessibility="non compliant"
        bottomItems={[
          {
            text: "Statistiques",
            linkProps: {
              href: "/statistiques",
            },
          },
          headerFooterDisplayItem,
        ]}
      />
    </>
  );
};
