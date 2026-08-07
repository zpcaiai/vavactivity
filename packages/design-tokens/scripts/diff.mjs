import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";

const file = resolve("packages/design-tokens/generated/tokens.json");
const digest = createHash("sha256").update(await readFile(file)).digest("hex");
console.log(JSON.stringify({ file, sha256: digest, breakingReviewRequired: process.env.TOKEN_PREVIOUS_SHA256 ? process.env.TOKEN_PREVIOUS_SHA256 !== digest : false }));
