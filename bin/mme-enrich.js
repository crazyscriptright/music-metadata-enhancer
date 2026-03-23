#!/usr/bin/env node
const { runPythonScript } = require("./_python_runner");
runPythonScript(
  "music_metadata_enhancer/enrich_metadata.py",
  process.argv.slice(2),
);
