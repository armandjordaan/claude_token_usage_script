# AGENTS.md

Guidance for AI agents working in this repo. (`CLAUDE.md` imports this file.)

## What this is

A single-purpose CLI that reports Claude Code **token spend per calendar month**
as CSV. The one tool is `token_accumulator.py`; everything else is docs.

## Run / dev

- Run: `python3 token_accumulator.py > spend.csv` — CSV (`month,tokens`) to
  stdout, a coverage report to stderr. `--by day` switches stdout to
  `date,tokens` (same store, day granularity).
- **Python standard library only** — no third-party deps, no virtualenv.
  Developed/tested on Python 3.12. Keep it dependency-free unless there's a
  strong reason.
- No automated test suite. If you change aggregation logic, validate against
  `~/.claude/stats-cache.json`: a *recent* day's deduped transcript total should
  match the cache ~1:1 (older days won't — transcripts prune). See the
  validation history in ADR 0002.

## How it works (data model)

Two individually-lossy sources are merged into a persistent store:

- **Transcripts** `~/.claude/projects/**/*.jsonl` — real-time ground truth
  (written on every API call), but pruned after ~30 days. Deduped by
  `message.id` taking the **max** `input+output` per id (streaming/iteration
  lines repeat an id with growing counts; naive sums over-count ~2.6×).
- **`~/.claude/stats-cache.json`** — backs the `/usage` Stats tab; only
  refreshed on the first `/usage` open of a day, omits today, and has gaps.
- Merged via **day-level max** into `token_store.json`, which is **monotonic**
  (a day's total never decreases).
- "Token spend" = `input_tokens + output_tokens`, cache tokens **excluded**
  (matches the Stats tab's "Total tokens"). `<synthetic>` messages skipped;
  subagent (sidechain) tokens included.

## Load-bearing decisions — do NOT undo (see `docs/adr/`)

- **No pexpect / no TUI scraping.** This repo was once named `pexpect_claude`;
  driving the `/usage` TUI was prototyped and deliberately rejected (ADR 0001).
  Read the JSON/transcripts — never automate the terminal UI.
- **Keep the two-source merge and the `message.id` max-dedup.** They look like
  over-engineering but each fixes a *verified* data-loss / over-count bug
  (ADR 0002). Don't collapse to a single source or a naive sum.
- **The store is monotonic.** The merge must never let a day's total shrink —
  that's what protects history when transcripts are partly pruned between runs.

## Conventions & gotchas

- Generated files — `token_store.json`, `spend.csv`, `accumulator.log` — are
  **gitignored**. Never commit them.
- The script locates `token_store.json` next to itself (`__file__`) and reads
  inputs via `$HOME`, so it's path-independent and cron-safe. Don't hardcode
  absolute paths into it.
- Numbers are intentionally **approximate** (~a few % vs `/usage`) because the
  two sources time-bucket differently. Expected, not a bug.
- Scheduling lives in the **user crontab** (Mondays 09:00), not in this repo —
  if you change paths or the entry point, update the crontab too.

## Docs to keep current

- `CONTEXT.md` — glossary (Token spend, Total tokens, …). Update when
  terminology shifts.
- `docs/adr/` — architecture decisions. Add one for a hard-to-reverse,
  surprising choice.
- `README.md` — user-facing usage.
