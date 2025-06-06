"use client";
import { fr } from "@codegouvfr/react-dsfr";
import Alert from "@codegouvfr/react-dsfr/Alert";
import { ReactNode, useState } from "react";

import { Autocomplete } from "../common/Autocomplete";
import { searchAgreement } from "./search";
import { Agreement } from "./search";

type Props = {
  onSearch?: (query: string, value?: Agreement[]) => void;
  onAgreementSelect?: (agreement?: Agreement) => void;
  selectedAgreementAlert?: (
    agreement?: Agreement
  ) => NonNullable<ReactNode> | undefined;
  defaultAgreement?: Agreement;
  trackingActionName: string;
};

export const AgreementSearchInput = ({
  onSearch,
  onAgreementSelect,
  selectedAgreementAlert,
  defaultAgreement,
}: Props) => {
  const [selectedAgreement, setSelectedAgreement] = useState(defaultAgreement);
  const [searchState, setSearchState] = useState<
    "noSearch" | "lowSearch" | "notFoundSearch" | "errorSearch" | "fullSearch"
  >("noSearch");
  const [error, setError] = useState("");
  const getStateMessage = () => {
    switch (searchState) {
      case "lowSearch":
        return (
          <>
            Indiquez au moins 3 caractères afin d&apos;affiner votre recherche
          </>
        );
      case "notFoundSearch":
        return (
          <>
            Aucune convention collective n&apos;a été trouvée.
            <br />
            Vérifiez l’orthographe de votre recherche ou le chiffre IDCC présent
            sur votre bulletin de paie
          </>
        );
      case "errorSearch":
        return <>{error}</>;
    }
  };
  const getInputState = () => {
    switch (searchState) {
      case "lowSearch":
        return "info";
      case "errorSearch":
      case "notFoundSearch":
        return "error";
    }
  };
  return (
    <>
      <div>
        <div className={fr.cx("fr-col-12")}>
          <Autocomplete<Agreement>
            defaultValue={selectedAgreement}
            dataTestId="AgreementSearchAutocomplete"
            hintText="Indiquez une convention collective pour améliorer la qualité de la réponse. Ex : transport routier ou 1486"
            label={
              <>
                Nom de la convention collective ou son numéro d’identification
                IDCC (4&nbsp;chiffres)
              </>
            }
            state={getInputState()}
            stateRelatedMessage={getStateMessage()}
            onChange={(agreement) => {
              setSelectedAgreement(agreement);
              if (onAgreementSelect) onAgreementSelect(agreement);
            }}
            displayLabel={(item) => {
              return item ? `${item.shortTitle} (IDCC ${item.num})` : "";
            }}
            lineAsLink={undefined}
            search={searchAgreement}
            onSearch={(query, agreements) => {
              if (onSearch) onSearch(query, agreements);
              if (!query) {
                setSearchState("noSearch");
              } else if (!agreements.length && query.length <= 2) {
                setSearchState("lowSearch");
              } else if (!agreements.length && query.length > 2) {
                setSearchState("notFoundSearch");
              } else {
                setSearchState("fullSearch");
              }
            }}
            onError={(message) => {
              setSearchState("errorSearch");
              setError(message);
            }}
          />
        </div>
        {searchState === "notFoundSearch" && (
          <Alert
            className={fr.cx("fr-mt-2w")}
            as="h2"
            title="Vous ne trouvez pas votre convention collective&nbsp;?"
            description={
              <>
                <p>Il peut y avoir plusieurs explications à cela&nbsp;:</p>
                <ul>
                  <li>
                    Votre convention collective a un autre code&nbsp;: si vous
                    le pouvez, utilisez le numéro Siret de votre entreprise. Ce
                    dernier doit être présent sur votre bulletin de paie.
                  </li>
                  <li>
                    Votre convention collective a un statut particulier&nbsp;:
                    administration ou établissements publics, associations,
                    secteur agricole, La Poste, La Croix Rouge etc.
                  </li>
                  <li>
                    Votre entreprise n’est rattachée à aucune convention
                    collective.
                  </li>
                </ul>
              </>
            }
            severity="info"
          />
        )}
        {selectedAgreement && selectedAgreementAlert?.(selectedAgreement) && (
          <Alert
            className={fr.cx("fr-mt-2w")}
            title="Nous n’avons pas de réponse pour cette convention collective"
            description={selectedAgreementAlert(selectedAgreement)}
            severity="warning"
          />
        )}
      </div>
    </>
  );
};
