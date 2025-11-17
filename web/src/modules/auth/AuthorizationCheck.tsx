"use client";

import { useSession } from "next-auth/react";
import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";

/**
 * Component that checks if the user is authorized
 * Redirects to /access-denied if user has unauthorized flag
 */
export function AuthorizationCheck() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Only check when session is loaded and user is authenticated
    if (status === "authenticated" && session) {
      console.log("🔒 Authorization check:", {
        unauthorized: session.unauthorized,
        pathname,
      });

      // If user is unauthorized and not already on access-denied page
      if (session.unauthorized && pathname !== "/access-denied") {
        console.log("❌ Unauthorized user detected - redirecting to /access-denied");
        router.push("/access-denied");
      }
    }
  }, [session, status, pathname, router]);

  // This component doesn't render anything
  return null;
}

