#!/usr/bin/env python3
"""
DemandRadar — one-command pipeline runner.

Chains the funnel by invoking the existing (unit-tested) stage scripts in order, so
"run DemandRadar" is one deterministic command instead of hand-orchestration. Each stage
already resumes/paces/circuit-breaks on its own; network stages are non-fatal (a throttle
or quota exhaustion warns and the run continues) so a partial refresh still ships.

Presets:
  full     bootstrap from scratch — generate -> broad(DDG) -> priority -> extract ->
           enrich -> resented -> export -> build. (broad + resented are slow/ban-prone;
           run this rarely, e.g. when the keyword lexicon changes.)
  refresh  the scheduled cadence — priority -> extract(bounded batch) -> enrich -> export
           -> build. Reuses the committed broad/priority; safe to run often.
  export   re-derive the dashboard only — export -> build. No network.

  python pipeline.py --preset refresh --max 240 --rate 18
  python pipeline.py --preset full --per-vertical 50

Note: this refreshes the dashboard DATA + rebuilds dashboard.html. Publishing that to the
claude.ai Artifact is a separate step (the Artifact tool) — CI uploads the built file.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
PY = sys.executable
TMPL = os.path.join(HERE, "dashboard.tmpl.html")
DATA = os.path.join(OUT, "dashboard-data.json")
HTML = os.path.join(HERE, "dashboard.html")


def run(label, script, argv, fatal):
    """Run a stage script; return True on success. Non-fatal stages warn and continue."""
    print(f"\n\033[1m━━ {label} ━━\033[0m", flush=True)
    rc = subprocess.run([PY, os.path.join(HERE, script), *argv]).returncode
    if rc != 0:
        msg = f"stage '{label}' exited {rc}"
        if fatal:
            print(f"  ✗ FATAL: {msg}", file=sys.stderr)
            sys.exit(rc)
        print(f"  ⚠ non-fatal: {msg} — continuing", file=sys.stderr)
        return False
    return True


def build_dashboard(tmpl_path=TMPL, data_path=DATA, html_path=HTML):
    """Inject dashboard-data.json into the template (escaping </script>) -> dashboard.html."""
    tmpl = open(tmpl_path).read()
    data = open(data_path).read().replace("</script>", "<\\/script>")
    if "__DATA__" not in tmpl:
        raise ValueError("template missing __DATA__ placeholder")
    open(html_path, "w").write(tmpl.replace("__DATA__", data))
    return html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", choices=["full", "refresh", "export"], default="refresh")
    ap.add_argument("--max", type=int, default=240, help="extract/enrich batch cap")
    ap.add_argument("--rate", type=float, default=18, help="iTunes calls/min")
    ap.add_argument("--per-vertical", type=int, default=50)
    ap.add_argument("--engine", default="ddg", help="broad autocomplete engine")
    a = ap.parse_args()
    kw = os.path.join(OUT, "keywords.jsonl")
    prio = os.path.join(OUT, "keywords.priority.jsonl")

    if a.preset == "full":
        run("generate keywords", "generate_keywords.py", [], fatal=True)
        run("broad demand (autocomplete)", "broad_pass.py", ["--engine", a.engine, "--workers", "2"], fatal=False)

    if a.preset in ("full", "refresh"):
        run("select priority", "select_priority.py", ["--per-vertical", str(a.per_vertical)], fatal=True)
        run("supply (iTunes)", "extract.py",
            ["--keywords", prio, "--workers", "2", "--rate", str(a.rate), "--max", str(a.max)], fatal=False)
        run("community enrich", "enrich_community.py", ["--max", str(a.max)], fatal=False)
        if a.preset == "full":
            run("resented-giant scan", "resented_giants.py", [], fatal=False)

    run("export dashboard data", "export_dashboard.py", [], fatal=True)

    print("\n\033[1m━━ build dashboard.html ━━\033[0m", flush=True)
    build_dashboard()
    print(f"  ✓ wrote {HTML}")
    print("\n✓ pipeline complete. Publish dashboard.html via the Artifact tool to refresh the live board.")


if __name__ == "__main__":
    main()
