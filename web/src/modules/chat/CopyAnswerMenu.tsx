import { fr } from "@codegouvfr/react-dsfr";
import { Button } from "@codegouvfr/react-dsfr/Button";
import React, {
  RefObject,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import styles from "./Chat.module.css";
import { AnswerSection, getAnswerSections } from "./answer-sections";

interface CopyAnswerMenuProps {
  /** Rendered markdown of the answer: the copies are taken from this DOM. */
  contentRef: RefObject<HTMLDivElement | null>;
  /** Raw answer, copied as a last resort. */
  fallbackText: string;
}

const COPIED_FEEDBACK_MS = 2000;
/** Space between the button and the menu. */
const MENU_GAP_PX = 4;
/** Space kept between the menu and the edge of the viewport. */
const VIEWPORT_MARGIN_PX = 8;

/** Writes HTML + plain text; plain text only where ClipboardItem is missing. */
async function writeToClipboard(html: string, text: string) {
  if (typeof ClipboardItem === "undefined") {
    await navigator.clipboard.writeText(text);
    return;
  }
  await navigator.clipboard.write([
    new ClipboardItem({
      "text/html": new Blob([html], { type: "text/html" }),
      "text/plain": new Blob([text], { type: "text/plain" }),
    }),
  ]);
}

const sectionToHtml = (section: AnswerSection) =>
  section.elements.map((el) => el.outerHTML).join("");

const sectionToText = (section: AnswerSection) =>
  section.elements.map((el) => el.innerText).join("\n\n");

/**
 * "Copier la réponse" button. When the answer has titled sections, it opens a
 * menu to copy either the full answer or a single section (its body, without
 * the title). Otherwise it copies the full answer directly, as before.
 *
 * The menu is rendered in a portal, fixed to the viewport. Inside the
 * scrolling messages area it would be clipped by the bottom edge and, being
 * out of flow there, it even stretched the area while open.
 */
export const CopyAnswerMenu = ({
  contentRef,
  fallbackText,
}: CopyAnswerMenuProps) => {
  const menuId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const copiedTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [sections, setSections] = useState<AnswerSection[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  // The sections come from the rendered answer, so read them once it is in
  // the DOM (and again when another conversation is shown at this index).
  useEffect(() => {
    setSections(
      contentRef.current ? getAnswerSections(contentRef.current) : []
    );
  }, [contentRef, fallbackText]);

  useEffect(
    () => () => {
      if (copiedTimeoutRef.current) clearTimeout(copiedTimeoutRef.current);
    },
    []
  );

  // Close on click outside and on Escape.
  useEffect(() => {
    if (!isOpen) return;
    const handleMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        !buttonRef.current?.contains(target) &&
        !menuRef.current?.contains(target)
      ) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  /**
   * Places the menu under the button, right-aligned with it. It never gets
   * wider than the answer (the actions row holding the button spans it),
   * opens upward when the viewport would cut it below and there is more room
   * above, and scrolls if even that room is not enough.
   */
  const positionMenu = useCallback(() => {
    const button = buttonRef.current;
    const menu = menuRef.current;
    if (!button || !menu) return;
    const viewportHeight = document.documentElement.clientHeight;
    const rect = button.getBoundingClientRect();
    const rowLeft = button.parentElement?.getBoundingClientRect().left ?? 0;

    // Sizes first: the position depends on them.
    menu.style.minWidth = `${rect.width}px`;
    menu.style.maxWidth = `min(22rem, ${Math.floor(rect.right - rowLeft)}px)`;
    const spaceBelow =
      viewportHeight - rect.bottom - MENU_GAP_PX - VIEWPORT_MARGIN_PX;
    const spaceAbove = rect.top - MENU_GAP_PX - VIEWPORT_MARGIN_PX;
    const opensUpward =
      menu.scrollHeight > spaceBelow && spaceAbove > spaceBelow;
    menu.style.maxHeight = `${Math.max(0, opensUpward ? spaceAbove : spaceBelow)}px`;

    // Same coordinates as the button's rect, whatever the viewport does.
    menu.style.left = `${Math.max(
      VIEWPORT_MARGIN_PX,
      rect.right - menu.offsetWidth
    )}px`;
    menu.style.top = `${
      opensUpward
        ? rect.top - MENU_GAP_PX - menu.offsetHeight
        : rect.bottom + MENU_GAP_PX
    }px`;
  }, []);

  // Position before paint, then follow the button while the page scrolls.
  useLayoutEffect(() => {
    if (!isOpen) return;
    positionMenu();
    menuRef.current
      ?.querySelector<HTMLElement>('[role="menuitem"]')
      ?.focus({ preventScroll: true });
    window.addEventListener("scroll", positionMenu, true);
    window.addEventListener("resize", positionMenu);
    return () => {
      window.removeEventListener("scroll", positionMenu, true);
      window.removeEventListener("resize", positionMenu);
    };
  }, [isOpen, positionMenu]);

  const showCopied = () => {
    setCopySuccess(true);
    if (copiedTimeoutRef.current) clearTimeout(copiedTimeoutRef.current);
    copiedTimeoutRef.current = setTimeout(
      () => setCopySuccess(false),
      COPIED_FEEDBACK_MS
    );
  };

  /** Copies one section, or the full answer when `section` is null. */
  const copy = async (section: AnswerSection | null) => {
    const root = contentRef.current;
    if (isOpen) {
      setIsOpen(false);
      buttonRef.current?.focus({ preventScroll: true });
    }
    const plainText = section
      ? sectionToText(section)
      : root?.innerText ?? fallbackText;
    try {
      if (section) {
        await writeToClipboard(sectionToHtml(section), plainText);
      } else if (root) {
        await writeToClipboard(root.innerHTML, plainText);
      } else {
        await navigator.clipboard.writeText(fallbackText);
      }
      showCopied();
    } catch (err) {
      console.error("Failed to copy text:", err);
      // Final fallback to plain text
      try {
        await navigator.clipboard.writeText(section ? plainText : fallbackText);
        showCopied();
      } catch (fallbackErr) {
        console.error("Fallback copy also failed:", fallbackErr);
      }
    }
  };

  const handleMenuKeyDown = (event: React.KeyboardEvent<HTMLUListElement>) => {
    if (event.key === "Tab") {
      // The menu lives at the end of the document (portal): give the focus
      // back to the button so that the Tab moves on from there.
      buttonRef.current?.focus();
      setIsOpen(false);
      return;
    }
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]')
    );
    const index = items.indexOf(document.activeElement as HTMLElement);
    let next: number | null = null;
    if (event.key === "ArrowDown") next = (index + 1) % items.length;
    else if (event.key === "ArrowUp")
      next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    if (next === null) return;
    event.preventDefault();
    items[next]?.focus();
  };

  const hasSections = sections.length > 0;

  return (
    <>
      <Button
        ref={buttonRef}
        onClick={() =>
          hasSections ? setIsOpen((open) => !open) : void copy(null)
        }
        iconId={copySuccess ? "fr-icon-check-line" : "fr-icon-file-text-line"}
        priority="secondary"
        size="small"
        className={styles.copyButton}
        nativeButtonProps={
          hasSections
            ? {
                "aria-haspopup": "menu",
                "aria-expanded": isOpen,
                "aria-controls": menuId,
              }
            : undefined
        }
      >
        {copySuccess ? "Copié !" : "Copier la réponse"}
        {hasSections && (
          <span
            className={`${fr.cx(
              isOpen ? "fr-icon-arrow-up-s-line" : "fr-icon-arrow-down-s-line",
              "fr-icon--sm"
            )} ${styles.copyChevron}`}
            aria-hidden="true"
          />
        )}
      </Button>
      {hasSections &&
        isOpen &&
        createPortal(
          <ul
            ref={menuRef}
            id={menuId}
            role="menu"
            aria-label="Partie de la réponse à copier"
            className={styles.copyMenuList}
            onKeyDown={handleMenuKeyDown}
          >
            <li role="none">
              <button
                type="button"
                role="menuitem"
                className={styles.copyMenuItem}
                onClick={() => copy(null)}
              >
                Réponse complète
              </button>
            </li>
            {sections.map((section, index) => (
              <li role="none" key={index}>
                <button
                  type="button"
                  role="menuitem"
                  className={styles.copyMenuItem}
                  onClick={() => copy(section)}
                >
                  {section.label}
                </button>
              </li>
            ))}
          </ul>,
          document.body
        )}
    </>
  );
};
