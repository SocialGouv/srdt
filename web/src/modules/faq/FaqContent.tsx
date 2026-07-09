"use client";

import { useEffect, useMemo } from "react";
import Image from "next/image";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fr } from "@codegouvfr/react-dsfr";
import { Accordion } from "@codegouvfr/react-dsfr/Accordion";
import { Button } from "@codegouvfr/react-dsfr/Button";
import { LayoutWrapper } from "@/modules/layout/LayoutWrapper";
import { ChatHistory } from "@/modules/chat/ChatHistory";
import { useSidebarNav } from "@/modules/chat/useSidebarNav";
import { externalLinkComponents } from "@/modules/common/markdownComponents";
import communityIllustration from "./community.svg";
import chatStyles from "@/modules/chat/Chat.module.css";
import styles from "./Faq.module.css";

const SUPPORT_URL = "https://tally.so/r/jao5z4";

type FaqEntry = { question: string; answer: string };

// Split the markdown into Q&A entries: each "## " heading is a question, the
// text until the next heading is its answer (see src/content/faq.md).
function parseFaq(markdown: string): FaqEntry[] {
  return markdown
    .split(/^##\s+/m)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      const newline = block.indexOf("\n");
      if (newline === -1) return { question: block, answer: "" };
      return {
        question: block.slice(0, newline).trim(),
        answer: block.slice(newline + 1).trim(),
      };
    });
}

type Props = {
  markdown: string;
};

export function FaqContent({ markdown }: Props) {
  const sidebar = useSidebarNav();

  // Land at the top of the page (the previous screen's scroll can carry over).
  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  const entries = useMemo(() => parseFaq(markdown), [markdown]);

  return (
    <LayoutWrapper fullWidth>
      <div
        className={`${chatStyles.chatContainer} ${chatStyles.chatContainerEmpty}`}
      >
        <ChatHistory {...sidebar} currentConversationId="" activeItem="faq" />

        <div className={chatStyles.chatMainContent}>
          <div className={styles.card}>
            <h1 className={styles.title}>FAQ - Questions fréquentes</h1>
            <p className={styles.intro}>
              Trouvez des réponses aux questions les plus courantes sur
              l&apos;utilisation de l&apos;assistant IA des SRDT.
            </p>

            <div className={`${styles.accordions} ${fr.cx("fr-accordions-group")}`}>
              {entries.map((entry, index) => (
                <Accordion
                  key={entry.question}
                  label={entry.question}
                  defaultExpanded={index === 0}
                >
                  <div className={styles.answer}>
                    <Markdown
                      remarkPlugins={[remarkGfm]}
                      components={externalLinkComponents}
                    >
                      {entry.answer}
                    </Markdown>
                  </div>
                </Accordion>
              ))}
            </div>

            <div className={styles.supportCard}>
              <Image
                src={communityIllustration}
                alt=""
                width={56}
                height={56}
                className={styles.supportIllustration}
              />
              <p className={styles.supportTitle}>
                Vous n&apos;avez pas trouvé votre réponse&nbsp;?
              </p>
              <p className={styles.supportText}>
                Contactez l&apos;équipe support, nous vous répondrons dans les
                meilleurs délais.
              </p>
              <Button
                iconId="fr-icon-external-link-line"
                iconPosition="right"
                linkProps={{
                  href: SUPPORT_URL,
                  target: "_blank",
                  rel: "noopener noreferrer",
                }}
              >
                Contacter le support
              </Button>
            </div>
          </div>
        </div>
      </div>
    </LayoutWrapper>
  );
}
