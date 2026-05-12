"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "./CardShell";
import { TYPE_TOKENS, type StatusKind } from "../_lib/tokens";

const t = TYPE_TOKENS.experience;

export function ExperienceGlance({ status = "proposed" }: { status?: StatusKind }) {
  return (
    <CardShell kind="experience" status={status} width="glance">
      <ImageStub />
      <Title>Tea ceremony · Urasenke</Title>
      <Sub>Kyoto · 90 min · indoor</Sub>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={t.tint}>Reflective</Chip>
        <Chip tint={t.tint}>Low effort</Chip>
        <Chip tint={t.tint}>Translator on hand</Chip>
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] text-ink/70">
        <EnergyMeter level={1} />
        <span>Best 14:00–16:00</span>
      </div>
    </CardShell>
  );
}

export function ExperienceCompact({
  status = "proposed",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="experience" status={status} width="compact">
      <CompactBody
        kind="experience"
        title="Tea ceremony · Urasenke"
        time="14:00"
        duration="90m"
      />
    </CardShell>
  );
}

export function ExperienceZoom() {
  return (
    <CardShell kind="experience" status="approved" width="zoom">
      <ImageStub tall />
      <Title className="text-[22px]">Private tea ceremony · Urasenke</Title>
      <p className="text-[12px] text-ink/65">Kyoto · Konnichian sub-temple · 90 minutes · indoor</p>

      <p className="mt-3 text-[12px] leading-relaxed text-ink/85">
        A 16th-generation Urasenke master receives you in a tatami room beside the
        original Konnichi-an. You will sit in seiza or seiza-stand for ~25 minutes;
        the host will read your party and pace accordingly. A short kaiseki bite
        precedes the matcha. Photography during the dōguzuke is welcomed; not
        during otemae.
      </p>

      <div className="mt-4 grid grid-cols-2 gap-4 text-[12px] text-ink/80">
        <Detail label="Difficulty" value="Easy · seated" />
        <Detail label="Energy after" value="Restorative" />
        <Detail label="Group size" value="Up to 6 · private" />
        <Detail label="Language" value="JA + live EN whisper" />
      </div>

      <div className="mt-5 grid grid-cols-3 gap-3">
        <Bring label="Socks (clean)" />
        <Bring label="Camera (silent shutter)" />
        <Bring label="No strong scent" />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="rounded border border-ink/10 bg-paper/60 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Best window</span>
          <DayWindow start={14} end={16} accent={t.accent} />
          <p className="mt-1 text-[11px] text-ink/65">Avoid right after a heavy lunch.</p>
        </div>
        <div className="rounded border border-ink/10 bg-paper/60 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">If it rains</span>
          <p className="mt-1 text-[11px] text-ink/80">
            Indoor experience — no change. Path to the entrance is covered.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        <Chip tint={t.tint}>Reflective</Chip>
        <Chip tint={t.tint}>Cultural · 16th gen master</Chip>
        <Chip tint={t.tint}>Quiet — phones off</Chip>
        <Chip tint={t.tint}>Allergen note: matcha, wagashi (sesame)</Chip>
      </div>
    </CardShell>
  );
}

function EnergyMeter({ level }: { level: 1 | 2 | 3 | 4 | 5 }) {
  const cells = [1, 2, 3, 4, 5];
  return (
    <span
      className="inline-flex items-center gap-1"
      role="img"
      aria-label={`Energy required: ${level} of 5`}
    >
      <span className="text-[10px] uppercase tracking-[0.18em] text-ink/55">Energy</span>
      <span className="inline-flex gap-0.5">
        {cells.map((c) => (
          <span
            key={c}
            className="block h-2 w-2 rounded-sm"
            style={{
              backgroundColor: c <= level ? t.accent : "rgba(10,10,10,0.12)",
            }}
          />
        ))}
      </span>
    </span>
  );
}

function DayWindow({ start, end, accent }: { start: number; end: number; accent: string }) {
  const HOURS = 24;
  return (
    <svg width="100%" height="22" viewBox="0 0 240 22" preserveAspectRatio="none" aria-hidden>
      <line x1="0" y1="11" x2="240" y2="11" stroke="#0a0a0a" strokeOpacity="0.12" />
      {Array.from({ length: HOURS + 1 }).map((_, i) => {
        const x = (i / HOURS) * 240;
        return (
          <line
            key={i}
            x1={x}
            y1={i % 6 === 0 ? 5 : 8}
            x2={x}
            y2={i % 6 === 0 ? 17 : 14}
            stroke="#0a0a0a"
            strokeOpacity={i % 6 === 0 ? 0.4 : 0.16}
          />
        );
      })}
      <rect
        x={(start / HOURS) * 240}
        y={6}
        width={((end - start) / HOURS) * 240}
        height={10}
        fill={accent}
        opacity={0.85}
      />
    </svg>
  );
}

function Bring({ label }: { label: string }) {
  return (
    <div className="rounded border border-ink/10 bg-paper px-2 py-1.5 text-[11px] text-ink/85">
      🤲 {label}
    </div>
  );
}

function ImageStub({ tall = false }: { tall?: boolean }) {
  return (
    <div
      className={`overflow-hidden rounded-md border border-ink/10 ${
        tall ? "mt-3 h-40 w-full" : "mt-2 h-16 w-full"
      }`}
      role="img"
      aria-label="Experience hero photo placeholder"
      style={{
        backgroundImage:
          "linear-gradient(135deg, #6a4318 0%, #b58a3a 45%, #ecddbb 100%)",
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
