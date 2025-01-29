"use client";

import { Button } from "@codegouvfr/react-dsfr/Button";
import { Input } from "@codegouvfr/react-dsfr/Input";
import { useState } from "react";
import { useAuth } from "@/hooks/use-auth";

export const AuthVerification = () => {
  const [verificationCode, setVerificationCode] = useState("");
  const [error, setError] = useState("");
  const { setHasValidatedAuth } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    try {
      const response = await fetch("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: verificationCode }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || "Code invalide");
      }

      setHasValidatedAuth(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Une erreur est survenue");
    }
  };

  return (
    <div className="fr-container fr-my-6w">
      <form onSubmit={handleSubmit}>
        <Input
          label="Code d'accès"
          state={error ? "error" : "default"}
          stateRelatedMessage={error}
          nativeInputProps={{
            value: verificationCode,
            onChange: (e) => setVerificationCode(e.target.value),
            type: "text",
            placeholder: "Entrez votre code",
            required: true,
          }}
        />
        <div className="fr-mt-2w">
          <Button type="submit">Valider</Button>
        </div>
      </form>
    </div>
  );
};
