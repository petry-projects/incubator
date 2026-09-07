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


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--in", dest="inp", default=os.path.join(here, "output", "keywords.broad.jsonl"))
    ap.add_argument("--out", default=os.path.join(here, "output", "keywords.priority.jsonl"))
    ap.add_argument("--per-vertical", type=int, default=50)
    args = ap.parse_args()

    by_vert = defaultdict(list)
    for l in open(args.inp):
        r = json.loads(l)
        if r.get("broad_interest") is None:
            continue
        by_vert[r["vertical"]].append(r)

    picked = []
    for vert, rows in by_vert.items():
        rows.sort(key=lambda r: (r.get("broad_interest", 0), r.get("app_intent", 0),
                                 r.get("n_suggestions", 0)), reverse=True)
        picked.extend(rows[: args.per_vertical])

    # keep the schema extract.py --keywords expects, carry broad signal through
    with open(args.out, "w") as f:
        for r in picked:
            f.write(json.dumps({
                "keyword": r["keyword"], "vertical": r["vertical"],
                "discovery_channel": r.get("discovery_channel"),
                "vertical_dynamics": r.get("vertical_dynamics"),
                "broad_interest": r.get("broad_interest"),
                "app_intent": r.get("app_intent"),
            }) + "\n")

    print(f"Selected {len(picked)} priority keywords ({args.per_vertical}/vertical x {len(by_vert)}) -> {args.out}")
    top = sorted(picked, key=lambda r: (r.get("broad_interest", 0), r.get("app_intent", 0)), reverse=True)[:20]
    print("Top 20 by broad demand:")
    for r in top:
        print(f"  bi={r.get('broad_interest')} app={r.get('app_intent')}  {r['keyword']:<26} [{r['vertical']}]")


if __name__ == "__main__":
    main()
