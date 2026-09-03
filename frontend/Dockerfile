# Multi-stage build using Next.js's "standalone" output (next.config.ts)
# so the final image only carries what's actually needed at runtime.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-slim AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Baked in at build time - if this needs to change per-environment, rebuild
# the image rather than relying on a runtime env var (Next.js inlines
# NEXT_PUBLIC_* values into the client bundle at build time).
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN npm run build

FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
# Docker sets HOSTNAME to the container's own ID by default, and Next's
# standalone server binds to process.env.HOSTNAME when it's set - without
# this override it ends up listening on that container-ID hostname instead
# of all interfaces, so nothing outside the container (a platform's proxy
# included) can ever reach it, even though the process is running fine.
# Known Next.js standalone-Docker gotcha - not specific to any one host.
ENV HOSTNAME="0.0.0.0"
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
