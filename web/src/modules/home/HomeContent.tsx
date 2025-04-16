"use client";

import { useAuth } from "@/hooks/use-auth";
import { AuthVerification } from "@/modules/auth/AuthVerification";
import { Chat } from "@/modules/chat/Chat";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";

export function HomeContent() {
  const { hasValidatedAuth } = useAuth();
  return (
    <LayoutWrapper>
      {hasValidatedAuth ? <Chat /> : <AuthVerification />}
    </LayoutWrapper>
  );
}