FROM node:24.4.1-alpine3.22

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

RUN corepack enable

WORKDIR /workspace

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY apps/user-web/package.json ./apps/user-web/package.json
COPY apps/admin-web/package.json ./apps/admin-web/package.json
COPY packages/api-client/package.json ./packages/api-client/package.json
COPY packages/contracts/package.json ./packages/contracts/package.json
COPY packages/design-tokens/package.json ./packages/design-tokens/package.json
COPY packages/eslint-config/package.json ./packages/eslint-config/package.json

RUN corepack pnpm install --frozen-lockfile \
    --filter @vav/user-web... \
    --filter @vav/admin-web...

COPY apps ./apps
COPY packages ./packages

CMD ["corepack", "pnpm", "--filter", "@vav/user-web", "dev"]
