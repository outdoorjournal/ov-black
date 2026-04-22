# Landing page imagery

Drop a landscape hero photo at `hero.jpg` in this directory to power the
ambient background on the home page (`apps/web/app/page.tsx`).

Recommended:

- Aspect ratio: wide landscape (2:1 or 16:9), at least 2400px on the long edge.
- Subject: atmospheric outdoor/travel imagery — dusk mountains, remote coast,
  desert dunes, alpine lake. Avoid bright midday light; the page overlays a
  dark gradient that reads best against lower-key photography.
- Format: JPG for photographic content, ~200–400 KB after compression.

If `hero.jpg` is absent the page falls back to a layered radial gradient so
the layout never breaks.
