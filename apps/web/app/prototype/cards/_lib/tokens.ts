// Design tokens for the cards prototype.
//
// Each card type maps to:
//   - A primary "type" color used in the corner mark, divider, and chips.
//     All chosen to clear WCAG AA (4.5:1) on the paper bg #f7f4ee when
//     used for body text, and 3:1 for large text / non-text indicators.
//   - A soft "tint" used for chip backgrounds.
//   - An icon component (lucide).
//
// Principle: never rely on color alone. Pair every color cue with an icon,
// label, or texture. See A11yPanel for the full checklist.

import {
  Camera,
  Car,
  Coffee,
  Footprints,
  Hourglass,
  MapPin,
  Mountain,
  Plane,
  Ship,
  StickyNote,
  Train,
  Utensils,
  type LucideIcon,
} from "lucide-react";
import { BedDouble } from "lucide-react";

export type CardKind =
  | "flight"
  | "subway"
  | "train"
  | "drive"
  | "walk"
  | "boat"
  | "hotel"
  | "experience"
  | "meal"
  | "free_time"
  | "waiting"
  | "note"
  | "destination";

export interface TypeToken {
  label: string;
  short: string;
  accent: string;
  tint: string;
  Icon: LucideIcon;
  glyph: string;
  blurb: string;
}

export const TYPE_TOKENS: Record<CardKind, TypeToken> = {
  flight: {
    label: "Flight",
    short: "FLT",
    accent: "#2c4a6b",
    tint: "#dde6ef",
    Icon: Plane,
    glyph: "✈",
    blurb: "Long-haul, charter, regional.",
  },
  subway: {
    label: "Subway",
    short: "SUB",
    accent: "#3a4d63",
    tint: "#dde2ea",
    Icon: Train,
    glyph: "▤",
    blurb: "Metro lines, transfers, signage.",
  },
  train: {
    label: "Train",
    short: "TRN",
    accent: "#4a5a3f",
    tint: "#dde3d2",
    Icon: Train,
    glyph: "▥",
    blurb: "Shinkansen, intercity, scenic rail.",
  },
  drive: {
    label: "Private car",
    short: "CAR",
    accent: "#5a4a3a",
    tint: "#e8dfd2",
    Icon: Car,
    glyph: "▢",
    blurb: "Driver, vehicle, route preview.",
  },
  walk: {
    label: "On foot",
    short: "WLK",
    accent: "#5a5040",
    tint: "#e3ddcf",
    Icon: Footprints,
    glyph: "→",
    blurb: "Route, surface, points of interest.",
  },
  boat: {
    label: "Boat",
    short: "BOA",
    accent: "#3a5a6b",
    tint: "#d6e1e8",
    Icon: Ship,
    glyph: "≈",
    blurb: "Ferry, charter, water transfer.",
  },
  hotel: {
    label: "Hotel",
    short: "HTL",
    accent: "#2f5240",
    tint: "#d6e2d6",
    Icon: BedDouble,
    glyph: "◻",
    blurb: "Lodging with check-in window.",
  },
  experience: {
    label: "Experience",
    short: "EXP",
    accent: "#8a5a1b",
    tint: "#ecddbb",
    Icon: Mountain,
    glyph: "◉",
    blurb: "Activity, tour, guided moment.",
  },
  meal: {
    label: "Meal",
    short: "MEA",
    accent: "#8a3a2a",
    tint: "#ebd2c6",
    Icon: Utensils,
    glyph: "◆",
    blurb: "Restaurant, omakase, picnic.",
  },
  free_time: {
    label: "Free time",
    short: "FRE",
    accent: "#6b5a3a",
    tint: "#e6dec5",
    Icon: Coffee,
    glyph: "◌",
    blurb: "Open block; energy-aware.",
  },
  waiting: {
    label: "Waiting",
    short: "WAI",
    accent: "#5a5a5a",
    tint: "#dedcd6",
    Icon: Hourglass,
    glyph: "⏳",
    blurb: "Buffer between fixed nodes.",
  },
  note: {
    label: "Note",
    short: "NTE",
    accent: "#7a6618",
    tint: "#f4e9b8",
    Icon: StickyNote,
    glyph: "✎",
    blurb: "Author-attached annotation.",
  },
  destination: {
    label: "Destination",
    short: "DST",
    accent: "#1a1a1a",
    tint: "#d6d4cf",
    Icon: MapPin,
    glyph: "⌂",
    blurb: "Region anchor; container.",
  },
};

export type StatusKind =
  | "idea"
  | "proposed"
  | "approved"
  | "booked"
  | "confirmed"
  | "discarded";

export const STATUS_TOKENS: Record<
  StatusKind,
  { label: string; description: string; nonColorCue: string }
> = {
  idea: {
    label: "Idea",
    description: "Mentioned in conversation; not yet a candidate.",
    nonColorCue: "Dashed border, italic title, 70% opacity.",
  },
  proposed: {
    label: "Proposed",
    description: "Surfaced for the traveler to react to.",
    nonColorCue: "Solid border, footer tag “Proposed”, soft shadow.",
  },
  approved: {
    label: "Approved",
    description: "Traveler said yes; not yet booked.",
    nonColorCue: "Corner ribbon + check glyph + “Approved” tag.",
  },
  booked: {
    label: "Booked",
    description: "Held with the operator; payment may pend.",
    nonColorCue: "Filled corner mark + lock glyph + “Booked” tag.",
  },
  confirmed: {
    label: "Confirmed",
    description: "Locked: confirmation number + payment cleared.",
    nonColorCue: "Double border + double-check glyph + “Confirmed” tag.",
  },
  discarded: {
    label: "Dismissed",
    description: "Explicitly removed; kept for history.",
    nonColorCue: "Strikethrough title + 50% grayscale.",
  },
};

// Real Tokyo Metro line colors used in the subway zoom example.
// Source: official Tokyo Metro brand guidelines (publicly published).
export const METRO_LINE_COLORS: Record<string, string> = {
  Ginza: "#f39700",
  Marunouchi: "#e60012",
  Hibiya: "#9caeb7",
  Tozai: "#00a7db",
  Chiyoda: "#009944",
  Yurakucho: "#c1a470",
  Hanzomon: "#9b7cb6",
  Namboku: "#00ada9",
  Fukutoshin: "#bb641d",
};

export const PAPER_BG = "#f7f4ee";
export const INK = "#0a0a0a";

export const NOISE_BG =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='1' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.05 0 0 0 0 0.04 0 0 0 0 0.03 0 0 0 0.06 0'/></filter><rect width='140' height='140' filter='url(%23n)'/></svg>\")";
