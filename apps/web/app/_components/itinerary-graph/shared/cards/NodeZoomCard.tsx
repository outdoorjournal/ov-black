"use client";

// Rich "zoom" detail card — the expanded view shown when a traveler or advisor
// clicks a node on the timeline. Where NodeCard renders the 260px glance, this
// renders the 640px detail sheet from /prototype/cards: each type gets its
// signature layout (flight boarding pass + jet-lag protocol, train stop
// sequence + window briefing, subway line diagram in agency colours, hotel
// "from your door" walking list, meal etiquette + pre-meal phrases, experience
// energy meter + best-window). Every section is data-driven off the node's
// card-attrs metadata and only renders when the field is present, so partial
// itineraries still look composed.

import type { ReactNode } from "react";

import { formatDistance } from "@/app/_components/concierge/surfaces/RouteSurface";
import { SurfaceMap } from "@/app/_components/concierge/surfaces/SurfaceMap";
import { decodePolyline, type LngLat } from "@/lib/chat/polyline";

import { formatClock, formatDuration, offsetHoursOr } from "../../model/horizontalTime";
import type { NodeResponse } from "../../model/horizontalTypes";
import { placePhotoUrl } from "../../model/placePhoto";
import { inferCardKind } from "./CardBody";
import { CardShell, Chip, Sub, Title } from "./CardShell";
import {
  METRO_LINE_COLORS,
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "./tokens";

// ── Metadata shape (a permissive read-side view of card_attrs.py) ──────

interface Geo {
  lat?: number;
  lng?: number;
  label?: string;
}
interface Snapshot {
  title?: string;
  cover_image?: string;
  price?: string;
  location?: string;
  activities?: string[];
}
interface SceneryCallout {
  minute_offset?: number;
  side?: string;
  what?: string;
}
interface TrainStop {
  station?: string;
  arrives_at?: string;
  departs_at?: string;
}
interface SubwayLine {
  name?: string;
  agency_color?: string;
}
interface SubwayTransfer {
  station?: string;
  line_color?: string;
}
interface SignageGloss {
  native?: string;
  romanization?: string;
  traveler_lang?: string;
}
interface WalkingDistance {
  label?: string;
  minutes?: number;
  mode?: string;
}
interface Etiquette {
  label?: string;
  body?: string;
}
interface Phrase {
  native?: string;
  romanization?: string;
  gloss?: string;
}
interface Vehicle {
  make?: string;
  capacity?: number;
  plate?: string;
  plate_native_script?: string;
}
interface Driver {
  name?: string;
  languages?: string[];
  contact_link?: string;
}
interface Place {
  rating?: number;
  rating_count?: number;
  hours?: string[];
  website?: string;
  phone?: string;
  maps_url?: string;
  photo_token?: string;
}
interface GalleryImage {
  url?: string;
  caption?: string;
  credit?: string;
}
interface Operator {
  name?: string;
  logo_url?: string;
  profile_url?: string;
  vetted?: boolean;
}

interface ZoomMeta {
  description?: string;
  body?: string;
  ambient_image?: string;
  time_of_day?: string;
  location?: Geo;
  from_location?: Geo;
  to_location?: Geo;
  duration_minutes?: number;
  start_time?: string;
  snapshot?: Snapshot;
  // flight
  iata_from?: string;
  iata_to?: string;
  flight_code?: string;
  cabin?: string;
  seat?: string;
  terminal?: string;
  gate?: string;
  aircraft?: string;
  miles?: number;
  tz_delta_hours?: number;
  scenic_side?: string;
  lounge_proximity?: string;
  jet_lag_protocol?: string;
  wifi?: string;
  depart_at?: string;
  arrive_at?: string;
  // train / subway
  from_station?: string;
  to_station?: string;
  train_name?: string;
  train_number?: string;
  platform?: string;
  car?: string;
  pass_eligibility?: string;
  food_on_board?: string;
  stops?: TrainStop[];
  scenery_callouts?: SceneryCallout[];
  lines?: SubwayLine[];
  transfers?: SubwayTransfer[];
  signage_gloss?: SignageGloss[];
  fare_or_pass_note?: string;
  mode?: string;
  // drive / walk / boat
  eta_minutes?: number;
  vehicle?: Vehicle;
  driver?: Driver;
  bag_capacity?: number;
  distance_m?: number;
  distance_meters?: number;
  route_polyline?: string;
  surface_notes?: string[];
  pois_along?: Geo[];
  dock_from?: string;
  dock_to?: string;
  motion_sickness_rating?: string;
  bring_with?: string[];
  schedule_frequency?: string;
  // hotel
  name?: string;
  room_type?: string;
  stars?: number;
  nights?: number;
  check_in?: string;
  check_out?: string;
  confirmation_number?: string;
  bedding?: string;
  in_room_amenities?: string[];
  walking_to?: WalkingDistance[];
  profile_prefs_honored?: string[];
  neighborhood_blurb?: string;
  // experience + meal POI enrichment (Google Places)
  place?: Place;
  // experience
  category?: string;
  energy_required?: number;
  energy_after?: string;
  difficulty?: string;
  best_window?: { start_hour?: number; end_hour?: number };
  gear_list?: string[];
  weather_contingency?: string;
  allergens?: string[];
  language_support?: string;
  group_size?: string;
  gallery?: GalleryImage[];
  operator?: Operator;
  // meal
  cuisine_class?: string;
  seating_at?: string;
  dress_code?: string;
  dietary_flags?: string[];
  etiquette?: Etiquette[];
  pre_meal_phrases?: Phrase[];
  reservation_number?: string;
  cancellation_policy?: string;
  price?: string;
  // free_time
  weather?: string;
  energy_advice?: string;
  suggestion_grid?: string[];
  // waiting
  lounge_info?: string;
  use_this_time_to?: string[];
  facilities?: string[];
  // note
  author_name?: string;
  author_role?: string;
  visibility?: string;
  tags?: string[];
}

function statusToKind(status: NodeResponse["status"]): StatusKind {
  switch (status) {
    case "pending":
    case "approved":
    case "booked":
    case "confirmed":
    case "discarded":
      return status;
    default:
      return "pending";
  }
}

// ── Public component ───────────────────────────────────────────────────

/** Where this zoom card is rendered. The full-detail `"modal"` (default) shows
 *  everything; the `"rail"` LARGE form on the journal spine is a preview into
 *  that modal, so it trades secondary richness (the moments gallery) for a
 *  cleaner read — the gallery is one tap away in the modal it opens. */
export type ZoomVariant = "modal" | "rail";

export function NodeZoomCard({
  node,
  tzOffsetHours,
  variant = "modal",
}: {
  node: NodeResponse;
  tzOffsetHours: number;
  variant?: ZoomVariant;
}) {
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);
  const m = (node.metadata ?? {}) as ZoomMeta;

  // The booked/confirmed footer band carries the operator's reference + a
  // short date stamp; pull the most relevant ones per type.
  const serial =
    m.confirmation_number ?? m.reservation_number ?? m.flight_code ?? undefined;
  const stampIso = m.depart_at ?? m.seating_at ?? m.check_in ?? m.start_time;
  const statusDate = stampIso
    ? formatDayStamp(stampIso, offsetHoursOr(stampIso, tzOffsetHours))
    : undefined;

  return (
    <CardShell
      kind={kind}
      status={status}
      width="zoom"
      lockReason={node.lock_reason ?? null}
      lockLabel={node.type}
      {...(serial ? { serial } : {})}
      {...(statusDate ? { statusDate } : {})}
    >
      <ZoomBody node={node} kind={kind} meta={m} tz={tzOffsetHours} variant={variant} />
    </CardShell>
  );
}

function ZoomBody({
  node,
  kind,
  meta,
  tz,
  variant,
}: {
  node: NodeResponse;
  kind: CardKind;
  meta: ZoomMeta;
  tz: number;
  variant: ZoomVariant;
}) {
  switch (kind) {
    case "flight":
      return <FlightZoom node={node} m={meta} tz={tz} />;
    case "train":
      return <TrainZoom node={node} m={meta} tz={tz} />;
    case "subway":
      return <SubwayZoom node={node} m={meta} />;
    case "drive":
      return <DriveZoom node={node} m={meta} />;
    case "walk":
      return <WalkZoom node={node} m={meta} />;
    case "boat":
      return <BoatZoom node={node} m={meta} />;
    case "hotel":
      return <HotelZoom node={node} m={meta} tz={tz} />;
    case "experience":
    case "destination":
      return <ExperienceZoom node={node} m={meta} variant={variant} />;
    case "meal":
      return <MealZoom node={node} m={meta} tz={tz} />;
    case "free_time":
      return <FreeTimeZoom node={node} m={meta} tz={tz} />;
    case "waiting":
      return <WaitingZoom node={node} m={meta} />;
    case "note":
      return <NoteZoom node={node} m={meta} />;
    default:
      return <GenericZoom node={node} m={meta} />;
  }
}

// ── Per-type bodies ────────────────────────────────────────────────────

function FlightZoom({ node, m, tz }: { node: NodeResponse; m: ZoomMeta; tz: number }) {
  const t = TYPE_TOKENS.flight;
  const depart = m.depart_at ? formatClock(m.depart_at, offsetHoursOr(m.depart_at, tz)) : null;
  const arrive = m.arrive_at ? formatClock(m.arrive_at, offsetHoursOr(m.arrive_at, tz)) : null;
  const departDate = m.depart_at ? formatDayStamp(m.depart_at, offsetHoursOr(m.depart_at, tz)) : null;
  const arriveDate = m.arrive_at ? formatDayStamp(m.arrive_at, offsetHoursOr(m.arrive_at, tz)) : null;
  // Only flag the arrival date when it lands on a different calendar day (red-eye / date-line crossings).
  const arriveDateShown = arriveDate && arriveDate !== departDate ? arriveDate : null;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  return (
    <>
      <Title>{node.title}</Title>
      {m.cabin || m.aircraft ? (
        <p className="text-[12px] text-ink/65">
          {[cityOnly(m.from_location?.label), cityOnly(m.to_location?.label), prettify(m.cabin)]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : null}

      <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-4">
        <Endpoint code={m.iata_from} city={cityOnly(m.from_location?.label)} time={depart} date={departDate} />
        <FlightArcLarge accent={t.accent} duration={dur} miles={m.miles ? `${m.miles.toLocaleString()} mi` : null} />
        <Endpoint code={m.iata_to} city={cityOnly(m.to_location?.label)} time={arrive} date={arriveDateShown} align="right" />
      </div>

      <DetailGrid
        rows={[
          ["Cabin · seat", joinDot([prettify(m.cabin), m.seat])],
          ["Aircraft", m.aircraft],
          ["Terminal · gate", joinDot([m.terminal, m.gate])],
          ["Time-zone delta", typeof m.tz_delta_hours === "number" ? `${m.tz_delta_hours > 0 ? "+" : ""}${m.tz_delta_hours}h` : null],
          ["Lounge", m.lounge_proximity],
          ["Wi-Fi", m.wifi],
        ]}
      />

      <ChipRow
        tint={t.tint}
        chips={[m.scenic_side ? `Scenic ${m.scenic_side} side` : null]}
      />

      {m.jet_lag_protocol ? (
        <NoteBox label="Jet-lag protocol">{m.jet_lag_protocol}</NoteBox>
      ) : null}
      {m.description ? <NoteBox label="Notes">{m.description}</NoteBox> : null}
    </>
  );
}

function TrainZoom({ node, m, tz }: { node: NodeResponse; m: ZoomMeta; tz: number }) {
  const t = TYPE_TOKENS.train;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  const stops = (m.stops ?? []).filter((s) => s.station);
  const callouts = (m.scenery_callouts ?? []).filter((c) => c.what);
  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <Title>{node.title}</Title>
        {dur ? <span className="font-mono text-[12px] text-ink/65">{dur}</span> : null}
      </div>
      <p className="text-[12px] text-ink/65">
        {joinDot([m.train_name && m.train_number ? `${m.train_name} ${m.train_number}` : m.train_name, m.mode])}
      </p>

      {stops.length > 1 ? (
        <div className="mt-5">
          <StopSequence stops={stops} accent={t.accent} tz={tz} />
        </div>
      ) : null}

      <DetailGrid
        rows={[
          ["Platform · car · seat", joinDot([m.platform, m.car && `Car ${m.car}`, m.seat])],
          ["Pass", m.pass_eligibility],
          ["On board", m.food_on_board],
        ]}
      />

      {callouts.length > 0 ? (
        <NoteBox label="Window briefing">
          <ul className="space-y-0.5">
            {callouts.map((c, i) => (
              <li key={i}>
                · {c.what}
                {c.side ? ` — ${c.side} window` : ""}
                {typeof c.minute_offset === "number" ? ` (~min ${c.minute_offset})` : ""}
              </li>
            ))}
          </ul>
        </NoteBox>
      ) : null}

      <ChipRow tint={t.tint} chips={[m.mode]} />
    </>
  );
}

function SubwayZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  const t = TYPE_TOKENS.subway;
  const lines = (m.lines ?? []).filter((l) => l.name);
  const signage = (m.signage_gloss ?? []).filter((s) => s.native);
  return (
    <>
      <Title>{node.title}</Title>
      <p className="text-[12px] text-ink/65">{joinDot([m.mode, m.fare_or_pass_note])}</p>

      {lines.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {lines.map((l, i) => (
            <span key={i} className="inline-flex items-center gap-1.5 text-[12px] text-ink/85">
              <span
                aria-hidden
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: l.agency_color ?? "#888" }}
              />
              {l.name}
            </span>
          ))}
        </div>
      ) : null}

      {(m.transfers ?? []).length > 0 ? (
        <p className="mt-2 text-[11px] text-ink/65">
          Transfer at {(m.transfers ?? []).map((x) => x.station).filter(Boolean).join(", ")}
        </p>
      ) : null}

      <DetailGrid
        rows={[
          ["Board at", m.from_station],
          ["Alight at", m.to_station],
          ["Fare", m.fare_or_pass_note],
        ]}
      />

      {signage.length > 0 ? (
        <NoteBox label="Look for">
          <div className="mt-1 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {signage.map((s, i) => (
              <div key={i} className="rounded border border-ink/15 bg-paper px-2 py-1.5">
                <p className="font-serif text-[14px] leading-tight text-ink">{s.native}</p>
                {s.traveler_lang ? (
                  <p className="text-[9px] uppercase tracking-[0.16em] text-ink/55">
                    {s.traveler_lang}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </NoteBox>
      ) : null}

      <ChipRow tint={t.tint} chips={[m.mode]} />
    </>
  );
}

// Decode a drive card's stored route into Mapbox-ready geometry: the polyline
// as the drawn line, and the from/to GeoPoints as endpoint markers (falling
// back to the polyline's own ends when a card predates stored coordinates).
function driveRouteGeometry(m: ZoomMeta): { line: LngLat[]; markers: LngLat[] } {
  const line = m.route_polyline ? decodePolyline(m.route_polyline) : [];
  const markers: LngLat[] = [];
  const from = m.from_location;
  const to = m.to_location;
  if (from?.lng !== undefined && from.lat !== undefined) markers.push([from.lng, from.lat]);
  if (to?.lng !== undefined && to.lat !== undefined) markers.push([to.lng, to.lat]);
  if (markers.length === 0 && line.length > 1) {
    const first = line[0];
    const last = line[line.length - 1];
    if (first) markers.push(first);
    if (last) markers.push(last);
  }
  return { line, markers };
}

function DriveZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  const t = TYPE_TOKENS.drive;
  const eta = m.eta_minutes ?? m.duration_minutes;
  const meters = m.distance_meters ?? m.distance_m;
  const facts = joinDot([
    typeof eta === "number" ? formatDuration(eta) : null,
    typeof meters === "number" && meters > 0 ? formatDistance(meters) : null,
  ]);
  const { line, markers } = driveRouteGeometry(m);
  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <Title>{node.title}</Title>
        {facts ? <span className="font-mono text-[12px] text-ink/65">{facts}</span> : null}
      </div>
      <p className="text-[12px] text-ink/65">{joinDot([m.vehicle?.make, "Private transfer"])}</p>

      {line.length > 1 || markers.length > 0 ? (
        <SurfaceMap
          markers={markers}
          {...(line.length > 1 ? { line } : {})}
          className="mt-3 h-44 rounded border border-ink/10"
        />
      ) : null}

      {m.driver?.name ? (
        <div className="mt-3 flex items-center gap-3">
          <span
            aria-hidden
            className="h-10 w-10 shrink-0 rounded-full border border-ink/15 bg-ink/5"
            style={{ backgroundImage: "radial-gradient(circle at 50% 60%, rgba(0,0,0,0.18), transparent 70%)" }}
          />
          <div className="min-w-0">
            <p className="text-[13px] text-ink/90">{m.driver.name}</p>
            {(m.driver.languages ?? []).length > 0 ? (
              <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">
                {(m.driver.languages ?? []).join(" · ")}
              </p>
            ) : null}
          </div>
          {m.driver.contact_link ? (
            <a href={m.driver.contact_link} className="ml-auto text-[11px] underline text-ink/85">
              Call driver
            </a>
          ) : null}
        </div>
      ) : null}

      <DetailGrid
        rows={[
          ["Vehicle", m.vehicle?.make],
          ["Plate", m.vehicle?.plate_native_script ?? m.vehicle?.plate],
          ["Bag capacity", typeof m.bag_capacity === "number" ? `${m.bag_capacity} bags` : null],
          ["From → to", joinArrow([m.from_location?.label, m.to_location?.label])],
        ]}
      />

      {m.description ? <NoteBox label="Route notes">{m.description}</NoteBox> : null}
      <ChipRow tint={t.tint} chips={[m.bag_capacity ? "Luggage assist" : null]} />
    </>
  );
}

function WalkZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  const t = TYPE_TOKENS.walk;
  const dist = typeof m.distance_m === "number" ? `${(m.distance_m / 1000).toFixed(1)} km` : null;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  const pois = (m.pois_along ?? []).filter((p) => p.label);
  return (
    <>
      <Title>{node.title}</Title>
      <Sub>{joinDot([dist, dur, joinArrow([m.from_location?.label, m.to_location?.label])])}</Sub>

      <div className="mt-3 h-14 w-full overflow-hidden rounded border border-ink/10">
        <svg width="100%" height="100%" viewBox="0 0 240 56" preserveAspectRatio="none" aria-hidden>
          <path
            d="M 6 44 C 50 44, 70 20, 120 24 S 200 14, 234 12"
            stroke={t.accent}
            strokeWidth="2.5"
            fill="none"
            strokeLinecap="round"
          />
          <circle cx="6" cy="44" r="3.5" fill={t.accent} />
          <circle cx="234" cy="12" r="3.5" fill={t.accent} />
        </svg>
      </div>

      {pois.length > 0 ? (
        <NoteBox label="Along the way">
          <ul className="space-y-0.5">
            {pois.map((p, i) => (
              <li key={i}>· {p.label}</li>
            ))}
          </ul>
        </NoteBox>
      ) : null}

      <ChipRow tint={t.tint} chips={m.surface_notes ?? []} />
      {m.description ? <NoteBox label="Notes">{m.description}</NoteBox> : null}
    </>
  );
}

function BoatZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  const t = TYPE_TOKENS.boat;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <Title>{node.title}</Title>
        {dur ? <span className="font-mono text-[12px] text-ink/65">{dur}</span> : null}
      </div>
      <Sub>{joinArrow([m.dock_from, m.dock_to])}</Sub>

      <DetailGrid
        rows={[
          ["Frequency", m.schedule_frequency],
          ["Sea conditions", m.motion_sickness_rating ? `${prettify(m.motion_sickness_rating)} motion` : null],
        ]}
      />

      <ChipRow tint={t.tint} chips={m.bring_with ?? []} />
      {m.description ? <NoteBox label="On the crossing">{m.description}</NoteBox> : null}
    </>
  );
}

function HotelZoom({ node, m, tz }: { node: NodeResponse; m: ZoomMeta; tz: number }) {
  const t = TYPE_TOKENS.hotel;
  const cover = m.snapshot?.cover_image ?? m.ambient_image;
  const checkIn = m.check_in ? formatDayStamp(m.check_in, offsetHoursOr(m.check_in, tz)) : null;
  const checkOut = m.check_out ? formatDayStamp(m.check_out, offsetHoursOr(m.check_out, tz)) : null;
  const walking = (m.walking_to ?? []).filter((w) => w.label);
  const amenities = m.in_room_amenities ?? [];
  return (
    <>
      <div className="grid grid-cols-[160px_1fr] gap-4 sm:grid-cols-[200px_1fr] sm:gap-5">
        <ImageHero src={cover} fallbackTint="#5e6e5d" tall />
        <div className="min-w-0">
          <Title>{m.name ?? m.snapshot?.title ?? node.title}</Title>
          {typeof m.stars === "number" && m.stars > 0 ? (
            <div className="mt-0.5 text-[13px] tracking-[0.15em] text-brand" aria-label={`${m.stars}-star hotel`}>
              {"★".repeat(Math.min(5, m.stars))}
            </div>
          ) : null}
          <p className="text-[12px] text-ink/65">
            {joinDot([m.snapshot?.location ?? m.location?.label, m.room_type])}
          </p>
          <ChipRow
            tint={t.tint}
            chips={[m.room_type, ...(amenities.slice(0, 3))]}
          />
          <DetailGrid
            rows={[
              ["Check-in", checkIn],
              ["Check-out", checkOut],
              ["Confirmation", m.confirmation_number],
              ["Bedding", m.bedding],
            ]}
          />
        </div>
      </div>

      <PlaceInfo place={m.place} tint={t.tint} />

      {walking.length > 0 || m.neighborhood_blurb ? (
        <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {walking.length > 0 ? (
            <div className="rounded border border-ink/10 bg-paper/60 p-3">
              <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">From your door</span>
              <ul className="mt-2 space-y-1 text-[11px] text-ink/85">
                {walking.map((w, i) => (
                  <li key={i} className="flex items-center justify-between gap-2">
                    <span>{w.label}</span>
                    <span className="font-mono text-[10px] text-ink/55">
                      {w.minutes} min{w.mode ? ` · ${w.mode}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {m.neighborhood_blurb ? (
            <div className="rounded border border-ink/10 bg-paper/60 p-3">
              <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Neighborhood</span>
              <p className="mt-1.5 text-[11px] leading-relaxed text-ink/80">{m.neighborhood_blurb}</p>
            </div>
          ) : null}
        </div>
      ) : null}

      <ChipRow tint={t.tint} chips={m.profile_prefs_honored ?? []} />
    </>
  );
}

function ExperienceZoom({
  node,
  m,
  variant,
}: {
  node: NodeResponse;
  m: ZoomMeta;
  variant: ZoomVariant;
}) {
  const t = TYPE_TOKENS.experience;
  const cover = placePhotoUrl(m.place?.photo_token) ?? m.snapshot?.cover_image ?? m.ambient_image;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  const gear = m.gear_list ?? [];
  return (
    <>
      {cover ? <ImageHero src={cover} fallbackTint="#b58a3a" tall /> : null}
      <Title>{m.snapshot?.title ?? node.title}</Title>
      <p className="text-[12px] text-ink/65">
        {joinDot([m.location?.label ?? m.snapshot?.location, prettify(m.category), dur])}
      </p>

      <OperatorSeal operator={m.operator} />

      {m.description ? (
        <p className="mt-3 text-[12px] leading-relaxed text-ink/85">{m.description}</p>
      ) : null}

      {/* The moments gallery is secondary richness — shown in the full-detail
          modal, dropped from the LARGE rail preview it opens (keeps the rail
          card a clean read; the gallery is one tap away). */}
      {variant === "modal" ? <MomentsGallery images={m.gallery} /> : null}

      <PlaceInfo place={m.place} tint={t.tint} />

      <DetailGrid
        rows={[
          ["Difficulty", m.difficulty],
          ["Energy after", prettify(m.energy_after)],
          ["Group size", m.group_size],
          ["Language", m.language_support],
        ]}
      />

      <div className="mt-4 flex items-center justify-between gap-3">
        {typeof m.energy_required === "number" ? <EnergyMeter level={m.energy_required} accent={t.accent} /> : <span />}
        {m.best_window && typeof m.best_window.start_hour === "number" && typeof m.best_window.end_hour === "number" ? (
          <span className="text-[11px] text-ink/65">
            Best {m.best_window.start_hour}:00–{m.best_window.end_hour}:00
          </span>
        ) : null}
      </div>
      {m.best_window && typeof m.best_window.start_hour === "number" && typeof m.best_window.end_hour === "number" ? (
        <DayWindow start={m.best_window.start_hour} end={m.best_window.end_hour} accent={t.accent} />
      ) : null}

      {gear.length > 0 ? <ChipRow tint={t.tint} chips={gear.map((g) => `🤲 ${g}`)} /> : null}
      {(m.allergens ?? []).length > 0 ? (
        <ChipRow tint={t.tint} chips={[`Allergens: ${(m.allergens ?? []).join(", ")}`]} />
      ) : null}
      {m.weather_contingency ? <NoteBox label="If it rains">{m.weather_contingency}</NoteBox> : null}
    </>
  );
}

function MealZoom({ node, m, tz }: { node: NodeResponse; m: ZoomMeta; tz: number }) {
  const t = TYPE_TOKENS.meal;
  const cover = placePhotoUrl(m.place?.photo_token) ?? m.snapshot?.cover_image ?? m.ambient_image;
  const seating = m.seating_at ? formatClock(m.seating_at, offsetHoursOr(m.seating_at, tz)) : null;
  const etiquette = (m.etiquette ?? []).filter((e) => e.label);
  const phrases = (m.pre_meal_phrases ?? []).filter((p) => p.native);
  const diet = m.dietary_flags ?? [];
  return (
    <>
      <div className="grid grid-cols-[160px_1fr] gap-4 sm:grid-cols-[200px_1fr] sm:gap-5">
        <ImageHero src={cover} fallbackTint="#8a3a2a" tall />
        <div className="min-w-0">
          <Title>{m.snapshot?.title ?? node.title}</Title>
          <p className="text-[12px] text-ink/65">
            {joinDot([prettify(m.cuisine_class), m.snapshot?.location ?? m.location?.label, m.price])}
          </p>
          {m.description ? (
            <p className="mt-2 text-[12px] leading-relaxed text-ink/85">{m.description}</p>
          ) : null}
          <DetailGrid
            rows={[
              ["Seating", joinDot([seating, m.dress_code])],
              ["Reservation", m.reservation_number],
              ["Cancellation", m.cancellation_policy],
            ]}
          />
        </div>
      </div>

      {etiquette.length > 0 ? (
        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {etiquette.map((e, i) => (
            <div key={i} className="rounded border border-ink/10 bg-paper px-3 py-2">
              <p className="text-[10px] uppercase tracking-[0.18em] text-ink/55">{e.label}</p>
              {e.body ? <p className="mt-1 text-[11px] text-ink/80">{e.body}</p> : null}
            </div>
          ))}
        </div>
      ) : null}

      {diet.length > 0 || phrases.length > 0 ? (
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
          {diet.length > 0 ? (
            <div className="rounded border border-ink/10 bg-paper/60 p-3">
              <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Diet on file</span>
              <ul className="mt-2 space-y-0.5 text-[11px] text-ink/85">
                {diet.map((d, i) => (
                  <li key={i}>· {d}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {phrases.length > 0 ? (
            <div className="rounded border border-ink/10 bg-paper/60 p-3">
              <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Pre-meal phrases</span>
              <ul className="mt-2 space-y-0.5 text-[11px] text-ink/85">
                {phrases.map((p, i) => (
                  <li key={i}>
                    · {p.native}
                    {p.romanization ? ` — ${p.romanization}` : ""}
                    {p.gloss ? ` (${p.gloss})` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}

      <ChipRow tint={t.tint} chips={[m.dress_code, ...diet.slice(0, 1)]} />

      <PlaceInfo place={m.place} tint={t.tint} />
    </>
  );
}

function FreeTimeZoom({ node, m, tz }: { node: NodeResponse; m: ZoomMeta; tz: number }) {
  const t = TYPE_TOKENS.free_time;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  const grid = m.suggestion_grid ?? [];
  void tz;
  return (
    <>
      <Title className="italic">{node.title}</Title>
      <p className="text-[12px] text-ink/65">{joinDot([dur, m.weather])}</p>

      {m.energy_advice ? <NoteBox label="Energy advice">{m.energy_advice}</NoteBox> : null}

      {grid.length > 0 ? (
        <div className="mt-4">
          <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">If you want to fill it</span>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
            {grid.map((g, i) => (
              <div key={i} className="rounded border border-ink/10 bg-paper px-2.5 py-2 text-[12px] text-ink/85">
                {g}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <ChipRow tint={t.tint} chips={["No commitments"]} />
    </>
  );
}

function WaitingZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  const t = TYPE_TOKENS.waiting;
  const dur = typeof m.duration_minutes === "number" ? formatDuration(m.duration_minutes) : null;
  const todo = m.use_this_time_to ?? [];
  return (
    <>
      <div className="flex items-baseline justify-between gap-3">
        <Title>{node.title}</Title>
        {dur ? <span className="font-mono text-[12px] text-ink/65">{dur}</span> : null}
      </div>
      {m.lounge_info ? <Sub>{m.lounge_info}</Sub> : null}

      {todo.length > 0 ? (
        <NoteBox label="Use this time to">
          <ul className="space-y-1">
            {todo.map((x, i) => (
              <li key={i}>· {x}</li>
            ))}
          </ul>
        </NoteBox>
      ) : null}

      <ChipRow tint={t.tint} chips={m.facilities ?? []} />
    </>
  );
}

function NoteZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  const t = TYPE_TOKENS.note;
  return (
    <>
      <Title>{node.title}</Title>
      {m.body ? <p className="mt-2 text-[12px] leading-relaxed text-ink/85">{m.body}</p> : null}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/55">
        {m.author_name ? <span>{m.author_name}</span> : null}
        {m.author_role ? <span>· {m.author_role}</span> : null}
        {m.visibility ? <span>· {m.visibility}</span> : null}
      </div>
      {(m.tags ?? []).length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(m.tags ?? []).map((tag) => (
            <Chip key={tag} tint={t.tint} outlined>
              {tag}
            </Chip>
          ))}
        </div>
      ) : null}
    </>
  );
}

function GenericZoom({ node, m }: { node: NodeResponse; m: ZoomMeta }) {
  return (
    <>
      <Title>{node.title}</Title>
      {m.location?.label ? <Sub>{m.location.label}</Sub> : null}
      {m.description ? (
        <p className="mt-2 text-[12px] leading-relaxed text-ink/85">{m.description}</p>
      ) : null}
    </>
  );
}

// ── Shared sub-components ──────────────────────────────────────────────

function Endpoint({
  code,
  city,
  time,
  date,
  align = "left",
}: {
  code: string | undefined;
  city: string | null;
  time: string | null;
  date?: string | null;
  align?: "left" | "right";
}) {
  const a = align === "right" ? "text-right" : "text-left";
  return (
    <div className={a}>
      <p className="font-mono text-[22px] leading-none tracking-widest text-ink">{code ?? "—"}</p>
      {city ? <p className="mt-1 text-[11px] text-ink/65">{city}</p> : null}
      {time ? <p className="mt-2 font-mono text-[14px] text-ink/85">{time}</p> : null}
      {date ? (
        <p className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.14em] text-ink/55">{date}</p>
      ) : null}
    </div>
  );
}

function FlightArcLarge({
  accent,
  duration,
  miles,
}: {
  accent: string;
  duration: string | null;
  miles: string | null;
}) {
  return (
    <div className="flex flex-col items-center">
      <svg width="160" height="48" viewBox="0 0 180 56" aria-hidden>
        <path d="M 6 40 C 50 -10, 130 -10, 174 40" stroke={accent} strokeWidth="1.2" fill="none" strokeDasharray="3 3" />
        <circle cx="6" cy="40" r="3" fill={accent} />
        <circle cx="174" cy="40" r="3" fill={accent} />
        <text x="90" y="14" textAnchor="middle" className="fill-ink/55" fontSize="10">
          ✈
        </text>
      </svg>
      {duration ? <p className="font-mono text-[12px] tracking-wide text-ink/75">{duration}</p> : null}
      {miles ? <p className="text-[10px] uppercase tracking-[0.18em] text-ink/50">{miles}</p> : null}
    </div>
  );
}

function StopSequence({ stops, accent, tz }: { stops: TrainStop[]; accent: string; tz: number }) {
  const w = 600;
  const padX = 28;
  const innerW = w - padX * 2;
  const stepX = stops.length > 1 ? innerW / (stops.length - 1) : 0;
  const y = 38;
  return (
    <div className="overflow-x-auto">
      <svg width={w} height="110" viewBox={`0 0 ${w} 110`} role="img" aria-label="Stop sequence">
        <line x1={padX} y1={y} x2={w - padX} y2={y} stroke={accent} strokeWidth="2" />
        {stops.map((s, i) => {
          const cx = padX + i * stepX;
          const isEnd = i === 0 || i === stops.length - 1;
          const tIso = s.departs_at ?? s.arrives_at;
          const clock = tIso ? formatClock(tIso, offsetHoursOr(tIso, tz)) : null;
          return (
            <g key={i}>
              <circle cx={cx} cy={y} r={isEnd ? 7 : 4} fill={isEnd ? accent : "#f7f4ee"} stroke={accent} strokeWidth="2" />
              {clock ? (
                <text x={cx} y={y - 12} textAnchor="middle" fontSize="9" fontFamily="ui-monospace, monospace" className="fill-ink/70">
                  {clock}
                </text>
              ) : null}
              <text x={cx} y={y + 22} textAnchor="middle" fontSize="10" fontFamily="ui-sans-serif, system-ui" className="fill-ink/85">
                {s.station}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function EnergyMeter({ level, accent }: { level: number; accent: string }) {
  const clamped = Math.max(1, Math.min(5, Math.round(level)));
  return (
    <span className="inline-flex items-center gap-1.5" role="img" aria-label={`Energy required: ${clamped} of 5`}>
      <span className="text-[10px] uppercase tracking-[0.18em] text-ink/55">Energy</span>
      <span className="inline-flex gap-0.5">
        {[1, 2, 3, 4, 5].map((c) => (
          <span
            key={c}
            className="block h-2 w-2 rounded-sm"
            style={{ backgroundColor: c <= clamped ? accent : "rgba(10,10,10,0.12)" }}
          />
        ))}
      </span>
    </span>
  );
}

function DayWindow({ start, end, accent }: { start: number; end: number; accent: string }) {
  const HOURS = 24;
  return (
    <svg width="100%" height="22" viewBox="0 0 240 22" preserveAspectRatio="none" aria-hidden className="mt-2">
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
      <rect x={(start / HOURS) * 240} y={6} width={((end - start) / HOURS) * 240} height={10} fill={accent} opacity={0.85} />
    </svg>
  );
}

// Rating + hours + contact/map links for a Places-sourced POI. The gradient
// stub is fine when we know nothing about a place; when Google gives us a crowd
// rating, opening hours, and a way to reach it, showing that is what turns a
// bare title into a real card. Renders nothing when `place` carries no content.
function PlaceInfo({ place, tint }: { place: Place | undefined; tint: string }) {
  if (!place) return null;
  const rating = typeof place.rating === "number" ? place.rating.toFixed(1) : null;
  const count =
    typeof place.rating_count === "number" ? place.rating_count.toLocaleString() : null;
  const hours = place.hours ?? [];
  const links: Array<{ label: string; href: string }> = [];
  if (place.website) links.push({ label: "Website ↗", href: place.website });
  if (place.phone) links.push({ label: place.phone, href: `tel:${place.phone.replace(/\s+/g, "")}` });
  if (place.maps_url) links.push({ label: "View on Google Maps ↗", href: place.maps_url });
  if (!rating && hours.length === 0 && links.length === 0) return null;
  return (
    <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3">
      {rating ? (
        <div className="flex items-baseline gap-1.5">
          <span className="text-[13px] font-medium text-ink/90">★ {rating}</span>
          {count ? <span className="text-[11px] text-ink/55">{count} reviews</span> : null}
        </div>
      ) : null}
      {hours.length > 0 ? (
        <div className="mt-2">
          <p className="text-[10px] uppercase tracking-[0.2em] text-ink/50">Hours</p>
          <ul className="mt-1 space-y-0.5 text-[11px] leading-relaxed text-ink/75">
            {hours.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {links.length > 0 ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {links.map((l) => (
            <a
              key={l.href}
              href={l.href}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full border border-ink/15 px-2.5 py-1 text-[11px] text-ink/80 transition-colors hover:bg-ink/5"
              style={{ backgroundColor: tint }}
            >
              {l.label}
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// The "moments that define this adventure" gallery — the OV trip's supporting
// images beyond the hero. A captioned thumbnail strip: hover reveals the
// caption + credit, clicking opens the full image. Renders nothing when the
// item carries no gallery (Places experiences, sparse cards).
function MomentsGallery({ images }: { images?: GalleryImage[] | undefined }) {
  const shots = (images ?? []).filter((g): g is GalleryImage & { url: string } =>
    Boolean(g.url),
  );
  if (shots.length === 0) return null;
  return (
    <div className="mt-5">
      <p className="text-[10px] uppercase tracking-[0.2em] text-ink/50">
        Moments that define this adventure
      </p>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {shots.map((img, i) => (
          <a
            key={`${img.url}-${i}`}
            href={img.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group relative block aspect-[4/3] overflow-hidden rounded-md border border-ink/10 bg-ink/5"
            title={img.caption ?? undefined}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- public OV CDN URL; next/image loaders unneeded, degrades to the tint on error. */}
            <img
              src={img.url}
              alt={img.caption ?? ""}
              loading="lazy"
              className="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
              onError={(e) => {
                e.currentTarget.style.display = "none";
              }}
            />
            {img.caption ? (
              <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/65 to-transparent px-2 pb-1.5 pt-4 text-[10px] leading-tight text-paper opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                {img.caption}
                {img.credit ? (
                  <span className="mt-0.5 block text-[8px] uppercase tracking-[0.14em] text-paper/70">
                    {img.credit}
                  </span>
                ) : null}
              </span>
            ) : null}
          </a>
        ))}
      </div>
    </div>
  );
}

// The vetted-operator seal — the operator's logo + name beside a "specially
// vetted" mark, the whole row a link out to their OV profile page (new tab).
// Rendered on both the modal and the LARGE rail form. Renders nothing when the
// card carries no operator (the vast majority of cards).
function OperatorSeal({ operator }: { operator?: Operator | undefined }) {
  if (!operator?.name) return null;
  const href = operator.profile_url;
  const body = (
    <>
      {operator.logo_url ? (
        <span className="flex h-9 shrink-0 items-center rounded-sm bg-paper px-2 shadow-[0_1px_3px_rgba(10,10,10,0.08)] ring-1 ring-ink/10">
          {/* eslint-disable-next-line @next/next/no-img-element -- same-origin /public SVG; next/image loaders unneeded. */}
          <img src={operator.logo_url} alt={operator.name} className="h-5 w-auto" />
        </span>
      ) : null}
      <span className="min-w-0">
        <span className="block font-serif text-[13px] leading-tight text-ink">
          {operator.name}
        </span>
        {operator.vetted ? (
          <span className="mt-0.5 flex items-center gap-1 text-[9px] uppercase tracking-[0.16em] text-brand">
            <VettedSeal /> Specially vetted
          </span>
        ) : null}
      </span>
      {href ? (
        <span className="ml-auto shrink-0 self-center text-[10px] uppercase tracking-[0.16em] text-ink/45 transition-colors group-hover/seal:text-brand">
          Operator ↗
        </span>
      ) : null}
    </>
  );
  const cls =
    "group/seal mt-4 flex items-center gap-3 rounded-lg border border-ink/12 bg-paper/70 px-3 py-2.5";
  return href ? (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="card-operator-seal"
      className={`${cls} transition-colors hover:border-brand/40 hover:bg-brand/[0.04]`}
    >
      {body}
    </a>
  ) : (
    <div data-testid="card-operator-seal" className={cls}>
      {body}
    </div>
  );
}

// The little rosette that marks the operator as OV-vetted — a scalloped seal
// with a check, drawn in the brand accent (orange as punctuation, not paint).
function VettedSeal() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden className="text-brand">
      <path
        fill="currentColor"
        d="M12 1.5l2.35 1.86 2.98-.34 1.02 2.82 2.82 1.02-.34 2.98L22.5 12l-1.86 2.35.34 2.98-2.82 1.02-1.02 2.82-2.98-.34L12 22.5l-2.35-1.86-2.98.34-1.02-2.82-2.82-1.02.34-2.98L1.5 12l1.86-2.35-.34-2.98 2.82-1.02 1.02-2.82 2.98.34z"
      />
      <path
        fill="none"
        stroke="#fff"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M8.5 12.2l2.4 2.4 4.6-4.9"
      />
    </svg>
  );
}

function ImageHero({ src, fallbackTint, tall = false }: { src?: string | undefined; fallbackTint: string; tall?: boolean }) {
  return (
    <div
      className={`relative overflow-hidden rounded-md border border-ink/10 ${tall ? "h-36 w-full" : "h-24 w-full"}`}
      role="img"
      aria-label="Card image"
      style={{
        // Gradient is always the base layer; a real photo (when present) covers
        // it and, on a load error, hides itself to reveal the tint underneath.
        backgroundImage: `linear-gradient(135deg, ${fallbackTint} 0%, #f7f4ee 100%)`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- proxied/remote URL, next/image loaders unneeded; degrades to the gradient on error.
        <img
          src={src}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      ) : (
        <span className="absolute bottom-1 right-1.5 text-[8px] uppercase tracking-[0.18em] text-paper/85">photo</span>
      )}
    </div>
  );
}

function NoteBox({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mt-4 rounded border border-ink/10 bg-paper/60 p-3 text-[11px] leading-relaxed text-ink/80">
      <span className="text-[10px] uppercase tracking-[0.2em] text-ink/50">{label}</span>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function DetailGrid({ rows }: { rows: Array<[string, string | null | undefined]> }) {
  const present = rows.filter(([, v]) => v);
  if (present.length === 0) return null;
  return (
    <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-[12px] text-ink/80">
      {present.map(([label, value]) => (
        <div key={label}>
          <p className="text-[10px] uppercase tracking-[0.18em] text-ink/50">{label}</p>
          <p className="text-ink/85">{value}</p>
        </div>
      ))}
    </div>
  );
}

function ChipRow({ tint, chips }: { tint: string; chips: Array<string | null | undefined> }) {
  const present = chips.filter((c): c is string => Boolean(c));
  if (present.length === 0) return null;
  return (
    <div className="mt-4 flex flex-wrap gap-1.5">
      {present.map((c, i) => (
        <Chip key={`${c}-${i}`} tint={tint}>
          {c}
        </Chip>
      ))}
    </div>
  );
}

// ── String helpers ─────────────────────────────────────────────────────

function cityOnly(label: string | undefined): string | null {
  if (!label) return null;
  return label.replace(/\s*\([^)]*\)\s*$/, "").trim() || null;
}

function prettify(s: string | undefined | null): string | null {
  if (!s) return null;
  const words = s.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}

function joinDot(parts: Array<string | null | undefined>): string | null {
  const present = parts.filter((p): p is string => Boolean(p));
  return present.length ? present.join(" · ") : null;
}

function joinArrow(parts: Array<string | null | undefined>): string | null {
  const present = parts.filter((p): p is string => Boolean(p));
  return present.length ? present.join(" → ") : null;
}

// "2024-07-04T15:25:00+09:00" → "Thu Jul 4" in the card's local zone.
function formatDayStamp(iso: string, tzOffsetHours: number): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return "";
  const [, y, mo, d] = m;
  const dt = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d)));
  const wd = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][dt.getUTCDay()];
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][dt.getUTCMonth()];
  void tzOffsetHours;
  return `${wd} ${mon} ${dt.getUTCDate()}`;
}
