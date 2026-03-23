#!/usr/bin/env node
const { spawnSync } = require("child_process");
const path = require("path");

function findPython() {
  const candidates = [];

  if (process.env.PYTHON) {
    candidates.push([process.env.PYTHON, []]);
  }

  if (process.platform === "win32") {
    candidates.push(["py", ["-3"]]);
  }

  candidates.push(["python3", []]);
  candidates.push(["python", []]);

  for (const [cmd, prefix] of candidates) {
    const probe = spawnSync(cmd, [...prefix, "--version"], { stdio: "ignore" });
    if (probe.status === 0) {
      return { cmd, prefix };
    }
  }

  return null;
}

function runPythonScript(scriptName, scriptArgs) {
  const python = findPython();
  if (!python) {
    console.error(
      "Python 3 not found. Install Python and ensure it is in PATH.",
    );
    process.exit(1);
  }

  const scriptPath = path.resolve(__dirname, "..", scriptName);
  const args = [...python.prefix, scriptPath, ...scriptArgs];

  const result = spawnSync(python.cmd, args, { stdio: "inherit" });

  if (typeof result.status === "number") {
    process.exit(result.status);
  }

  process.exit(1);
}

module.exports = { runPythonScript };
