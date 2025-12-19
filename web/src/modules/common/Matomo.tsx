"use client";
import { init, push } from "@socialgouv/matomo-next";
import { useSession } from "next-auth/react";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

const MATOMO_URL = "https://matomo.fabrique.social.gouv.fr/";
const MATOMO_SITE_ID = "134";

const MatomoComponent = () => {
  const [initialised, setInitialised] = useState(false);
  const { data: session, status } = useSession();
  const previousAuthStatus = useRef<string | null>(null);
  const lastKnownUserHash = useRef<string | null>(null);
  useEffect(() => {
    if (MATOMO_URL && MATOMO_SITE_ID && !initialised) {
      init({ url: MATOMO_URL, siteId: MATOMO_SITE_ID });
      setInitialised(true);
    }
  }, [initialised]);

  useEffect(() => {
    const currentUserHash = session?.userHash;

    // Associate a stable, non-PII user id for adoption metrics.
    if (status === "authenticated" && currentUserHash) {
      lastKnownUserHash.current = currentUserHash;
      push(["setUserId", currentUserHash]);
    } else {
      push(["resetUserId"]);
    }

    // Track connection history (login/logout) once per status transition.
    if (previousAuthStatus.current !== status) {
      const now = new Date().toISOString();
      if (
        status === "authenticated" &&
        previousAuthStatus.current !== "authenticated"
      ) {
        push(["trackEvent", "auth", "login", currentUserHash || "unknown"]);
        push(["trackEvent", "auth", "login_date", now]);
      } else if (
        status === "unauthenticated" &&
        previousAuthStatus.current === "authenticated"
      ) {
        push([
          "trackEvent",
          "auth",
          "logout",
          lastKnownUserHash.current || "unknown",
        ]);
        push(["trackEvent", "auth", "logout_date", now]);
      }
      previousAuthStatus.current = status;
    }
  }, [session?.userHash, status]);

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
