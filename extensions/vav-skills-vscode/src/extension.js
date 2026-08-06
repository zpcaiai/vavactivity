"use strict";

const vscode = require("vscode");

const SAFE_COMMANDS = Object.freeze({
  validate: ["validate", "--directory", "."],
  test: ["test", "--directory", "."],
  doctor: ["doctor", "--directory", "."]
});

function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function rootPath() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) throw new Error("Open a trusted VAV workspace first.");
  return folder.uri.fsPath;
}

function launch(command, args) {
  const configuration = vscode.workspace.getConfiguration("vavSkills");
  const cliPath = configuration.get("cliPath", "./scripts/vavctl");
  if (cliPath.includes("\n") || cliPath.includes("\0")) {
    throw new Error("Invalid VAV CLI path.");
  }
  const terminal = vscode.window.createTerminal({name: `VAV Skill: ${command}`, cwd: rootPath()});
  terminal.show();
  terminal.sendText([shellQuote(cliPath), "skill", command, ...args.map(shellQuote)].join(" "), true);
}

async function createSkill() {
  const name = await vscode.window.showInputBox({
    prompt: "Reverse-domain Skill name",
    validateInput: (value) => /^[a-z0-9]+(?:[.-][a-z0-9]+)+$/u.test(value) ? undefined : "Use a canonical Skill name."
  });
  if (!name) return;
  const type = await vscode.window.showQuickPick(
    ["query", "command", "workflow", "agent-tool", "event-handler", "provider-adapter", "domain-pack"],
    {placeHolder: "Skill type"}
  );
  if (!type) return;
  launch("create", ["--name", name, "--type", type, "--runtime", "python", "--directory", `skill-packs/internal/${name}`]);
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("vavSkills.create", createSkill),
    ...Object.entries(SAFE_COMMANDS).map(([name, args]) =>
      vscode.commands.registerCommand(`vavSkills.${name}`, () => launch(name, args))
    ),
    vscode.commands.registerCommand("vavSkills.build", () =>
      launch("build", ["--directory", ".", "--output", "dist/skill.vavskill"])
    ),
    vscode.commands.registerCommand("vavSkills.schemaDiff", () =>
      vscode.window.showInformationMessage(
        "Run vav skill schema diff with explicit --from-schema and --to-schema paths. Major-version and privacy review gates cannot be bypassed."
      )
    )
  );
}

function deactivate() {}

module.exports = {activate, deactivate, SAFE_COMMANDS, shellQuote};
