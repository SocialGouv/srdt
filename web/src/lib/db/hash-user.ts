/**
 * Generate the same hashed user ID as used in Matomo tracking.
 * Uses SHA-256 with the same salt prefix to ensure consistency.
 * This is a server-side version using Node.js crypto.
 */
export async function hashEmailForUserId(email: string): Promise<string> {
  const normalized = email.toLowerCase().trim();

  // Same salt prefix as MatomoUserTracking.tsx
  const salted = `srdt-matomo:${normalized}`;

  // Use Node.js crypto for server-side hashing
  const encoder = new TextEncoder();
  const data = encoder.encode(salted);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);

  // Convert to hex and take first 24 chars (same as Matomo)
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashHex = hashArray
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return hashHex.slice(0, 24);
}
