import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("frontend image workflow owns both web images and emits an immutable handoff", () => {
  const workflow = read(".github/workflows/build-images.yml");
  assert.match(workflow, /name: user-web, target: user-production/u);
  assert.match(workflow, /name: admin-web, target: admin-production/u);
  assert.match(workflow, /vavactivity-web-\$\{\{ matrix\.name \}\}/u);
  assert.doesNotMatch(workflow, /\/vav-\$\{\{ matrix\.name \}\}/u);
  assert.match(workflow, /frontend_commit=\$\{GITHUB_SHA\}/u);
  assert.match(workflow, /user_web_image=.*user-web\.image/u);
  assert.match(workflow, /admin_web_image=.*admin-web\.image/u);
});

test("complete E2E explicitly assembles the split backend and frontend checkouts", () => {
  const workflow = read(".github/workflows/complete-e2e.yml");
  assert.match(workflow, /repository: zpcaiai\/vavactivity/u);
  assert.match(workflow, /VAV_WEB_ROOT:/u);
  assert.match(workflow, /VAV_BACKEND_ROOT:/u);
  assert.match(workflow, /COMPOSE_FILE:.*backend\/docker-compose\.yml/u);
  const setup = read("e2e/global-setup.ts");
  assert.match(setup, /process\.env\.VAV_BACKEND_ROOT/u);
  assert.match(setup, /cwd: backendRoot/u);
});

test("frontend container build is self-contained", () => {
  const dockerfile = read("infra/docker/frontend.Dockerfile");
  assert.match(dockerfile, /AS user-production/u);
  assert.match(dockerfile, /AS admin-production/u);
  assert.doesNotMatch(dockerfile, /services\/api|\.\.\/vavactivity/u);
});

test("production SPA delivery sets browser security and cache controls", () => {
  const nginx = ["spa.nginx.conf", "security-headers.conf"]
    .map((file) => read(`infra/docker/${file}`))
    .join("\n");
  for (const header of [
    "Content-Security-Policy",
    "Permissions-Policy",
    "Referrer-Policy",
    "X-Content-Type-Options",
    "X-Frame-Options"
  ]) {
    assert.match(nginx, new RegExp(`add_header ${header}`));
  }
  assert.match(nginx, /Cache-Control "public, immutable"/);
  assert.match(nginx, /Cache-Control "no-cache"/);
});
