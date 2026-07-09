import { FaqContent } from "@/modules/faq/FaqContent";
import { getFaqContent } from "@/modules/faq/content";

export const metadata = {
  title: "Aide / FAQ",
};

// Read the markdown at build time so the content is baked into the static HTML.
// The writer edits `src/content/faq.md` on GitHub; a redeploy publishes the change.
export const dynamic = "force-static";

export default function FaqPage() {
  return <FaqContent markdown={getFaqContent()} />;
}
