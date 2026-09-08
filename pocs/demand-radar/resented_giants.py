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
import argparse, json, os, re, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "DemandRadar-spike/0.6 (+petry-projects/incubator; research)"
CATS = {
    "pricing": ["used to be free", "cost money", "costs money", "now costs", "pay for", "pay to",
                "paywall", "behind a paywall", "subscription", "subscribe", "premium", "expensive",
                "charge", "money grab", "cash grab", "greedy", "rip off", "ripoff", "overpriced",
                "free version", "no longer free", "have to pay"],
    "ads": ["ads", "adverts", "advertisement", "pop up", "pop-up", "popup", "commercials",
            "so many ads", "full of ads", "ad every"],
    "enshittification": ["used to be", "used to love", "used to work", "got worse", "gotten worse",
                         "getting worse", "downhill", "ruined", "ruining", "bring back", "worse now",
                         "not the same", "since the update", "update ruined", "went downhill", "was better"],
    "missing": ["took away", "removed", "no longer", "took out", "gutted", "basic feature", "can't even"],
}
SWITCH = ("pricing", "ads", "enshittification")  # the gripes that actually drive users to leave


def _cat_pattern(kws):
    """Compile a category's terms into a boundary-aware regex so 'ads' matches 'ads'/'so
    many ads' but not 'heads', and 'charge' doesn't match 'discharge'. Boundaries are added
    only where the term edge is a word char (phrases and symbols still match literally)."""
    parts = []
    for k in kws:
        esc = re.escape(k)
        left = r"\b" if k[:1].isalnum() else ""
        right = r"\b" if k[-1:].isalnum() else ""
        parts.append(left + esc + right)
    return re.compile("|".join(parts))


CAT_RE = {c: _cat_pattern(kws) for c, kws in CATS.items()}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15).read()


def resolve_id(name):
    try:
        d = json.loads(get("https://itunes.apple.com/search?" + urllib.parse.urlencode(
            {"term": name, "country": "us", "entity": "software", "limit": 1})))
        return (d.get("results") or [{}])[0].get("trackId")
    except Exception:
        return None


def fetch_low_reviews(tid):
    """Recent 1-3 star reviews as (rating, title, content)."""
    out = []
    for page in (1, 2):
        try:
            r = json.loads(get(f"https://itunes.apple.com/us/rss/customerreviews/page={page}/id={tid}/sortBy=mostRecent/json"))
        except Exception:
            break
        for e in r.get("feed", {}).get("entry", []):
            rt = e.get("im:rating", {}).get("label")
            if rt and int(rt) <= 3:
                out.append((int(rt), (e.get("title", {}).get("label") or ""), (e.get("content", {}).get("label") or "")))
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
    return {"n_low": n, "cat_hits": cat_hits, "switch_hits": switch_hits,
            "resent_frac": round(switch_hits / n, 2) if n else 0.0, "gripes": gripes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(HERE, "output", "records.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "output", "resented.json"))
    ap.add_argument("--min-market", type=int, default=8000)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=2.2)
    args = ap.parse_args()

    with open(args.inp, encoding='utf-8') as f:
        records = [json.loads(l) for l in f]
    leaders = {}
    for r in records:
        ms = r["supply"].get("market_size") or 0
        if ms < args.min_market:
            continue
        lead = next((a for a in r["supply"].get("solutions", []) if (a.get("rating_count") or 0) == ms and a.get("app")), None)
        if not lead:
            continue
        k = lead["app"].lower()
        if k not in leaders or ms > leaders[k]["market"]:
            leaders[k] = {"app": lead["app"], "id": lead.get("id"), "market": ms,
                          "vert": r["industry"], "kw": r["canonical_query"], "leaderR": r["supply"].get("leader_rating")}

    if os.path.exists(args.out):
        with open(args.out, encoding='utf-8') as f:
            out = json.load(f)
    else:
        out = {}
    todo = [k for k in leaders if k not in out]
    if args.max:
        todo = todo[: args.max]
    print(f"proven-market leaders: {len(leaders)} | already done: {len(out)} | to process: {len(todo)}", flush=True)

    for i, k in enumerate(todo):
        L = leaders[k]
        tid = L["id"] or resolve_id(L["app"])
        time.sleep(args.sleep)
        if not tid:
            out[k] = {**L, "resented": False, "note": "no-id"}
            continue
        sc = scan(fetch_low_reviews(tid))
        time.sleep(args.sleep)
        resented = L["market"] >= args.min_market and sc["switch_hits"] >= 4 and sc["resent_frac"] >= 0.25
        out[k] = {**L, "id": tid, **sc, "resented": resented}
        if (i + 1) % 10 == 0:
            with open(args.out, "w", encoding='utf-8') as f:
                json.dump(out, f)
            print(f"  {i+1}/{len(todo)}  (resented so far: {sum(1 for v in out.values() if v.get('resented'))})", flush=True)

    with open(args.out, "w", encoding='utf-8') as f:
        json.dump(out, f)
    rg = sorted([v for v in out.values() if v.get("resented")],
                key=lambda v: -(v["resent_frac"] * (v["market"] ** 0.5)))
    print(f"\nRESENTED GIANTS: {len(rg)}")
    for v in rg[:20]:
        cats = ",".join(c for c in SWITCH if v.get("cat_hits", {}).get(c))
        print(f"  {v.get('leaderR')}star /{v['market']:>9,}  resent={int(v['resent_frac']*100)}% [{cats}]  {v['app'][:34]}  (e.g. '{v['kw']}' [{v['vert']}])")
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
