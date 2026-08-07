const permissionPattern = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,5}$/u;

export function validatePermissions(values: Iterable<string>): ReadonlySet<string> {
  const permissions = new Set(values);
  for (const permission of permissions) {
    if (!permissionPattern.test(permission) || permission.includes("*")) {
      throw new Error(`Invalid or overbroad Skill permission: ${permission}`);
    }
  }
  return permissions;
}

export function effectivePermissions(
  caller: Iterable<string>,
  installation: Iterable<string>,
  manifest: Iterable<string>,
  runtime: Iterable<string>
): ReadonlySet<string> {
  const layers = [caller, installation, manifest, runtime].map(validatePermissions);
  return new Set([...layers[0]].filter((value) => layers.slice(1).every((layer) => layer.has(value))));
}

export function requirePermission(contextPermissions: ReadonlySet<string>, permission: string): void {
  validatePermissions([permission]);
  if (!contextPermissions.has(permission)) throw new Error("SKILL_PERMISSION_DENIED");
}
