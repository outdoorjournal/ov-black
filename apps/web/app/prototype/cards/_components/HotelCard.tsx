"use client";

import { CardShell, Chip, CompactBody, Sub, Title } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import { TYPE_TOKENS, type StatusKind } from "@/app/_components/itinerary-graph/shared/cards/tokens";

const t = TYPE_TOKENS.hotel;

export function HotelGlance({ status = "booked" }: { status?: StatusKind }) {
  return (
    <CardShell kind="hotel" status={status} width="glance">
      <div className="mt-1.5 flex gap-3">
        <ImageStub label="Aman" />
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-[16px] leading-snug text-ink truncate">
            Aman Tokyo
          </h3>
          <Sub>Ōtemachi · Imperial Palace view</Sub>
          <p className="mt-1 text-[11px] text-ink/75">3 nights · ¥¥¥¥</p>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <Chip tint={t.tint}>King · Suite</Chip>
        <Chip tint={t.tint}>14:00 → 12:00</Chip>
      </div>
    </CardShell>
  );
}

export function HotelCompact({
  status = "booked",
}: {
  status?: StatusKind;
}) {
  return (
    <CardShell kind="hotel" status={status} width="compact">
      <CompactBody kind="hotel" title="Aman Tokyo" duration="3 nights" />
    </CardShell>
  );
}

export function HotelZoom() {
  return (
    <CardShell kind="hotel" status="confirmed" width="zoom">
      <div className="grid grid-cols-[200px_1fr] gap-5">
        <ImageStub label="Aman Tokyo" tall />
        <div>
          <Title className="text-[22px]">Aman Tokyo</Title>
          <p className="text-[12px] text-ink/65">Ōtemachi · 33rd–38th floor of the Ōtemachi Tower</p>

          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip tint={t.tint}>Deluxe Suite · 71㎡</Chip>
            <Chip tint={t.tint}>Imperial Palace view</Chip>
            <Chip tint={t.tint}>Onsen access</Chip>
            <Chip tint={t.tint}>Private dining</Chip>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 text-[12px] text-ink/80">
            <Detail label="Check-in" value="Wed 29 Apr · 14:00" />
            <Detail label="Check-out" value="Sat 02 May · 12:00" />
            <Detail label="Confirmation" value="AMAN-TYO-3349812" />
            <Detail label="Bedding" value="King · turn-down 21:00" />
          </div>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4">
        <div className="rounded border border-ink/10 bg-paper/60 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">From your door</span>
          <ul className="mt-2 space-y-1 text-[11px] text-ink/80">
            <Walking to="Ōtemachi station" mins={2} mode="indoor" />
            <Walking to="Imperial Palace East Gardens" mins={9} />
            <Walking to="Tsukiji" mins={18} />
            <Walking to="Ginza" mins={22} />
          </ul>
        </div>
        <div className="rounded border border-ink/10 bg-paper/60 p-3">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Neighborhood</span>
          <p className="mt-1.5 text-[11px] leading-relaxed text-ink/80">
            Quiet financial district at night; ideal for jet-lagged first stay.
            Sunday morning the Palace runs are unmissable. Dinner reservations
            outside Ōtemachi recommended; in-house Musashi for sushi if staying in.
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5">
        <Chip tint={t.tint}>Quiet floor requested</Chip>
        <Chip tint={t.tint}>Vegetarian breakfast on file</Chip>
        <Chip tint={t.tint}>Late check-out 14:00 (held)</Chip>
      </div>
    </CardShell>
  );
}

function Walking({ to, mins, mode }: { to: string; mins: number; mode?: string }) {
  return (
    <li className="flex items-center justify-between gap-2">
      <span className="text-ink/85">{to}</span>
      <span className="font-mono text-[10px] text-ink/55">
        {mins} min{mode ? ` · ${mode}` : ""}
      </span>
    </li>
  );
}

function ImageStub({ label, tall = false }: { label: string; tall?: boolean }) {
  return (
    <div
      className={`relative shrink-0 overflow-hidden rounded-md border border-ink/10 ${
        tall ? "h-44 w-full" : "h-14 w-14"
      }`}
      aria-label={`${label} photo placeholder`}
      role="img"
      style={{
        backgroundImage:
          "linear-gradient(135deg, #5e6e5d 0%, #8aa088 40%, #c8c1a4 100%)",
      }}
    >
      <span className="absolute bottom-1 right-1.5 text-[8px] uppercase tracking-[0.18em] text-paper/85">
        photo
      </span>
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
