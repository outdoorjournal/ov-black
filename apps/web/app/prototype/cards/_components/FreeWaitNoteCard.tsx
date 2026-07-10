"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import { TYPE_TOKENS, type StatusKind } from "@/app/_components/itinerary-graph/shared/cards/tokens";

const free = TYPE_TOKENS.free_time;
const wait = TYPE_TOKENS.waiting;
const note = TYPE_TOKENS.note;

export function FreeTimeGlance({ status = "pending" }: { status?: StatusKind }) {
  return (
    <CardShell kind="free_time" status={status} width="glance">
      <div className="mt-1 rounded-md border border-dashed border-ink/20 px-2.5 py-2">
        <h3 className="font-serif italic text-[15px] leading-snug text-ink/85">
          Open afternoon · Kyoto
        </h3>
        <Sub>3 hr · low energy recommended</Sub>
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-ink/70">
        <span>Sunset 18:42</span>
        <span>Energy: rest</span>
      </div>
    </CardShell>
  );
}

export function FreeTimeCompact({
  status = "pending",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="free_time" status={status} width="compact">
      <CompactBody
        kind="free_time"
        title="Open afternoon"
        time="14:00"
        duration="3h"
      />
    </CardShell>
  );
}

export function FreeTimeZoom() {
  return (
    <CardShell kind="free_time" status="pending" width="zoom">
      <Title className="text-[22px] italic">Open afternoon · Kyoto</Title>
      <p className="text-[12px] text-ink/65">Wed 14 May · 14:00 → 17:30 · weather: clear, 19°C</p>

      <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Energy advice</span>
        <p className="mt-1 text-[11px] text-ink/85">
          You walked 14 km this morning at Fushimi Inari. Recommend a slow pocket:
          a quiet bath, a sit-down tea, a nap before dinner at Kichisen.
        </p>
      </div>

      <div className="mt-5">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">If you want to fill it</span>
        <div className="mt-2 grid grid-cols-3 gap-3">
          <Suggestion title="Funaoka Onsen" sub="6 min · cab · 90 min" energy={1} accent={free.accent} />
          <Suggestion title="Ippodō Tea" sub="walk · 18 min · 60 min" energy={1} accent={free.accent} />
          <Suggestion title="Nishijin Textile" sub="cab · 12 min · 75 min" energy={2} accent={free.accent} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        <Chip tint={free.tint}>No commitments</Chip>
        <Chip tint={free.tint}>Light rain umbrella in suite</Chip>
      </div>
    </CardShell>
  );
}

function Suggestion({
  title,
  sub,
  energy,
  accent,
}: {
  title: string;
  sub: string;
  energy: 1 | 2 | 3;
  accent: string;
}) {
  return (
    <div className="rounded border border-ink/10 bg-paper px-2 py-2">
      <p className="font-serif text-[14px] leading-tight text-ink">{title}</p>
      <p className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-ink/55">{sub}</p>
      <span className="mt-1.5 inline-flex gap-0.5" aria-label={`Energy ${energy} of 5`}>
        {[1, 2, 3, 4, 5].map((c) => (
          <span
            key={c}
            className="block h-1.5 w-1.5 rounded-sm"
            style={{ backgroundColor: c <= energy ? accent : "rgba(10,10,10,0.12)" }}
          />
        ))}
      </span>
    </div>
  );
}

export function WaitingGlance({ status = "pending" }: { status?: StatusKind }) {
  return (
    <CardShell kind="waiting" status={status} width="glance">
      <Title>Pre-flight buffer</Title>
      <Sub>HND · 2h 15m before boarding</Sub>
      <div className="mt-2 h-2 w-full rounded-full" aria-hidden style={{ backgroundColor: "rgba(10,10,10,0.08)" }}>
        <div className="h-2 w-1/3 rounded-full" style={{ backgroundColor: wait.accent }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={wait.tint}>Lounge access</Chip>
        <Chip tint={wait.tint}>Wi-Fi · power</Chip>
      </div>
    </CardShell>
  );
}

export function WaitingCompact({
  status = "pending",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="waiting" status={status} width="compact">
      <CompactBody
        kind="waiting"
        title="Check-in window"
        time="17:30"
        duration="30m"
      />
    </CardShell>
  );
}

export function WaitingZoom() {
  return (
    <CardShell kind="waiting" status="approved" width="zoom">
      <div className="flex items-baseline justify-between">
        <Title className="text-[22px]">Pre-flight buffer · Haneda</Title>
        <span className="font-mono text-[12px] text-ink/65">2h 15m</span>
      </div>
      <p className="text-[12px] text-ink/65">After Aman check-out · before DL 276 boarding 18:55</p>

      <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Use this time to</span>
        <ul className="mt-2 space-y-1 text-[11px] text-ink/85">
          <li>· Eat real food before the cabin: Tsubohachi soba @ T3 4F (12 min)</li>
          <li>· Refill water — fountain past security, near gate 110</li>
          <li>· Last currency exchange (cash for taxi at home)</li>
          <li>· Stretch — 7-minute leg routine, sent to your phone</li>
        </ul>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-[12px] text-ink/80">
        <Detail label="Lounge" value="Sky Club T3 · gate 110 · open" />
        <Detail label="Wi-Fi" value="Free 30 min · upgrade ¥800" />
        <Detail label="Restroom" value="Family · past kiosk K3" />
        <Detail label="Quiet zone" value="Mezzanine · north-east corner" />
      </div>
    </CardShell>
  );
}

export function NoteGlance({ status = "pending" }: { status?: StatusKind }) {
  return (
    <CardShell kind="note" status={status} width="glance" noteOverride>
      <div className="mt-1.5">
        <h3 className="font-serif text-[15px] leading-snug text-ink">
          Mark prefers earlier dinners
        </h3>
        <p className="mt-1 text-[11px] leading-snug text-ink/75">
          Last trip the 21:30 seating ran late and he was visibly fatigued.
          Aim for 19:00 from now on.
        </p>
        <div className="mt-2 flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/50">
          <span>S. advisor</span>
          <span>·</span>
          <span>Mar 12</span>
        </div>
      </div>
    </CardShell>
  );
}

export function NoteCompact({
  status = "pending",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="note" status={status} width="compact">
      <CompactBody kind="note" title="Bring umbrella" />
    </CardShell>
  );
}

export function NoteZoom() {
  return (
    <CardShell kind="note" status="approved" width="zoom" noteOverride>
      <div className="grid grid-cols-[1fr_220px] gap-5">
        <div>
          <Title className="text-[20px]">Mark prefers earlier dinners</Title>
          <p className="mt-2 text-[12px] leading-relaxed text-ink/85">
            Last trip the 21:30 seating at Le Bernardin ran late and he was visibly
            fatigued by the second course. From now on, aim for 19:00 in time-zoned
            destinations and 18:30 for tasting menus over 2.5 hours.
          </p>

          <div className="mt-4 rounded border border-ink/15 bg-paper/70 p-3">
            <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Replies</span>
            <ul className="mt-2 space-y-2 text-[11px] text-ink/80">
              <li>
                <span className="font-medium">Sarah</span> — got it; I&rsquo;ll re-check the Saito booking.
                <span className="ml-2 text-[10px] text-ink/50">Mar 12 · 11:42</span>
              </li>
              <li>
                <span className="font-medium">Agent</span> — Saito moved to 19:30; suggest Kichisen kaiseki at 18:00 in Kyoto for the same reason.
                <span className="ml-2 text-[10px] text-ink/50">Mar 12 · 11:48</span>
              </li>
            </ul>
          </div>
        </div>

        <div className="rounded border border-ink/15 bg-paper/70 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Attached to</span>
          <div className="mt-2 rounded border border-ink/10 bg-paper p-2">
            <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">Meal</p>
            <p className="font-serif text-[14px] leading-tight">Sushi Saito · 19:30</p>
          </div>
          <p className="mt-3 text-[10px] uppercase tracking-[0.2em] text-ink/50">Tags</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Chip tint={note.tint} outlined>traveler-pref</Chip>
            <Chip tint={note.tint} outlined>fatigue</Chip>
            <Chip tint={note.tint} outlined>recurring</Chip>
          </div>
          <p className="mt-3 text-[10px] uppercase tracking-[0.2em] text-ink/50">Author</p>
          <p className="text-[12px] text-ink/85">Sarah · advisor</p>
          <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">Mar 12, 2026 · 11:30</p>
        </div>
      </div>
    </CardShell>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.18em] text-ink/50">{label}</p>
      <p className="text-ink/85">{value}</p>
    </div>
  );
}
