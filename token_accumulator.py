#!/usr/bin/env python3
"""Accumulate Claude Code token spend by month into a persistent store.

WHY THIS EXISTS
    Claude Code's /usage Stats tab (and its backing file
    ~/.claude/stats-cache.json) is lossy: it only recomputes when you open
    /usage (at most once/day), omits the current day, and has verified gaps
    (whole active days missing). The ground truth is the session transcripts
    (~/.claude/projects/**/*.jsonl), which Claude Code writes automatically on
    every API call -- but those are pruned after ~30 days (cleanupPeriodDays).

    This tool merges BOTH sources into a persistent store (token_store.json)
    that never prunes, taking the day-level max so it keeps whichever source
    is more complete for each day:
      * recent days  -> deduped transcripts (complete, matches the cache ~1:1)
      * older days   -> stats-cache.json    (transcripts already pruned)
      * days the cache missed entirely (e.g. 2026-05-30) -> transcripts
    Run it on a schedule (e.g. weekly cron) so each day is captured before its
    transcript ages out. The persistent max guards against a day shrinking if
    its transcripts are partly pruned between runs.

DEFINITIONS / CAVEATS
    "Token spend" = input_tokens + output_tokens (cache tokens excluded),
    matching the Stats tab's "Total tokens". <synthetic> messages are skipped;
    subagent (sidechain) tokens are included (and tracked separately).
    Transcript records are deduped by message.id taking the MAX usage seen
    (streaming/iteration lines repeat the same id with growing counts).
    Numbers are approximate (~within ~5-10% of /usage) -- the two sources
    aggregate and time-bucket slightly differently.

OUTPUT
    A CSV on stdout -- ``month,tokens,input,output`` by default, or
    ``date,tokens,input,output`` with ``--by day``. ``tokens`` is the total;
    ``input``/``output`` break it down where a transcript-derived split exists
    and are left blank for older cache-only days (the split is unrecoverable
    there). A coverage report goes to stderr.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
DEFAULT_PROJECTS = HOME / ".claude" / "projects"
DEFAULT_STATS_CACHE = HOME / ".claude" / "stats-cache.json"
DEFAULT_STORE = Path(__file__).resolve().parent / "token_store.json"
PRUNE_WARN_DAYS = 25  # warn if newest transcript is older than this (~cleanupPeriodDays)


def harvest_transcripts(projects_dir: Path) -> dict[str, dict]:
    """Aggregate per-day token usage from transcript jsonl files.

    Dedupes by ``message.id`` taking the max input+output for each id (streaming
    / iteration lines repeat an id with growing counts), sums per (date, model),
    then collapses to a day record. Returns ``{date: {inout, input, output,
    cache_read, cache_creation, messages, sidechain_inout, models, source}}``.
    """
    # tmp[(date, model)][message_id] = best record seen for that id
    tmp: dict[tuple[str, str], dict] = defaultdict(dict)
    noid = 0
    for fp in glob.glob(str(projects_dir / "**" / "*.jsonl"), recursive=True):
        try:
            fh = open(fp, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    continue
                ts = obj.get("timestamp")
                msg = obj.get("message")
                if not ts or not isinstance(msg, dict):
                    continue
                model = msg.get("model")
                if not model or model == "<synthetic>":
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                inp = usage.get("input_tokens") or 0
                out = usage.get("output_tokens") or 0
                io = inp + out
                mid = msg.get("id")
                if not mid:
                    mid, noid = f"_noid_{noid}", noid + 1
                bucket = tmp[(ts[:10], model)]
                prev = bucket.get(mid)
                if prev is None or io > prev["inout"]:
                    bucket[mid] = {
                        "inout": io,
                        "input": inp,
                        "output": out,
                        "cache_read": usage.get("cache_read_input_tokens") or 0,
                        "cache_creation": usage.get("cache_creation_input_tokens") or 0,
                        "sidechain": bool(obj.get("isSidechain")),
                    }

    days: dict[str, dict] = {}
    for (date, model), recs in tmp.items():
        day = days.setdefault(date, {
            "inout": 0, "input": 0, "output": 0, "cache_read": 0,
            "cache_creation": 0, "messages": 0, "sidechain_inout": 0,
            "models": {}, "source": "transcript",
        })
        model_inout = 0
        for r in recs.values():
            model_inout += r["inout"]
            day["input"] += r["input"]
            day["output"] += r["output"]
            day["cache_read"] += r["cache_read"]
            day["cache_creation"] += r["cache_creation"]
            day["messages"] += 1
            if r["sidechain"]:
                day["sidechain_inout"] += r["inout"]
        day["inout"] += model_inout
        day["models"][model] = model_inout
    return days


def seed_from_stats_cache(path: Path) -> dict[str, dict]:
    """Per-day input+output from stats-cache.json's daily series.

    The daily integer is already input+output (cache excluded), verified
    against modelUsage. Used as a floor: the day-level max-merge lets it win
    for older days whose transcripts have been pruned.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict] = {}
    for entry in data.get("dailyModelTokens", []):
        date = entry.get("date")
        if not date:
            continue
        models = {m: int(v) for m, v in entry.get("tokensByModel", {}).items()}
        out[date] = {"inout": sum(models.values()), "models": models, "source": "stats-cache"}
    return out


def merge_into(store_days: dict, fresh: dict) -> None:
    """Day-level max-merge ``fresh`` into ``store_days`` in place.

    Per day, keep whichever source has the larger input+output total -- recent
    days favour the (complete) transcripts, older days favour the cache once
    transcripts prune. Monotonic: a day's total never decreases, so partial
    pruning between runs cannot shrink history. On a tie the richer transcript
    record wins. Day-level (not per-model) avoids cross-bucket double counting
    when the two sources assign a midnight-boundary turn to different dates.
    """
    for date, rec in fresh.items():
        cur = store_days.get(date)
        if (
            cur is None
            or rec["inout"] > cur["inout"]
            or (rec["inout"] == cur["inout"]
                and cur.get("source") != "transcript"
                and rec.get("source") == "transcript")
        ):
            store_days[date] = rec


def aggregate(store_days: dict, by: str) -> dict[str, dict]:
    """Roll the store up by ``"month"`` (``YYYY-MM``) or ``"day"`` (``YYYY-MM-DD``).

    Returns ``{key: {"tokens", "input", "output"}}``. ``tokens`` is always the
    authoritative input+output total. ``input``/``output`` are summed only over
    days that carry a transcript-derived split; a key with no such day reports
    them as ``None`` (cache-only history never stored the split -- it's
    unrecoverable, so the CSV leaves those cells blank rather than guess 0).
    For a month mixing transcript and cache days, ``input + output`` is the
    known portion and is therefore < ``tokens``.
    """
    keylen = 7 if by == "month" else 10
    agg: dict[str, dict] = {}
    for date, rec in store_days.items():
        row = agg.setdefault(date[:keylen], {"tokens": 0, "input": None, "output": None})
        row["tokens"] += rec["inout"]
        if "input" in rec and "output" in rec:
            row["input"] = (row["input"] or 0) + rec["input"]
            row["output"] = (row["output"] or 0) + rec["output"]
    return agg


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE,
                    help="persistent store file (default: next to this script)")
    ap.add_argument("--projects", type=Path, default=DEFAULT_PROJECTS,
                    help="Claude Code projects/ transcript dir")
    ap.add_argument("--stats-cache", type=Path, default=DEFAULT_STATS_CACHE,
                    help="stats-cache.json used as a historical floor")
    ap.add_argument("--no-harvest", action="store_true",
                    help="report from the existing store without reading transcripts")
    ap.add_argument("--no-seed", action="store_true",
                    help="do not merge stats-cache.json")
    ap.add_argument("--by", choices=("month", "day"), default="month",
                    help="CSV granularity: calendar month (default) or calendar day")
    args = ap.parse_args(argv[1:])

    if args.store.exists():
        try:
            store = json.loads(args.store.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"store {args.store} is corrupt; refusing to overwrite", file=sys.stderr)
            return 1
    else:
        store = {"schema": 1, "days": {}, "meta": {}}
    days = store.setdefault("days", {})
    store.setdefault("meta", {})
    before_keys = set(days)

    last_tx_day = None
    if not args.no_harvest:
        fresh = harvest_transcripts(args.projects)
        if fresh:
            last_tx_day = max(fresh)
        merge_into(days, fresh)
        if not args.no_seed:
            merge_into(days, seed_from_stats_cache(args.stats_cache))
        store["meta"]["last_harvest_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if last_tx_day:
            store["meta"]["last_transcript_day"] = last_tx_day
        tmp_path = args.store.with_name(args.store.name + ".tmp")
        tmp_path.write_text(json.dumps(store, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp_path, args.store)

    new_days = sorted(set(days) - before_keys)

    # ---- coverage report (stderr) ----
    lines = [f"# store: {args.store}"]
    if days:
        tx_days = sum(1 for rec in days.values() if rec.get("source") == "transcript")
        lines.append(
            f"# coverage: {min(days)} .. {max(days)}  "
            f"({len(days)} days; {tx_days} from transcripts, "
            f"{len(days) - tx_days} cache-only)"
        )
    newest = store["meta"].get("last_transcript_day") or last_tx_day
    if newest:
        lines.append(f"# newest transcript day seen: {newest}")
        try:
            age = (datetime.now(timezone.utc).date()
                   - datetime.strptime(newest, "%Y-%m-%d").date()).days
            if age > PRUNE_WARN_DAYS:
                lines.append(
                    f"# WARNING: newest transcript is {age}d old (> ~{PRUNE_WARN_DAYS}d) "
                    "-- run more often or days will be lost to pruning"
                )
        except ValueError:
            pass
    if not args.no_harvest:
        lines.append(
            f"# new days added this run: {len(new_days)}"
            + (f" ({new_days[0]} .. {new_days[-1]})" if new_days else "")
        )
    lines.append(
        "# tokens = input+output (cache excluded, subagents included); "
        "current day is partial until UTC midnight"
    )
    if days:
        nosplit = sum(rec["inout"] for rec in days.values() if "input" not in rec)
        if nosplit:
            lines.append(
                f"# input/output columns blank for {len(days) - tx_days} cache-only "
                f"days ({nosplit} tokens) -- split unrecoverable, total still counted"
            )
    print("\n".join(lines), file=sys.stderr)

    # ---- CSV (stdout): one row per month (default) or per day (--by day) ----
    rows = aggregate(days, args.by)
    header = "date" if args.by == "day" else "month"
    writer = csv.writer(sys.stdout)
    writer.writerow([header, "tokens", "input", "output"])
    for key in sorted(rows):
        r = rows[key]
        writer.writerow([
            key, r["tokens"],
            "" if r["input"] is None else r["input"],
            "" if r["output"] is None else r["output"],
        ])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
