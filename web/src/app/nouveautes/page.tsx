import { readFileSync } from "node:fs";
import { join } from "node:path";
import { NouveautesContent } from "@/modules/nouveautes/NouveautesContent";

export const metadata = {
  title: "Nouveautés",
};

// Read the markdown at build time so the content is baked into the static HTML.
// The writer edits `src/content/nouveautes.md` on GitHub; a redeploy publishes the change.
export const dynamic = "force-static";

// Strip HTML comments (author guidance kept in the file) before rendering.
const markdown = readFileSync(
  join(process.cwd(), "src", "content", "nouveautes.md"),
  "utf-8"
).replace(/<!--[\s\S]*?-->/g, "");

export default function NouveautesPage() {
  return <NouveautesContent markdown={markdown} />;
}
