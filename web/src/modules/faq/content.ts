// Server-only: reads the FAQ markdown from disk at build time. The `server-only`
// import makes the build fail with a clear message if a client component ever
// imports this file (it pulls in node:fs).
import "server-only";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { stripHtmlComments } from "@/modules/common/markdown";

// Next.js runs `next build` / the server with the app root (web/) as the cwd,
// so process.cwd() reliably points at the package root here.
const CONTENT_PATH = join(process.cwd(), "src", "content", "faq.md");

/** The FAQ markdown, with author-guidance HTML comments stripped. */
export function getFaqContent(): string {
  try {
    return stripHtmlComments(readFileSync(CONTENT_PATH, "utf-8"));
  } catch (error) {
    // Degrade gracefully (empty page) but make the failure visible in build /
    // server logs rather than silently shipping no content.
    console.error(`[faq] Could not read ${CONTENT_PATH}:`, error);
    return "";
  }
}
