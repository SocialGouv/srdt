import { JURISPRUDENCE_REQUEST_GUARD_TEXT } from "@/prompts/shared";

// Mots-clés signalant une demande explicite de jurisprudence.
const JURISPRUDENCE_REQUEST_PATTERN =
  /\b(jurisprudences?|arr[êe]ts?|cour de cassation|d[ée]cisions?)\b/i;

export const asksForJurisprudence = (question: string): boolean =>
  JURISPRUDENCE_REQUEST_PATTERN.test(question);

/**
 * Ajoute à la question envoyée au modèle une consigne interdisant d'inventer des décisions,
 * quand elle demande explicitement de la jurisprudence. N'est appliqué qu'au message de
 * génération : la question d'origine reste celle affichée et enregistrée.
 */
export const withJurisprudenceRequestGuard = (question: string): string =>
  asksForJurisprudence(question)
    ? `${question.trimEnd()} ${JURISPRUDENCE_REQUEST_GUARD_TEXT}`
    : question;
