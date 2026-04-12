# cancerstudio Research Intelligence

This folder is the repo-local knowledge system for tracking scientific, clinical,
and tooling updates that affect the cancerstudio pipeline.

## Structure

- `briefs/daily/` stores one Markdown brief plus machine-readable JSON artifacts per run.
- `dossiers/` stores long-lived topic summaries that are rewritten from promoted findings.
- `backlog/` stores the current implementation-oriented research backlog.
- `config/` stores the taxonomy and promotion rules that drive the runner.
- `cache/` stores raw fetched payloads and is intentionally gitignored.
- `state/` stores cursors, seen-item history, and watch-page versions and is intentionally gitignored.

## Run

```bash
python3 scripts/run_research_intelligence.py
```

Or through npm:

```bash
npm run research:run
```

The runner performs three deterministic passes:

1. Broad fetch across official APIs, preprints, trial activity, and watch pages.
2. Targeted deepening for the highest-scoring candidates.
3. Synthesis into the daily brief, dossiers, and research backlog.
