"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import { TYPE_TOKENS, type StatusKind } from "@/app/_components/itinerary-graph/shared/cards/tokens";

const t = TYPE_TOKENS.train;

interface Stop {
  name: string;
  arr?: string;
  dep?: string;
  kind?: "origin" | "stop" | "destination";
  scenic?: string;
}

const KODAMA_716: Stop[] = [
  { name: "Shin-Ōsaka", dep: "09:54", kind: "origin" },
  { name: "Kyōto", arr: "10:08", dep: "10:09" },
  { name: "Maibara", arr: "10:35", dep: "10:36", scenic: "Lake Biwa · west window" },
  { name: "Nagoya", arr: "11:19", dep: "11:21" },
  { name: "Hamamatsu", arr: "12:11", dep: "12:12", scenic: "Eel-bento window" },
  { name: "Shizuoka", arr: "12:46", dep: "12:47", scenic: "Mt. Fuji · north window from 12:55" },
  { name: "Atami", arr: "13:21", kind: "destination" },
];

export function TrainGlance({ status = "approved" }: { status?: StatusKind }) {
  return (
    <CardShell kind="train" status={status} width="glance">
      <Title>Shin-Ōsaka → Atami</Title>
      <Sub>Shinkansen Kodama 716 · Hikari/Sakura class skipped</Sub>
      <div className="mt-2 flex items-center justify-between font-mono text-[12px] text-ink/85">
        <span>09:54</span>
        <svg width="60" height="6" viewBox="0 0 60 6" aria-hidden>
          <line x1="2" y1="3" x2="58" y2="3" stroke={t.accent} strokeWidth="1.5" />
          <polygon points="56,1 60,3 56,5" fill={t.accent} />
        </svg>
        <span>13:21</span>
      </div>
      <div className="mt-1 flex items-center justify-between text-[11px] text-ink/65">
        <span>3h 27m · 6 stops</span>
        <span>Car 5 · 12A/B</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={t.tint}>JR Pass · OK</Chip>
        <Chip tint={t.tint}>Reserved</Chip>
      </div>
    </CardShell>
  );
}

export function TrainCompact({
  status = "approved",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="train" status={status} width="compact">
      <CompactBody
        kind="train"
        title="Shin-Ōsaka → Atami"
        time="09:54"
        duration="3h 27m"
      />
    </CardShell>
  );
}

export function TrainZoom() {
  return (
    <CardShell kind="train" status="approved" width="zoom">
      <div className="flex items-baseline justify-between">
        <Title className="text-[22px]">Shin-Ōsaka → Atami</Title>
        <span className="font-mono text-[12px] text-ink/65">3h 27m · 511 km</span>
      </div>
      <p className="text-[12px] text-ink/65">Shinkansen Kodama 716 · Tōkaidō line · Wed 14 May</p>

      <div className="mt-5">
        <StopSequence stops={KODAMA_716} accent={t.accent} />
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4 text-[12px] text-ink/80">
        <Detail label="Platform · Car · Seat" value="Shin-Ōsaka 21 · Car 5 · 12A/B" />
        <Detail label="Reservation" value="Reserved · paired window" />
        <Detail label="JR Pass" value="Eligible (Kodama only)" />
        <Detail label="Power" value="Outlet at every window seat" />
      </div>

      <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3 text-[11px] leading-relaxed text-ink/75">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Window briefing</span>
        <ul className="mt-1.5 space-y-0.5">
          <li>· 10:35 — Lake Biwa, west window</li>
          <li>· 12:55 — Mt. Fuji visible north for ~6 min if clear (40% Apr–May)</li>
          <li>· Bento window pre-departure: Ekiben at Shin-Ōsaka platform 21, lower concourse</li>
        </ul>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Chip tint={t.tint}>Quiet car</Chip>
        <Chip tint={t.tint}>Bento permitted</Chip>
        <Chip tint={t.tint}>Suitcase rack at car-end</Chip>
      </div>
    </CardShell>
  );
}

function StopSequence({ stops, accent }: { stops: Stop[]; accent: string }) {
  const w = 600;
  const padX = 24;
  const innerW = w - padX * 2;
  const stepX = innerW / (stops.length - 1);
  const y = 36;

  return (
    <div className="overflow-x-auto">
      <svg width={w} height="120" viewBox={`0 0 ${w} 120`} role="img" aria-label="Stop sequence">
        <line x1={padX} y1={y} x2={w - padX} y2={y} stroke={accent} strokeWidth="2" />
        {stops.map((s, i) => {
          const cx = padX + i * stepX;
          const isEnd = s.kind === "origin" || s.kind === "destination";
          return (
            <g key={s.name}>
              <circle
                cx={cx}
                cy={y}
                r={isEnd ? 7 : 4}
                fill={isEnd ? accent : "#f7f4ee"}
                stroke={accent}
                strokeWidth="2"
              />
              <text
                x={cx}
                y={y - 12}
                textAnchor="middle"
                fontSize="9"
                fontFamily="ui-monospace, monospace"
                className="fill-ink/70"
              >
                {s.dep ?? s.arr}
              </text>
              <text
                x={cx}
                y={y + 22}
                textAnchor="middle"
                fontSize="10"
                fontFamily="ui-sans-serif, system-ui"
                className="fill-ink/85"
              >
                {s.name}
              </text>
              {s.scenic ? (
                <text
                  x={cx}
                  y={y + 38}
                  textAnchor="middle"
                  fontSize="8"
                  fontFamily="ui-sans-serif, system-ui"
                  className="fill-ink/50"
                >
                  ◐ {s.scenic.split(" · ")[0]}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
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
