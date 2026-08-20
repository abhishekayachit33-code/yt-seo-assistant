# Built from frontend/:
#     docker build -f frontend/Dockerfile frontend
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, not read
# at runtime, so the browser-facing API URL has to be known here. Defaults
# to the dev server's; override with --build-arg for a real deployment.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# NextAuth needs a secret present during the build's page-collection pass.
# Scoped to this one RUN rather than set as ENV so the placeholder does not
# persist into an image layer -- a baked-in AUTH_SECRET would be a real
# secret in any image that did use it at runtime. The runtime value comes
# from the environment (see docker-compose.yml).
RUN AUTH_SECRET=build-time-placeholder npm run build


FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# output: "standalone" emits a server.js plus only the node_modules actually
# reached at runtime. static/ and public/ are not included in it and must be
# copied separately.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
