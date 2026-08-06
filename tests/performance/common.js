import http from "k6/http";
import { check } from "k6";

export const baseUrl = __ENV.BASE_URL || "http://localhost:8000";

export function get(path, label) {
  const response = http.get(`${baseUrl}${path}`, { tags: { journey: label } });
  check(response, { [`${label}: status below 500`]: (result) => result.status < 500 });
  return response;
}

export const coreThresholds = {
  checks: ["rate>=0.99"],
  http_req_failed: ["rate<0.01"],
  http_req_duration: ["p(95)<500", "p(99)<1500"]
};
