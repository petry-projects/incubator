# DemandRadar — extraction spike

Disposable spike for the DemandRadar idea ([incubator Discussion #44](https://github.com/petry-projects/incubator/discussions/44)).
Answers: **can we extract the load-bearing signal on a schedule, headless, with no paid dependency?** Yes.

## Pipeline

```
generate_keywords.py  # 0 idea space   25 verticals x domains x tools         -> output/keywords.jsonl (11,616)
broad_pass.py         # 1 WIDE/cheap    Google Suggest (~10/s, all verticals)  -> output/keywords.broad.jsonl
select_priority.py    # 2 rank+narrow   top-K per vertical by broad demand     -> output/keywords.priority.jsonl
extract.py            # 3 SUPPLY/scarce iTunes on PRIORITY only (ban-prone)    -> output/records.jsonl
enrich_community.py   # 4 community     StackExchange/YouTube, survivors only  -> output/records.enriched.jsonl
labels/               # 5 magnitude     MobileAction, manual, top survivors    -> app-store ground truth
rank_starter_list.py  #   merge + rank  demand-aware                           -> output/starter-list.md  <- deliverable
```

**Funnel principle (why this order):** the widest stage uses the HIGHEST-rate-limit source
(Google Suggest), and each narrower stage uses a scarcer/ban-prone source on fewer,
higher-ranked items — so iTunes only scores ~top-K/vertical, not all 11,616.

**Hard-won rule: every free endpoint IP-bans bursts** (iTunes after ~100 calls, Google
Suggest after ~6k). Use LOW concurrency + pacing from the first call; on a 403-storm go
SILENT — a job that keeps hitting a banned endpoint only extends the ban.

`starter-list.md` is the ranked idea list: non-REJECT candidates by gap severity + supply
scarcity + community corroboration + (app-store channel) MobileAction demand.

Runs weekly + on demand via [`.github/workflows/demand-radar-signal.yml`](../../.github/workflows/demand-radar-signal.yml),
which uploads exactly `output/dashboard-data.json`, `output/starter-list.md`, and `dashboard.html`
as the `demand-radar` artifact. The pipeline itself is standard-library only, so it runs on bare
`python3` (no pip). The separate repository test CI (`build-and-test` in `.github/workflows/ci.yml`)
does `pip install pytest` to run the unit tests.

```
python3 extract.py             # supply signal
python3 enrich_community.py    # + community sizing & corroboration (HN backend by default)
```

## What each layer fills

| Layer | Source | Auth | Status |
|---|---|---|---|
| Supply-quality: relevant incumbents, best rating, freshness, competition, satisfaction, `gap_type` | iTunes Search API | none | ✅ |
| Community sizing: `community_metric` + corroboration of store-absent gaps | Reddit (primary) / HN Algolia (live fallback) | Reddit=OAuth secret; HN=none | ✅ (HN live) |
| Demand magnitude: `app_store_volume` | MobileAction (manual) → `labels/` | paid | 🔒 manual labeled set only |

## Two load-bearing mechanics

**1. Relevance (extract.py).** v0 counted any high-rated app that *token-matched* the query as supply, so
it rated *everything* "served" (`raid dps meter` → **Decibel meters**, `valheim base builder` → **Tiny Tower**).
Now `relevance_score()` is graded — a query token in the app NAME counts full, in the DESCRIPTION counts
partial — which kills collisions while letting *branded* incumbents qualify via their description.
Paired with per-record `supply_confidence`: `discovery_channel = community` ⇒ `low` (App Store is the wrong
lens), so those emit `CANDIDATE*` = "store shows a gap, verify elsewhere."

**2. Community corroboration (enrich_community.py).** Turns `CANDIDATE*` into a real `CANDIDATE` only when
community chatter confirms demand (the "≥2 independent mechanisms" rule, #44): `mentions ≥ 300` → promote,
`< 50` → reject as too thin, else WATCH.

## Findings from running it (this is the point of the spike)

1. **Relevance is essential** — without it the supply layer is meaningless (everything reads "served").
2. **Community source must match the vertical.** The live HN backend is *tech-skewed*: it scored
   `valheim base builder` = 6 and `couch co op finder` = 0, wrongly demoting real gaming gaps. With **Reddit**
   (r/valheim ~700k) these would corroborate. HN proves the *mechanism*; Reddit is the correct *source* for gaming.
3. **Reddit is blocked from datacenter IPs** (unauth 403 in the sandbox; OAuth is rate-limited from cloud
   ranges too) — so the CI Reddit step needs a token **and** likely a proxy. Surfaced as a real infra risk.
4. **Community search is phrasing-sensitive** — `couch co op finder` = 0 but `couch co op` = 1843. Sizing
   should query the broadened concept/aliases, not the literal app-store keyword.
5. **App Store is blind to community gaps** — `labels/`: 9/9 community gaming keywords are N/A in MobileAction,
   3/3 app-store student keywords register. Empirical basis for gating paid ASO on `discovery_channel = app-store`.
6. **Demand magnitude collapses the app-store worklist.** Of 12 app-store starter candidates checked in
   MobileAction, only **`watermark remover`** (vol 48, diff 25) has real demand — and its incumbents are weak
   (3.98★). Five read the ~5 volume floor, four are N/A. So demand-aware ranking promotes the one
   demand-validated idea and demotes the rest as "real gap, no demand" — the precise payoff of layering
   demand (MobileAction) on supply (iTunes). Community candidates are sized separately (community metric).

## Scale reality (the repeatable-process finding)

The free **iTunes Search API hard-caps at ~20–30 calls/min and IP-bans bursts** (403 for ~an hour).
So the 11,616-keyword space **cannot** be scored in one run — bulk scoring is inherently a **polite
daily-batch** process. The pipeline is built for exactly this:
- `extract.py` is **rate-limited** (`--rate`, default 20/min — within the ~20–30/min iTunes
  limit above), **resumable** (skips already-scored
  keywords), **pollution-safe** (a throttled/failed fetch is skipped, never written as a false gap),
  and has a **403-storm circuit breaker** (pauses 300s, then resumes).
- The scheduled Action should run a **bounded batch per day** (`--max ~500 --rate ~20`); over ~2–3
  weeks it accumulates full coverage of the idea space. `generate_keywords.py` output is interleaved
  across verticals, so every partial run already spans all 25.
- Community/demand layers are quota-limited too (SE ~300/day, YouTube ~90/day) → enrich **survivors
  only**, budget-routed (`enrich_community.py --max`).

Net: "score 10k ideas" is a **cron-accumulated** deliverable, not a single run — which is the correct
architecture for a repeatable process anyway.

## Open refinement list

- **Relevance tuning** (still #1): graded token match is better but crude; branded-incumbent recall and
  semantic match remain open.
- **Wire Reddit for real** (token + proxy) so gaming candidates corroborate against their actual community.
- **Broaden community queries** with aliases before sizing.
- **Fix config channel labels** (creator-utilities is really `app-store`).
- **Merge `labels/` into records** as the `app_store_volume` field where present, and use the labeled set to
  calibrate the `supply_confidence` / satisfaction thresholds.
- Summary counter doesn't tally `CANDIDATE*` separately (cosmetic).

## Files

- `keyword-groups.json` — starter-kit app groups (edit freely)
- `extract.py` — supply extractor (stdlib)
- `enrich_community.py` — community sizing + corroboration (stdlib; Reddit/HN backends)
- `rank_starter_list.py` — merges labels, demand-aware ranking → `starter-list.md`
- `labels/mobileaction-labels.json` — manual MobileAction ground truth (app-store magnitude)
- `output/` — generated `records.jsonl`, `records.enriched.jsonl`, `summary.md`, `starter-list.md`

## Tests

Pure pipeline logic (gap classification, disruption thresholds, relevance, resentment
scoring, wedges, ranking) is unit-tested — the network `fetch` layer is separated from the
logic, so no mocking is needed.

```
cd pocs/demand-radar && python3 -m pytest tests/ -q
```

Run them locally with the command above (the repo `build-and-test` CI job is still the
stack-agnostic placeholder; a Python CI stack for this spike lands with a follow-up).
`tests/` covers `extract`, `resented_giants`, `broad_pass`, `export_dashboard`,
`enrich_community`, `rank_starter_list`, and `deep_dive`. The fetch/orchestration layers
(iTunes/DDG/reviews I/O, pacing, ban handling) are integration surface, exercised by real runs.

## Run it (one command)

`pipeline.py` chains the whole funnel via the stage scripts (each resumes/paces on its own;
network stages are non-fatal so a partial refresh still ships):

```
python3 pipeline.py --preset full     # bootstrap: generate→broad(DDG)→priority→extract→enrich→resented→export→build
python3 pipeline.py --preset refresh  # scheduled cadence: priority→extract(bounded)→enrich→export→build
python3 pipeline.py --preset export   # re-derive dashboard only (no network)
```

The scheduled Action (`.github/workflows/demand-radar-signal.yml`) runs `--preset refresh`
weekly and uploads `dashboard.html` + data as a build artifact. Publishing that to the live
claude.ai Artifact is a separate step (CI can't call the Artifact tool).
