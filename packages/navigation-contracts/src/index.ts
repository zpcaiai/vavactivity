export interface RouteContract {
  route_code: string;
  route_path: string;
  authentication_required: boolean;
  permission_codes: string[];
  fallback_route_code?: string;
  help_context_code?: string;
}

const sensitiveQuery = /[?&](phone|email|address|evidence|price|token|password)=/i;

export function assertSafeRoute(contract: RouteContract) {
  if (!contract.route_code || !contract.route_path.startsWith("/")) throw new Error("invalid route contract");
  if (sensitiveQuery.test(contract.route_path)) throw new Error("sensitive route query is forbidden");
  if (contract.authentication_required && !contract.fallback_route_code) throw new Error("authenticated routes require a fallback");
  return contract;
}

export function localizeRoute(path: string, locale: string) {
  return path.replace("{locale}", encodeURIComponent(locale));
}
