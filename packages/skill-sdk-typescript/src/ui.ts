export const extensionPoints = [
  "admin.dashboard.widget",
  "admin.entity.detail.tab",
  "user.account.settings.card",
  "skill.execution.result.renderer"
] as const;

export type ExtensionPoint = typeof extensionPoints[number];

export type UiExtension = Readonly<{
  extensionPoint: ExtensionPoint;
  component: string;
  permissions: ReadonlyArray<string>;
  sandbox: "iframe";
  contentSecurityPolicy: Readonly<{ connectSrc: ReadonlyArray<string> }>;
}>;

export function validateUiExtension(extension: UiExtension): void {
  if (!extensionPoints.includes(extension.extensionPoint)) throw new Error("UI_EXTENSION_POINT_UNKNOWN");
  if (extension.sandbox !== "iframe") throw new Error("UI_EXTENSION_SANDBOX_REQUIRED");
  if (extension.component.startsWith("http:") || extension.component.startsWith("https:")) {
    throw new Error("UI_EXTENSION_REMOTE_SCRIPT_FORBIDDEN");
  }
  if (extension.contentSecurityPolicy.connectSrc.includes("*")) throw new Error("UI_EXTENSION_CSP_WILDCARD_FORBIDDEN");
}
