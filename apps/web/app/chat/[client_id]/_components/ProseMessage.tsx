"use client";

// Renders an assistant message as markdown, in the house editorial voice.
//
// This is the single client-side change that unlocks the whole feature: every
// assistant turn (finished and mid-stream) flows through here, so structure the
// agent adds — short paragraphs, restrained emphasis, a compact list, a
// timeline block, an inline place chip — actually renders instead of arriving as
// one undifferentiated wall of prose.
//
// Two custom hooks extend plain markdown:
//   * `[Label](place:Query)` anchors  → <PlaceChip> (inline, expands a mini-map)
//   * ```ov-timeline <json>``` fences → <Timeline> (vertical "shape of the trip")
// Both are authored in the message body — the timeline by the runtime
// materialising the validated propose_timeline tool result — so they persist in
// turn.content and order themselves against the prose with no extra plumbing.
//
// Styling deliberately leans on inherited type (font/size/color come from the
// parent turn row) and adds only block rhythm + element treatments, so the
// streaming row and the finished row read identically.

import Markdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

import { PlaceChip } from "./PlaceChip";
import { Timeline, parseTimeline } from "./Timeline";

const PLACE_SCHEMES = ["place:", "ovplace:"] as const;

function placeQuery(href: string | undefined): string | null {
  if (!href) return null;
  for (const scheme of PLACE_SCHEMES) {
    if (href.startsWith(scheme)) return href.slice(scheme.length);
  }
  return null;
}

// Flatten link/code children to text. In practice these are single string
// nodes; the guard keeps stray element children from stringifying to junk.
function childrenToText(children: unknown): string {
  if (typeof children === "string") return children;
  if (typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childrenToText).join("");
  return "";
}

// Preserve our custom place: scheme through react-markdown's URL sanitiser;
// defer to the safe default for everything else (http/https/mailto/tel/relative).
function urlTransform(url: string): string {
  return placeQuery(url) !== null ? url : defaultUrlTransform(url);
}

const COMPONENTS: Components = {
  p: ({ children }) => <p className="mb-3.5 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => (
    <ul className="mb-3.5 list-disc space-y-1 pl-5 marker:text-brand/50 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-3.5 list-decimal space-y-1 pl-5 marker:text-ink/40 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-1 [&>p]:mb-0">{children}</li>,
  // Headings are pulled way down from browser defaults — this is a chat voice,
  // not a document. A stray `##` reads as a quiet lead-in, never a banner.
  h1: ({ children }) => (
    <span className="mb-2 mt-1 block font-serif text-[19px] font-medium leading-snug text-ink">
      {children}
    </span>
  ),
  h2: ({ children }) => (
    <span className="mb-2 mt-1 block font-serif text-[18px] font-medium leading-snug text-ink">
      {children}
    </span>
  ),
  h3: ({ children }) => (
    <span className="mb-1.5 mt-1 block font-sans text-[11px] uppercase tracking-[0.18em] text-ink/50">
      {children}
    </span>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3.5 border-l-2 border-brand/30 pl-3.5 text-ink/70">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-5 border-ink/10" />,
  a: ({ href, children }) => {
    const query = placeQuery(href);
    if (query !== null) {
      return <PlaceChip label={childrenToText(children)} query={query} />;
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-brand underline decoration-brand/40 underline-offset-2 hover:decoration-brand"
      >
        {children}
      </a>
    );
  },
  // Fenced ```ov-timeline blocks become the timeline; everything else stays code.
  code: ({ className, children }) => {
    if (className && /\blanguage-ov-timeline\b/.test(className)) {
      const data = parseTimeline(childrenToText(children));
      if (data) return <Timeline data={data} />;
      // Unparseable → fall through to a plain block so nothing is swallowed.
    }
    return (
      <code className="rounded bg-ink/[0.06] px-1 py-0.5 font-sans text-[0.85em] text-ink/80">
        {children}
      </code>
    );
  },
  // Unwrap <pre>: block embeds carry their own container, and this product
  // doesn't emit generic multi-line code blocks.
  pre: ({ children }) => <>{children}</>,
};

export type ProseMessageProps = {
  content: string;
  className?: string;
};

export function ProseMessage({ content, className }: ProseMessageProps) {
  return (
    <div className={cn("break-words", className)} data-testid="prose-message">
      <Markdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={COMPONENTS}
      >
        {content}
      </Markdown>
    </div>
  );
}
