# syntax=docker/dockerfile:1.9
#
# apps/web (Next.js 15, standalone) for ECS Fargate behind the shared ALB.
#
# Build with the REPO ROOT as context (not apps/web), so the pnpm workspace
# lockfile + the @ov-black/api-client workspace dependency are visible:
#
#   docker buildx build --platform linux/amd64 -f apps/web/Dockerfile \
#     -t <acct>.dkr.ecr.us-east-2.amazonaws.com/ov-black-web-staging:<tag> --push .
#
# NO build args: all public config (Supabase URL + anon key, API base URL, Mapbox
# token) is read at RUNTIME from the ECS task env (OVB_*), so one image works for
# every environment. See lib/env.ts + app/layout.tsx + infra/cdk/lib/api-stack.ts.

# ── base: Node 24 + pnpm via corepack ────────────────────────────────────────
FROM node:24-slim AS base
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable
WORKDIR /repo

# ── builder: install (with source present) then build api-client + web ────────
# We copy source BEFORE `pnpm install` so the workspace is complete and pnpm
# links @ov-black/api-client into apps/web/node_modules exactly as a local
# install does — installing against bare manifests left next build unable to
# resolve the workspace package.
FROM base AS deps
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json turbo.json tsconfig.base.json ./
COPY infra/cdk/package.json infra/cdk/
COPY packages/api-client packages/api-client
COPY apps/web apps/web
# Install the web subgraph WITH devDependencies (typescript/next live there).
# Do NOT set NODE_ENV=production before this — pnpm skips devDeps in production
# mode, which leaves `tsc` missing for the api-client build. `next build` runs in
# production regardless. infra/cdk's manifest is present so the frozen lockfile
# stays satisfiable; its deps are neither installed-for-build nor shipped.
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile --filter=@ov-black/web...

FROM deps AS builder
# Build the web subgraph in topological order: @ov-black/api-client
# (tsc -> dist, since dist/ is gitignored) then @ov-black/web.
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
