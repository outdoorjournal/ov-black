"use client";

// A small overlay shell for the advisor authoring modals (currently Analyze).
// Mirrors the CardComposer overlay — a centered paper panel over a dimmed
// backdrop, Esc-to-close, `role="dialog"` — so summoned authoring surfaces read
// as the same modal everywhere without a heavyweight dialog dependency (there is
// no shared Dialog primitive; only components/ui/dropdown-menu.tsx).

import { useEffect } from "react";
import type { ReactNode } from "react";

export function AuthoringModal({
  title,
  onClose,
  children,
  testId,
  widthClass = "max-w-lg",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
  /** Panel max-width tailwind class; wider for card-list surfaces. */
  widthClass?: string;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      {...(testId ? { "data-testid": testId } : {})}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label={`Close ${title}`}
        onClick={onClose}
        className="absolute inset-0 bg-ink/40"
      />

      <div
        role="dialog"
        aria-label={title}
        className={`relative z-10 flex max-h-[90vh] w-full ${widthClass} flex-col overflow-hidden rounded-xl border border-ink/10 bg-paper shadow-2xl`}
      >
        <header className="flex items-center justify-between border-b border-ink/10 px-5 py-4">
          <h2 className="font-serif text-xl text-ink">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            data-testid="authoring-modal-close"
            className="font-sans text-[11px] uppercase tracking-[0.18em] text-ink/50 transition-colors hover:text-ink"
          >
            Close
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
