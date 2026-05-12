"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "./CardShell";
import { TYPE_TOKENS, type StatusKind } from "../_lib/tokens";

const t = TYPE_TOKENS.flight;

export function FlightGlance({
  from = "DTW",
  to = "HND",
  code = "DL 275",
  duration = "13h 15m",
  status = "approved",
}: {
  from?: string;
  to?: string;
  code?: string;
  duration?: string;
  status?: StatusKind;
}) {
  return (
    <CardShell kind="flight" status={status} width="glance">
      <Title>
        {from} → {to}
      </Title>
      <div className="mt-2 flex items-center gap-2 font-mono text-[13px] tracking-widest text-ink/85">
        <span>{from}</span>
        <FlightArc accent={t.accent} />
        <span>{to}</span>
      </div>
      <div className="mt-1 flex items-center justify-between">
        <Sub>{code}</Sub>
        <span className="text-[11px] text-ink/60">{duration}</span>
      </div>
    </CardShell>
  );
}

export function FlightCompact({
  from = "DTW",
  to = "HND",
  duration = "13h 15m",
  status = "approved",
}: {
  from?: string;
  to?: string;
  duration?: string;
  status?: StatusKind;
}) {
  return (
    <CardShell kind="flight" status={status} width="compact">
      <CompactBody
        kind="flight"
        title={`${from} → ${to}`}
        duration={duration}
      />
    </CardShell>
  );
}

export function FlightZoom() {
  return (
    <CardShell kind="flight" status="confirmed" width="zoom">
      <Title className="text-[22px]">DTW → HND</Title>
      <p className="text-[12px] text-ink/65">Detroit · Tokyo Haneda · Delta One</p>

      <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-4">
        <Endpoint code="DTW" city="Detroit" zone="EDT" time="15:25" date="Tue Apr 28" />
        <FlightArcLarge accent={t.accent} duration="13h 15m" miles="6,341 mi" />
        <Endpoint code="HND" city="Tokyo" zone="JST" time="18:40+1" date="Wed Apr 29" align="right" />
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4 text-[12px] text-ink/80">
        <Detail label="Cabin" value="Delta One Suite · 5A" />
        <Detail label="Aircraft" value="Airbus A350-900" />
        <Detail label="Terminal · Gate" value="DTW · A · A38" />
        <Detail label="Time-zone delta" value="+13h" />
        <Detail label="Lounge" value="Sky Club · A38, near gate" />
        <Detail label="Wi-Fi" value="Free messaging · paid streaming" />
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        <Chip tint={t.tint}>Priority bag tag</Chip>
        <Chip tint={t.tint}>Sleep window 3h post-takeoff</Chip>
        <Chip tint={t.tint}>Right side · sunset over Aleutians</Chip>
      </div>

      <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3 text-[11px] leading-relaxed text-ink/75">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Jet-lag protocol</span>
        <p className="mt-1">
          Switch your watch to Tokyo time at boarding. Sleep block timed to local Tokyo
          night; light meal on wake. Day-of-arrival walk near hotel before first dinner.
        </p>
      </div>
    </CardShell>
  );
}

function Endpoint({
  code,
  city,
  zone,
  time,
  date,
  align = "left",
}: {
  code: string;
  city: string;
  zone: string;
  time: string;
  date: string;
  align?: "left" | "right";
}) {
  const a = align === "right" ? "text-right" : "text-left";
  return (
    <div className={a}>
      <p className="font-mono text-[24px] tracking-widest text-ink">{code}</p>
      <p className="text-[11px] text-ink/65">{city}</p>
      <p className="mt-2 font-mono text-[15px] text-ink/85">{time}</p>
      <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">{date} · {zone}</p>
    </div>
  );
}

function FlightArc({ accent }: { accent: string }) {
  return (
    <svg width="56" height="14" viewBox="0 0 56 14" aria-hidden>
      <path
        d="M 2 9 C 14 -2, 30 18, 54 9"
        stroke={accent}
        strokeWidth="1"
        fill="none"
        strokeDasharray="2 2"
        opacity="0.7"
      />
      <circle cx="2" cy="9" r="1.5" fill={accent} />
      <circle cx="54" cy="9" r="1.5" fill={accent} />
    </svg>
  );
}

function FlightArcLarge({
  accent,
  duration,
  miles,
}: {
  accent: string;
  duration: string;
  miles: string;
}) {
  return (
    <div className="flex flex-col items-center">
      <svg width="180" height="56" viewBox="0 0 180 56" aria-hidden>
        <path
          d="M 6 40 C 50 -10, 130 -10, 174 40"
          stroke={accent}
          strokeWidth="1.2"
          fill="none"
          strokeDasharray="3 3"
        />
        <circle cx="6" cy="40" r="3" fill={accent} />
        <circle cx="174" cy="40" r="3" fill={accent} />
        <text x="90" y="14" textAnchor="middle" className="fill-ink/55" fontSize="9" fontFamily="ui-monospace">
          ✈
        </text>
      </svg>
      <p className="font-mono text-[12px] tracking-wide text-ink/75">{duration}</p>
      <p className="text-[10px] uppercase tracking-[0.18em] text-ink/50">{miles}</p>
    </div>
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
