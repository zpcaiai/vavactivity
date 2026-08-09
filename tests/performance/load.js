import { sleep } from "k6";
import { coreThresholds, get } from "./common.js";

const local = __ENV.K6_PROFILE === "local";
export const options = {
  stages: local
    ? [{ duration: "5s", target: 10 }, { duration: "20s", target: 10 }, { duration: "5s", target: 0 }]
    : [{ duration: "1m", target: 50 }, { duration: "10m", target: 50 }, { duration: "1m", target: 0 }],
  thresholds: coreThresholds
};

export default function () {
  get("/api/v1/public/catalog/products", "catalog-load");
  get("/api/v1/public/courses", "course-load");
  get("/api/v1/activities", "activity-load");
  sleep(0.2);
}
