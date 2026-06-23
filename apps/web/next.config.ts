import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Containerized deploy (ECS Fargate behind the shared ALB) ships the
  // self-contained standalone server (.next/standalone/apps/web/server.js)
  // instead of `next start`. outputFileTracingRoot pins file-tracing to the
  // monorepo root so the standalone node_modules + server.js nesting is
  // deterministic across machines (default would guess from the lockfile).
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../../"),
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
