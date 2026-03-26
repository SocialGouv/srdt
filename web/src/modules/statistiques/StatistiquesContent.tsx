"use client";

import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";
import { fr } from "@codegouvfr/react-dsfr";

const METABASE_DASHBOARD_URL =
  "https://metabase-prod-srdt.ovh.fabrique.social.gouv.fr/public/dashboard/4b85eb05-647a-4b73-80b0-90ae6be7857d";

export function StatistiquesContent() {
  return (
    <LayoutWrapper>
      <div className={fr.cx("fr-my-5w")}>
        <h1>Statistiques</h1>
        <iframe
          src={METABASE_DASHBOARD_URL}
          width="100%"
          height="1000"
          title="Statistiques SRDT"
          sandbox="allow-scripts allow-same-origin"
          style={{ minHeight: "800px", border: "none" }}
        />
      </div>
    </LayoutWrapper>
  );
}
