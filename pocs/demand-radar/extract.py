#!/usr/bin/env python3
"""
DemandRadar — supply-signal extractor (spike; scale build).

Scripted, headless, ZERO-SECRET implementation of the load-bearing *free* layer
(#44 schema v3): supply-quality / gap detection via Apple's public iTunes Search
API (no auth). Scores each candidate idea and emits an `opportunity_record`.

Scale features:
  * reads output/keywords.jsonl (from generate_keywords.py) — 10k+ candidates.
  * concurrent workers (ThreadPoolExecutor) with polite jitter + backoff.
  * RESUMABLE: skips keywords already in output/records.jsonl; streams new records
    to disk as they complete, so an interrupted/throttled run just continues.

Usage:
  python extract.py --keywords output/keywords.jsonl --workers 6
  python extract.py                     # falls back to keyword-groups.json (small mode)
"""

import argparse
import json
import os
import random
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

ITUNES_SEARCH = "https://itunes.apple.com/search"
UA = "DemandRadar-spike/0.4 (+petry-projects/incubator; research)"
CREDIBLE_MIN_RATINGS = 50
TOP_N = 8
STOP = {"app", "apps", "the", "for", "best", "free", "pro", "plus", "with", "your"}
RELEVANCE_THRESHOLD = 0.6


def _now():
    return datetime.now(timezone.utc)


# --- global rate limiter (Apple Search API ~20-30/min; over that => throttle+empty) ---
_pace_lock = threading.Lock()
_next_at = [0.0]
_min_interval = [2.0]  # seconds between calls; set from --rate


def pace():
    with _pace_lock:
        now = time.time()
        wait = max(0.0, _next_at[0] - now)
        _next_at[0] = max(now, _next_at[0]) + _min_interval[0]
    if wait > 0:
        time.sleep(wait)


def fetch(term, country="us", limit=20, entity="software", retries=4):
    params = urllib.parse.urlencode({"term": term, "country": country, "entity": entity, "limit": limit})
    url = f"{ITUNES_SEARCH}?{params}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8")).get("results", []), True
        except Exception:  # noqa: BLE001 — throttle/network: backoff and retry
            if attempt == retries - 1:
                return [], False
            time.sleep(2.0 * (attempt + 1) + random.random())
    return [], False


def days_since(iso):
    if not iso:
        return None
    try:
        return (_now() - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    except Exception:  # noqa: BLE001
        return None


def content_tokens(term):
    return [w for w in term.lower().split() if w not in STOP and len(w) >= 4]


def relevance_score(term, app):
    toks = content_tokens(term)
    if not toks:
        return 1.0
    name = (app.get("trackName") or "").lower()
    desc = (app.get("description") or "").lower()
    score = sum(1.0 if t in name else 0.6 if t in desc else 0.0 for t in toks)
    return score / len(toks)


def is_relevant(term, app):
    return relevance_score(term, app) >= RELEVANCE_THRESHOLD


def analyze(term, results, discovery_channel=None):
    top = results[:TOP_N]
    relevant = [a for a in top if is_relevant(term, a)]
    credible = [a for a in relevant if (a.get("userRatingCount") or 0) >= CREDIBLE_MIN_RATINGS]
    rs = [a.get("averageUserRating") or 0 for a in credible]
    br = round(max(rs), 2) if rs else None
    ds = [d for a in credible if (d := days_since(a.get("currentVersionReleaseDate"))) is not None]
    fresh = min(ds) if ds else None
    n_credible, n_relevant = len(credible), len(relevant)

    if n_credible == 0:
        satisfaction = "none"
    elif br >= 4.5 and fresh is not None and fresh <= 180 and n_credible >= 2:
        satisfaction = "high"
    elif br >= 4.0 and fresh is not None and fresh <= 365:
        satisfaction = "medium"
    else:
        satisfaction = "low"

    if n_relevant == 0:
        gap_type = "absent-in-store"
    elif n_credible == 0:
        gap_type = "nascent"
    elif fresh is not None and fresh > 365:
        gap_type = "stale"
    elif br is not None and br < 3.5:
        gap_type = "low-quality"
    elif satisfaction == "high":
        gap_type = "served"
    else:
        gap_type = "thin"

    competition = "high" if n_credible >= 8 else "medium" if n_credible >= 3 else "low"
    if discovery_channel == "community":
        supply_confidence = "low"
    elif n_relevant == 0 and len(results) > 0:
        supply_confidence = "low"
    else:
        supply_confidence = "medium"

    if gap_type in ("absent-in-store", "nascent", "stale", "low-quality") and satisfaction in ("none", "low"):
        verdict = "CANDIDATE" if supply_confidence != "low" else "CANDIDATE*"
    elif satisfaction == "medium" or gap_type == "thin":
        verdict = "WATCH"
    else:
        verdict = "REJECT"

    # --- DISRUPTION LENS: proven market (high usage) + beatable leader (mediocre rating).
    # The opposite of the gap lens — a crowded, hated category (Quizlet/Splitwise-style) is a
    # target, not a reject. market_size = review count of the most-used RELEVANT incumbent. ---
    market_size = max((a.get("userRatingCount") or 0) for a in relevant) if relevant else 0
    leader = max(relevant, key=lambda a: a.get("userRatingCount") or 0) if relevant else None
    leader_rating = round(leader.get("averageUserRating"), 2) if leader and leader.get("averageUserRating") else None
    disruption = market_size >= 8000 and leader_rating is not None and 1.0 < leader_rating <= 4.2
    if disruption:
        verdict = "DISRUPT"  # override so proven-but-hated markets surface instead of REJECTing as "served"

    return {
        "results_total": len(results), "relevant_incumbents": n_relevant,
        "credible_incumbents": n_credible, "best_existing_rating": br,
        "freshest_incumbent_days": fresh, "best_existing_satisfaction": satisfaction,
        "gap_type": gap_type, "competition_intensity": competition,
        "market_size": market_size, "leader_rating": leader_rating, "disruption": disruption,
        "supply_confidence": supply_confidence, "verdict": verdict,
        "top_apps": [
            {"app": a.get("trackName"), "seller": a.get("sellerName"), "id": a.get("trackId"),
             "rating": a.get("averageUserRating"), "rating_count": a.get("userRatingCount"),
             "last_updated_days": days_since(a.get("currentVersionReleaseDate")),
             "price": a.get("formattedPrice")} for a in top
        ],
    }


def to_record(group, term, signal, captured_at):
    slug = term.lower().replace(" ", "-")
    return {
        "opportunity_id": f"og_{captured_at[:7].replace('-', '_')}_{group['name']}_{slug}",
        "canonical_query": term, "industry": group["name"],
        "vertical_dynamics": group.get("vertical_dynamics"),
        "discovery_channel": group.get("discovery_channel"), "captured_at": captured_at,
        "gap": {"gap_type": signal["gap_type"]},
        "demand": {"app_store_volume": None, "web_search_volume": None,
                   "community_metric": None, "collection_method": "itunes-search-api (supply-only)"},
        "supply": {"solution_exists": signal["relevant_incumbents"] > 0,
                   "best_existing_satisfaction": signal["best_existing_satisfaction"],
                   "best_existing_rating": signal["best_existing_rating"],
                   "freshest_incumbent_days": signal["freshest_incumbent_days"],
                   "competition_intensity": signal["competition_intensity"],
                   "relevant_incumbents": signal["relevant_incumbents"],
                   "credible_incumbents": signal["credible_incumbents"],
                   "market_size": signal["market_size"], "leader_rating": signal["leader_rating"],
                   "disruption": signal["disruption"],
                   "supply_confidence": signal["supply_confidence"],
                   "solutions": signal["top_apps"][:5]},
        "verdict_heuristic": signal["verdict"],
        "provenance": [{"mechanism": "supply-mapping", "source": "itunes-search-api", "collected_at": captured_at}],
        "downstream": {"score": None, "rank": None, "market_research": None, "dedup_verdict": None},
    }


def load_keywords(path):
    by_vert = {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        k = json.loads(line)
        by_vert.setdefault(k["vertical"], []).append(
            {"name": k["vertical"], "discovery_channel": k.get("discovery_channel"),
             "vertical_dynamics": k.get("vertical_dynamics"), "keyword": k["keyword"]})
    # round-robin interleave across verticals so any partial run covers all 25
    recs, lists = [], list(by_vert.values())
    for i in range(max(len(v) for v in lists)):
        for v in lists:
            if i < len(v):
                recs.append(v[i])
    return recs


def load_groups_json(path):
    cfg = json.load(open(path))
    recs = []
    for g in cfg["groups"]:
        for kw in g["keywords"]:
            recs.append({"name": g["name"], "discovery_channel": g.get("discovery_channel"),
                         "vertical_dynamics": g.get("vertical_dynamics"), "keyword": kw})
    return recs, cfg.get("store", "us")


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--keywords", default="")
    ap.add_argument("--config", default=os.path.join(here, "keyword-groups.json"))
    ap.add_argument("--out", default=os.path.join(here, "output", "records.jsonl"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--rate", type=float, default=35.0, help="max iTunes calls/min (Apple throttles ~>30)")
    ap.add_argument("--country", default="us")
    args = ap.parse_args()
    _min_interval[0] = 60.0 / max(1.0, args.rate)

    if args.keywords:
        kwrecs = load_keywords(args.keywords)
        country = args.country
    else:
        kwrecs, country = load_groups_json(args.config)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    # RESUME: skip keywords already scored
    done = set()
    if os.path.exists(args.out):
        for line in open(args.out):
            try:
                done.add(json.loads(line)["canonical_query"])
            except Exception:  # noqa: BLE001
                pass
    pending = [k for k in kwrecs if k["keyword"] not in done]
    if args.max:
        pending = pending[: args.max]
    captured_at = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"total={len(kwrecs)} done={len(done)} pending={len(pending)} workers={args.workers}", flush=True)

    lock = threading.Lock()
    counts = {"ok": 0, "fail": 0, "n": 0}
    out_f = open(args.out, "a")

    abort = threading.Event()  # set on a 403-storm → bail the batch fast (ban is active)

    def work(kw):
        if abort.is_set():
            return False
        pace()  # global rate limit — stay under Apple's throttle
        results, ok = fetch(kw["keyword"], country=country, limit=args.limit)
        with lock:
            counts["n"] += 1
            counts["consec"] = 0 if ok else counts.get("consec", 0) + 1
            if not ok:
                # throttled/failed fetch: DO NOT write (avoids false 'absent'); pending preserved
                counts["fail"] += 1
                if counts["consec"] >= 15 and not abort.is_set():
                    abort.set()
                    print(f"  ~~ 403-storm: ABORTING batch after {counts['fail']} fails (ban active); "
                          f"{counts['ok']} scored this batch, pending preserved for next cooldown ~~", flush=True)
                return False
            sig = analyze(kw["keyword"], results, discovery_channel=kw.get("discovery_channel"))
            rec = to_record(kw, kw["keyword"], sig, captured_at)
            out_f.write(json.dumps(rec) + "\n")
            out_f.flush()
            counts["ok"] += 1
            if counts["ok"] % 100 == 0:
                print(f"  {counts['ok']} scored / {counts['fail']} fail  ({kw['keyword']})", flush=True)
        return True

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(as_completed([ex.submit(work, k) for k in pending]))
    out_f.close()
    print(f"DONE. wrote {counts['n']} records (ok={counts['ok']} fail={counts['fail']}) -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
