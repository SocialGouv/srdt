import { JURISPRUDENCE_REQUEST_GUARD_TEXT } from "@/prompts/shared";

// Mots-clés signalant une demande explicite de jurisprudence (insensible à la casse, pluriels,
// accents omis) : jurisprudence(s), jurisprudentiel(le)(s), arrêt(s), Cour de cassation,
// « Cass. », décision(s).
const JURISPRUDENCE_REQUEST_PATTERN =
  /\b(jurisprudence|jurisprudentiel|arr[êe]ts?\b|cour\s+de\s+cassation|cass\.|d[ée]cisions?\b)/i;

// Normalisation NFC : un accent saisi sous forme décomposée (« e » + accent combinant) ne doit
// pas empêcher la détection de « arrêt » ou « décision ».
export const asksForJurisprudence = (question: string): boolean =>
  JURISPRUDENCE_REQUEST_PATTERN.test(question.normalize("NFC"));

/**
 * Ajoute à la question envoyée au modèle une consigne interdisant d'inventer des décisions,
 * quand elle demande explicitement de la jurisprudence. N'est appliqué qu'au message de
 * génération : la question d'origine reste celle affichée et enregistrée.
 */
export const withJurisprudenceRequestGuard = (question: string): string =>
  asksForJurisprudence(question)
    ? `${question.trimEnd()} ${JURISPRUDENCE_REQUEST_GUARD_TEXT}`
    : question;
