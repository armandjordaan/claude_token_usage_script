# Claude Code Token Usage

Tools that read Claude Code's local usage statistics (the data behind the
`/usage` → **Stats** tab) and report token consumption over time.

## Language

**Token spend**:
The number of tokens consumed over a period, counted as `inputTokens + outputTokens`.
_Avoid_: cost (means dollars), usage (overloaded — see Flagged ambiguities)

**Total tokens**:
All-time **Token spend** summed across every model — the headline figure shown on the Stats tab.
_Avoid_: grand total

**Monthly token spend**:
**Token spend** aggregated by calendar month (`YYYY-MM`).

**Cache tokens**:
`cacheReadInputTokens + cacheCreationInputTokens`; deliberately **excluded** from **Token spend**.
_Avoid_: prompt-cache usage

**Model usage**:
A per-model record of tokens consumed by Claude Code.

## Relationships

- **Total tokens** = sum of **Monthly token spend** over all months = sum over all **Model usage** of `input + output`
- **Token spend** excludes **Cache tokens** (which are ~190× larger here, so the distinction matters)
- Dollar cost is **not** a concept this project reports — the source data's `costUSD` is unpopulated

## Example dialogue

> **Dev:** "You want per-month spend — that's tokens, right, not dollars?"
> **Domain expert:** "Tokens. There's no cost figure; the cost field is always zero."
> **Dev:** "And does spend include the cache reads? Those are over a billion."
> **Domain expert:** "No — Token spend is input + output only. Cache tokens are excluded, same as the 'Total tokens' the Stats tab shows."

## Flagged ambiguities

- "spend" was ambiguous between **dollars** and **tokens** — resolved: it means **tokens**; USD cost is not tracked.
- "usage" is overloaded between plan-limit consumption (the `/usage` → **Usage** tab: session/weekly quota) and historical **Token spend** (the **Stats** tab). This project deals only with the Stats-tab token counts.
