"""Shared failure signal for the DemandRadar stage modules.

Stages are run two ways: as CLIs (`python extract.py ...`) and in-process by pipeline.py.
A stage's run() therefore must not call sys.exit() on bad input — it raises StageError and
lets the caller decide: the CLI reports the message and exits 1, the pipeline records the
stage as failed and (for non-fatal stages) carries on.
"""

import sys


class StageError(Exception):
    """A stage cannot continue: unreadable/malformed input or missing credentials."""


def run_cli(fn, *args, **kwargs):
    """Call a stage's run() from its CLI main(): a StageError becomes a one-line stderr
    message and exit status 1 instead of a traceback."""
    try:
        return fn(*args, **kwargs)
    except StageError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
