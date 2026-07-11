"use client";

// Shell-style recall of previously sent messages for a chat composer. Up walks
// back through what you've sent this session, Down walks forward and finally
// restores the draft you were mid-way through typing — mirroring Claude Code and
// a terminal prompt. History is per-composer and lives only for the session.
//
// To avoid fighting multiline editing, Up only recalls when the caret sits on
// the first line and Down only when it sits on the last line; otherwise the
// arrows move the caret between lines as usual.

import { useCallback, useRef, type KeyboardEvent } from "react";

export interface SentHistory {
  // Call when a message is actually sent — appends it and resets navigation.
  record: (sent: string) => void;
  // Drop-in replacement for the composer's value setter: a manual edit returns
  // us to "live draft" mode so the next Up snapshots the edited text.
  onValueChange: (next: string) => void;
  // Attach to the textarea; handles ArrowUp / ArrowDown recall.
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
}

export function useSentHistory(setValue: (v: string) => void): SentHistory {
  const historyRef = useRef<string[]>([]);
  // null = editing a live draft; a number indexes into historyRef.
  const navRef = useRef<number | null>(null);
  const draftRef = useRef("");

  const record = useCallback((sent: string) => {
    const trimmed = sent.trim();
    if (!trimmed) return;
    const h = historyRef.current;
    // Skip consecutive duplicates so resending the same line twice in a row
    // doesn't create two identical history entries to step past.
    if (h[h.length - 1] !== trimmed) h.push(trimmed);
    navRef.current = null;
    draftRef.current = "";
  }, []);

  const onValueChange = useCallback(
    (next: string) => {
      navRef.current = null;
      setValue(next);
    },
    [setValue],
  );

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      const el = e.currentTarget;
      const h = historyRef.current;
      const caretStart = el.selectionStart ?? 0;
      const caretEnd = el.selectionEnd ?? el.value.length;
      const newlineBeforeCaret = el.value.slice(0, caretStart).includes("\n");
      const newlineAfterCaret = el.value.slice(caretEnd).includes("\n");

      if (e.key === "ArrowUp" && !newlineBeforeCaret) {
        if (h.length === 0) return;
        e.preventDefault();
        if (navRef.current === null) {
          draftRef.current = el.value;
          navRef.current = h.length - 1;
        } else if (navRef.current > 0) {
          navRef.current -= 1;
        }
        setValue(h[navRef.current] ?? "");
      } else if (e.key === "ArrowDown" && !newlineAfterCaret) {
        if (navRef.current === null) return;
        e.preventDefault();
        if (navRef.current < h.length - 1) {
          navRef.current += 1;
          setValue(h[navRef.current] ?? "");
        } else {
          // Stepped past the newest — restore the draft we snapshotted.
          navRef.current = null;
          setValue(draftRef.current);
        }
      }
    },
    [setValue],
  );

  return { record, onValueChange, onKeyDown };
}
