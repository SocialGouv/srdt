"use client";

import {
  useState,
  useEffect,
  useRef,
  forwardRef,
  useImperativeHandle,
} from "react";
import { fr } from "@codegouvfr/react-dsfr";

interface AutoresizeTextareaProps {
  value: string;
  onChange: (value: string) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  disabled?: boolean;
  maxLines?: number;
  className?: string;
  style?: React.CSSProperties;
}

export interface AutoresizeTextareaRef {
  focus: () => void;
  blur: () => void;
}

export const AutoresizeTextarea = forwardRef<
  AutoresizeTextareaRef,
  AutoresizeTextareaProps
>(
  (
    {
      value,
      onChange,
      onKeyDown,
      placeholder = "Saisissez votre message",
      disabled = false,
      maxLines = 10,
      className,
      style,
      ...props
    },
    ref
  ) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [lineHeight, setLineHeight] = useState(24);

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
      blur: () => textareaRef.current?.blur(),
    }));

    const resizeTextarea = () => {
      if (textareaRef.current) {
        const textarea = textareaRef.current;

        // Reset height to auto to get the correct scrollHeight
        textarea.style.height = "auto";

        // Calculate line height from computed style if not set
        if (lineHeight === 24) {
          const computedStyle = window.getComputedStyle(textarea);
          const computedLineHeight = parseInt(computedStyle.lineHeight);
          if (!isNaN(computedLineHeight)) {
            setLineHeight(computedLineHeight);
          }
        }

        const maxHeight = lineHeight * maxLines;
        const contentHeight = textarea.scrollHeight;

        if (contentHeight <= maxHeight) {
          // Content fits within max lines, hide overflow and set exact height
          textarea.style.height = `${Math.max(contentHeight, lineHeight)}px`;
          textarea.style.overflowY = "hidden";
        } else {
          // Content exceeds max lines, set max height and enable scrolling
          textarea.style.height = `${maxHeight}px`;
          textarea.style.overflowY = "auto";
        }
      }
    };

    useEffect(() => {
      resizeTextarea();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value, lineHeight, maxLines]);

    useEffect(() => {
      // Resize on mount
      resizeTextarea();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value);
      // Small timeout to ensure the DOM is updated before resizing
      setTimeout(resizeTextarea, 0);
    };

    const handlePaste = () => {
      // Delay to allow paste content to be processed
      setTimeout(resizeTextarea, 0);
    };

    return (
      <textarea
        {...props}
        ref={textareaRef}
        className={className || fr.cx("fr-input")}
        placeholder={placeholder}
        value={value}
        onChange={handleChange}
        onKeyDown={onKeyDown}
        onPaste={handlePaste}
        disabled={disabled}
        style={{
          resize: "none",
          minHeight: `${lineHeight}px`,
          lineHeight: `${lineHeight}px`,
          ...style,
        }}
      />
    );
  }
);

AutoresizeTextarea.displayName = "AutoresizeTextarea";
