import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  typedRoutes: true,
  images: {
    // Mood-frame backgrounds load directly from the Unsplash CDN — see
    // lib/atmos/moods.ts. Keeping them remote avoids committing ~7 MB of
    // binary placeholders and lets the curated photo IDs evolve without
    // touching the repo.
    remotePatterns: [
      { protocol: "https", hostname: "images.unsplash.com" },
    ],
  },
};

export default nextConfig;
