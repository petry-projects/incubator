#!/usr/bin/env python3
"""
DemandRadar — broad demand pass (spike; funnel stage 1).

The WIDEST, cheapest funnel stage: score ALL candidate ideas with a HIGH-rate-limit
source before spending the scarce/ban-prone ones. Uses **Google Suggest** (autocomplete)
— no key, ~10/s, covers every vertical, and is a real consumer-demand signal: if Google
autocompletes "<idea>" (especially "<idea> app"), people are searching it.

Output: output/keywords.broad.jsonl  — every keyword + a `broad_interest` score.
Then select_priority() (see rank/select step) takes top-K per vertical into the small
`keywords.priority.jsonl` that the low-throughput iTunes supply pass actually scores.

  python broad_pass.py --workers 8

Resumable (skips keywords already scored), streamed to disk.
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

UA = "Mozilla/5.0 (research; petry-projects/incubator DemandRadar-spike)"

# --- global rate limiter: space autocomplete calls regardless of worker count ---
# Workers fire concurrently, so without this N workers could burst N requests at once
# and trip the engine's throttle (biasing the scored subset). pace() reserves the next
# slot atomically and sleeps OUTSIDE the lock, so calls stay >= _min_interval apart.
_pace_lock = threading.Lock()
_next_at = [0.0]
_min_interval = [0.05]  # seconds between calls (~20/s across all workers)


def pace():
    with _pace_lock:
        now = time.time()
        wait_s = max(0.0, _next_at[0] - now)
        _next_at[0] = max(now, _next_at[0]) + _min_interval[0]
    if wait_s > 0:
        time.sleep(wait_s)

# Autocomplete engines. Both return [query, [suggestions]]. DDG is the default because it
# has a different IP-ban profile than Google — swapping SOURCE beats rotating IP.
ENGINES = {
    "ddg": ("https://ac.duckduckgo.com/ac/", lambda q: {"q": q, "type": "list"}),
    "google": ("https://suggestqueries.google.com/complete/search", lambda q: {"client": "firefox", "q": q}),
}


def suggest(term, engine="ddg"):
    base, mk = ENGINES[engine]
    url = base + "?" + urllib.parse.urlencode(mk(term))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    return data[1] if len(data) > 1 and isinstance(data[1], list) else []


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def score(term, suggestions):
    s = [x.lower() for x in suggestions]
    n = len(s)
    app_intent = 1 if any("app" in _words(x) for x in s) else 0
    toks = [w for w in term.lower().split() if len(w) >= 4]
    # on-topic = suggestion contains every idea token as a WHOLE WORD (word-boundary, not
    # substring) so "podcast counterargument" no longer matches "counter". Curbs inflation.
    on_topic = sum(1 for x in s if all(t in _words(x) for t in toks)) if toks else n
    return {"broad_interest": on_topic + 4 * app_intent, "n_suggestions": n,
            "app_intent": app_intent, "on_topic": on_topic}


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--in", dest="inp", default=os.path.join(here, "output", "keywords.jsonl"))
    ap.add_argument("--out", default=os.path.join(here, "output", "keywords.broad.jsonl"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--engine", default="ddg", choices=list(ENGINES))
    args = ap.parse_args()

    try:
        with open(args.inp, encoding="utf-8") as f:
            kws = [json.loads(line) for line in f]
    except (OSError, ValueError) as e:  # file-access / malformed JSON — report, don't traceback
        print(f"Error reading input keywords from {args.inp}: {e}", file=sys.stderr)
        sys.exit(1)
    done = set()
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        # Only treat a keyword as done if it has a valid score; failed rows
                        # (broad_interest is None) stay pending so a resume retries them.
                        if rec.get("broad_interest") is not None:
                            done.add(rec["keyword"])
                    except Exception:  # noqa: BLE001
                        pass
        except OSError as e:
            print(f"Error reading existing broad keywords from {args.out}: {e}", file=sys.stderr)
            sys.exit(1)
    pending = [k for k in kws if k["keyword"] not in done]
    print(f"total={len(kws)} done={len(done)} pending={len(pending)} workers={args.workers}", flush=True)

    lock = threading.Lock()
    counts = {"n": 0, "fail": 0}

    with open(args.out, "a", encoding='utf-8') as out_f:
        def work(k):
            pace()  # global rate limit BEFORE the request — spaces bursts across all workers
            try:
                sg = suggest(k["keyword"], engine=args.engine)
                rec = {**k, **score(k["keyword"], sg), "suggestions": sg[:6]}
                okk = True
            except Exception:  # noqa: BLE001
                rec = {**k, "broad_interest": None, "n_suggestions": None, "error": True}
                okk = False
            with lock:
                out_f.write(json.dumps(rec) + "\n")
                out_f.flush()
                counts["n"] += 1
                if not okk:
                    counts["fail"] += 1
                if counts["n"] % 1000 == 0:
                    print(f"  {counts['n']}/{len(pending)}  fail={counts['fail']}", flush=True)
            return okk

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            wait([ex.submit(work, k) for k in pending])
    print(f"DONE broad pass: {counts['n']} scored (fail={counts['fail']}) -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
