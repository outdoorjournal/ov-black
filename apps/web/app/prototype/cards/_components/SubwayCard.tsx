"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import { METRO_LINE_COLORS, TYPE_TOKENS, type StatusKind } from "@/app/_components/itinerary-graph/shared/cards/tokens";

const t = TYPE_TOKENS.subway;

interface Station {
  name: string;
  code: string;
  transfer?: string;
}

const GINZA_LINE: Station[] = [
  { name: "Asakusa", code: "G19" },
  { name: "Tawaramachi", code: "G18" },
  { name: "Inarichō", code: "G17" },
  { name: "Ueno", code: "G16", transfer: "Hibiya" },
  { name: "Ueno-hirokōji", code: "G15", transfer: "Chiyoda" },
  { name: "Suehirochō", code: "G14" },
  { name: "Kanda", code: "G13" },
  { name: "Mitsukoshimae", code: "G12", transfer: "Hanzomon" },
  { name: "Nihombashi", code: "G11", transfer: "Tozai" },
  { name: "Kyōbashi", code: "G10" },
  { name: "Ginza", code: "G09", transfer: "Marunouchi" },
];

export function SubwayGlance({ status = "approved" }: { status?: StatusKind }) {
  return (
    <CardShell kind="subway" status={status} width="glance">
      <Title>Asakusa → Ginza</Title>
      <Sub>Tokyo Metro · Ginza Line</Sub>
      <div className="mt-2 flex items-center gap-2">
        <span
          aria-hidden
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: METRO_LINE_COLORS["Ginza"] }}
        />
        <span className="font-mono text-[11px] tracking-widest text-ink/80">G19 → G09</span>
        <span className="ml-auto text-[11px] text-ink/65">17 min · ¥210</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={t.tint}>10 stops</Chip>
        <Chip tint={t.tint}>1 transfer-free</Chip>
      </div>
    </CardShell>
  );
}

export function SubwayCompact({
  status = "approved",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="subway" status={status} width="compact">
      <CompactBody
        kind="subway"
        title="Asakusa → Ginza"
        time="14:05"
        duration="17m"
      />
    </CardShell>
  );
}

export function SubwayZoom() {
  return (
    <CardShell kind="subway" status="approved" width="zoom">
      <div className="flex items-baseline justify-between">
        <Title className="text-[22px]">Asakusa → Ginza</Title>
        <span className="font-mono text-[12px] text-ink/65">17 min · ¥210</span>
      </div>
      <p className="text-[12px] text-ink/65">Tokyo Metro · Ginza Line · weekday off-peak</p>

      <div className="mt-5">
        <LineDiagram
          stations={GINZA_LINE}
          color={METRO_LINE_COLORS["Ginza"] ?? "#f39700"}
          highlight={[0, 10]}
        />
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4 text-[12px] text-ink/80">
        <Detail label="Board at" value="Asakusa · Exit 1, platform 1" />
        <Detail label="Alight at" value="Ginza · Exit A2 (Mitsukoshi)" />
        <Detail label="IC card" value="Suica / Pasmo · ¥210" />
        <Detail label="Step-free" value="Elevator at Asakusa & Ginza" />
      </div>

      <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3 text-[11px] leading-relaxed text-ink/75">
        <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Look for</span>
        <div className="mt-2 grid grid-cols-3 gap-3 text-center">
          <Sign jp="銀座線" en="Ginza Line" color={METRO_LINE_COLORS["Ginza"] ?? "#f39700"} />
          <Sign jp="渋谷方面" en="Toward Shibuya" />
          <Sign jp="出口" en="Exit · 出 = exit" />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <Chip tint={t.tint}>Priority seats forward of car 3</Chip>
        <Chip tint={t.tint}>Quiet — no calls</Chip>
        <Chip tint={t.tint}>Women-only car (last) before 09:30</Chip>
      </div>
    </CardShell>
  );
}

function LineDiagram({
  stations,
  color,
  highlight,
}: {
  stations: Station[];
  color: string;
  highlight: [number, number];
}) {
  const [start, end] = highlight;
  const w = 580;
  const padX = 28;
  const innerW = w - padX * 2;
  const stepX = innerW / (stations.length - 1);
  const y = 40;

  return (
    <div className="overflow-x-auto">
      <svg width={w} height="120" viewBox={`0 0 ${w} 120`} role="img" aria-label="Ginza Line stations from Asakusa to Ginza">
        <line x1={padX} y1={y} x2={w - padX} y2={y} stroke="#0a0a0a" strokeOpacity="0.18" strokeWidth="3" />
        <line
          x1={padX + start * stepX}
          y1={y}
          x2={padX + end * stepX}
          y2={y}
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
        />
        {stations.map((s, i) => {
          const cx = padX + i * stepX;
          const isEndpoint = i === start || i === end;
          const onPath = i >= start && i <= end;
          return (
            <g key={s.code}>
              <circle
                cx={cx}
                cy={y}
                r={isEndpoint ? 7 : 4}
                fill={isEndpoint ? color : "#f7f4ee"}
                stroke={onPath ? color : "#0a0a0a"}
                strokeOpacity={onPath ? 1 : 0.35}
                strokeWidth={isEndpoint ? 2 : 1.5}
              />
              {s.transfer ? (
                <circle
                  cx={cx}
                  cy={y - 14}
                  r={3}
                  fill={(s.transfer && METRO_LINE_COLORS[s.transfer]) || "#888"}
                  aria-label={`Transfer to ${s.transfer} Line`}
                />
              ) : null}
              <text
                x={cx}
                y={y + 22}
                textAnchor="end"
                transform={`rotate(-45, ${cx}, ${y + 22})`}
                fontSize="9"
                fontFamily="ui-sans-serif, system-ui"
                className={onPath ? "fill-ink/85" : "fill-ink/45"}
              >
                {s.name}
              </text>
              <text
                x={cx}
                y={y - 22}
                textAnchor="middle"
                fontSize="8"
                fontFamily="ui-monospace, monospace"
                className="fill-ink/55"
              >
                {s.code}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Sign({ jp, en, color }: { jp: string; en: string; color?: string }) {
  return (
    <div className="rounded border border-ink/15 bg-paper px-2 py-1.5">
      <p
        className="font-serif text-[13px] leading-tight"
        style={{ color: color ?? "#0a0a0a" }}
      >
        {jp}
      </p>
      <p className="text-[9px] uppercase tracking-[0.16em] text-ink/55">{en}</p>
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
