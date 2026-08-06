import { coreThresholds, get } from "./common.js"; export const options={vus:5,duration:"20s",thresholds:coreThresholds}; export default function(){get("/api/v1/public/courses","course-list");}
