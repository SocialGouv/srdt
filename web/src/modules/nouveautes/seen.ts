// Client-safe: tracks, per browser, which version of the Nouveautés page the
// user has already seen. Paired with getNouveautesVersion() (server-side).
const NOUVEAUTES_SEEN_KEY = "nouveautes-seen-version";

export function getSeenNouveautesVersion(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(NOUVEAUTES_SEEN_KEY);
  } catch {
    return null;
  }
}

export function markNouveautesSeen(version: string): void {
  if (typeof window === "undefined" || !version) return;
  try {
    localStorage.setItem(NOUVEAUTES_SEEN_KEY, version);
  } catch {
    // Ignore storage failures (private mode, quota, …).
  }
}
