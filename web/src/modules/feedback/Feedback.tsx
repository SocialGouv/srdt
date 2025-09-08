"use client";

import { useEffect, useRef } from "react";

declare global {
  interface Window {
    Tally?: {
      loadEmbeds: () => void;
    };
  }
}

type Props = {
  familyModel?: string;
  modelName?: string;
  scenarioVersion?: string;
  globalResponseTime?: number;
  inputNbTokens?: number;
  outputNbTokens?: number;
  userQuestion?: string;
  llmResponse?: string;
  errorMessage?: string;
  idcc?: string;
  isFollowupResponse?: boolean;
};

export const Feedback = (props: Props) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const getTallyUrl = () => {
    const baseUrl = "https://tally.so/embed/mZ19Gy";
    const defaultParams =
      "alignLeft=1&hideTitle=1&transparentBackground=1&dynamicHeight=1";

    const additionalParams = Object.entries(props)
      .filter(([{}, value]) => value !== undefined)
      .map(
        ([key, value]) =>
          `${key}=${encodeURIComponent(value?.toString() ?? "")}`
      )
      .join("&");

    return `${baseUrl}?${defaultParams}${
      additionalParams ? "&" + additionalParams : ""
    }`;
  };

  useEffect(() => {
    const loadTally = () => {
      if (window.Tally) {
        window.Tally.loadEmbeds();
      } else {
        const iframes = document.querySelectorAll(
          "iframe[data-tally-src]:not([src])"
        );
        iframes.forEach((iframe) => {
          if (iframe instanceof HTMLIFrameElement && iframe.dataset.tallySrc) {
            iframe.src = iframe.dataset.tallySrc;
          }
        });
      }
    };

    const script = document.createElement("script");
    script.src = "https://tally.so/widgets/embed.js";
    script.async = true;
    script.onload = loadTally;
    script.onerror = loadTally;
    document.body.appendChild(script);

    return () => {
      document.body.removeChild(script);
    };
  }, []);

  return (
    <iframe
      ref={iframeRef}
      data-tally-src={getTallyUrl()}
      loading="lazy"
      width="100%"
      height="944"
      frameBorder="0"
      marginHeight={0}
      marginWidth={0}
      title="Feedback agents / assistant SRDT"
    />
  );
};
