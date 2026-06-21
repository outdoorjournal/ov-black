"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import { TYPE_TOKENS, type StatusKind } from "@/app/_components/itinerary-graph/shared/cards/tokens";

const drive = TYPE_TOKENS.drive;
const walk = TYPE_TOKENS.walk;

export function DriveGlance({ status = "booked" }: { status?: StatusKind }) {
  return (
    <CardShell kind="drive" status={status} width="glance">
      <Title>Haneda → Aman Tokyo</Title>
      <Sub>Private transfer · Lexus LM</Sub>
      <div className="mt-2 flex items-center gap-3">
        <div
          aria-hidden
          className="h-9 w-9 shrink-0 rounded-full border border-ink/15 bg-ink/5"
          style={{
            backgroundImage:
              "radial-gradient(circle at 50% 60%, rgba(0,0,0,0.18), transparent 70%)",
          }}
        />
        <div className="min-w-0 flex-1">
          <p className="text-[12px] text-ink/85 truncate">Hiroshi T. · 17 yrs</p>
          <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">EN · JA</p>
        </div>
        <span className="font-mono text-[11px] text-ink/65">42 min</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={drive.tint}>Plate 品川 330 · ぬ 12-34</Chip>
      </div>
    </CardShell>
  );
}

export function DriveCompact({
  status = "booked",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="drive" status={status} width="compact">
      <CompactBody
        kind="drive"
        title="Haneda → Aman"
        time="18:55"
        duration="42m"
      />
    </CardShell>
  );
}

export function WalkCompact({
  status = "approved",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="walk" status={status} width="compact">
      <CompactBody
        kind="walk"
        title="Aman → Ginza"
        time="10:30"
        duration="14m"
      />
    </CardShell>
  );
}

export function DriveZoom() {
  return (
    <CardShell kind="drive" status="confirmed" width="zoom">
      <div className="flex items-baseline justify-between">
        <Title className="text-[22px]">Haneda → Aman Tokyo</Title>
        <span className="font-mono text-[12px] text-ink/65">42 min · 18 km</span>
      </div>
      <p className="text-[12px] text-ink/65">Private transfer · Wed 29 Apr · 18:55 pickup</p>

      <div className="mt-4 grid grid-cols-[180px_1fr] gap-4">
        <div>
          <div
            aria-hidden
            className="h-32 w-full rounded border border-ink/10 bg-ink/5"
            style={{
              backgroundImage:
                "radial-gradient(circle at 50% 40%, rgba(0,0,0,0.22), transparent 70%)",
            }}
          />
          <p className="mt-2 text-[11px] text-ink/85">Hiroshi Tanaka</p>
          <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">17 yrs · EN · JA · DE</p>
          <a className="mt-1 inline-block text-[11px] underline text-ink/85" href="#">Call · +81 90-…</a>
        </div>

        <div>
          <RoutePreview accent={drive.accent} />
          <div className="mt-3 grid grid-cols-2 gap-3 text-[12px] text-ink/80">
            <Detail label="Vehicle" value="Lexus LM 350h · 4 seats" />
            <Detail label="Plate" value="品川 330 · ぬ 12-34" />
            <Detail label="Bag capacity" value="4 medium · 2 large" />
            <Detail label="Greet" value="Arrivals D · sign “Voyage”" />
          </div>
        </div>
      </div>

      <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3 text-[11px] leading-relaxed text-ink/75">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Route notes</span>
        <p className="mt-1">
          Bayshore Route → Inner Circle. Light traffic 19:00. Driver will detour past
          Tokyo Tower if you say the word; otherwise direct.
        </p>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Chip tint={drive.tint}>Child seat on request</Chip>
        <Chip tint={drive.tint}>Bottled water</Chip>
        <Chip tint={drive.tint}>Wi-Fi onboard</Chip>
      </div>
    </CardShell>
  );
}

export function WalkGlance({ status = "approved" }: { status?: StatusKind }) {
  return (
    <CardShell kind="walk" status={status} width="glance">
      <Title>To Sensō-ji</Title>
      <Sub>0.6 km · 8 min · flat</Sub>
      <div className="mt-2 h-12 w-full overflow-hidden rounded border border-ink/10">
        <svg width="100%" height="100%" viewBox="0 0 240 48" preserveAspectRatio="none" aria-hidden>
          <path
            d="M 6 36 C 40 36, 60 18, 100 22 S 180 14, 234 12"
            stroke={walk.accent}
            strokeWidth="2.5"
            fill="none"
            strokeLinecap="round"
          />
          <circle cx="6" cy="36" r="3" fill={walk.accent} />
          <circle cx="234" cy="12" r="3" fill={walk.accent} />
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={walk.tint}>Cobblestone last 100m</Chip>
      </div>
    </CardShell>
  );
}
function RoutePreview({ accent }: { accent: string }) {
  return (
    <svg
      width="100%"
      height="120"
      viewBox="0 0 380 120"
      preserveAspectRatio="none"
      role="img"
      aria-label="Route preview from Haneda to Aman Tokyo"
      className="rounded border border-ink/10 bg-ink/[0.03]"
    >
      <line x1="0" y1="40" x2="380" y2="40" stroke="#0a0a0a" strokeOpacity="0.06" />
      <line x1="0" y1="80" x2="380" y2="80" stroke="#0a0a0a" strokeOpacity="0.06" />
      <line x1="120" y1="0" x2="120" y2="120" stroke="#0a0a0a" strokeOpacity="0.06" />
      <line x1="240" y1="0" x2="240" y2="120" stroke="#0a0a0a" strokeOpacity="0.06" />
      <path
        d="M 24 92 C 80 88, 110 70, 160 64 S 260 50, 356 26"
        stroke={accent}
        strokeWidth="2.5"
        fill="none"
        strokeLinecap="round"
      />
      <circle cx="24" cy="92" r="4" fill={accent} />
      <text x="32" y="100" fontSize="10" className="fill-ink/75">HND</text>
      <circle cx="356" cy="26" r="4" fill={accent} />
      <text x="350" y="20" textAnchor="end" fontSize="10" className="fill-ink/75">Aman Tokyo</text>
      <text x="190" y="12" textAnchor="middle" fontSize="9" className="fill-ink/55">Bayshore Route → Inner Circle</text>
    </svg>
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
