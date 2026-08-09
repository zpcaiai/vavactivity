import { sleep } from "k6";
import { coreThresholds, get } from "./common.js";

const local = __ENV.K6_PROFILE === "local";
export const options = {
  stages: local
    ? [{ duration: "5s", target: 5 }, { duration: "5s", target: 30 }, { duration: "10s", target: 30 }, { duration: "5s", target: 0 }]
    : [{ duration: "1m", target: 10 }, { duration: "20s", target: 150 }, { duration: "3m", target: 150 }, { duration: "1m", target: 0 }],
  thresholds: coreThresholds
};

export default function () {
  get("/api/v1/health/ready", "ready-spike");
  get("/api/v1/public/catalog/products", "catalog-spike");
  sleep(0.1);
}
