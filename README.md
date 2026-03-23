# Metadata Tools (Standalone + Backend Compatible)

This folder can run in two modes:

1. Integrated mode (inside current backend project)
2. Standalone mode (you can `git init` in this folder and use it as a separate repo)

## Scripts

- `enrich_metadata.py`
- `fix_album_art.py`
- `picard_fallback_enricher.py`

## Standalone Setup

```bash
python -m venv venv
# Windows
venv\\Scripts\\activate
# macOS/Linux
# source venv/bin/activate
pip install -r requirements.txt
```

Create `.env` (optional):

- `ACOUSTID_API_KEY=...`

## Usage

```bash
python enrich_metadata.py "D:\\music\\song.mp3" -y
python fix_album_art.py "D:\\music\\song.mp3"
```

One-command local checkup:

```bash
python pre_push.py
```

## Notes

- In integrated mode, scripts reuse backend modules from `spoflac_core` and `utils`.
- In standalone mode, scripts automatically fall back to local compatibility helpers from `standalone_compat.py`.
- For AcoustID fingerprinting you need:
  - `pyacoustid`
  - `fpcalc` installed and available in PATH
  - `ACOUSTID_API_KEY`

## Contribution & CI

- Contribution rules: `CONTRIBUTING.md`
- GitHub Actions checkup workflow: `.github/workflows/checkup.yml`
