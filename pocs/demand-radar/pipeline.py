#!/usr/bin/env python3
"""
DemandRadar — one-command pipeline runner.

Chains the funnel by calling the existing (unit-tested) stage modules in order, in-process,
so "run DemandRadar" is one deterministic command instead of hand-orchestration. Each stage
already resumes/paces/circuit-breaks on its own; network stages are non-fatal (a throttle
or quota exhaustion warns and the run continues) so a partial refresh still ships.

Presets:
  full     bootstrap from scratch — generate -> broad(DDG) -> priority -> extract ->
           enrich -> resented -> export -> build. (broad + resented are slow/ban-prone;
           run this rarely, e.g. when the keyword lexicon changes.)
  refresh  the scheduled cadence — priority -> extract(bounded batch) -> enrich -> export
           -> build. Reuses the committed broad/priority; safe to run often. extract only
           scores priority keywords that have NO record yet (it never re-scores), so once
           the priority set is fully covered a refresh updates community metrics and the
           exports only. To re-score supply, remove those rows from output/records.jsonl.
  export   re-derive the dashboard only — export -> build. No network.

  python pipeline.py --preset refresh --max 240 --rate 18
  python pipeline.py --preset full --per-vertical 50

Note: this refreshes the dashboard DATA + rebuilds dashboard.html. Publishing that to the
claude.ai Artifact is a separate step (the Artifact tool) — CI uploads the built file.
"""

import argparse
import os
import sys
import traceback

import broad_pass
import enrich_community
import export_dashboard
import extract
import generate_keywords
import rank_starter_list
import resented_giants
import select_priority
from errors import StageError

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TMPL = os.path.join(HERE, "dashboard.tmpl.html")
DATA = os.path.join(OUT, "dashboard-data.json")
HTML = os.path.join(HERE, "dashboard.html")


def run(label, fn, fatal):
    """Run a stage callable in-process; return True on success. Non-fatal stages warn and
    continue. Stages are imported and called directly (no subprocess), so no command line is
    ever assembled from this script's arguments."""
    print(f"\n\033[1m━━ {label} ━━\033[0m", flush=True)
    try:
        fn()
        return True
    except StageError as e:  # the stage reported it cannot continue (bad input / no credentials)
        print(f"  {e}", file=sys.stderr)
    except Exception:  # noqa: BLE001 — a crashed stage is a failed stage; keep its traceback
        traceback.print_exc()
    msg = f"stage '{label}' failed"
    if fatal:
        print(f"  ✗ FATAL: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"  ⚠ non-fatal: {msg} — continuing", file=sys.stderr)
    return False


def build_dashboard(tmpl_path=TMPL, data_path=DATA, html_path=HTML):
    """Inject dashboard-data.json into the template (escaping `<`) -> dashboard.html."""
    try:
        with open(tmpl_path, encoding="utf-8") as f:
            tmpl = f.read()
        with open(data_path, encoding="utf-8") as f:
            # Escape EVERY '<' (not just a lowercase '</script>') so no cased/spaced HTML
            # end tag in review text can terminate the <script> block. '<' is a valid
            # JSON/JS escape that reads back as '<', so the payload is unchanged at runtime.
            data = f.read().replace("<", "\\u003c")
    except (OSError, UnicodeError) as e:  # file-access / encoding — report, don't traceback
        print(f"Error building dashboard: {e}", file=sys.stderr)
        sys.exit(1)
    if "__DATA__" not in tmpl:  # a real programming error in the template — surface it
        raise ValueError("template missing __DATA__ placeholder")
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(tmpl.replace("__DATA__", data))
    except OSError as e:
        print(f"Error building dashboard: {e}", file=sys.stderr)
        sys.exit(1)
    return html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=["full", "refresh", "export"], default="refresh")
    ap.add_argument("--max", type=int, default=240, help="extract/enrich batch cap")
    ap.add_argument("--rate", type=float, default=18, help="iTunes calls/min")
    ap.add_argument("--per-vertical", type=int, default=50)
    ap.add_argument("--engine", default="ddg", choices=list(broad_pass.ENGINES), help="broad autocomplete engine")
    a = ap.parse_args()

    degraded = []  # non-fatal stages that failed — the run ships but must NOT report clean success

    def stage(label, fn, fatal):
        if not run(label, fn, fatal):
            degraded.append(label)

    if a.preset == "full":
        stage("generate keywords", generate_keywords.run, fatal=True)
        stage("broad demand (autocomplete)", lambda: broad_pass.run(workers=2, engine=a.engine), fatal=False)

    if a.preset in ("full", "refresh"):
        stage("select priority", lambda: select_priority.run(per_vertical=a.per_vertical), fatal=True)
        stage(
            "supply (iTunes)",
            lambda: extract.run(keywords_path=extract.PRIORITY_PATH, workers=2, rate=a.rate, max_n=a.max),
            fatal=False,
        )
        stage(
            "community enrich",
            lambda: enrich_community.run(source=enrich_community.default_source(), max_n=a.max),
            fatal=False,
        )
        if a.preset == "full":
            stage("resented-giant scan", resented_giants.run, fatal=False)

    stage("export dashboard data", export_dashboard.main, fatal=True)
    # Refresh the ranked starter list too — it's an uploaded deliverable, so exporting the
    # dashboard data without re-ranking would ship a stale starter-list.md.
    stage("rank starter list", rank_starter_list.main, fatal=True)

    print("\n\033[1m━━ build dashboard.html ━━\033[0m", flush=True)
    build_dashboard()
    print(f"  ✓ wrote {HTML}")

    if degraded:
        # A network stage failed: the dashboard/starter-list were still rebuilt from whatever
        # records survived, but that data may be stale/partial — do NOT report clean success.
        print(
            f"\n⚠ pipeline finished DEGRADED — {len(degraded)} stage(s) failed: "
            f"{', '.join(degraded)}. Published data may be stale or partial.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("\n✓ pipeline complete. Publish dashboard.html via the Artifact tool to refresh the live board.")


if __name__ == "__main__":
    main()
