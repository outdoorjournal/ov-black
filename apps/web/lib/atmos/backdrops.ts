// The atmospheric backdrop pool — the big curated set of dark-cinematic
// travel frames behind the immersive surfaces (the /new intake, and any
// future full-bleed moment).
//
// Same Unsplash CDN convention as lib/atmos/moods.ts (2400px, q=80,
// auto=format, fit=crop; images.unsplash.com is allowlisted in
// next.config.ts). Every id below was verified against the CDN and visually
// curated: landscape-first, horizon-heavy, reads well under the ink veil.
// The front door's five hero frames lead the list so the hand-off from
// landing → first adventure feels like one continuous room.

const UNSPLASH = (id: string): string =>
  `https://images.unsplash.com/photo-${id}?w=2400&q=80&auto=format&fit=crop`;

export const ATMOSPHERIC_BACKDROPS: readonly string[] = [
  // ── the front-door set (app/page.tsx) ────────────────────────────────────
  UNSPLASH("1761141954476-2921e2e43e99"), // kyoto-zen — pagoda at golden dusk
  UNSPLASH("1634951412593-b2cdca1ae519"), // monsoon — Ha Long Bay karsts
  UNSPLASH("1761078206756-68d3023f3021"), // savannah — acacia at orange sunset
  UNSPLASH("1732045133230-1a670eef8620"), // highland — misty Scottish crags
  UNSPLASH("1717508723994-ec9c13a6d4bc"), // andes — red desert ranges
  // ── peaks & alpenglow ────────────────────────────────────────────────────
  UNSPLASH("1506905925346-21bda4d32df4"), // alpenglow summits over a cloud sea
  UNSPLASH("1464822759023-fed622ff2c3b"), // blue range over pine valley
  UNSPLASH("1519681393784-d120267933ba"), // milky way over a snowbound peak
  UNSPLASH("1483728642387-6c3bdd6c93e5"), // teal twilight mountain wall
  UNSPLASH("1469474968028-56623f02e42e"), // sunbeams raking green ridgelines
  UNSPLASH("1508739773434-c26b3d09e071"), // dolomites pass at golden hour
  UNSPLASH("1454496522488-7a8e488e8606"), // himalayan massif in snow
  UNSPLASH("1486870591958-9b9d0d1dda99"), // lone snow peak over golden steppe
  UNSPLASH("1544735716-392fe2489ffa"), // stupa beneath the Everest wall
  // ── water: lakes, fjords, falls ──────────────────────────────────────────
  UNSPLASH("1476514525535-07fb3b4ae5f1"), // wooden prow gliding Lago di Braies
  UNSPLASH("1493246507139-91e8fad9978e"), // Moraine Lake at alpenglow
  UNSPLASH("1439066615861-d1af74d74000"), // still dock on a glass lake
  UNSPLASH("1501785888041-af3ef285b470"), // turquoise water, drifting boats
  UNSPLASH("1433086966358-54859d0ed716"), // waterfall under a stone footbridge
  UNSPLASH("1476610182048-b716b8518aae"), // Icelandic falls at pink dusk
  UNSPLASH("1527004013197-933c4bb611b3"), // Lofoten red cabins on the sound
  UNSPLASH("1508672019048-805c876b67e2"), // fjord dock, mountains closing in
  UNSPLASH("1503220317375-aaad61436b1b"), // backpacker reading a fjord
  // ── coast & islands ──────────────────────────────────────────────────────
  UNSPLASH("1510414842594-a61c69b5ae57"), // turquoise cove, big sur cliffs
  UNSPLASH("1505142468610-359e7d316be0"), // aerial surf, teal on white
  UNSPLASH("1507525428034-b723cf961d3e"), // low sun on a wet shoreline
  UNSPLASH("1519046904884-53103b34b206"), // palms over a quiet beach
  UNSPLASH("1533105079780-92b9be482077"), // santorini terrace over the caldera
  // ── desert, savannah, far places ─────────────────────────────────────────
  UNSPLASH("1547234935-80c7145ec969"), // Wadi Rum's red silence
  UNSPLASH("1516026672322-bc52d61a55d5"), // lone acacia against the sun
  UNSPLASH("1523805009345-7448845a9e53"), // giraffe in amber grass
  UNSPLASH("1516426122078-c23e76319801"), // safari at last light
  UNSPLASH("1526392060635-9d6019884377"), // Machu Picchu wearing its clouds
  UNSPLASH("1504457047772-27faf1c00561"), // karst river village, mirror water
  UNSPLASH("1530789253388-582c481c54b0"), // hot-air balloons over Cappadocia
  // ── forest & green ───────────────────────────────────────────────────────
  UNSPLASH("1441974231531-c6227db76b6e"), // light through old-growth pines
  UNSPLASH("1447752875215-b2761acb3c5d"), // footbridge into deep forest
  UNSPLASH("1470071459604-3b5ec3a7fe05"), // highland mist at sundown
  UNSPLASH("1502082553048-f009c37129b9"), // one grand tree in an open field
  // ── the leaving itself ───────────────────────────────────────────────────
  UNSPLASH("1476900543704-4312b78632f8"), // wing over a sunset from the window seat
];
