"use client";

// The reading surface — the concierge lays one editorial piece on the table.
//
// Unlike the options surface (whose pick flows back as a chat message), this
// panel's single action writes directly: "Add to reading list" persists the
// article into the traveler's Collection as an `article` node. The metadata is
// already in hand from the catalog, so the save carries it verbatim — no
// second fetch of the (auth-walled) source page. R014: the button disables
// while the save is in flight; no spinners beyond a quiet label swap.

import { BookOpen, Check, Plus } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import type { ArticleSurfaceView } from "./types";

export type ArticleSurfaceProps = {
  article: ArticleSurfaceView;
  /** Persist the article into the Collection; resolves true on success. */
  onAdd: (article: ArticleSurfaceView) => Promise<boolean>;
};

export function ArticleSurface({ article, onAdd }: ArticleSurfaceProps) {
  const [state, setState] = useState<"idle" | "saving" | "saved">("idle");

  const add = async () => {
    if (state !== "idle") return;
    setState("saving");
    const ok = await onAdd(article);
    setState(ok ? "saved" : "idle");
  };

  return (
    <div className="flex flex-col" data-testid="article-surface">
      {article.ogImage ? (
        // Plain <img>: no next/image remote-pattern coupling for a surface that
        // renders arbitrary catalog hosts; object-cover keeps the 16:9 frame.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={article.ogImage}
          alt=""
          className="aspect-[16/9] w-full object-cover"
        />
      ) : (
        <div className="flex aspect-[16/9] w-full items-center justify-center bg-ink/5">
          <BookOpen className="h-8 w-8 text-ink/25" aria-hidden />
        </div>
      )}

      <div className="px-6 py-5">
        {article.publication ? (
          <p className="font-sans text-[11px] uppercase tracking-[0.16em] text-brand">
            {article.publication}
          </p>
        ) : null}
        <h2 className="mt-1.5 font-serif text-[22px] leading-snug text-ink">
          {article.title}
        </h2>
        {article.excerpt ? (
          <p className="mt-2.5 font-sans text-[13px] leading-relaxed text-ink/70">
            {article.excerpt}
          </p>
        ) : null}
        {article.readingTimeMinutes ? (
          <p className="mt-2 font-sans text-[11px] tracking-wide text-ink/45">
            {article.readingTimeMinutes} min read
          </p>
        ) : null}

        <div className="mt-5 flex items-center gap-4">
          <button
            type="button"
            disabled={state !== "idle"}
            onClick={add}
            data-testid="article-surface-add"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 font-sans text-[12px] tracking-wide transition-colors",
              state === "saved"
                ? "bg-brand/10 text-brand ring-1 ring-inset ring-brand/40"
                : "bg-brand text-brand-foreground hover:bg-brand/90 disabled:opacity-60",
            )}
          >
            {state === "saved" ? (
              <>
                <Check className="h-3.5 w-3.5" aria-hidden />
                Added to reading list
              </>
            ) : (
              <>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                {state === "saving" ? "Adding…" : "Add to reading list"}
              </>
            )}
          </button>
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="article-surface-read"
            className="font-sans text-[12px] tracking-wide text-ink/55 underline-offset-4 transition-colors hover:text-ink hover:underline"
          >
            Read
          </a>
        </div>
      </div>
    </div>
  );
}
