// Curated atmospheric backgrounds for the basecamp/chat mood frame.
//
// `imageUrl` points at the Unsplash CDN directly. The Next/Image
// remote-pattern allowlist for `images.unsplash.com` is configured in
// `next.config.ts`; the `?w=...&q=...&auto=format&fit=crop` query
// renders a JPEG sized for the full-bleed background layer that sits
// at ~55% opacity over the palette.
//
// The agent's set_mood tool is the source of truth for which mood to
// pick. Keep this list aligned with `apps/agent/src/agent/moods.py` —
// when adding a mood, edit both.

export type MoodId =
  | "glacial"
  | "ember"
  | "amber"
  | "verdant"
  | "tidal"
  | "onyx"
  | "alpine"
  | "paris-cafe"
  | "kyoto-zen"
  | "savannah"
  | "polar"
  | "andes"
  | "monsoon"
  | "riviera"
  | "highland"
  | "olympus";

export type MoodPalette = {
  bg: string;
  fg: string;
  accent: string;
};

export type MoodEntry = {
  palette: MoodPalette;
  imageUrl: string;
  keywords: string[];
};

export const DEFAULT_MOOD: MoodId = "alpine";

// Common Unsplash CDN params: 2400px wide is enough for retina laptops
// at 1440px, q=80 keeps each frame under ~250 KB, fit=crop honors the
// CDN-side cropping focal point. auto=format upgrades modern browsers
// to AVIF/WebP automatically.
const UNSPLASH = (id: string): string =>
  `https://images.unsplash.com/photo-${id}?w=2400&q=80&auto=format&fit=crop`;

export const MOODS: Record<MoodId, MoodEntry> = {
  glacial: {
    palette: { bg: "#0f1f2e", fg: "#d8e6f0", accent: "#7fb3d5" },
    imageUrl: UNSPLASH("1496340077100-9573d8b77463"),
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
    imageUrl: UNSPLASH("1750859876327-f9360664c362"),
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
    imageUrl: UNSPLASH("1518098268026-4e89f1a2cd8e"),
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
    imageUrl: UNSPLASH("1583470790878-4f4f3811a01f"),
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
    imageUrl: UNSPLASH("1757258632083-e9b8a5345047"),
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
    imageUrl: UNSPLASH("1761173084851-1e5302e931fe"),
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
    // Matterhorn at blue hour — deep slate dusk, matches the alpine palette.
    imageUrl: UNSPLASH("1775735018294-9774004551ef"),
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
  "paris-cafe": {
    palette: { bg: "#1c1410", fg: "#efd9b4", accent: "#c8995a" },
    imageUrl: UNSPLASH("1757435755336-f715ff8896d8"),
    keywords: [],
  },
  "kyoto-zen": {
    palette: { bg: "#10141a", fg: "#d2c7b6", accent: "#7a6a55" },
    imageUrl: UNSPLASH("1761141954476-2921e2e43e99"),
    keywords: [],
  },
  savannah: {
    palette: { bg: "#2a1f10", fg: "#e6c98c", accent: "#b07a3a" },
    imageUrl: UNSPLASH("1761078206756-68d3023f3021"),
    keywords: [],
  },
  polar: {
    palette: { bg: "#0c1218", fg: "#dde6f0", accent: "#a8c4dc" },
    imageUrl: UNSPLASH("1764957080454-dd997a855733"),
    keywords: [],
  },
  andes: {
    palette: { bg: "#1a1614", fg: "#d2bfa6", accent: "#8a6f55" },
    imageUrl: UNSPLASH("1717508723994-ec9c13a6d4bc"),
    keywords: [],
  },
  monsoon: {
    palette: { bg: "#0e1a1a", fg: "#bdd5ce", accent: "#5a8a82" },
    imageUrl: UNSPLASH("1634951412593-b2cdca1ae519"),
    keywords: [],
  },
  riviera: {
    palette: { bg: "#0e1822", fg: "#cfdce8", accent: "#6f9ec0" },
    imageUrl: UNSPLASH("1568282167464-cb0d811b05c2"),
    keywords: [],
  },
  highland: {
    palette: { bg: "#181c1a", fg: "#cdd2c8", accent: "#7e8a78" },
    imageUrl: UNSPLASH("1732045133230-1a670eef8620"),
    keywords: [],
  },
  // Mount Olympus / Greece campaign — sun-warmed stone + Aegean light.
  olympus: {
    palette: { bg: "#1c1913", fg: "#e8dcc4", accent: "#c69a54" },
    imageUrl: UNSPLASH("1602343168117-bb8ffe3e2e9f"),
    keywords: [],
  },
};

export const MOOD_IDS: MoodId[] = Object.keys(MOODS) as MoodId[];
