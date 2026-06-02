# Merge pruning transcripts with the stale stats cache via day-level max

Neither source of Claude Code token usage is complete on its own: `stats-cache.json` is recomputed only on the first `/usage` open of a calendar day, omits the current day, and has verified gaps (it undercounted May 2026 by ~16% and dropped 2026-05-30's 474k tokens entirely), while the session transcripts (`projects/**/*.jsonl`) are real-time ground truth but are pruned after ~30 days (`cleanupPeriodDays`). So `token_accumulator.py` reads **both**, dedupes transcript usage by `message.id` taking the max per id (streaming/iteration lines repeat an id with growing counts, which otherwise inflates totals ~2.6×), and keeps whichever source has the larger `input+output` **per day** in a persistent `token_store.json` that only ever grows.

Day-level (not per-model) max is deliberate: it avoids cross-bucket double counting when the cache and the UTC-stamped transcripts assign a midnight-boundary turn to different dates, at a cost of <0.1% versus per-model max. The store is monotonic so partial transcript pruning between runs can never shrink a day's recorded total.

## Consequences

- The tool **must run on a schedule** (a weekly cron is installed) — if more than ~30 days pass between runs, a day's transcript can be pruned before it was ever captured, and that day is then lost to both sources.
- Numbers are **approximate** (~within a few % of the `/usage` Stats tab) because the two sources time-bucket and aggregate slightly differently. They are, however, *more* complete than the cache alone.
- Once a day's transcript is pruned, its stored value can never be revised — whatever was captured before pruning is final.
