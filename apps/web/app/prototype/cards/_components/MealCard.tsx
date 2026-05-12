"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "./CardShell";
import { TYPE_TOKENS, type StatusKind } from "../_lib/tokens";

const t = TYPE_TOKENS.meal;

export function MealGlance({ status = "booked" }: { status?: StatusKind }) {
  return (
    <CardShell kind="meal" status={status} width="glance">
      <Title>Sushi Saito</Title>
      <Sub>Roppongi · 19:30 seating · omakase</Sub>
      <div className="mt-2 flex items-center gap-2 text-[11px] text-ink/75">
        <span aria-hidden>☾</span>
        <span>Dinner · 2 hr</span>
        <span className="text-ink/30">·</span>
        <span>¥¥¥¥</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={t.tint}>Pescatarian on file</Chip>
        <Chip tint={t.tint}>Smart casual</Chip>
      </div>
    </CardShell>
  );
}

export function MealCompact({
  status = "booked",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="meal" status={status} width="compact">
      <CompactBody
        kind="meal"
        title="Sushi Saito"
        time="19:30"
        duration="2h"
      />
    </CardShell>
  );
}

export function MealZoom() {
  return (
    <CardShell kind="meal" status="confirmed" width="zoom">
      <div className="grid grid-cols-[200px_1fr] gap-5">
        <DishStub />
        <div>
          <Title className="text-[22px]">Sushi Saito</Title>
          <p className="text-[12px] text-ink/65">Roppongi · 3 Michelin · counter-only · omakase</p>

          <p className="mt-3 text-[12px] leading-relaxed text-ink/85">
            Saito-san hand-cuts each piece in front of you across ~22 nigiri.
            The pace is brisk; eat each piece within 30 seconds of being placed.
            Conversation is welcome but quiet — the room is small.
          </p>

          <div className="mt-4 grid grid-cols-2 gap-3 text-[12px] text-ink/80">
            <Detail label="Seating" value="Wed 29 Apr · 19:30 · 2 hr" />
            <Detail label="Counter" value="Seats 5 & 6 · center" />
            <Detail label="Reservation" value="SAITO-2904-AC" />
            <Detail label="Cancellation" value="48 hr · charged in full" />
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-3 gap-3">
        <Etiquette label="Eat with hands" body="Nigiri is finger food here." />
        <Etiquette label="No fragrance" body="Affects nose-up tastings." />
        <Etiquette label="Phone away" body="Photos discouraged at counter." />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="rounded border border-ink/10 bg-paper/60 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Diet on file</span>
          <ul className="mt-2 space-y-0.5 text-[11px] text-ink/85">
            <li>· Pescatarian — no land meat</li>
            <li>· Tree-nut allergy — verified</li>
            <li>· Sake by master — junmai daiginjō flight</li>
          </ul>
        </div>
        <div className="rounded border border-ink/10 bg-paper/60 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Pre-meal phrases</span>
          <ul className="mt-2 space-y-0.5 text-[11px] text-ink/85">
            <li>· いただきます — itadakimasu (begin)</li>
            <li>· お任せします — omakase shimasu (your choice)</li>
            <li>· ごちそうさま — gochisōsama (after)</li>
          </ul>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        <Chip tint={t.tint}>Smart casual · no shorts</Chip>
        <Chip tint={t.tint}>Cash + AmEx</Chip>
        <Chip tint={t.tint}>Adults only · 12+</Chip>
        <Chip tint={t.tint}>Allergen flag: shellfish, soy</Chip>
      </div>
    </CardShell>
  );
}

function Etiquette({ label, body }: { label: string; body: string }) {
  return (
    <div className="rounded border border-ink/10 bg-paper px-3 py-2">
      <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">{label}</p>
      <p className="mt-1 text-[11px] text-ink/80">{body}</p>
    </div>
  );
}

function DishStub() {
  return (
    <div
      className="h-44 w-full overflow-hidden rounded-md border border-ink/10"
      role="img"
      aria-label="Signature dish photo placeholder"
      style={{
        backgroundImage:
          "radial-gradient(circle at 35% 40%, #c2603e 0%, #8a3a2a 40%, #4a1c14 100%)",
      }}
    />
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
