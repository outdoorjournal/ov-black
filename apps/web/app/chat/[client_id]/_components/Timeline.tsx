// Vertical "shape of the trip" timeline.
//
// The agent emits this via the validated `propose_timeline` tool; the runtime
// materialises the result as a fenced ```ov-timeline JSON block inside the
// reply text, and ProseMessage swaps that block for this component. Keeping the
// data in the message body (rather than a bespoke SSE frame) means it survives
// reload and orders itself naturally against the surrounding prose for free.
//
// Visual language follows the house style: serif titles, a hairline spine, and
// the burnt-orange accent used only as the node markers — punctuation, not fill.

import { cn } from "@/lib/utils";

export type TimelineDay = {
  // Left rail label, e.g. "Day 1" or "Days 2–3".
  label: string;
  // The anchor of the day — a place or move, e.g. "North toward Lefkada".
  title: string;
  // Optional supporting line, e.g. "overnight at Nidri or Sivota".
  detail?: string;
};

export type TimelineData = {
  caption?: string;
  days: TimelineDay[];
};

// Tolerant parser for the fenced JSON payload. Anything that isn't a usable
// shape returns null so ProseMessage can fall back to rendering the raw block
// rather than throwing mid-stream. Individual malformed days are dropped.
export function parseTimeline(raw: string): TimelineData | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;

  const rawDays = (parsed as { days?: unknown }).days;
  if (!Array.isArray(rawDays)) return null;

  const days: TimelineDay[] = [];
  for (const d of rawDays) {
    if (!d || typeof d !== "object") continue;
    const label = (d as { label?: unknown }).label;
    const title = (d as { title?: unknown }).title;
    if (typeof label !== "string" || typeof title !== "string") continue;
    const detail = (d as { detail?: unknown }).detail;
    days.push({
      label,
      title,
      ...(typeof detail === "string" && detail.length > 0 ? { detail } : {}),
    });
  }
  if (days.length === 0) return null;

  const caption = (parsed as { caption?: unknown }).caption;
  return {
    days,
    ...(typeof caption === "string" && caption.length > 0 ? { caption } : {}),
  };
}

export function Timeline({ data }: { data: TimelineData }) {
  return (
    <span
      data-testid="chat-timeline"
      className="my-5 block rounded-md bg-ink/3 px-5 py-4 ring-1 ring-inset ring-ink/6"
    >
      {data.caption ? (
        <span className="mb-4 block font-sans text-[10px] uppercase tracking-[0.22em] text-ink/45">
          {data.caption}
        </span>
      ) : null}

      <span className="block">
        {data.days.map((day, i) => {
          const last = i === data.days.length - 1;
          return (
            <span key={i} className="grid grid-cols-[auto_1fr] gap-x-3.5">
              {/* Spine column: node marker + connector to the next day. */}
              <span className="relative flex flex-col items-center">
                <span
                  aria-hidden
                  className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-brand ring-2 ring-paper"
                />
                {!last ? (
                  <span aria-hidden className="w-px flex-1 bg-ink/12" />
                ) : null}
              </span>

              {/* Content column. */}
              <span className={cn("block", last ? "pb-0" : "pb-4")}>
                <span className="block font-sans text-[10px] uppercase tracking-[0.18em] text-ink/45">
                  {day.label}
                </span>
                <span className="mt-0.5 block font-serif text-[17px] leading-snug text-ink">
                  {day.title}
                </span>
                {day.detail ? (
                  <span className="mt-0.5 block font-sans text-[13px] leading-snug text-ink/55">
                    {day.detail}
                  </span>
                ) : null}
              </span>
            </span>
          );
        })}
      </span>
    </span>
  );
}
