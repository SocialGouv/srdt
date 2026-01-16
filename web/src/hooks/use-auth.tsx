"use client";

import { useSession } from "next-auth/react";

export function useAuth() {
  // Handle case where useSession returns undefined during static generation
  const sessionResult = useSession();
  const session = sessionResult?.data;
  const status = sessionResult?.status ?? "loading";

  // A user is truly authenticated only if:
  // 1. They have a valid session (status === "authenticated")
  // 2. They are NOT marked as unauthorized
  const isAuthenticated = status === "authenticated" && !session?.unauthorized;

  return {
    session,
    status,
    isAuthenticated,
    isLoading: status === "loading",
    user: session?.user,
    isUnauthorized: session?.unauthorized === true,
  };
}
