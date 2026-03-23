#!/usr/bin/env node
const { runPythonScript } = require("./_python_runner");
runPythonScript(
  "music_metadata_enhancer/fix_album_art.py",
  process.argv.slice(2),
);
