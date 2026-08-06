import { coreThresholds, get } from "./common.js";
export const options = { vus: 5, duration: "30s", thresholds: coreThresholds };
export default function () { get("/api/v1/public/content/pages/home?locale=zh-CN", "home"); get("/api/v1/public/catalog/products", "catalog"); }
