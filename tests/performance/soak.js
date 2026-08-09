import { sleep } from "k6";
import { coreThresholds, get } from "./common.js";

const local = __ENV.K6_PROFILE === "local";
export const options = {
  vus: local ? 5 : 25,
  duration: __ENV.SOAK_DURATION || (local ? "1m" : "2h"),
  thresholds: coreThresholds
};

export default function () {
  get("/api/v1/health/ready", "ready-soak");
  get("/api/v1/public/catalog/products", "catalog-soak");
  get("/api/v1/activities", "activity-soak");
  sleep(0.5);
}
