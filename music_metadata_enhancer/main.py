from __future__ import annotations

import argparse
import importlib
import sys


def _run_module_main(module_name: str, args: list[str]) -> int:
    try:
        module = importlib.import_module(f"music_metadata_enhancer.{module_name}")
    except Exception:
        module = importlib.import_module(module_name)
    original_argv = sys.argv[:]
    try:
        sys.argv = [module_name, *args]
        module.main()
        return 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        return code
    finally:
        sys.argv = original_argv


def enrich_cli() -> int:
    return _run_module_main("enrich_metadata", sys.argv[1:])


def fix_art_cli() -> int:
    return _run_module_main("fix_album_art", sys.argv[1:])


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="mme",
        description="Music Metadata Enhancer CLI",
    )
    sub = parser.add_subparsers(dest="command")

    enrich = sub.add_parser("enrich", help="Run metadata enrichment")
    enrich.add_argument("args", nargs=argparse.REMAINDER)

    fix_art = sub.add_parser("fix-art", help="Run album art fixer")
    fix_art.add_argument("args", nargs=argparse.REMAINDER)

    ns = parser.parse_args()

    if ns.command == "enrich":
        return _run_module_main("enrich_metadata", ns.args)
    if ns.command == "fix-art":
        return _run_module_main("fix_album_art", ns.args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
