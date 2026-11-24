// Usage indicators collected from the users: the NPS and the "time saved"
// question. No React, no DOM: imported by the widgets and by the save route,
// which validates what it receives against these values.

/** Answers to "Diriez-vous que la réponse de l'assistant IA vous a fait gagner du temps ?" */
export const TIME_SAVED_ANSWERS = ["yes", "no", "dont_know"] as const;
export type TimeSavedAnswer = (typeof TIME_SAVED_ANSWERS)[number];

export const isTimeSavedAnswer = (value: unknown): value is TimeSavedAnswer =>
  TIME_SAVED_ANSWERS.includes(value as TimeSavedAnswer);

/** NPS: "Recommanderiez-vous l'assistant IA à un collègue ?", from 0 to 10. */
export const NPS_MIN = 0;
export const NPS_MAX = 10;

export const isNpsScore = (value: unknown): value is number =>
  Number.isInteger(value) &&
  (value as number) >= NPS_MIN &&
  (value as number) <= NPS_MAX;

/** What opened the NPS modal (tracked with the score). */
export const NPS_TRIGGERS = ["copy", "exit_intent"] as const;
export type NpsTrigger = (typeof NPS_TRIGGERS)[number];

export const isNpsTrigger = (value: unknown): value is NpsTrigger =>
  NPS_TRIGGERS.includes(value as NpsTrigger);
