FROM node:24.4.1-alpine3.22@sha256:820e86612c21d0636580206d802a726f2595366e1b867e564cbc652024151e8a AS dependencies

ENV PNPM_HOME="/pnpm" COREPACK_HOME="/corepack" PATH="/pnpm:$PATH" PNPM_CONFIG_FETCH_RETRIES="5"
RUN corepack enable
WORKDIR /workspace

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY apps/user-web/package.json ./apps/user-web/package.json
COPY apps/admin-web/package.json ./apps/admin-web/package.json
COPY packages/api-client/package.json ./packages/api-client/package.json
COPY packages/contracts/package.json ./packages/contracts/package.json
COPY packages/design-tokens/package.json ./packages/design-tokens/package.json
COPY packages/eslint-config/package.json ./packages/eslint-config/package.json
RUN --mount=type=cache,target=/corepack \
    --mount=type=cache,target=/pnpm/store \
    corepack pnpm install --store-dir=/pnpm/store --frozen-lockfile --filter @vav/user-web... --filter @vav/admin-web...

FROM dependencies AS development
COPY apps ./apps
COPY packages ./packages
CMD ["corepack", "pnpm", "--filter", "@vav/user-web", "dev"]

FROM development AS build-user
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN corepack pnpm --filter @vav/user-web build

FROM development AS build-admin
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN corepack pnpm --filter @vav/admin-web build

FROM nginxinc/nginx-unprivileged:1.27.4-alpine3.21@sha256:62a904036bfc0e4a4f2b556e34cbf17bc136b47fde8cdb4628762725f48c5782 AS user-production
COPY infra/docker/spa.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-user /workspace/apps/user-web/dist /usr/share/nginx/html
USER 101:101

FROM nginxinc/nginx-unprivileged:1.27.4-alpine3.21@sha256:62a904036bfc0e4a4f2b556e34cbf17bc136b47fde8cdb4628762725f48c5782 AS admin-production
COPY infra/docker/spa.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-admin /workspace/apps/admin-web/dist /usr/share/nginx/html
USER 101:101
