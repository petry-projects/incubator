#!/usr/bin/env python3
"""
DemandRadar — starter-list ranker (spike, phase 3).

Reads the enriched records, drops the REJECTs, scores the survivors with a simple
transparent heuristic, merges any manual MobileAction magnitude labels, and writes
a ranked `output/starter-list.md` — the robust idea starter list.

It also flags app-store-channel candidates that still lack a magnitude read
(`needs_magnitude`) — that column is the worklist for the manual MobileAction pass.

Score = gap severity + supply-scarcity + community corroboration. Deliberately
legible, not tuned — the labeled set (labels/) is what a real scorer trains on.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
GAP_W = {"absent-in-store": 3, "absent": 3, "nascent": 2, "stale": 2, "low-quality": 2, "thin": 1, "served": 0}
COMP_W = {"low": 2, "medium": 1, "high": 0}


def load_labels():
    path = os.path.join(HERE, "labels", "mobileaction-labels.json")
    out = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for lab in json.load(f).get("labels", []):
                out[lab["keyword"].lower()] = lab
    return out


def community_bonus(rec):
    cm = (rec.get("demand") or {}).get("community_metric") or {}
    m = cm.get("mentions")
    if m is None:
        return 0, None
    if m >= 300:
        return 2, m
    if m >= 50:
        return 1, m
    return 0, m


def load_broad():
    """keyword -> (broad_interest, app_intent) from the Google-Suggest broad pass."""
    path = os.path.join(HERE, "output", "keywords.broad.jsonl")
    out = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for l in f:
                r = json.loads(l)
                if r.get("broad_interest") is not None:
                    out[r["keyword"].lower()] = (r.get("broad_interest") or 0, r.get("app_intent") or 0)
    return out


def main():
    src = os.path.join(HERE, "output", "records.enriched.jsonl")
    if not os.path.exists(src):
        src = os.path.join(HERE, "output", "records.jsonl")
    with open(src, encoding='utf-8') as f:
        records = [json.loads(l) for l in f]
    labels = load_labels()
    broad = load_broad()

    rows = []
    for r in records:
        v = r.get("verdict_heuristic", "")
        if v.startswith("REJECT"):
            continue
        gap = r["gap"]["gap_type"]
        comp = r["supply"]["competition_intensity"]
        cbonus, mentions = community_bonus(r)
        bi, app_intent = broad.get(r["canonical_query"].lower(), (0, 0))
        gap_w = GAP_W.get(gap, 0)
        trust_note = None
        if gap == "absent-in-store":
            if r["discovery_channel"] == "app-store":
                # UNRELIABLE on app-store: usually a relevance false-negative (a real app
                # exists under a different name — 'step calculator' vs 'Pedometer++'). Do NOT
                # let it top the list on 'absent' alone; only MobileAction volume (below) can
                # promote it. Trustworthy app-store signals are stale/low-quality/thin, where
                # we actually matched and assessed real incumbents.
                gap_w = 1.0
                trust_note = "unverified-absent"
            elif not (app_intent or bi >= 6):
                gap_w = 0.5  # community nonsense combo (no demand)
        demand_bonus = app_intent + min(bi, 8) / 4.0   # reward real autocomplete demand
        score = gap_w + COMP_W.get(comp, 0) + cbonus + demand_bonus
        lab = labels.get(r["canonical_query"].lower())
        vol = lab["volume"] if lab else None
        # Demand-aware: MobileAction magnitude only applies to app-store channel (#44).
        # A labeled app-store candidate with real volume gets a boost; one that is N/A
        # or at the ~5 floor is demand-validated-EMPTY -> heavy demote (real gap, no demand).
        mag_note = None
        if r["discovery_channel"] == "app-store" and lab is not None:
            if vol is not None and vol >= 40:
                score += 2; mag_note = "demand-validated"
            elif vol is not None and vol >= 15:
                score += 1
            else:  # vol <= ~5 floor, or null/N/A
                score -= 3; mag_note = "no store demand"
        needs_mag = (r["discovery_channel"] == "app-store") and (lab is None)
        rows.append({
            "score": round(score, 1), "kw": r["canonical_query"], "group": r["industry"],
            "channel": r["discovery_channel"], "gap": gap, "comp": comp,
            "sat": r["supply"]["best_existing_satisfaction"], "mentions": mentions,
            "demand": f"{app_intent}/{bi}", "vol": vol, "verdict": v,
            "needs_mag": needs_mag, "mag_note": mag_note, "trust_note": trust_note,
        })

    rows.sort(key=lambda x: (-x["score"], x["group"]))

    out = os.path.join(HERE, "output", "starter-list.md")
    with open(out, "w") as f:
        f.write("# DemandRadar — idea starter list (ranked)\n\n")
        f.write(f"{len(rows)} non-REJECT candidates from {len(records)} keywords. ")
        f.write("Score = gap severity + supply scarcity + community corroboration (legible, untuned).\n\n")
        f.write("`vol` = MobileAction App Store volume (manual label; blank = not yet pulled). ")
        f.write("`*` in verdict = store gap needing non-store verification.\n\n")
        f.write("`demand` = Google-Suggest app_intent/broad_interest (nonsense gate). "
                "`community` via YouTube is loose (inflated) — treat as directional.\n\n")
        f.write("| score | keyword | group | channel | gap | comp | demand | community | store vol | verdict | note |\n")
        f.write("|--:|---|---|---|---|---|:--:|--:|--:|---|---|\n")
        for x in rows:
            parts = [x["mag_note"], x.get("trust_note")]
            if x["needs_mag"]:
                parts.append("needs MA ▲")
            note = " · ".join(p for p in parts if p)
            f.write(
                f"| {x['score']} | {x['kw']} | {x['group']} | {x['channel']} | {x['gap']} | "
                f"{x['comp']} | {x['demand']} | {x['mentions'] if x['mentions'] is not None else '—'} | "
                f"{x['vol'] if x['vol'] is not None else '—'} | {x['verdict']} | {note} |\n"
            )
        worklist = [x["kw"] for x in rows if x["needs_mag"]]
        f.write(f"\n**MobileAction worklist ({len(worklist)} app-store candidates need magnitude):**\n\n")
        f.write(", ".join(f"`{k}`" for k in worklist) + "\n")

    print(f"Wrote {out}  ({len(rows)} candidates)")
    print("Top 15:")
    for x in rows[:15]:
        print(f"  {x['score']}  {x['kw']:<24} {x['group']:<20} {x['channel']:<10} {x['gap']:<15} {x['verdict']}")


if __name__ == "__main__":
    main()
