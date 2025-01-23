"use client";

import { Header as DsfrHeader } from "@codegouvfr/react-dsfr/Header";
import { Footer as DsfrFooter } from "@codegouvfr/react-dsfr/Footer";
import { Badge } from "@codegouvfr/react-dsfr/Badge";
import { ReactNode } from "react";
import { fr } from "@codegouvfr/react-dsfr";

type Props = {
  children: ReactNode;
};

export const LayoutWrapper = ({ children }: Props) => {
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
      />
      <div className={fr.cx("fr-container")}>{children}</div>
      <DsfrFooter accessibility="non compliant" />
    </>
  );
};
