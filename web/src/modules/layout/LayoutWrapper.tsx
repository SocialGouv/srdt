"use client";

import { Header as DsfrHeader } from "@codegouvfr/react-dsfr/Header";
import { Footer as DsfrFooter } from "@codegouvfr/react-dsfr/Footer";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import { ReactNode } from "react";
import { headerFooterDisplayItem } from "@codegouvfr/react-dsfr/Display";
import { fr } from "@codegouvfr/react-dsfr";
import { useAuth } from "@/hooks/use-auth";
import { signOut } from "next-auth/react";

type Props = {
  children: ReactNode;
};

export const LayoutWrapper = ({ children }: Props) => {
  const { isAuthenticated, user } = useAuth();

  const handleSignOut = async () => {
    await signOut({ callbackUrl: "/" });
  };

  return (
    <>
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
