#!/usr/bin/env python3
"""Export candidates + BOTH opportunity lenses to a compact JSON for the dashboard.
 - Gap lens (build an absent/weak niche): score from rank_starter_list.py logic.
 - Disruption lens (attack a proven market with a beatable leader): market_size x dissatisfaction.
Includes a record if it's a non-REJECT gap candidate OR a disruption target."""
import json, os, math, re
HERE = os.path.dirname(os.path.abspath(__file__))
GAP_W = {"absent-in-store": 3, "absent": 3, "nascent": 2, "stale": 2, "low-quality": 2, "thin": 1, "served": 0}
COMP_W = {"low": 2, "medium": 1, "high": 0}
STOP = {"app", "apps", "the", "for", "best", "free", "pro", "plus", "with", "your"}
DISRUPT_USERS, DISRUPT_RATING = 8000, 4.2

def toks(q): return [w for w in q.lower().split() if w not in STOP and len(w) >= 4]
def name_rel(name, q):
    t = toks(q); n = (name or "").lower(); return bool(t) and all(x in n for x in t)

def load_labels():
    p = os.path.join(HERE, "labels", "mobileaction-labels.json")
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return {l["keyword"].lower(): l for l in json.load(f).get("labels", [])}
    return {}

def load_broad():
    p = os.path.join(HERE, "output", "keywords.broad.jsonl"); out = {}
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if r.get("broad_interest") is not None:
                    out[r["keyword"].lower()] = (r.get("broad_interest") or 0, r.get("app_intent") or 0)
    return out

def cbonus(m): return 0 if m is None else 2 if m >= 300 else 1 if m >= 50 else 0

def load_resented():
    p = os.path.join(HERE, "output", "resented.json")
    if os.path.exists(p):
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    return {}

def disruption(rec):
    """(market_size, leader_rating, leader_app, is_target). Uses detector fields if present,
    else derives from stored top-5 via name-relevance (lossy for pre-detector records)."""
    sup = rec.get("supply"); q = rec["canonical_query"]
    if sup is None: return 0, None, None, False
    if sup.get("market_size") is not None:  # scored with the new detector
        lr = sup.get("leader_rating")
        # Filter solutions by relevance to query before picking the leader (consistent with else case)
        apps = [a for a in sup.get("solutions", []) if name_rel(a.get("app"), q) and a.get("rating")]
        lead = max(apps, key=lambda a: a.get("rating_count") or 0, default=None) if apps else None
        return sup["market_size"], lr, (lead or {}).get("app"), bool(sup.get("disruption"))
    apps = [a for a in sup.get("solutions", []) if name_rel(a.get("app"), q) and a.get("rating")]
    if not apps: return 0, None, None, False
    lead = max(apps, key=lambda a: a.get("rating_count") or 0)
    ms = lead.get("rating_count") or 0; lr = lead.get("rating")
    lr = round(lr, 2) if lr else None
    return ms, lr, lead.get("app"), (ms >= DISRUPT_USERS and lr is not None and 1.0 < lr <= DISRUPT_RATING)

def wedge_from(rg):
    """Synthesize a 'how to win' wedge from a resented leader's gripe categories."""
    if not rg: return None
    ch = rg.get("cat_hits", {})
    tmpl = {
        "pricing": "Fix the money model \u2014 pricing/paywall is the top complaint; win with a genuinely free tier or a one-time unlock, not another subscription.",
        "ads": "Ship ad-free \u2014 ads are a repeated gripe and 'no ads' is itself a selling point.",
        "enshittification": "Be the simple, un-bloated alternative \u2014 users say it got worse / raised prices / removed basics; restore the clean original.",
        "missing": "Restore the removed/basic features users keep citing.",
    }
    order = sorted([c for c in tmpl if ch.get(c)], key=lambda c: -ch.get(c, 0))
    return [tmpl[c] for c in order[:3]] or None


def main():
    src = os.path.join(HERE, "output", "records.enriched.jsonl")
    if not os.path.exists(src): src = os.path.join(HERE, "output", "records.jsonl")
    labels, broad, resented = load_labels(), load_broad(), load_resented()
    out = []
    with open(src, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line); v = r.get("verdict_heuristic", "")
            ms, lr, lapp, star_dis = disruption(r)
            rg = resented.get((lapp or "").lower()) if lapp else None
            res_flag = bool(rg and rg.get("resented"))
            dis = star_dis or res_flag  # disruption = low-rated giant OR well-rated-but-RESENTED giant
            if v.startswith("REJECT") and not dis:  # keep gap-candidates OR disruption targets
                continue
            gap = r["gap"]["gap_type"]; comp = r["supply"]["competition_intensity"]; ch = r["discovery_channel"]
            cm = (r.get("demand") or {}).get("community_metric") or {}
            m = cm.get("mentions"); m = m if isinstance(m, int) else None
            bi, app_intent = broad.get(r["canonical_query"].lower(), (0, 0))
            gap_w = GAP_W.get(gap, 0); trust = None
            if gap == "absent-in-store":
                if ch == "app-store": gap_w = 1.0; trust = "unverified-absent"
                elif not (app_intent or bi >= 6): gap_w = 0.5
            score = gap_w + COMP_W.get(comp, 0) + cbonus(m) + app_intent + min(bi, 8) / 4.0
            lab = labels.get(r["canonical_query"].lower()); vol = lab["volume"] if lab else None
            magnote = None
            if ch == "app-store" and lab is not None:
                if vol is not None and vol >= 40: score += 2; magnote = "demand-validated"
                elif vol is not None and vol >= 15: score += 1
                else: score -= 3; magnote = "no-store-demand"
            ds_star = math.log10(ms) * max(0.0, 4.6 - lr) if star_dis and ms > 0 and lr else 0.0
            ds_res = math.log10(ms) * rg["resent_frac"] if res_flag and ms > 0 else 0.0
            dscore = round(max(ds_star, ds_res), 2)
            verdict = "DISRUPT" if dis else v
            sup = r["supply"]
            out.append({
                "kw": r["canonical_query"], "vert": r["industry"], "ch": ch, "gap": gap,
                "comp": comp, "sat": sup["best_existing_satisfaction"], "verdict": verdict,
                "score": round(score, 1), "comm": m, "commSrc": cm.get("source"),
                "app": app_intent, "bi": bi, "vol": vol, "magnote": magnote, "trust": trust,
                "needsMA": (ch == "app-store" and lab is None and not dis),
                "market": ms or None, "leaderR": lr, "leaderApp": lapp, "disrupt": dis, "dScore": dscore,
                "resented": res_flag, "resentFrac": rg.get("resent_frac") if res_flag else None,
                "resentCats": [c for c in ("pricing", "ads", "enshittification") if res_flag and rg.get("cat_hits", {}).get(c)] if res_flag else None,
                "gripes": rg.get("gripes") if res_flag else None,
                "wedge": wedge_from(rg) if res_flag else None,
                "bestRating": sup.get("best_existing_rating"), "fresh": sup.get("freshest_incumbent_days"),
                "relInc": sup.get("relevant_incumbents"),
                "apps": [{"n": a.get("app"), "r": a.get("rating"), "c": a.get("rating_count"),
                          "u": a.get("last_updated_days")} for a in sup.get("solutions", [])[:5]],
            })
    out.sort(key=lambda x: (-max(x["score"], x["dScore"]*2), x["kw"]))
    dest = os.path.join(HERE, "output", "dashboard-data.json")
    with open(dest, "w", encoding='utf-8') as f:
        json.dump(out, f, separators=(",", ":"))
    nd = sum(1 for x in out if x["disrupt"])
    print(f"wrote {len(out)} candidates ({nd} disruption targets) -> {dest} ({os.path.getsize(dest)//1024} KB)")

if __name__ == "__main__":
    main()
