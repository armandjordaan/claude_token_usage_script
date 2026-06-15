# Claude Code monthly token spend

A small tool that reports how many tokens you've spent in Claude Code, per
calendar month, as CSV.

```
python3 token_accumulator.py > spend.csv
```

Stdout is `month,tokens` CSV; a coverage report (and any pruning warnings) go
to stderr.

For a day-by-day breakdown, pass `--by day` (stdout becomes `date,tokens`):

```
python3 token_accumulator.py --by day > spend-daily.csv
```

Both views read the same store — the monthly numbers are just the daily ones
summed by calendar month — so neither re-harvests differently.

## Why it works the way it does

The obvious source — the `/usage` → Stats tab and its file
`~/.claude/stats-cache.json` — is **lossy**: it only recomputes on the first
`/usage` open of a day, omits the current day, and has real gaps (it had
undercounted one month by ~16% and dropped a 474k-token day entirely). The
**session transcripts** (`~/.claude/projects/**/*.jsonl`) are real-time ground
truth, written on every API call with no action from you — but they're pruned
after ~30 days.

So `token_accumulator.py` reads **both**, dedupes transcript usage by
`message.id` (taking the max per id), and keeps whichever source has the larger
`input + output` **per day** in a persistent store, `token_store.json`, that
only ever grows. Recent days come from the transcripts; older days, once their
transcripts prune, come from the cache.

See [docs/adr/](docs/adr/) for the full reasoning and [CONTEXT.md](CONTEXT.md)
for terminology.

## Scheduling

A weekly cron is installed to keep the store current without you opening
`/usage`:

```
0 9 * * 1  python3 .../token_accumulator.py > .../spend.csv 2>> .../accumulator.log
```

**Run it at least every ~30 days.** If a gap longer than the transcript
retention window opens up, days can be pruned before they're ever captured and
are then lost. The stderr report prints the newest transcript day seen and
warns when it's older than 25 days.

## What counts as a token

`input_tokens + output_tokens` — cache-read and cache-creation tokens are
**excluded** (matching the Stats tab's "Total tokens"). `<synthetic>` messages
are skipped; subagent (sidechain) tokens are included.

Totals are **approximate** — within a few percent of what `/usage` shows, since
the two sources time-bucket slightly differently. They are, however, *more*
complete than the cache alone.

## Files

| File | Role | In git? |
|---|---|---|
| `token_accumulator.py` | the tool | yes |
| `CONTEXT.md`, `docs/adr/` | glossary + decisions | yes |
| `token_store.json` | persistent accumulated store | **no** (gitignored) |
| `spend.csv`, `accumulator.log` | generated output | no (gitignored) |

> **Back up `token_store.json`.** It's gitignored as generated data, but it is
> the *only* durable home for any day the cache missed once that day's
> transcript has pruned. If you'd rather have it under version control, remove
> it from `.gitignore` and commit it.
