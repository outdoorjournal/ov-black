"use client";

// The send surface. A shadcn Textarea + Button with Enter-to-send semantics
// (Shift+Enter inserts a newline). We deliberately avoid any busy-state
// affordances while streaming — the S05 craft-feel brief forbids the usual
// loading primitives. Instead the button is disabled and the placeholder
// text shifts, which is enough signal.

import { useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export type ComposerProps = {
  disabled: boolean;
  onSend: (content: string) => void;
};

export function Composer({ disabled, onSend }: ComposerProps) {
  const [value, setValue] = useState("");

  function submit(): void {
    const trimmed = value.trim();
    if (trimmed.length === 0 || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    // Enter submits; Shift+Enter allows multi-line drafting.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div
      className="border-t border-ink/10 bg-paper/80 px-6 py-4"
      data-testid="chat-composer"
    >
      <div className="flex items-end gap-3">
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          placeholder={
            disabled ? "The concierge is writing…" : "Write to your concierge"
          }
          className="min-h-[72px] resize-none border-ink/15 bg-paper font-sans text-base text-ink placeholder:text-ink/40"
          data-testid="chat-composer-textarea"
        />
        <Button
          type="button"
          onClick={submit}
          disabled={disabled || value.trim().length === 0}
          className="h-11 px-6 font-sans text-xs uppercase tracking-[0.2em]"
          data-testid="chat-composer-send"
        >
          Send
        </Button>
      </div>
    </div>
  );
}
