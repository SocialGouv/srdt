import { NouveautesContent } from "@/modules/nouveautes/NouveautesContent";
import {
  getNouveautesContent,
  getNouveautesVersion,
} from "@/modules/nouveautes/version";

export const metadata = {
  title: "Nouveautés",
};

// Read the markdown at build time so the content is baked into the static HTML.
// The writer edits `src/content/nouveautes.md` on GitHub; a redeploy publishes
// the change (and bumps the version that drives the "unread" dot).
export const dynamic = "force-static";

export default function NouveautesPage() {
  return (
    <NouveautesContent
      markdown={getNouveautesContent()}
      version={getNouveautesVersion()}
    />
  );
}
