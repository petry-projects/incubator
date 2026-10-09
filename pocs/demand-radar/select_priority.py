#!/usr/bin/env python3
"""
DemandRadar — priority selector (spike; funnel stage 2).

Reads the broad pass (keywords.broad.jsonl) and picks the top-K ideas PER VERTICAL by
broad_interest, writing the small `keywords.priority.jsonl` that the low-throughput,
ban-prone iTunes supply pass actually scores. Per-vertical (not global top-N) so every
vertical gets supply coverage regardless of Google-Suggest bias.

  python select_priority.py --per-vertical 50
"""

import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
# Fixed data locations. Deliberately NOT CLI options: a path taken from argv would flow into
# open() (path injection); callers that need other locations (tests) pass them to run().
IN_PATH = os.path.join(HERE, "output", "keywords.broad.jsonl")
OUT_PATH = os.path.join(HERE, "output", "keywords.priority.jsonl")


def run(inp=IN_PATH, out=OUT_PATH, per_vertical=50):
    by_vert = defaultdict(list)
    with open(inp, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("broad_interest") is None:
                continue
            by_vert[r["vertical"]].append(r)

    picked = []
    for vert, rows in by_vert.items():
        rows.sort(
            key=lambda r: (r.get("broad_interest", 0), r.get("app_intent", 0), r.get("n_suggestions", 0)), reverse=True
        )
        picked.extend(rows[:per_vertical])

    # keep the schema extract.load_keywords expects, carry broad signal through
    with open(out, "w", encoding="utf-8") as f:
        for r in picked:
            f.write(
                json.dumps(
                    {
                        "keyword": r["keyword"],
                        "vertical": r["vertical"],
                        "discovery_channel": r.get("discovery_channel"),
                        "vertical_dynamics": r.get("vertical_dynamics"),
                        "broad_interest": r.get("broad_interest"),
                        "app_intent": r.get("app_intent"),
                    }
                )
                + "\n"
            )

    print(f"Selected {len(picked)} priority keywords ({per_vertical}/vertical x {len(by_vert)}) -> {out}")
    top = sorted(picked, key=lambda r: (r.get("broad_interest", 0), r.get("app_intent", 0)), reverse=True)[:20]
    print("Top 20 by broad demand:")
    for r in top:
        print(f"  bi={r.get('broad_interest')} app={r.get('app_intent')}  {r['keyword']:<26} [{r['vertical']}]")
    return len(picked)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-vertical", type=int, default=50)
    args = ap.parse_args()
    run(per_vertical=args.per_vertical)


if __name__ == "__main__":
    main()
