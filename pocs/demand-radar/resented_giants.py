#!/usr/bin/env python3
"""
DemandRadar — resented-giant detector (disruption lens, review-TEXT signal).

Star ratings are a dead end for disruption (App Store skews 4.6+). The real
Quizlet/Booklet play is a WELL-RATED giant users resent for monetization. This
finds them: for every proven-market leader (max-review relevant incumbent, >=8k
reviews) it pulls recent 1-3 star reviews via Apple's FREE customer-reviews RSS
and scores pricing / ads / enshittification gripes — regardless of star rating.

Output: output/resented.json  { leader_lower: {app,id,market,resent_frac,gripes,resented,...} }
Resumable (skips leaders already processed). Paced to avoid iTunes throttling.

  python resented_giants.py [--max N] [--min-market 8000]
"""

import argparse
import json
import os
import time
import urllib.parse
import urllib.request

from patterns import cat_pattern

HERE = os.path.dirname(os.path.abspath(__file__))
# Fixed data locations. Deliberately NOT CLI options: a path taken from argv would flow into
# open() (path injection); callers that need other locations (tests) pass them to run().
IN_PATH = os.path.join(HERE, "output", "records.jsonl")
OUT_PATH = os.path.join(HERE, "output", "resented.json")
UA = "DemandRadar-spike/0.6 (+petry-projects/incubator; research)"
CATS = {
    "pricing": [
        "used to be free",
        "cost money",
        "costs money",
        "now costs",
        "pay for",
        "pay to",
        "paywall",
        "behind a paywall",
        "subscription",
        "subscribe",
        "premium",
        "expensive",
        "charge",
        "money grab",
        "cash grab",
        "greedy",
        "rip off",
        "ripoff",
        "overpriced",
        "free version",
        "no longer free",
        "have to pay",
    ],
    "ads": [
        "ads",
        "adverts",
        "advertisement",
        "pop up",
        "pop-up",
        "popup",
        "commercials",
        "so many ads",
        "full of ads",
        "ad every",
    ],
    "enshittification": [
        "used to be",
        "used to love",
        "used to work",
        "got worse",
        "gotten worse",
        "getting worse",
        "downhill",
        "ruined",
        "ruining",
        "bring back",
        "worse now",
        "not the same",
        "since the update",
        "update ruined",
        "went downhill",
        "was better",
    ],
    "missing": ["took away", "removed", "no longer", "took out", "gutted", "basic feature", "can't even"],
}
SWITCH = ("pricing", "ads", "enshittification")  # the gripes that actually drive users to leave


CAT_RE = {c: cat_pattern(kws) for c, kws in CATS.items()}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15).read()


def resolve_id(name):
    """Look a leader's track id up by app name. Only an exact (case-insensitive) title match
    counts: taking the first search hit could attribute another app's reviews to this leader."""
    try:
        d = json.loads(
            get(
                "https://itunes.apple.com/search?"
                + urllib.parse.urlencode({"term": name, "country": "us", "entity": "software", "limit": 5})
            )
        )
    except Exception:  # noqa: BLE001
        return None
    want = name.strip().lower()
    return next(
        (r.get("trackId") for r in d.get("results") or [] if (r.get("trackName") or "").strip().lower() == want),
        None,
    )


def fetch_low_reviews(tid):
    """Recent 1-3 star reviews as (rating, title, content), or None when no page could be
    fetched at all (timeout/throttle) — "no sample" must not read as "no complaints"."""
    out = []
    for page in (1, 2):
        try:
            r = json.loads(
                get(f"https://itunes.apple.com/us/rss/customerreviews/page={page}/id={tid}/sortBy=mostRecent/json")
            )
        except Exception:  # noqa: BLE001
            if page == 1:
                return None
            break
        for e in r.get("feed", {}).get("entry", []):
            rt = e.get("im:rating", {}).get("label")
            if rt and int(rt) <= 3:
                out.append(
                    (int(rt), (e.get("title", {}).get("label") or ""), (e.get("content", {}).get("label") or ""))
                )
        time.sleep(0.4)
    return out


def scan(reviews):
    n = len(reviews)
    cat_hits = {c: 0 for c in CATS}
    gripes = []
    switch_hits = 0
    for rt, title, body in reviews:
        hay = (title + " . " + body).lower()
        hit_cats = [c for c, rx in CAT_RE.items() if rx.search(hay)]
        for c in hit_cats:
            cat_hits[c] += 1
        if any(c in SWITCH for c in hit_cats):
            switch_hits += 1
            if len(gripes) < 4:
                gripes.append({"r": rt, "t": title[:60], "b": body[:150], "c": [c for c in hit_cats if c in SWITCH]})
    return {
        "n_low": n,
        "cat_hits": cat_hits,
        "switch_hits": switch_hits,
        "resent_frac": round(switch_hits / n, 2) if n else 0.0,
        "gripes": gripes,
    }


def run(inp=IN_PATH, out_path=OUT_PATH, min_market=8000, max_n=0, sleep=2.2):
    with open(inp, encoding="utf-8") as f:
        records = [json.loads(line) for line in f]
    leaders = {}
    for r in records:
        ms = r["supply"].get("market_size") or 0
        if ms < min_market:
            continue
        lead = next(
            (a for a in r["supply"].get("solutions", []) if (a.get("rating_count") or 0) == ms and a.get("app")), None
        )
        if not lead:
            continue
        k = lead["app"].lower()
        if k not in leaders or ms > leaders[k]["market"]:
            leaders[k] = {
                "app": lead["app"],
                "id": lead.get("id"),
                "market": ms,
                "vert": r["industry"],
                "kw": r["canonical_query"],
                "leaderR": r["supply"].get("leader_rating"),
            }

    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as f:
            out = json.load(f)
    else:
        out = {}
    todo = [k for k in leaders if k not in out]
    if max_n:
        todo = todo[:max_n]
    print(f"proven-market leaders: {len(leaders)} | already done: {len(out)} | to process: {len(todo)}", flush=True)

    unfetched = 0
    for i, k in enumerate(todo):
        L = leaders[k]
        tid = L["id"] or resolve_id(L["app"])
        time.sleep(sleep)
        if not tid:
            out[k] = {**L, "resented": False, "note": "no-id"}
            continue
        reviews = fetch_low_reviews(tid)
        time.sleep(sleep)
        if reviews is None:
            # Not recorded, so the next (resumed) run retries this leader instead of
            # treating a failed fetch as a completed "not resented" scan.
            unfetched += 1
            continue
        sc = scan(reviews)
        resented = L["market"] >= min_market and sc["switch_hits"] >= 4 and sc["resent_frac"] >= 0.25
        out[k] = {**L, "id": tid, **sc, "resented": resented}
        if (i + 1) % 10 == 0:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(out, f)
            print(
                f"  {i + 1}/{len(todo)}  (resented so far: {sum(1 for v in out.values() if v.get('resented'))})",
                flush=True,
            )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    rg = sorted(
        [v for v in out.values() if v.get("resented")], key=lambda v: -(v["resent_frac"] * (v["market"] ** 0.5))
    )
    print(f"\nRESENTED GIANTS: {len(rg)}")
    for v in rg[:20]:
        cats = ",".join(c for c in SWITCH if v.get("cat_hits", {}).get(c))
        print(
            f"  {v.get('leaderR')}star /{v['market']:>9,}  resent={int(v['resent_frac'] * 100)}% [{cats}]  {v['app'][:34]}  (e.g. '{v['kw']}' [{v['vert']}])"
        )
    if unfetched:
        print(f"\n{unfetched} leader(s) had no fetchable reviews this run; left pending for the next one")
    print(f"\n-> {out_path}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-market", type=int, default=8000)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=2.2)
    args = ap.parse_args()
    run(min_market=args.min_market, max_n=args.max, sleep=args.sleep)


if __name__ == "__main__":
    main()
