import { extensionPoints, validateUiExtension, type ExtensionPoint } from "@vav/skill-sdk";

export { extensionPoints };
export type { ExtensionPoint };

export type ExtensionRegistration = Readonly<{
  id: string;
  extensionPoint: ExtensionPoint;
  assetPath: string;
  assetSha256: string;
  permissions: ReadonlyArray<string>;
  connectSrc: ReadonlyArray<string>;
}>;

export type HostEnvelope = Readonly<{
  protocol: "vav.skill-ui/v1";
  requestId: string;
  type: "host.response" | "host.error";
  payload: unknown;
}>;

export type ExtensionEnvelope = Readonly<{
  protocol: "vav.skill-ui/v1";
  requestId: string;
  type: "extension.ready" | "extension.resize" | "extension.invoke";
  payload: unknown;
}>;

const ID = /^[a-z0-9]+(?:[.-][a-z0-9]+)+$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const PERMISSION = /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,6}$/u;
const ASSET = /^ui\/dist\/[A-Za-z0-9._/-]+\.js$/u;

function canonicalOrigin(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "https:" && url.hostname !== "localhost") {
    throw new Error("UI_EXTENSION_ORIGIN_HTTPS_REQUIRED");
  }
  return url.origin;
}

export function validateRegistration(registration: ExtensionRegistration): void {
  validateUiExtension({
    extensionPoint: registration.extensionPoint,
    component: registration.assetPath,
    permissions: registration.permissions,
    sandbox: "iframe",
    contentSecurityPolicy: { connectSrc: registration.connectSrc }
  });
  if (!ID.test(registration.id)) throw new Error("UI_EXTENSION_ID_INVALID");
  if (!SHA256.test(registration.assetSha256)) throw new Error("UI_EXTENSION_DIGEST_INVALID");
  if (!ASSET.test(registration.assetPath) || registration.assetPath.includes("..")) {
    throw new Error("UI_EXTENSION_ASSET_PATH_INVALID");
  }
  if (new Set(registration.permissions).size !== registration.permissions.length) {
    throw new Error("UI_EXTENSION_PERMISSION_DUPLICATE");
  }
  if (registration.permissions.some((permission) => !PERMISSION.test(permission))) {
    throw new Error("UI_EXTENSION_PERMISSION_INVALID");
  }
  for (const source of registration.connectSrc) {
    if (source !== "self") canonicalOrigin(source);
  }
}

export function iframePolicy(
  registration: ExtensionRegistration,
  artifactBaseUrl: string
): Readonly<{
  src: string;
  sandbox: "allow-scripts";
  referrerPolicy: "no-referrer";
  csp: string;
}> {
  validateRegistration(registration);
  const base = new URL(artifactBaseUrl);
  const src = new URL(registration.assetPath, base);
  if (src.origin !== base.origin) throw new Error("UI_EXTENSION_CROSS_ORIGIN_ASSET_FORBIDDEN");
  src.searchParams.set("sha256", registration.assetSha256);
  const connect = registration.connectSrc.map((item) => item === "self" ? "'self'" : canonicalOrigin(item));
  return {
    src: src.toString(),
    sandbox: "allow-scripts",
    referrerPolicy: "no-referrer",
    csp: [
      "default-src 'none'",
      "script-src 'self'",
      "style-src 'self'",
      `connect-src ${connect.length ? connect.join(" ") : "'none'"}`,
      "img-src 'self' data:",
      "font-src 'self'",
      "base-uri 'none'",
      "form-action 'none'",
      "frame-ancestors 'self'"
    ].join("; ")
  };
}

function isEnvelope(value: unknown): value is ExtensionEnvelope {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return candidate.protocol === "vav.skill-ui/v1"
    && typeof candidate.requestId === "string"
    && candidate.requestId.length >= 8
    && ["extension.ready", "extension.resize", "extension.invoke"].includes(String(candidate.type));
}

export function createHostMessageHandler(options: Readonly<{
  expectedOrigin: string;
  frameWindow: Window;
  allowedActions: ReadonlySet<string>;
  invoke: (action: string, input: unknown) => Promise<unknown>;
}>): (event: MessageEvent<unknown>) => Promise<void> {
  const expectedOrigin = canonicalOrigin(options.expectedOrigin);
  return async (event: MessageEvent<unknown>): Promise<void> => {
    if (event.origin !== expectedOrigin || event.source !== options.frameWindow || !isEnvelope(event.data)) {
      return;
    }
    const envelope = event.data;
    if (envelope.type !== "extension.invoke") return;
    const request = envelope.payload as Record<string, unknown> | null;
    const action = request && typeof request.action === "string" ? request.action : "";
    const response = (type: HostEnvelope["type"], payload: unknown): void => {
      options.frameWindow.postMessage({
        protocol: "vav.skill-ui/v1",
        requestId: envelope.requestId,
        type,
        payload
      } satisfies HostEnvelope, expectedOrigin);
    };
    if (!options.allowedActions.has(action)) {
      response("host.error", { code: "UI_EXTENSION_ACTION_DENIED" });
      return;
    }
    try {
      response("host.response", await options.invoke(action, request?.input));
    } catch {
      response("host.error", { code: "UI_EXTENSION_INVOCATION_FAILED" });
    }
  };
}
