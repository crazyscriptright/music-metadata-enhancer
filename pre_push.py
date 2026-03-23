#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run_step(label: str, cmd: list[str]) -> None:
    print(f"\n==> {label}")
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT), check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    print("Running tools pre-push checks...")

    run_step("Compile check", [PY, "-m", "compileall", "-q", "."])
    run_step(
        "Critical module check",
        [
            PY,
            "-m",
            "py_compile",
            "enrich_metadata.py",
            "fix_album_art.py",
            "picard_fallback_enricher.py",
            "standalone_compat.py",
        ],
    )
    run_step("CLI help check", [PY, "enrich_metadata.py", "--help"])
    run_step("CLI help check", [PY, "fix_album_art.py", "--help"])

    print("\n✅ Tools pre-push checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
