# Observed Play Import Candidates

Place raw PTCG Live battle log exports here for import into the observed-play corpus.

## Rules

- **Do not commit raw log files.** The `.gitignore` prevents `.txt`, `.md`, and `.log` files
  in this directory from being committed. This README is the only committed file here.
- One battle per file.
- Use `.txt` or `.md` extensions.
- Filename should include archetypes if known.
  Example: `gardevoir-vs-dragapult-2026-05-10.md`
- Do not manually rewrite card names unless correcting obvious export corruption.
- Include decklist markdown in a separate file when available.

## Current Priority Gaps (Phase 7.2c gate)

| Priority | Archetype | Target | Current |
|---|---|---|---|
| 1 | Salazzle ex | ≥5 clean logs | 1 |
| 1 | Gardevoir vs Dragapult (cross-matchup) | ≥3 logs for this pair | 1 |
| 2 | Charizard ex | ≥5 clean logs | 1 |
| 2 | Crustle vs Dragapult (cross-matchup) | ≥3 logs for this pair | 0 |
| 2 | Gardevoir vs non-mirror | ≥3 logs for any pair | 1 |

## Import Procedure

After staging files here, run the observed-play import flow through the existing API or
the backend service. Do not create a new importer. See:

```text
backend/app/api/observed_play.py
backend/app/observed_play/ingest.py
```

Then rerun the corpus readiness gate:
```text
docs/proposals/OBSERVED_PLAY_CORPUS_EXPANSION_PHASE_7_2_READINESS_REPORT.md
```
