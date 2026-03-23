# Contributing to Metadata Tools

Thanks for contributing to this standalone tools package.

## Scope

This repo focuses on:

- `music_metadata_enhancer/enrich_metadata.py`
- `music_metadata_enhancer/fix_album_art.py`
- `music_metadata_enhancer/picard_fallback_enricher.py`
- `music_metadata_enhancer/standalone_compat.py`

Keep changes scoped to metadata/artwork tooling.

## Local Setup

```bash
python -m venv venv
# Windows
venv\\Scripts\\activate
# macOS/Linux
# source venv/bin/activate
pip install -r requirements.txt
```

Optional environment variables in `.env`:

- `ACOUSTID_API_KEY` for AcoustID fingerprint lookup

## Development Rules

- Prefer root-cause fixes over temporary workarounds.
- Keep backward compatibility for both standalone mode and integrated backend mode.
- Avoid unrelated refactors in the same PR.
- Keep CLI behavior stable unless change is intentional and documented.

## Checkup Rules (before PR)

Run these locally:

```bash
python -m compileall -q .
python -m py_compile music_metadata_enhancer/enrich_metadata.py music_metadata_enhancer/fix_album_art.py music_metadata_enhancer/picard_fallback_enricher.py music_metadata_enhancer/standalone_compat.py
python music_metadata_enhancer/enrich_metadata.py --help
python music_metadata_enhancer/fix_album_art.py --help
```

## Pull Request Checklist

- [ ] Change is focused and minimal
- [ ] Syntax checks pass
- [ ] Help/CLI behavior still works
- [ ] README or usage docs updated if behavior changed
- [ ] Notes included for env/dependency changes (if any)

## Commit Guidance

Use clear commit messages:

- `fix: ...` bug fix
- `feat: ...` new behavior
- `chore: ...` maintenance/docs

Example: `fix: fallback to standalone compat when backend modules unavailable`
