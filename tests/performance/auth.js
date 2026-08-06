import http from "k6/http"; import { check } from "k6"; import { baseUrl, coreThresholds } from "./common.js";
export const options = { vus: 3, duration: "20s", thresholds: coreThresholds };
export default function () { const r=http.post(`${baseUrl}/api/v1/auth/login`, JSON.stringify({email:__ENV.TEST_EMAIL||"load@example.invalid",password:__ENV.TEST_PASSWORD||"invalid"}), {headers:{"Content-Type":"application/json"}}); check(r,{"auth bounded response":x=>[200,401,422,429].includes(x.status)}); }
