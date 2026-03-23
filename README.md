# Metadata Tools (Standalone + Backend Compatible)

This folder can run in two modes:

1. Integrated mode (inside current backend project)
2. Standalone mode (you can `git init` in this folder and use it as a separate repo)

## Scripts

- `music_metadata_enhancer/enrich_metadata.py`
- `music_metadata_enhancer/fix_album_art.py`
- `music_metadata_enhancer/picard_fallback_enricher.py`

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
python music_metadata_enhancer/enrich_metadata.py "D:\\music\\song.mp3" -y
python music_metadata_enhancer/fix_album_art.py "D:\\music\\song.mp3"
```

One-command local checkup:

```bash
python music_metadata_enhancer/pre_push.py
```

## Notes

- In integrated mode, scripts reuse backend modules from `spoflac_core` and `utils`.
- In standalone mode, scripts automatically fall back to local compatibility helpers from `music_metadata_enhancer/standalone_compat.py`.
- For AcoustID fingerprinting you need:
  - `pyacoustid`
  - `fpcalc` installed and available in PATH
  - `ACOUSTID_API_KEY`

## Contribution & CI

- Contribution rules: `CONTRIBUTING.md`
- GitHub Actions checkup workflow: `.github/workflows/checkup.yml`

## Publish-ready Scaffolding

This folder now contains both release tracks:

Python package structure:

```text
music-metadata-enhancer/
├── music_metadata_enhancer/
│   ├── __init__.py
│   └── main.py
├── pyproject.toml
├── README.md
└── LICENSE
```

- **PyPI**: `pyproject.toml`
  - Build: `python -m build`
  - Publish: `python -m twine upload dist/*`
  - CLI entry points after install:
    - `mme-enrich`
    - `mme-fix-art`

- **npm wrapper**: `package.json` + `bin/`
  - Packs Node CLIs that call local Python scripts.
  - CLI entry points after install:
    - `mme-enrich`
    - `mme-fix-art`
  - Publish: `npm publish`

> Note: npm package requires Python 3 installed on the target machine.
