"""Loading the current opportunity records for the reporting stages
(export_dashboard.py, rank_starter_list.py)."""

import json
import os


def _read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _key(rec):
    return rec.get("industry"), rec.get("canonical_query")


def load_current(here):
    """Every record scored so far, each in its most enriched form.

    output/records.jsonl is appended to by every supply batch; output/records.enriched.jsonl
    is a full rewrite from the last *successful* enrichment. Reading only the enriched file
    would hide records appended after an enrichment that failed or was skipped, so start from
    the base file and overlay the enriched copy of each record that has one."""
    base = os.path.join(here, "output", "records.jsonl")
    enriched = os.path.join(here, "output", "records.enriched.jsonl")
    if not os.path.exists(enriched):
        return _read(base)
    enriched_rows = _read(enriched)
    if not os.path.exists(base):
        return enriched_rows
    by_key = {_key(r): r for r in enriched_rows}
    return [by_key.get(_key(r), r) for r in _read(base)]
