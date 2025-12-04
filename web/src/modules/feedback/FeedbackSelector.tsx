"use client";

import { useSession } from "next-auth/react";
import { Feedback } from "./Feedback";
import { SimpleFeedback } from "./SimpleFeedback";

type FeedbackSelectorProps = {
  modelName?: string;
  familyModel?: string;
  scenarioVersion?: string;
  globalResponseTime?: number;
  inputNbTokens?: number;
  outputNbTokens?: number;
  userQuestion?: string;
  llmResponse?: string;
  errorMessage?: string;
  idcc?: string;
  isFollowupResponse?: boolean;
};

const isBetaTester = (email: string | null | undefined): boolean => {
  if (!email) return false;

  const betaTestersListEnv = process.env.BETA_TESTERS_LIST;
  if (!betaTestersListEnv) return false;

  const betaTestersList = betaTestersListEnv
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);

  return betaTestersList.includes(email.toLowerCase());
};

export const FeedbackSelector = (props: FeedbackSelectorProps) => {
  const { data: session } = useSession();
  const userEmail = session?.user?.email || session?.profile?.email;

  const isRestrictedGroup = isBetaTester(userEmail);

  // Beta testers (restricted group) see the Tally form
  if (isRestrictedGroup) {
    return <Feedback {...props} />;
  }

  // Regular users (expanded group) see the simple thumbs up/down feedback
  return <SimpleFeedback {...props} />;
};
