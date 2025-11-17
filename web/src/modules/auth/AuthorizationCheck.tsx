"use client";

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";

/**
 * Component that checks if the user is authorized
 * Redirects to /access-denied if user has unauthorized flag
 * Shows a loading state to prevent flash of unauthorized content
 */
export function AuthorizationCheck() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    // Skip check if on access-denied page
    if (pathname === "/access-denied") {
      setIsChecking(false);
      return;
    }

    // Wait for session to load
    if (status === "loading") {
      return;
    }

    // Check authorization when session is loaded
    if (status === "authenticated" && session) {
      if (session.unauthorized) {
        // Redirect immediately without showing content
        router.push("/access-denied");
        return;
      }
    }

    // Authorization check complete
    setIsChecking(false);
  }, [session, status, pathname, router]);

  // Show loading overlay while checking authorization
  // This prevents flash of unauthorized content
  if (isChecking && pathname !== "/access-denied" && pathname !== "/") {
    return (
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: "white",
          zIndex: 9999,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div className="fr-container">
          <div className="fr-grid-row fr-grid-row--center">
            <div className="fr-col-auto">
              <p className="fr-text--lg">Chargement...</p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
