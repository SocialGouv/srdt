import { NpsTrigger } from "./indicators";

const NPS_SHOWN_KEY = "nps-shown";
export const NPS_REQUEST_EVENT = "srdt:nps-request";

/** The NPS modal is shown once per browser, answered or not. */
export function hasNpsBeenShown(): boolean {
  try {
    return localStorage.getItem(NPS_SHOWN_KEY) !== null;
  } catch {
    return false;
  }
}

export function markNpsShown(): void {
  try {
    localStorage.setItem(NPS_SHOWN_KEY, new Date().toISOString());
  } catch {
    // Ignore storage failures (private mode, quota, …).
  }
}

/**
 * Asks the NPS modal (mounted once by the chat) to open. It does nothing if
 * the modal was already shown.
 */
export function requestNps(trigger: NpsTrigger): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<NpsTrigger>(NPS_REQUEST_EVENT, { detail: trigger })
  );
}
