import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const packageManifest = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8")
);
const source = readFileSync(new URL("../src/extension.js", import.meta.url), "utf8");

test("extension activates for canonical manifests and supplies safe local commands", () => {
  assert.ok(packageManifest.activationEvents.includes("workspaceContains:**/skill.yaml"));
  const commands = packageManifest.contributes.commands.map((item) => item.command);
  for (const expected of ["vavSkills.create", "vavSkills.validate", "vavSkills.test", "vavSkills.build", "vavSkills.doctor"]) {
    assert.ok(commands.includes(expected));
  }
});

test("extension never offers grant, production activation, signing, or Marketplace approval", () => {
  const surface = JSON.stringify(packageManifest) + source;
  assert.doesNotMatch(surface, /grantProduction|activateProduction|signOfficial|approveMarketplace/u);
  assert.doesNotMatch(surface, /VAV_ACCESS_TOKEN|PRIVATE_KEY|--token/u);
});

test("manifest schema association is fail closed", () => {
  assert.deepEqual(packageManifest.contributes.yamlValidation[0].fileMatch, ["**/skill.yaml"]);
  assert.equal(packageManifest.contributes.yamlValidation[0].url, "./schemas/skill-manifest.schema.json");
  const bundledSchema = JSON.parse(
    readFileSync(new URL("../schemas/skill-manifest.schema.json", import.meta.url), "utf8")
  );
  assert.equal(bundledSchema.additionalProperties, false);
  assert.ok(Array.isArray(bundledSchema.required));
  assert.ok(bundledSchema.required.includes("metadata"));
});
