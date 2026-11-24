/** The question shows up this long after the answer was fully displayed. */
export const TIME_SAVED_QUESTION_DELAY_MS = 60_000;

/** Chance for an answer to be followed by the question. */
export const TIME_SAVED_QUESTION_PROBABILITY = 0.3;

/**
 * "Diriez-vous que la réponse de l'assistant IA vous a fait gagner du temps ?",
 * persisted with its conversation. Drawn at random when an answer completes,
 * asked at most once per conversation.
 */
export interface TimeSavedSurvey {
  /** Index, in the conversation messages, of the answer it is about. */
  messageIndex: number;
  /** When that answer was fully displayed (ms since epoch). */
  answerDisplayedAt: number;
  status: "pending" | "shown" | "answered";
}

/**
 * Called when an answer completes, to decide whether the question follows it.
 * A question already shown (or answered) in the conversation is kept as is. A
 * question drawn for an earlier answer but never shown (a follow-up came
 * before the delay) doesn't count: the new answer gets its own draw.
 */
export function drawTimeSavedSurvey(
  current: TimeSavedSurvey | undefined,
  messageIndex: number,
  random = Math.random()
): TimeSavedSurvey | undefined {
  if (current && current.status !== "pending") return current;
  if (random >= TIME_SAVED_QUESTION_PROBABILITY) return undefined;
  return { messageIndex, answerDisplayedAt: Date.now(), status: "pending" };
}
