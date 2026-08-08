# Hugging Face Docker Space image: build both Vue applications and expose them
# through one unprivileged nginx process on the Space port.
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
COPY packages/experience-components/package.json ./packages/experience-components/package.json
COPY packages/help-components/package.json ./packages/help-components/package.json
COPY packages/journey-contracts/package.json ./packages/journey-contracts/package.json
COPY packages/navigation-contracts/package.json ./packages/navigation-contracts/package.json
COPY packages/search-components/package.json ./packages/search-components/package.json
COPY packages/ui-admin/package.json ./packages/ui-admin/package.json
COPY packages/ui-core/package.json ./packages/ui-core/package.json
COPY packages/ui-user/package.json ./packages/ui-user/package.json
RUN --mount=type=cache,target=/pnpm/store \
    corepack pnpm install --store-dir=/pnpm/store --frozen-lockfile \
      --filter @vav/user-web... --filter @vav/admin-web...

FROM dependencies AS build
COPY apps ./apps
COPY packages ./packages
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_ADMIN_BASE_PATH=/admin/
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN corepack pnpm --filter @vav/design-tokens build \
    && corepack pnpm --filter @vav/user-web build \
    && VITE_BASE_PATH="$VITE_ADMIN_BASE_PATH" corepack pnpm --filter @vav/admin-web build

FROM nginxinc/nginx-unprivileged:1.31.3-alpine3.24@sha256:a6c3ec0c0d249d68b0682df854d4a9e222b90fb607dc3fcf2f1d2fcbc85d347e
COPY deploy/huggingface/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/user-web/dist /usr/share/nginx/html
COPY --from=build /workspace/apps/admin-web/dist /usr/share/nginx/html/admin
EXPOSE 7860
USER 101:101
