"use client";

import { fr } from "@codegouvfr/react-dsfr";
import Image from "next/image";
import Button from "@codegouvfr/react-dsfr/Button";
import Input, { InputProps } from "@codegouvfr/react-dsfr/Input";
import Downshift from "downshift";
import { useState } from "react";
import Spinner from "./Spinner.svg";
import Link from "next/link";
import { redirect } from "next/navigation";

export type AutocompleteProps<K> = InputProps & {
  onChange?: (value: K | undefined, suggestions?: K[]) => void;
  onError?: (value: string) => void;
  onSearch?: (query: string, results: K[]) => void;
  displayLabel: (item: K | null) => string;
  search: (search: string) => Promise<K[]>;
  dataTestId?: string;
  lineAsLink?: (value: K) => string;
  displayNoResult?: boolean;
  defaultValue?: K;
  onInputValueChange?: (value: string) => void;
  isSearch?: boolean;
  placeholder?: string;
};

export const Autocomplete = <K,>({
  onChange,
  onSearch,
  onError,
  onInputValueChange,
  displayLabel,
  lineAsLink,
  search,
  label,
  state,
  stateRelatedMessage,
  hintText,
  dataTestId,
  defaultValue,
  displayNoResult,
  isSearch = false,
  placeholder,
}: AutocompleteProps<K>) => {
  const [loading, setLoading] = useState(false);
  const [inputRef, setInputRef] = useState<HTMLInputElement | null>();
  const [suggestions, setSuggestions] = useState<K[]>([]);

  return (
    <Downshift<K>
      initialSelectedItem={defaultValue}
      onInputValueChange={async (value, stateAndHelpers) => {
        if (!stateAndHelpers.selectedItem) {
          onInputValueChange?.(value);

          if (!value) {
            onSearch?.(value, []);
            return;
          }

          try {
            setLoading(true);
            const results = await search(value);
            onSearch?.(value, results);
            setSuggestions(results);
          } catch (error) {
            onError?.(error as string);
            setSuggestions([]);
          } finally {
            setLoading(false);
          }
        }
      }}
      onChange={(item) => {
        if (item && onChange) onChange(item, suggestions);
        if (lineAsLink && item) redirect(lineAsLink(item));
      }}
      itemToString={displayLabel}
    >
      {({
        getInputProps,
        getItemProps,
        getLabelProps,
        getMenuProps,
        inputValue,
        isOpen,
        highlightedIndex,
        selectedItem,
        getRootProps,
        clearSelection,
      }) => (
        <div
          {...getRootProps({}, { suppressRefError: true })}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            width: "100%",
            position: "relative",
          }}
        >
          <Input
            nativeLabelProps={getLabelProps()}
            hideLabel={isSearch}
            addon={
              <>
                <div
                  style={{
                    position: "absolute",
                    right: 0,
                    height: "100%",
                    alignContent: "center",
                  }}
                >
                  {!loading && (selectedItem || inputValue) && (
                    <Button
                      data-testid={`${
                        dataTestId ? dataTestId + "-" : ""
                      }autocomplete-close`}
                      iconId="fr-icon-close-circle-fill"
                      className={fr.cx("fr-p-0")}
                      style={{
                        backgroundColor: "unset",
                      }}
                      onClick={() => {
                        clearSelection();
                        if (onChange) onChange(undefined, []);
                        if (onSearch) onSearch("", []);
                        setSuggestions([]);
                        inputRef?.focus();
                      }}
                      priority="tertiary no outline"
                      title="Effacer la sélection"
                      type="button"
                    >
                      <span className={"fr-sr-only"}>Effacer la sélection</span>
                    </Button>
                  )}
                  {loading && (
                    <Image
                      className={fr.cx("fr-mr-1v")}
                      priority
                      src={Spinner}
                      alt="Chargement en cours"
                    />
                  )}
                </div>
              </>
            }
            nativeInputProps={{
              type: "search",
              placeholder,
              ref: setInputRef,
              ...getInputProps(),
            }}
            className={`${fr.cx("fr-mb-0")}`}
            hintText={hintText}
            label={label}
            state={state}
            stateRelatedMessage={stateRelatedMessage}
            classes={{
              wrap: isSearch ? undefined : undefined,
              root: undefined,
            }}
            style={{
              width: "100%",
              ...(isSearch ? { marginTop: 0 } : {}),
            }}
          />
          <ul
            {...getMenuProps()}
            className={`${fr.cx("fr-p-0", "fr-m-0")}`}
            style={{
              position: "absolute",
              top: "100%",
              left: 0,
              width: "100%",
              zIndex: 1000,
              backgroundColor: "var(--background-default-grey)",
              listStyleType: "none",
              borderTop: "none",
              boxShadow: "0 4px 8px rgba(0, 0, 0, 0.1)",
              maxHeight: "300px",
              overflowY: "auto",
              ...(isSearch ? { marginTop: 0, textAlign: "left" } : {}),
            }}
          >
            {isOpen && suggestions.length
              ? suggestions.map((item, index) => (
                  <li
                    {...getItemProps({
                      item,
                      index,
                    })}
                    key={`${displayLabel(item)}${index}`}
                    className={fr.cx("fr-p-3v")}
                    style={{
                      cursor: "pointer",
                      color: "var(--text-action-high-blue-france)",
                      ...(highlightedIndex === index
                        ? {
                            backgroundColor:
                              "var(--background-default-grey-hover)",
                            fontWeight: "bold",
                          }
                        : {}),
                    }}
                  >
                    {lineAsLink ? (
                      <Link
                        href={lineAsLink(item)}
                        style={{
                          backgroundImage: "none",
                        }}
                      >
                        {displayLabel(item)}
                      </Link>
                    ) : (
                      <>{displayLabel(item)}</>
                    )}
                  </li>
                ))
              : isOpen &&
                displayNoResult &&
                !selectedItem && (
                  <li className={fr.cx("fr-p-3v")}>Aucun résultat</li>
                )}
          </ul>
          {isSearch && (
            <button
              className="fr-btn fr-icon-search-line fr-btn--icon"
              title="Rechercher"
              type="submit"
            >
              <span className={fr.cx("fr-sr-only")}>Rechercher</span>
            </button>
          )}
        </div>
      )}
    </Downshift>
  );
};
