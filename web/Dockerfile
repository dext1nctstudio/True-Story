# =============================================================================
# TRUE STORY  ·  web application
# =============================================================================
# Multi stage so the runtime image carries the standalone server bundle rather
# than the whole node_modules tree.
# =============================================================================

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev 2>/dev/null || npm install --omit=dev

FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci 2>/dev/null || npm install
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0

# The standalone server.js Next.js generates binds to `process.env.HOSTNAME`,
# defaulting to "localhost" only when unset -- and most container platforms
# (Render included) auto inject their own HOSTNAME set to the container's own
# id, which the server then binds to instead. That interface is reachable
# from inside the container and from nowhere else, so the platform's edge
# proxy gets an instant connection refusal it reports as a 502, while the
# app's own logs show it as having started cleanly. Setting HOSTNAME here
# explicitly overrides whatever the platform would otherwise inject.

RUN groupadd --gid 1001 nodejs \
    && useradd --uid 1001 --gid nodejs --create-home nextjs

# `output: "standalone"` in next.config.mjs produces exactly this layout.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 8080

# Shell form, deliberately, and HOSTNAME bound here rather than only in the
# ENV block above. A platform's own container orchestration (Render's
# included, and this is a documented Kubernetes behaviour since HOSTNAME is
# how a pod learns its own name) can inject a HOSTNAME environment variable
# at the container level that arrives *after* this image's baked in ENV is
# read, silently overriding it -- observed directly: the standalone server
# logged itself listening on the container's own pod hostname instead of
# 0.0.0.0, which nothing outside the container can reach, so the platform's
# edge proxy returned an instant 502 while the app's own logs showed a clean
# start. `VAR=value command` at the point of exec always wins for that one
# child process, which no environment set earlier in the container's life
# can override, so this is the one place the standalone server's own
# `process.env.HOSTNAME || '0.0.0.0'` fallback is not left to chance.
CMD ["/bin/sh", "-c", "HOSTNAME=0.0.0.0 node server.js"]
