FROM node:24.4.1-alpine3.22

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

RUN corepack enable

WORKDIR /workspace

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY apps ./apps
COPY packages ./packages

RUN corepack pnpm install --frozen-lockfile

CMD ["corepack", "pnpm", "--filter", "@vav/user-web", "dev"]

