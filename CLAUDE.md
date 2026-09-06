# Working conventions

## Git

Commit and push every change. Do not ask first, do not leave work uncommitted,
and do not wait for review before committing — review happens on the branch.

- Work on the branch named for the task (currently `claude/map-ui-improvements-bdj87k`).
- Push with `git push -u origin <branch>`.
- `main` deploys the GitHub Pages site, so feature branches are the safe place
  to land work in progress.

## Build

```bash
python -m scripts.build --config config.yml            # static PNG: output/va_ghg_map.png
python -m scripts.build --config config.yml --target deck   # web assets: output/deck-data/
python -m scripts.diagnose_geometry                    # trace geometry when a GEOS call fails
```

Both build targets regenerate committed artifacts under `output/`; commit those
alongside the code that produced them.
