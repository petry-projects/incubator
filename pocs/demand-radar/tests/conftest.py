"""Make the demand-radar scripts importable as modules for unit tests, and keep every test
hermetic: no real network, no real sleeping.

The stage scripts live one level up and aren't a package, and helpers.py sits beside this
file; put both directories on sys.path (explicitly, so it holds under any pytest import mode)."""

import json
import os
import sys
import time
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from helpers import FakeHTTP  # noqa: E402 — needs the sys.path entries above


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record time.sleep() calls instead of sleeping (the stages pace/back off heavily)."""
    calls = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


@pytest.fixture(autouse=True)
def http(monkeypatch):
    """Replace urlopen with a FakeHTTP router; an unrouted URL fails the test, so nothing
    can reach the real network."""
    fake = FakeHTTP()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def argv(monkeypatch):
    """Set sys.argv for a CLI main() under test."""

    def _set(*args):
        monkeypatch.setattr(sys, "argv", ["prog", *args])

    return _set


@pytest.fixture
def write_jsonl():
    def _write(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return str(path)

    return _write
