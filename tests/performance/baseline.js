import { sleep } from "k6";
import { coreThresholds, get } from "./common.js";

export const options = { stages: [{ duration: "10s", target: 5 }, { duration: "30s", target: 5 }, { duration: "10s", target: 0 }], thresholds: coreThresholds };
export default function () {
  get("/api/v1/health/live", "health");
  get("/api/v1/public/catalog/products", "catalog");
  get("/api/v1/public/courses", "courses");
  get("/api/v1/activities", "activities");
  sleep(0.5);
}
