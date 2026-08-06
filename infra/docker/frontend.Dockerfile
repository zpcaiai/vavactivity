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

FROM nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:a6c3ec0c0d249d68b0682df854d4a9e222b90fb607dc3fcf2f1d2fcbc85d347e AS user-production
COPY infra/docker/spa.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-user /workspace/apps/user-web/dist /usr/share/nginx/html
USER 101:101

FROM nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:a6c3ec0c0d249d68b0682df854d4a9e222b90fb607dc3fcf2f1d2fcbc85d347e AS admin-production
COPY infra/docker/spa.nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-admin /workspace/apps/admin-web/dist /usr/share/nginx/html
USER 101:101
