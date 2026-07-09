// Server-only: reads the markdown from disk at build time. The `server-only`
// import makes the build fail with a clear message if a client component ever
// imports this file (it pulls in node:fs / node:crypto).
import "server-only";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const CONTENT_PATH = join(process.cwd(), "src", "content", "nouveautes.md");

/** Remove HTML comments, repeating until stable so no `<!--` can survive
 *  interleaved/nested markers (satisfies CodeQL's incomplete-sanitization check). */
function stripHtmlComments(input: string): string {
  let previous;
  let output = input;
  do {
    previous = output;
    output = output.replace(/<!--[\s\S]*?-->/g, "");
  } while (output !== previous);
  return output;
}

/** The rendered markdown, with author-guidance HTML comments stripped. */
export function getNouveautesContent(): string {
  try {
    return stripHtmlComments(readFileSync(CONTENT_PATH, "utf-8"));
  } catch {
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
