"""Plain helpers shared by the DemandRadar test modules (fixtures live in conftest.py)."""

import json


class FakeResponse:
    """Stand-in for the object urlopen() returns (read() + context-manager use)."""

    def __init__(self, payload):
        self._body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHTTP:
    """Routes a request URL to a canned payload by substring. A payload may be a JSON-able
    value, raw bytes, an Exception to raise, or a callable(url) returning any of those."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def add(self, fragment, payload):
        self.routes.append((fragment, payload))
        return self

    def __call__(self, req, timeout=None):
        url = getattr(req, "full_url", req)
        self.calls.append(url)
        for fragment, payload in self.routes:
            if fragment in url:
                if callable(payload):
                    payload = payload(url)
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(payload)
        raise AssertionError(f"unexpected network call: {url}")


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_record(
    kw,
    industry="pets",
    channel="app-store",
    verdict="CANDIDATE",
    gap="nascent",
    comp="low",
    market=0,
    leader_rating=None,
    disruption=False,
    solutions=(),
    community=None,
):
    """A minimal opportunity_record in the shape extract.to_record() emits."""
    return {
        "canonical_query": kw,
        "industry": industry,
        "discovery_channel": channel,
        "verdict_heuristic": verdict,
        "gap": {"gap_type": gap},
        "demand": {"community_metric": community},
        "supply": {
            "competition_intensity": comp,
            "best_existing_satisfaction": "none",
            "best_existing_rating": None,
            "freshest_incumbent_days": None,
            "relevant_incumbents": len(solutions),
            "market_size": market,
            "leader_rating": leader_rating,
            "disruption": disruption,
            "solutions": list(solutions),
        },
    }
