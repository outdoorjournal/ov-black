import type { StaticImageData } from "next/image";

import glacialImg from "@/app/chat/[client_id]/_components/atmos/images/glacial.jpg";
import emberImg from "@/app/chat/[client_id]/_components/atmos/images/ember.jpg";
import amberImg from "@/app/chat/[client_id]/_components/atmos/images/amber.jpg";
import verdantImg from "@/app/chat/[client_id]/_components/atmos/images/verdant.jpg";
import tidalImg from "@/app/chat/[client_id]/_components/atmos/images/tidal.jpg";
import onyxImg from "@/app/chat/[client_id]/_components/atmos/images/onyx.jpg";
import alpineImg from "@/app/chat/[client_id]/_components/atmos/images/alpine.jpg";

export type MoodId =
  | "glacial"
  | "ember"
  | "amber"
  | "verdant"
  | "tidal"
  | "onyx"
  | "alpine"
  // Basecamp additions — agent-driven (no keyword classifier consulting),
  // placeholder imagery reuses existing assets until real photography
  // lands. Keep this union aligned with apps/agent/src/agent/moods.py.
  | "paris-cafe"
  | "kyoto-zen"
  | "savannah"
  | "polar"
  | "andes"
  | "monsoon"
  | "riviera"
  | "highland";

export type MoodPalette = {
  bg: string;
  fg: string;
  accent: string;
};

export type MoodEntry = {
  palette: MoodPalette;
  imageUrl: StaticImageData;
  keywords: string[];
};

export const DEFAULT_MOOD: MoodId = "alpine";

export const MOODS: Record<MoodId, MoodEntry> = {
  glacial: {
    palette: { bg: "#0f1f2e", fg: "#d8e6f0", accent: "#7fb3d5" },
    imageUrl: glacialImg,
    keywords: [
      "patagonia",
      "iceland",
      "antarctica",
      "fjord",
      "glacier",
      "arctic",
      "norway",
    ],
  },
  ember: {
    palette: { bg: "#2a1410", fg: "#f4c6a5", accent: "#d97442" },
    imageUrl: emberImg,
    keywords: [
      "morocco",
      "marrakech",
      "sahara",
      "desert",
      "sunset",
      "dune",
      "moab",
    ],
  },
  amber: {
    palette: { bg: "#1f1608", fg: "#f5d9a0", accent: "#c89141" },
    imageUrl: amberImg,
    keywords: [
      "tuscany",
      "rome",
      "florence",
      "chianti",
      "umbria",
      "siena",
      "provence",
    ],
  },
  verdant: {
    palette: { bg: "#0e1f16", fg: "#c8e0cd", accent: "#5a9a6f" },
    imageUrl: verdantImg,
    keywords: [
      "amazon",
      "jungle",
      "rainforest",
      "costa",
      "borneo",
      "congo",
      "forest",
    ],
  },
  tidal: {
    palette: { bg: "#0a1a26", fg: "#bcd7e2", accent: "#4ea0be" },
    imageUrl: tidalImg,
    keywords: [
      "ocean",
      "beach",
      "coast",
      "maldives",
      "reef",
      "caribbean",
      "bali",
    ],
  },
  onyx: {
    palette: { bg: "#0a0a12", fg: "#c8c8d4", accent: "#6a6a86" },
    imageUrl: onyxImg,
    keywords: [
      "tokyo",
      "shibuya",
      "manhattan",
      "brooklyn",
      "skyline",
      "metro",
      "shanghai",
    ],
  },
  alpine: {
    palette: { bg: "#1a1e22", fg: "#d0d4d8", accent: "#7a8890" },
    imageUrl: alpineImg,
    keywords: [
      "mountain",
      "alps",
      "summit",
      "trail",
      "hike",
      "ridge",
      "meadow",
    ],
  },
  // Basecamp additions. Keywords intentionally empty — these are picked
  // by the agent via the set_mood tool, not the keyword classifier.
  // Imagery placeholders aliased to nearest existing assets.
  "paris-cafe": {
    palette: { bg: "#1c1410", fg: "#efd9b4", accent: "#c8995a" },
    imageUrl: amberImg,
    keywords: [],
  },
  "kyoto-zen": {
    palette: { bg: "#10141a", fg: "#d2c7b6", accent: "#7a6a55" },
    imageUrl: onyxImg,
    keywords: [],
  },
  savannah: {
    palette: { bg: "#2a1f10", fg: "#e6c98c", accent: "#b07a3a" },
    imageUrl: emberImg,
    keywords: [],
  },
  polar: {
    palette: { bg: "#0c1218", fg: "#dde6f0", accent: "#a8c4dc" },
    imageUrl: glacialImg,
    keywords: [],
  },
  andes: {
    palette: { bg: "#1a1614", fg: "#d2bfa6", accent: "#8a6f55" },
    imageUrl: alpineImg,
    keywords: [],
  },
  monsoon: {
    palette: { bg: "#0e1a1a", fg: "#bdd5ce", accent: "#5a8a82" },
    imageUrl: verdantImg,
    keywords: [],
  },
  riviera: {
    palette: { bg: "#0e1822", fg: "#cfdce8", accent: "#6f9ec0" },
    imageUrl: tidalImg,
    keywords: [],
  },
  highland: {
    palette: { bg: "#181c1a", fg: "#cdd2c8", accent: "#7e8a78" },
    imageUrl: alpineImg,
    keywords: [],
  },
};

export const MOOD_IDS: MoodId[] = Object.keys(MOODS) as MoodId[];
