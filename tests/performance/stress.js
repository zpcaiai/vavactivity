import { sleep } from "k6";
import { coreThresholds, get } from "./common.js";

const local = __ENV.K6_PROFILE === "local";
export const options = {
  stages: local
    ? [{ duration: "10s", target: 10 }, { duration: "10s", target: 25 }, { duration: "10s", target: 40 }, { duration: "10s", target: 0 }]
    : [{ duration: "3m", target: 50 }, { duration: "3m", target: 100 }, { duration: "3m", target: 200 }, { duration: "2m", target: 0 }],
  thresholds: coreThresholds
};

export default function () {
  get("/api/v1/public/catalog/products", "catalog-stress");
  get("/api/v1/public/courses", "course-stress");
  sleep(0.1);
}
