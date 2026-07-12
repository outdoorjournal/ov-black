"use client";

// The send surface. An auto-growing textarea + Button with Enter-to-send
// semantics (Shift+Enter inserts a newline). We deliberately avoid any
// busy-state affordances while streaming — the S05 craft-feel brief forbids the
// usual loading primitives. Instead the button is disabled and the placeholder
// text shifts, which is enough signal. The auto-grow behaviour is shared with
// every other concierge composer via AutoGrowTextarea; Up/Down recall of prior
// sent messages is shared via useSentHistory.

import { useState } from "react";

import { AutoGrowTextarea } from "@/components/ui/auto-grow-textarea";
import { Button } from "@/components/ui/button";
import { useSentHistory } from "@/lib/useSentHistory";

export type ComposerProps = {
  disabled: boolean;
  onSend: (content: string) => void;
};

export function Composer({ disabled, onSend }: ComposerProps) {
  const [value, setValue] = useState("");
  const history = useSentHistory(setValue);

  function submit(): void {
    const trimmed = value.trim();
    if (trimmed.length === 0 || disabled) return;
    onSend(trimmed);
    history.record(trimmed);
    setValue("");
  }

  return (
    <div
      className="border-t border-ink/10 bg-paper/80 px-6 py-4"
      data-testid="chat-composer"
    >
      <div className="flex items-end gap-3">
        <AutoGrowTextarea
          value={value}
          onValueChange={history.onValueChange}
          onKeyDown={history.onKeyDown}
          onSubmit={submit}
          disabled={disabled}
          minHeightPx={56}
          placeholder={
            disabled ? "The concierge is writing…" : "Write to your concierge"
          }
          className="flex w-full rounded-md border border-ink/15 bg-paper-white px-3 py-2 font-sans text-base text-ink ring-offset-background placeholder:text-ink/40 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
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
