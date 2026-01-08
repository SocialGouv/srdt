import { fr } from "@codegouvfr/react-dsfr";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Config, PROMPT_INSTRUCTIONS } from "@/constants";

export const metadata = {
  title: "Prompt instructions (interne)",
};

const markdownComponents = {
  a: ({ ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a {...props} target="_blank" rel="noopener noreferrer" />
  ),
  // Demote headings because the prompt strings contain their own "# ..." title
  h1: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className={fr.cx("fr-h3")} {...props}>
      {children}
    </h3>
  ),
  h2: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h4 className={fr.cx("fr-h4")} {...props}>
      {children}
    </h4>
  ),
  h3: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h5 className={fr.cx("fr-h5")} {...props}>
      {children}
    </h5>
  ),
};

type PromptKey =
  | "generate_instruction"
  | "generate_instruction_idcc"
  | "generate_followup_instruction"
  | "generate_followup_instruction_idcc";

const PROMPT_ORDER: Array<{ key: PromptKey; title: string }> = [
  { key: "generate_instruction", title: "1) Réponse initiale (sans IDCC)" },
  {
    key: "generate_instruction_idcc",
    title: "2) Réponse initiale (avec IDCC)",
  },
  { key: "generate_followup_instruction", title: "3) Suivi (sans IDCC)" },
  { key: "generate_followup_instruction_idcc", title: "4) Suivi (avec IDCC)" },
];

export default function PromptInstructionsPage() {
  const prompts = PROMPT_INSTRUCTIONS[Config.V2_0];

  return (
    <div className={fr.cx("fr-my-5w", "fr-container")}>
      <h1 className={fr.cx("fr-h1")}>Prompt instructions — v2.0</h1>

      <div className={fr.cx("fr-grid-row", "fr-grid-row--gutters")}>
        {PROMPT_ORDER.map(({ key, title }) => {
          const promptText = prompts[key];
          return (
            <section key={key} className={fr.cx("fr-col-12")}>
              <h2 className={fr.cx("fr-h2")}>{title}</h2>

              <div className={fr.cx("fr-callout", "fr-mb-3w")}>
                <Markdown
                  remarkPlugins={[remarkGfm]}
                  components={markdownComponents}
                >
                  {promptText}
                </Markdown>
              </div>

              <details className={fr.cx("fr-mb-5w")}>
                <summary>Afficher le markdown brut</summary>
                <pre
                  className={fr.cx("fr-mt-2w")}
                  style={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    padding: "1rem",
                    border: "1px solid var(--border-default-grey)",
                    borderRadius: "0.25rem",
                    background: "var(--background-alt-grey)",
                  }}
                >
                  {promptText}
                </pre>
              </details>
            </section>
          );
        })}
      </div>
    </div>
  );
}
