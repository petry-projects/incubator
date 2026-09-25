# DemandRadar — continue here

Disposable spike ([incubator Discussion #44](https://github.com/petry-projects/incubator/discussions/44)).
A repeatable funnel that finds app opportunities two ways and produces decision-ready briefs.

## What it does (the pipeline, all scripted, free data, no auth except an optional YouTube key)

```
generate_keywords.py   # 0  25 verticals x domains x tool-types -> output/keywords.jsonl (14,520)
broad_pass.py          # 1  WIDE demand filter, DuckDuckGo autocomplete (--engine ddg; google banned) -> keywords.broad.jsonl
select_priority.py     # 2  top-K/vertical by broad demand -> keywords.priority.jsonl (1,250)
extract.py             # 3  SUPPLY via iTunes Search (paced/resumable/circuit-breaker); also the
                       #    disruption detector (market_size, leader_rating) -> records.jsonl
enrich_community.py    # 4  community sizing: StackExchange / YouTube-views / HN (budget-routed) -> records.enriched.jsonl
resented_giants.py     # 4b review-TEXT disruption: mine 1-3star reviews of proven-market leaders for
                       #    monetization/ads/enshittification resentment -> resented.json
rank_starter_list.py   #    gap-lens ranking -> starter-list.md
export_dashboard.py    #    merge BOTH lenses -> output/dashboard-data.json
deep_dive.py --keyword "X"   # per-pick opportunity BRIEF -> output/deepdive/<slug>.{md,json}
```

Two lenses:
- **Gap** — build an absent/weak niche. (Converged; top clusters: auto-vehicle, accessibility-seniors, finance.)
- **Disrupt** — attack a proven market whose leader is beatable. Star-rating disruption is a DEAD END
  (89% of proven markets have >4.6-star leaders); the real signal is **review-text resentment** — well-rated
  giants (4.6-4.9star) hated for monetization (Quizlet 4.78/1.09M/46%, MyFitnessPal, CamScanner, AllTrails...).
  `resented_giants.py` found 128.

## Current state (as committed)
- ~1,190/1,250 priority keywords supply-scored (gap-lens star re-run paused ~720; disruption re-run current).
- 225 proven-market leaders scanned -> 128 resented giants; 259 disruption targets on the dashboard.
- 3 deep-dive briefs done: mood tracker, guitar chords, white noise (all: paywall is the #1 wedge).
- MobileAction labels in `labels/mobileaction-labels.json` (manual; includes the resented markets' vol/difficulty).

## Dashboard (Artifact — keep the SAME URL)
https://claude.ai/code/artifact/7d8ef7d9-0f9e-4fc9-a32e-d2a50c125394
Rebuild + republish after any data change:
```
python3 pocs/demand-radar/export_dashboard.py
python3 -c "t=open('pocs/demand-radar/dashboard.tmpl.html').read(); d=open('pocs/demand-radar/output/dashboard-data.json').read().replace('</script>','<\\/script>'); open('pocs/demand-radar/dashboard.html','w').write(t.replace('__DATA__',d))"
# then: Artifact tool, file_path pocs/demand-radar/dashboard.html  (same path = same URL)
```

## Re-setup needed in a new session
- **YouTube key**: the old one was recycled. Get a new YouTube Data API v3 key, then `export YOUTUBE_API_KEY=...`
  (put it in a gitignored env file, e.g. a scratchpad `dr.env`, and `source` it before `enrich_community.py`).
  Without it, enrich falls back to StackExchange/HackerNews automatically.
- **MobileAction**: manual validation runs through the user's logged-in browser session (insights.mobileaction.co
  Keyword Inspector). Drive it via the Chrome browser tools; read Volume/Difficulty per keyword.
- **Rate limits**: every free endpoint IP-bans bursts (iTunes ~20-30/min, DDG/Google Suggest ~6k). Use LOW
  concurrency + pacing from the first call; on a 403-storm go SILENT.

## Highest-value next steps
1. **MobileAction-validate** the top disruption markets' search volume + the gap shortlist (turns list -> go/no-go).
2. **Batch deep-dives** across the top ~15 resented giants (`deep_dive.py` per target).
3. **Promote a winner** into the incubator: open an Ideas Discussion + drop the deep-dive as
   `ideas/<slug>/market-research.md` — the graduation this funnel feeds.
4. **Refinements**: sharpen gripe/love lexicons; add real user-phrase seeds so franchises (e.g. "minecraft backup")
   enter the keyword space; resume the gap-lens star re-run for full market-size coverage.

## Ready-to-paste continuation prompt
> Continue the DemandRadar spike in petry-projects/incubator (pocs/demand-radar/). Read pocs/demand-radar/CONTINUE.md
> and README.md first. The scripted funnel (generate -> DDG broad -> select_priority -> iTunes supply + disruption
> detector -> enrich (SE/YouTube/HN) -> resented_giants review-text scan -> rank/export -> deep_dive briefs) and the
> dashboard (https://claude.ai/code/artifact/7d8ef7d9-0f9e-4fc9-a32e-d2a50c125394) are built and populated. I want to
> [PICK: (a) MobileAction-validate the top disruption + gap candidates via my browser session; (b) batch deep_dive.py
> across the top ~15 resented giants; (c) promote <pick> into an incubator Ideas Discussion + ideas/<slug>/
> market-research.md; (d) refine detectors]. Note: I need to provide a fresh YOUTUBE_API_KEY (old one recycled);
> respect the rate-limit rules (pace, no bursts). Don't push/PR unless I ask.
