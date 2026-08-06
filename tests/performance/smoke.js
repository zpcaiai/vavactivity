import { sleep } from "k6";
import { coreThresholds, get } from "./common.js";

export const options = { vus: 2, duration: "10s", thresholds: coreThresholds };
export default function () {
  get("/api/v1/health/live", "health-live");
  get("/api/v1/health/ready", "health-ready");
  get("/api/v1/public/catalog/products", "catalog-public");
  sleep(0.2);
}
