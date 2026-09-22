# Arrival: A&E Wait Times

## What this is
A Hong Kong A&E waiting-time forecaster for the HKUST AI Literacy Course (Path E).
It takes the Hospital Authority's single published wait figure and shows it against
what that department usually publishes at the same hour of the week, plus the 1-in-20
long wait and travel time. Students run it locally from one double-clickable launcher.

## Status
Working on macOS and Windows. Windows was broken until 2026-09-22 and is now fixed.
Student tutorial written. Fixes are committed locally but NOT yet pushed to GitHub.

## Current progress
- [x] Engine, routing, frontend and launchers built
- [x] 488 tests pass (`uv run --group test pytest` in `engine/`)
- [x] Fixed the Windows-fatal `ZoneInfoNotFoundError` (see Decisions)
- [x] Fixed three smaller launcher faults: unescaped `&` in the .bat `title`,
      LF-only line endings in the .bat, and silenced uv-installer errors
- [x] `A&E Wait Times - Student Tutorial.docx` written, 13 pages with screenshots
- [ ] Push the fixes to https://github.com/northlight7/arrival-ae-wait-times
      (students downloading the ZIP still get the broken Windows build until this happens)
- [ ] Re-test on a real Windows machine after the push

## Decisions
- **Pure Python, no compiled wheels.** `stats.py` reproduces numpy's default quantile so
  the shipped app needs no wheel matching the user's CPU. numpy exists only in the `test`
  dependency group, to prove the two agree. Keep it that way.
- **`tzdata` is a win32-only dependency.** Windows ships no IANA time-zone database, so
  `ZoneInfo("Asia/Hong_Kong")` raised at import and the server never started. `engine.py`
  also falls back to a fixed UTC+8 with a printed warning, which is exact rather than a
  guess because Hong Kong has had no DST since 1979.
- **The app refuses rather than invents.** Outside the current Hong Kong hour there is no
  published-versus-normal comparison, because the board only ever publishes a figure for
  right now. A hospital with no honest travel time is dropped from the ranking and named.
  This refusal is the teaching point of the whole project, and the tutorial is built
  around triggering it on purpose.
- **Everything installs inside the folder.** The launchers redirect every uv cache and
  Python install into the project directory, so deleting the folder removes every trace
  and no admin password is needed.

## Notes
- Run it: double-click `LAUNCHER.command` (macOS) or `LAUNCHER.bat` (Windows), then open
  http://127.0.0.1:8094.
- `.gitattributes` forces CRLF on `*.bat`. Do not remove it: cmd.exe seeks through a batch
  file as it runs, and LF-only endings break `goto` into the labels the error paths use.
- `data/ae_corpus.json` (232 MB) and `data/ae_corpus.next.json` (136 MB) are gitignored.
  The shipped corpus is `ae_corpus.json.gz`. `.next.json` is an unmerged backfill and is
  deliberately kept, not stale.
- Tutorial working files live in `.internal/`: `build_tutorial.py` regenerates the docx
  from `.internal/screenshots/`. That folder is gitignored.
- Two live feeds, both open data, no key: the Hospital Authority A&E board and the
  Transport Department speed detectors.
