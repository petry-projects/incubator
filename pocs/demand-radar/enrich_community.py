#!/usr/bin/env python3
"""
DemandRadar — community-sizing enricher (spike; scale build).

Adds `demand.community_metric` to the SURVIVORS (non-REJECT records) and uses it to
corroborate store-absent gaps (#44). At 10k scale the community sources are quota-
limited, so this enriches only the top survivors, budget-aware, routed per vertical:

  * youtube       — best for culture/consumer verticals (gaming, creator, collectors).
                    Needs YOUTUBE_API_KEY. Quota 10k units/day; search.list=100 units
                    => ~90 lookups/day. totalResults is a rough (capped) estimate.
  * stackexchange — best for Q&A verticals (tabletop, fitness, cooking, ...). No auth,
                    ~300 req/day/IP. Per-vertical site (SITE_MAP).
  * hackernews    — no auth, unlimited-ish; tech-skewed fallback.
  * reddit        — best overall but needs an app + is IP-blocked from cloud. Gated.

Usage:
  python enrich_community.py --max 300                 # top 300 survivors, auto-routed
  DR_COMMUNITY_SOURCE=stackexchange python enrich_community.py   # force one source
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

UA = "DemandRadar-spike/0.4 (+petry-projects/incubator; research)"

# preferred community backend per vertical
VERTICAL_SOURCE = {
    "gaming-companions": "youtube", "creator-content": "youtube", "collectors-hobbies": "youtube",
    "fashion-beauty": "youtube", "hobbies-crafts": "youtube", "niche-sports": "youtube",
    "mental-wellness": "youtube", "events-social": "youtube", "faith-spiritual": "youtube",
    "auto-vehicle": "youtube", "accessibility-seniors": "youtube", "everyday-utilities": "youtube",
    "small-business": "youtube", "productivity-work": "youtube",
    "tabletop-ttrpg": "stackexchange", "student-education": "stackexchange",
    "health-fitness": "stackexchange", "food-cooking": "stackexchange", "home-diy": "stackexchange",
    "pets-animals": "stackexchange", "travel-outdoors": "stackexchange", "finance-money": "stackexchange",
    "parenting-kids": "stackexchange", "gardening-plants": "stackexchange", "music-audio": "stackexchange",
}
SITE_MAP = {
    "gaming-companions": "gaming", "tabletop-ttrpg": "rpg", "student-education": "academia",
    "health-fitness": "fitness", "food-cooking": "cooking", "home-diy": "diy", "pets-animals": "pets",
    "travel-outdoors": "travel", "finance-money": "money", "parenting-kids": "parenting",
    "gardening-plants": "gardening", "creator-content": "video", "music-audio": "music",
}
THRESHOLDS = {  # (corroborate_at, too_thin_below) — units differ wildly by source
    "youtube": (50_000, 2_000),   # summed views of RELEVANT top videos (real demand)
    "hackernews": (300, 50), "stackexchange": (25, 3), "reddit": (10, 2),
}
# per-source daily budgets (respect free quotas)
BUDGET = {"youtube": 90, "stackexchange": 280, "hackernews": 10_000, "reddit": 900}


def hn_mentions(q):
    url = "http://hn.algolia.com/api/v1/search?query=%s&hitsPerPage=1" % urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return {"source": "hackernews", "mentions": json.loads(urllib.request.urlopen(req, timeout=20).read()).get("nbHits", 0), "query": q}


def se_mentions(q, site):
    params = urllib.parse.urlencode({"order": "desc", "sort": "activity", "q": q, "site": site, "filter": "total"})
    if os.environ.get("STACKEXCHANGE_KEY"):
        params += "&key=" + urllib.parse.quote(os.environ["STACKEXCHANGE_KEY"])
    req = urllib.request.Request("https://api.stackexchange.com/2.3/search/advanced?" + params, headers={"User-Agent": UA})
    d = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return {"source": "stackexchange", "site": site, "mentions": d.get("total"), "quota_remaining": d.get("quota_remaining"), "query": q}


def yt_mentions(q):
    """Community demand = summed VIEWS of the top videos whose title actually matches the
    query. totalResults was useless (capped at ~1M, inflated for any common word); view
    counts of *relevant* videos are a real engagement/demand signal."""
    key = os.environ["YOUTUBE_API_KEY"]
    p = urllib.parse.urlencode({"part": "snippet", "type": "video", "maxResults": 8,
                                "order": "relevance", "q": q, "key": key})
    d = json.loads(urllib.request.urlopen(
        urllib.request.Request("https://www.googleapis.com/youtube/v3/search?" + p, headers={"User-Agent": UA}), timeout=20).read())
    toks = [w for w in q.lower().split() if len(w) >= 4]
    id_title = {it["id"]["videoId"]: (it["snippet"]["title"] or "").lower()
                for it in d.get("items", []) if it.get("id", {}).get("videoId")}
    relevant = [vid for vid, t in id_title.items() if all(tok in t for tok in toks)] if toks else list(id_title)
    views = 0
    if relevant:
        p2 = urllib.parse.urlencode({"part": "statistics", "id": ",".join(relevant), "key": key})
        d2 = json.loads(urllib.request.urlopen(
            urllib.request.Request("https://www.googleapis.com/youtube/v3/videos?" + p2, headers={"User-Agent": UA}), timeout=20).read())
        views = sum(int(v.get("statistics", {}).get("viewCount", 0)) for v in d2.get("items", []))
    return {"source": "youtube", "mentions": views, "relevant_videos": len(relevant),
            "est_total": d.get("pageInfo", {}).get("totalResults"), "query": q}


def reddit_token(cid, secret):
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", data=data,
                                 headers={"User-Agent": UA, "Authorization": f"Basic {auth}"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())["access_token"]


def fetch_for(record, forced, budget_left, rtoken, dead):
    """Route a record to a community source (respecting forced source + budgets + dead sources)."""
    q, vert = record["canonical_query"], record.get("industry")
    chain = [forced] if forced else [VERTICAL_SOURCE.get(vert, "hackernews"), "stackexchange", "hackernews"]
    for src in chain:
        if src in dead or budget_left.get(src, 0) <= 0:
            continue
        try:
            if src == "youtube":
                cm = yt_mentions(q)
            elif src == "stackexchange":
                site = SITE_MAP.get(vert)
                if not site:
                    continue
                cm = se_mentions(q, site)
            elif src == "reddit" and rtoken:
                continue  # reddit path documented but gated/blocked from cloud
            else:
                cm = hn_mentions(q)
            budget_left[src] -= 1
            return cm
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "quota" in str(e).lower():
                dead.add(src)  # exhausted for this run — stop trying it (no more wasted 429s)
                print(f"  ~ {src} exhausted (429/quota); skipping it for the rest of this run", file=sys.stderr)
            else:
                print(f"  ! {src} failed for {q!r}: {e}", file=sys.stderr)
            continue
    return {"source": "none", "mentions": None}


def recompute(record, cm):
    if record.get("discovery_channel") != "community":
        return record["verdict_heuristic"], None
    v = record["verdict_heuristic"]
    if not v.startswith("CANDIDATE") or cm.get("mentions") is None:
        return v, None
    corr, thin = THRESHOLDS.get(cm.get("source", ""), (300, 50))
    m = cm["mentions"]
    if m >= corr:
        return "CANDIDATE", "community-corroborated"
    if m < thin:
        return "REJECT", "community-too-thin"
    return "WATCH", "community-weak"


def supply_score(r):
    GAP = {"absent-in-store": 3, "absent": 3, "nascent": 2, "stale": 2, "low-quality": 2, "thin": 1}
    COMP = {"low": 2, "medium": 1, "high": 0}
    return GAP.get(r["gap"]["gap_type"], 0) + COMP.get(r["supply"]["competition_intensity"], 0)


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--in", dest="inp", default=os.path.join(here, "output", "records.jsonl"))
    ap.add_argument("--out", default=os.path.join(here, "output", "records.enriched.jsonl"))
    ap.add_argument("--source", default=os.environ.get("DR_COMMUNITY_SOURCE", ""))  # "" = auto-route
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    records = [json.loads(l) for l in open(args.inp)]
    survivors = [r for r in records if not r.get("verdict_heuristic", "").startswith("REJECT")]
    survivors.sort(key=supply_score, reverse=True)
    targets = survivors[: args.max]
    print(f"records={len(records)} survivors={len(survivors)} enriching_top={len(targets)}", flush=True)

    rtoken = None
    if args.source == "reddit":
        cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
        rtoken = reddit_token(cid, sec) if cid and sec else None

    budget_left = dict(BUDGET)
    dead = set()  # sources that 429'd this run — skipped thereafter (circuit breaker)
    changed = []
    for i, r in enumerate(targets):
        cm = fetch_for(r, args.source or None, budget_left, rtoken, dead)
        r["demand"]["community_metric"] = cm
        nv, note = recompute(r, cm)
        if nv != r["verdict_heuristic"]:
            changed.append((r["canonical_query"], r["verdict_heuristic"], nv, cm.get("mentions"), cm.get("source")))
            r["verdict_heuristic"] = nv
            r["corroboration_count"] = 2
            r["community_note"] = note
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(targets)}  budgets={budget_left}", flush=True)
        time.sleep(args.sleep)

    with open(args.out, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nEnriched {len(targets)} survivors -> {args.out}")
    print(f"budgets remaining: {budget_left}")
    print(f"verdict changes: {len(changed)}  (corroborated: {sum(1 for c in changed if c[2]=='CANDIDATE')})")


if __name__ == "__main__":
    main()
