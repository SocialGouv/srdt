"use client";
import { init, push } from "@socialgouv/matomo-next";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { ALLOWED_EMAIL_DOMAINS } from "@/constants";

const MATOMO_URL = "https://matomo.fabrique.social.gouv.fr/";
const MATOMO_SITE_ID = "134";

// Custom dimension ID for department tracking (configure this in Matomo admin)
const DEPARTMENT_DIMENSION_ID = 1;

// Map email domains to department names
const DOMAIN_TO_DEPARTMENT: Record<string, string> = {
  "bouches-du-rhone.gouv.fr": "Bouches-du-Rhône",
  "maine-et-loire.gouv.fr": "Maine-et-Loire",
  "creuse.gouv.fr": "Creuse",
  "nord.gouv.fr": "Nord",
  "pas-de-calais.gouv.fr": "Pas-de-Calais",
  "aisne.gouv.fr": "Aisne",
  "oise.gouv.fr": "Oise",
  "somme.gouv.fr": "Somme",
  "calvados.gouv.fr": "Calvados",
  "manche.gouv.fr": "Manche",
  "orne.gouv.fr": "Orne",
  "eure.gouv.fr": "Eure",
  "seine-maritime.gouv.fr": "Seine-Maritime",
  "charente.gouv.fr": "Charente",
  "charente-maritime.gouv.fr": "Charente-Maritime",
  "correze.gouv.fr": "Corrèze",
  "dordogne.gouv.fr": "Dordogne",
  "gironde.gouv.fr": "Gironde",
  "landes.gouv.fr": "Landes",
  "lot-et-garonne.gouv.fr": "Lot-et-Garonne",
  "pyrenees-atlantiques.gouv.fr": "Pyrénées-Atlantiques",
  "deux-sevres.gouv.fr": "Deux-Sèvres",
  "vienne.gouv.fr": "Vienne",
  "haute-vienne.gouv.fr": "Haute-Vienne",
  "travail.gouv.fr": "DGT",
  "beta.gouv.fr": "Beta.gouv",
  "fabrique.social.gouv.fr": "Fabrique Numérique",
  "drieets.gouv.fr": "DRIEETS",
  "sg.social.gouv.fr": "SG Social",
};

/**
 * Extract department from email address based on allowed domains
 */
function getDepartmentFromEmail(email: string | null | undefined): string | null {
  if (!email) return null;
  
  const emailLower = email.toLowerCase();
  const domain = ALLOWED_EMAIL_DOMAINS.find((d) => emailLower.endsWith(`@${d}`));
  
  if (domain) {
    return DOMAIN_TO_DEPARTMENT[domain] || domain;
  }
  
  return null;
}

/**
 * Generate a short hash (24 chars) from an email for Matomo user ID
 * Uses a simple but effective hash based on the email string
 */
function hashEmail(email: string): string {
  let hash = 0;
  const str = email.toLowerCase();
  
  // Generate multiple hash values for better distribution
  const hashes: number[] = [];
  
  for (let round = 0; round < 4; round++) {
    hash = round * 31337;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash + char * (round + 1)) | 0;
    }
    hashes.push(Math.abs(hash));
  }
  
  // Convert to base36 and concatenate for a 24-char string
  const base36 = hashes.map((h) => h.toString(36)).join("");
  return base36.slice(0, 24).padEnd(24, "0");
}

const MatomoComponent = () => {
  const [initialised, setInitialised] = useState(false);
  const [userIdSet, setUserIdSet] = useState(false);
  const { user, isAuthenticated } = useAuth();

  // Initialize Matomo
  useEffect(() => {
    if (MATOMO_URL && MATOMO_SITE_ID && !initialised) {
      init({ url: MATOMO_URL, siteId: MATOMO_SITE_ID });
    }
    return () => {
      setInitialised(true);
    };
  }, [initialised, setInitialised]);

  // Set user ID and department when user is authenticated
  useEffect(() => {
    if (!initialised || userIdSet) return;
    
    if (isAuthenticated && user?.email) {
      const hashedUserId = hashEmail(user.email);
      const department = getDepartmentFromEmail(user.email);
      
      // Set the hashed user ID
      push(["setUserId", hashedUserId]);
      
      // Set department as custom dimension if available
      if (department) {
        push(["setCustomDimension", DEPARTMENT_DIMENSION_ID, department]);
      }
      
      setUserIdSet(true);
    }
  }, [initialised, isAuthenticated, user?.email, userIdSet]);

  // Reset user ID tracking on logout
  useEffect(() => {
    if (!isAuthenticated && userIdSet) {
      push(["resetUserId"]);
      setUserIdSet(false);
    }
  }, [isAuthenticated, userIdSet]);

  const searchParams = useSearchParams(),
    pathname = usePathname();

  const searchParamsString = searchParams.toString();
  useEffect(() => {
    if (!pathname) return;
    // may be necessary to decodeURIComponent searchParamsString ?
    const url = pathname + (searchParamsString ? "?" + searchParamsString : "");
    push(["setCustomUrl", url]);
    push(["trackPageView"]);
  }, [pathname, searchParamsString]);
  return null;
};

export default function Matomo() {
  return (
    <Suspense>
      <MatomoComponent />
    </Suspense>
  );
}
