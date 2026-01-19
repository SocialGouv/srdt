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
  /** Database conversation ID for saving feedback */
  dbConversationId?: string;
};

export const FeedbackSelector = (props: FeedbackSelectorProps) => {
  const { data: session } = useSession();
  const isRestrictedGroup = Boolean(session?.isBetaTester);

  // Beta testers (restricted group) see the Tally form
  if (isRestrictedGroup) {
    return <Feedback {...props} />;
  }

  // Regular users (expanded group) see the simple thumbs up/down feedback
  return <SimpleFeedback {...props} />;
};
