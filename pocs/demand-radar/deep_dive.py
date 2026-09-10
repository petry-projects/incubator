#!/usr/bin/env python3
"""
DemandRadar — deep dive on a top pick (disruption / market opportunity brief).

Answers "how do I win this market?" for one keyword: pulls the competitor set (what
users actually see when they search), mines each leader's reviews for what users
HATE (the openings) and what they LOVE (what to preserve), reads the pricing/staleness
landscape, and synthesizes a WEDGE + writes a readable opportunity brief.

  python deep_dive.py --keyword "mood tracker"
  python deep_dive.py --keyword "guitar chords" --top 8 --pages 3

Outputs: output/deepdive/<slug>.json  and  output/deepdive/<slug>.md
Free data only (iTunes Search API + customer-reviews RSS). Paced; no auth.
"""
import argparse, collections, json, os, re, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "DemandRadar-spike/0.6 (+petry-projects/incubator; research)"

GRIPES = {
    "pricing / paywall": ["paywall", "behind a wall", "locked behind", "subscription", "subscribe",
        "premium", "pay for", "pay to", "have to pay", "costs money", "cost money", "now costs",
        "not free", "isn't free", "used to be free", "expensive", "overpriced", "money grab",
        "cash grab", "greedy", "rip off", "ripoff", "charge", "$"],
    "ads": ["ads", "adverts", "advertisement", "pop up", "pop-up", "popup", "commercials", "full of ads"],
    "got worse (enshittification)": ["used to", "got worse", "gotten worse", "downhill", "ruined",
        "bring back", "worse now", "not the same", "since the update", "update ruined", "was better"],
    "bugs / reliability": ["bug", "crash", "crashes", "glitch", "broken", "won't open", "wont open",
        "freezes", "freezing", "lag", "laggy", "sync issue", "lost my data", "lost data"],
    "missing / limited": ["wish", "missing", "no way to", "can't", "cant", "needs a", "would be nice",
        "please add", "add a", "no option", "lacks", "limited"],
}
# the gripe categories that actually drive users to abandon/switch (resentment signal)
RESENT_CATS = ("pricing / paywall", "ads", "got worse (enshittification)")
LOVES = ["simple", "easy", "clean", "love it", "love this", "best", "intuitive", "private", "offline",
         "no ads", "free", "cute", "aesthetic", "minimal", "beautiful", "fast", "reliable", "customizable"]
WISH_RE = re.compile(r"(?:wish|would love|needs?|please add|no way to|can'?t)\b[^.!?]{0,80}", re.I)


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20).read()


def load_ma_label(kw):
    p = os.path.join(HERE, "labels", "mobileaction-labels.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            labels = json.load(fh).get("labels", [])
        for label in labels:
            if label["keyword"].lower() == kw.lower():
                return label
    return None


def competitors(kw, top):
    d = json.loads(get("https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": kw, "country": "us", "entity": "software", "limit": max(top, 10)})))
    return d.get("results", [])[:top]


def reviews(tid, pages):
    out = []
    for pg in range(1, pages + 1):
        try:
            r = json.loads(get(f"https://itunes.apple.com/us/rss/customerreviews/page={pg}/id={tid}/sortBy=mostRecent/json"))
        except Exception:  # noqa: BLE001
            break
        for e in r.get("feed", {}).get("entry", []):
            rt = e.get("im:rating", {}).get("label")
            if rt:
                out.append((int(rt), e.get("title", {}).get("label", ""), e.get("content", {}).get("label", "")))
        time.sleep(0.4)
    return out


def analyze_reviews(revs):
    low = [x for x in revs if x[0] <= 3]
    high = [x for x in revs if x[0] >= 4]
    gcat = collections.Counter()
    quotes = collections.defaultdict(list)
    resenting = 0  # count each low review AT MOST ONCE toward resent_frac (not per category)
    for rt, t, b in low:
        hay = (t + " . " + b).lower()
        hit_resent = False
        for c, kws in GRIPES.items():
            if any(k in hay for k in kws):
                gcat[c] += 1
                if c in RESENT_CATS:
                    hit_resent = True
                if len(quotes[c]) < 3:
                    quotes[c].append({"r": rt, "t": t[:70], "b": b[:160]})
        if hit_resent:
            resenting += 1
    loves = collections.Counter()
    for rt, t, b in high:
        hay = (t + " . " + b).lower()
        for w in LOVES:
            if w in hay:
                loves[w.replace(" it", "").replace(" this", "")] += 1
    wishes = []
    for rt, t, b in low + high:
        for m in WISH_RE.findall(b):
            s = m.strip()
            if 12 < len(s) < 90 and s.lower() not in [w.lower() for w in wishes]:
                wishes.append(s)
    return {"n": len(revs), "n_low": len(low), "n_high": len(high),
            "resent_frac": round(resenting / len(low), 2) if low else 0,
            "gripes": dict(gcat), "quotes": {k: v for k, v in quotes.items()},
            "loves": dict(loves.most_common(8)), "wishes": wishes[:6]}


WEDGE_TEMPLATES = {
    "pricing / paywall": "**Fix the money model** ({n} gripes — the dominant complaint): win with a genuinely useful free tier or a one-time unlock, not another subscription/paywall-after-2-entries.",
    "ads": "**Ship ad-free** ({n} gripes): ads are a repeated complaint here, and 'no ads' is itself a selling point users praise.",
    "got worse (enshittification)": "**Be the simple, un-bloated alternative** ({n} gripes): users say the incumbents got worse / raised prices / removed basics — restore the clean original experience.",
    "bugs / reliability": "**Make reliability the pitch** ({n} gripes): recurring crashes / broken widgets / lost-data complaints — rock-solid sync + export/backup is a real differentiator.",
    "missing / limited": "**Close the feature gaps** ({n} gripes) users keep explicitly asking for (see the wishes list).",
}


def synth_wedge(market_gripes, loves):
    total = sum(market_gripes.values()) or 1
    w = []
    for cat, n in sorted(market_gripes.items(), key=lambda x: -x[1]):
        if n >= max(3, 0.12 * total) and cat in WEDGE_TEMPLATES:
            w.append(WEDGE_TEMPLATES[cat].format(n=n))
    if loves:
        w.append("**Keep what they love:** " + ", ".join(list(loves)[:5]) + " — don't out-feature these into complexity.")
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--min-ratings", type=int, default=2000, help="only review-mine competitors above this (real incumbents)")
    args = ap.parse_args()

    kw = args.keyword
    slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
    outdir = os.path.join(HERE, "output", "deepdive")
    os.makedirs(outdir, exist_ok=True)
    ma = load_ma_label(kw)

    apps = competitors(kw, args.top)
    time.sleep(2.0)
    comps = []
    market_gripes = collections.Counter()
    all_wishes = []
    for a in apps:
        c = {"app": a.get("trackName"), "id": a.get("trackId"), "seller": a.get("sellerName"),
             "rating": round(a.get("averageUserRating") or 0, 2), "count": a.get("userRatingCount") or 0,
             "price": a.get("formattedPrice"), "updated": (a.get("currentVersionReleaseDate") or "")[:7],
             "genre": a.get("primaryGenreName")}
        if c["count"] >= args.min_ratings and c["id"]:
            rv = analyze_reviews(reviews(c["id"], args.pages))
            c["reviews"] = rv
            for k, v in rv["gripes"].items():
                market_gripes[k] += v
            all_wishes += rv["wishes"]
            time.sleep(0.6)
        comps.append(c)

    loves = collections.Counter()
    for c in comps:
        for k, v in (c.get("reviews", {}).get("loves") or {}).items():
            loves[k] += v
    wedge = synth_wedge(market_gripes, dict(loves.most_common(6)))

    result = {"keyword": kw, "mobileaction": ma, "competitors": comps,
              "market_gripes": dict(market_gripes), "market_loves": dict(loves.most_common(8)),
              "wishes": all_wishes[:10], "wedge": wedge}
    with open(os.path.join(outdir, slug + ".json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    # ---- markdown brief ----
    L = []
    L.append(f"# Deep dive — **{kw}**\n")
    if ma:
        L.append(f"**Market demand (MobileAction):** search volume `{ma.get('volume')}` · difficulty `{ma.get('difficulty')}` · {ma.get('ranked_apps')} ranked apps. {ma.get('note','')}\n")
    L.append("## The market — who you're up against\n")
    L.append("| App | ★ | Ratings | Price | Updated | Resent% |")
    L.append("|---|--:|--:|---|---|--:|")
    for c in comps:
        rv = c.get("reviews")
        res = f"{int(rv['resent_frac']*100)}%" if rv else "—"
        L.append(f"| {c['app']} | {c['rating']} | {c['count']:,} | {c['price']} | {c['updated']} | {res} |")
    cutoff = time.strftime("%Y-%m", time.gmtime(time.time() - 365 * 86400))
    stale = [c["app"] for c in comps if c["updated"] and c["updated"] < cutoff]
    if stale:
        L.append(f"\n*Aging (no update since {cutoff}):* {', '.join(stale)} — softer targets.")
    L.append("\n## What the market gets wrong — the openings\n")
    for cat, n in sorted(market_gripes.items(), key=lambda x: -x[1]):
        L.append(f"- **{cat}** — {n} complaint(s) across leaders")
        for c in comps:
            for q in (c.get("reviews", {}).get("quotes", {}).get(cat, []))[:1]:
                # collapse literal newlines so a multi-line review body stays one list item
                L.append("    - *\"{}\"* — {}".format(
                    " ".join(q["t"].split()), " ".join(q["b"].split())))
                break
    L.append("\n## What users love — preserve these\n")
    L.append(", ".join(f"**{k}** ({v})" for k, v in loves.most_common(8)) or "—")
    if result["wishes"]:
        L.append("\n## Specific feature wishes (from reviews)\n")
        for w in result["wishes"]:
            L.append(f"- \"{w}\"")
    L.append("\n## The wedge — how to win\n")
    for b in wedge:
        L.append(f"- {b}")
    with open(os.path.join(outdir, slug + ".md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print(f"wrote {outdir}/{slug}.md (+ .json)")
    print("\n".join(L))


if __name__ == "__main__":
    main()
