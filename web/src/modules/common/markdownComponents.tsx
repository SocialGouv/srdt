import React from "react";

/**
 * Shared react-markdown renderers for editable content pages.
 * Only external links open in a new tab; internal/relative links behave normally.
 * `node` is react-markdown's AST node — drop it so it isn't forwarded to the DOM.
 */
export const externalLinkComponents = {
  a: ({
    href,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    node: _node,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { node?: unknown }) => {
    const isExternal = typeof href === "string" && /^https?:\/\//.test(href);
    return (
      <a
        href={href}
        {...props}
        {...(isExternal
          ? { target: "_blank", rel: "noopener noreferrer" }
          : {})}
      />
    );
  },
};
