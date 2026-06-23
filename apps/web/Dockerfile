# syntax=docker/dockerfile:1.9
#
# apps/web (Next.js 15, standalone) for ECS Fargate behind the shared ALB.
#
# IMPORTANT: build with the REPO ROOT as context, not apps/web, so the pnpm
# workspace lockfile + the @ov-black/api-client workspace dependency are visible:
#
#   docker buildx build --platform linux/amd64 -f apps/web/Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.black.dev.outdoorvoyage.com \
#     --build-arg NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co \
#     --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon-key> \
#     --build-arg NEXT_PUBLIC_MAPBOX_API_KEY=<mapbox-public-token> \
#     -t <acct>.dkr.ecr.us-east-2.amazonaws.com/ov-black-web-staging:<tag> --push .
#
# The four NEXT_PUBLIC_* values are inlined into the client bundle at `next build`
# time (not read at runtime), so they MUST be passed as build args. All four are
# public-by-design; the Supabase service-role key never touches this image.

# ── base: Node 24 + pnpm via corepack ────────────────────────────────────────
FROM node:24-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo

# ── deps: resolve the web + api-client subgraph from the frozen lockfile ──────
# Copy only manifests first so this layer caches until a dependency changes.
FROM base AS deps
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json turbo.json tsconfig.base.json ./
COPY apps/web/package.json apps/web/
COPY packages/api-client/package.json packages/api-client/
COPY infra/cdk/package.json infra/cdk/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter=@ov-black/web...

# ── builder: build api-client (tsc) then web (next build, standalone) ─────────
FROM deps AS builder
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_MAPBOX_API_KEY
ENV NODE_ENV=production \
    NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_MAPBOX_API_KEY=$NEXT_PUBLIC_MAPBOX_API_KEY
COPY packages/api-client packages/api-client
COPY apps/web apps/web
# pnpm runs `build` across the filtered subgraph in topological order:
# @ov-black/api-client (tsc -> dist, since dist/ is gitignored) then @ov-black/web.
RUN pnpm --filter=@ov-black/web... run build

# ── runner: minimal image with only the standalone server output ─────────────
FROM node:24-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN groupadd --system --gid 1001 nodejs \
 && useradd --system --uid 1001 --gid nodejs nextjs
# Standalone output is rooted at the monorepo root (outputFileTracingRoot), so
# server.js lands under apps/web/ and the traced node_modules at the top level.
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/public ./apps/web/public
USER nextjs
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
