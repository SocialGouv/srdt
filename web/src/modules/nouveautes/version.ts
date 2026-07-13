// Server-only: reads the markdown from disk at build time. The `server-only`
// import makes the build fail with a clear message if a client component ever
// imports this file (it pulls in node:fs / node:crypto).
import "server-only";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { stripHtmlComments } from "@/modules/common/markdown";

// Next.js runs `next build` / the server with the app root (web/) as the cwd,
// so process.cwd() reliably points at the package root here.
const CONTENT_PATH = join(process.cwd(), "src", "content", "nouveautes.md");

/** The rendered markdown, with author-guidance HTML comments stripped. */
export function getNouveautesContent(): string {
  try {
    return stripHtmlComments(readFileSync(CONTENT_PATH, "utf-8"));
  } catch (error) {
    // Degrade gracefully (empty page) but make the failure visible in build /
    // server logs rather than silently shipping no content.
    console.error(`[nouveautes] Could not read ${CONTENT_PATH}:`, error);
    return "";
  }
}

/**
 * A short fingerprint of the visible content. It changes whenever the writer
 * edits `nouveautes.md`, which is how the "unread" dot knows there is something
 * new to show. Comment-only edits don't change it (comments are stripped first).
 */
export function getNouveautesVersion(): string {
  const content = getNouveautesContent();
  if (!content) return "";
  return createHash("sha256").update(content).digest("hex").slice(0, 12);
}
