"""
Tests for the back half of the funnel: community enrichment, the resented-giant scan, the
dashboard export, the starter-list ranker, the deep dive and the one-command pipeline runner.

Same rules as test_funnel_stages.py: the network is faked and all files live under tmp_path.
"""

import base64
import email.message
import json
import math
import urllib.error
import urllib.request

import pytest
from helpers import FakeResponse, make_record, read_jsonl

import deep_dive
import enrich_community as enrich
import errors
import export_dashboard as dash
import pipeline
import rank_starter_list as rank
import records
import resented_giants as rg

# ───────────────────────── enrich_community.py: sources ─────────────────────────


class FakeOpener:
    """Stand-in for urllib.request.build_opener(...): records the request, returns a payload."""

    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        return FakeResponse(self.payload)


@pytest.fixture
def opener(monkeypatch):
    def _install(payload):
        fake = FakeOpener(payload)
        handlers = []

        def build_opener(*hs):
            handlers.extend(hs)
            return fake

        monkeypatch.setattr(urllib.request, "build_opener", build_opener)
        fake.handlers = handlers
        return fake

    return _install


class TestRedirectHandler:
    def test_blocks_redirects_off_oauth_reddit(self):
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token")
        with pytest.raises(urllib.error.HTTPError):
            enrich.HTTPSOnlyRedirectHandler().redirect_request(
                req, None, 302, "Found", email.message.Message(), "http://evil.example/steal"
            )

    def test_follows_redirects_that_stay_on_oauth_reddit(self):
        req = urllib.request.Request("https://www.reddit.com/api/v1/access_token")
        new = enrich.HTTPSOnlyRedirectHandler().redirect_request(
            req, None, 302, "Found", email.message.Message(), "https://oauth.reddit.com/next"
        )
        assert new.full_url == "https://oauth.reddit.com/next"


class TestCommunitySources:
    def test_hackernews_counts_hits(self, http):
        http.add("hn.algolia.com", {"nbHits": 7})
        assert enrich.hn_mentions("mood tracker") == {"source": "hackernews", "mentions": 7, "query": "mood tracker"}
        assert "query=mood%20tracker" in http.calls[0]

    def test_stackexchange_without_key(self, http, monkeypatch):
        monkeypatch.delenv("STACKEXCHANGE_KEY", raising=False)
        http.add("api.stackexchange.com", {"total": 4, "quota_remaining": 250})
        cm = enrich.se_mentions("dice roller", "rpg")
        assert cm == {
            "source": "stackexchange",
            "site": "rpg",
            "mentions": 4,
            "quota_remaining": 250,
            "query": "dice roller",
        }
        assert "site=rpg" in http.calls[0]
        assert "key=" not in http.calls[0]

    def test_stackexchange_appends_key_when_configured(self, http, monkeypatch):
        monkeypatch.setenv("STACKEXCHANGE_KEY", "k 1")
        http.add("api.stackexchange.com", {"total": 0})
        enrich.se_mentions("q", "rpg")
        assert http.calls[0].endswith("&key=k%201")

    def test_youtube_requires_a_key(self, monkeypatch):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="YOUTUBE_API_KEY"):
            enrich.yt_mentions("mood tracker")

    def test_youtube_sums_views_of_relevant_videos_only(self, http, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt")
        http.add(
            "youtube/v3/search",
            {
                "pageInfo": {"totalResults": 99},
                "items": [
                    {"id": {"videoId": "a"}, "snippet": {"title": "Best Mood Tracker apps"}},
                    {"id": {"videoId": "b"}, "snippet": {"title": "Counterargument compilation"}},
                    {"id": {}, "snippet": {"title": "a channel, not a video"}},
                ],
            },
        )
        http.add("youtube/v3/videos", {"items": [{"statistics": {"viewCount": "1200"}}]})
        cm = enrich.yt_mentions("mood tracker")
        assert cm == {
            "source": "youtube",
            "mentions": 1200,
            "relevant_videos": 1,
            "est_total": 99,
            "query": "mood tracker",
        }
        assert "id=a&" in http.calls[1]

    def test_youtube_no_relevant_videos_skips_the_stats_call(self, http, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt")
        http.add("youtube/v3/search", {"items": [{"id": {"videoId": "b"}, "snippet": {"title": "unrelated"}}]})
        cm = enrich.yt_mentions("mood tracker")
        assert cm["mentions"] == 0
        assert cm["relevant_videos"] == 0
        assert len(http.calls) == 1

    def test_youtube_short_query_keeps_every_video(self, http, monkeypatch):
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt")
        http.add("youtube/v3/search", {"items": [{"id": {"videoId": "b"}, "snippet": {"title": "anything"}}]})
        http.add("youtube/v3/videos", {"items": [{"statistics": {"viewCount": "5"}}]})
        assert enrich.yt_mentions("ab")["mentions"] == 5

    def test_reddit_token_uses_basic_auth_and_the_guarded_opener(self, opener):
        fake = opener({"access_token": "tok"})
        assert enrich.reddit_token("id", "secret") == "tok"
        req = fake.requests[0]
        assert req.full_url == "https://www.reddit.com/api/v1/access_token"
        assert req.get_header("Authorization") == "Basic " + base64.b64encode(b"id:secret").decode()
        assert isinstance(fake.handlers[0], enrich.HTTPSOnlyRedirectHandler)

    def test_reddit_calls_cannot_reach_the_network_unfaked(self):
        with pytest.raises(AssertionError, match="unexpected network call via opener"):
            enrich.reddit_mentions("mood tracker", "tok")

    def test_reddit_mentions_counts_posts(self, opener):
        fake = opener({"data": {"children": [{}, {}, {}]}})
        assert enrich.reddit_mentions("mood tracker", "tok") == {
            "source": "reddit",
            "mentions": 3,
            "query": "mood tracker",
        }
        assert fake.requests[0].get_header("Authorization") == "bearer tok"
        assert fake.requests[0].full_url.startswith("https://oauth.reddit.com/search?q=mood+tracker")


# ───────────────────────── enrich_community.py: routing ─────────────────────────


@pytest.fixture
def sources(monkeypatch):
    """Replace the four fetchers with recorders; each can be told to raise."""
    calls = []
    fail = {}

    def make(name):
        def fetcher(q, *extra):
            calls.append((name, q, *extra))
            if name in fail:
                raise fail[name]
            return {"source": name, "mentions": 400, "query": q}

        return fetcher

    monkeypatch.setattr(enrich, "yt_mentions", make("youtube"))
    monkeypatch.setattr(enrich, "se_mentions", make("stackexchange"))
    monkeypatch.setattr(enrich, "hn_mentions", make("hackernews"))
    monkeypatch.setattr(enrich, "reddit_mentions", make("reddit"))
    return calls, fail


def rec_for(vertical, q="mood tracker"):
    return {"canonical_query": q, "industry": vertical}


class TestFetchFor:
    def test_routes_to_the_verticals_preferred_source_and_spends_budget(self, sources):
        calls, _ = sources
        budget = dict(enrich.BUDGET)
        cm = enrich.fetch_for(rec_for("gaming-companions"), None, budget, None, set())
        assert cm["source"] == "youtube"
        assert budget["youtube"] == enrich.BUDGET["youtube"] - 1
        assert calls == [("youtube", "mood tracker")]

    def test_quota_error_marks_source_dead_and_falls_through(self, sources, capsys):
        calls, fail = sources
        fail["youtube"] = RuntimeError("HTTP Error 429: Too Many Requests")
        dead = set()
        cm = enrich.fetch_for(rec_for("gaming-companions"), None, dict(enrich.BUDGET), None, dead)
        assert dead == {"youtube"}
        assert cm["source"] == "stackexchange"
        assert calls[1] == ("stackexchange", "mood tracker", "gaming")
        assert "youtube exhausted" in capsys.readouterr().err

    def test_bare_403_status_trips_the_breaker(self, sources):
        # YouTube reports an exhausted quota as "HTTP Error 403: Forbidden" — no "quota"/"429" text
        _, fail = sources
        fail["youtube"] = urllib.error.HTTPError("u", 403, "Forbidden", email.message.Message(), None)
        dead = set()
        cm = enrich.fetch_for(rec_for("gaming-companions"), None, dict(enrich.BUDGET), None, dead)
        assert dead == {"youtube"}
        assert cm["source"] == "stackexchange"

    def test_quota_word_also_trips_the_breaker(self, sources):
        _, fail = sources
        fail["hackernews"] = RuntimeError("daily Quota exceeded")
        dead = set()
        enrich.fetch_for(rec_for("unmapped"), None, dict(enrich.BUDGET), None, dead)
        assert dead == {"hackernews"}

    def test_other_errors_are_reported_and_the_chain_continues_to_none(self, sources, capsys):
        calls, fail = sources
        fail["hackernews"] = RuntimeError("connection reset")
        dead = set()
        # unmapped vertical: hackernews (fails) -> stackexchange (no site: skipped) -> hackernews (fails)
        cm = enrich.fetch_for(rec_for("unmapped"), None, dict(enrich.BUDGET), None, dead)
        assert cm == {"source": "none", "mentions": None}
        assert dead == set()
        assert [c[0] for c in calls] == ["hackernews", "hackernews"]
        assert "hackernews failed for 'mood tracker'" in capsys.readouterr().err

    def test_skips_dead_and_out_of_budget_sources(self, sources):
        calls, _ = sources
        budget = dict(enrich.BUDGET, stackexchange=0)
        cm = enrich.fetch_for(rec_for("gaming-companions"), None, budget, None, {"youtube"})
        assert cm["source"] == "hackernews"
        assert calls == [("hackernews", "mood tracker")]

    def test_forced_reddit_without_token_yields_none(self, sources):
        calls, _ = sources
        cm = enrich.fetch_for(rec_for("pets"), "reddit", dict(enrich.BUDGET), None, set())
        assert cm == {"source": "none", "mentions": None}
        assert calls == []

    def test_forced_reddit_with_token(self, sources):
        calls, _ = sources
        cm = enrich.fetch_for(rec_for("pets"), "reddit", dict(enrich.BUDGET), "tok", set())
        assert cm["source"] == "reddit"
        assert calls == [("reddit", "mood tracker", "tok")]


class TestRecomputeGuards:
    def test_community_record_without_a_metric_keeps_its_verdict(self):
        rec = make_record("speedrun timer", channel="community", verdict="CANDIDATE*")
        assert enrich.recompute(rec, {"source": "none", "mentions": None}) == ("CANDIDATE*", None)

    def test_non_candidate_community_record_is_not_promoted(self):
        rec = make_record("speedrun timer", channel="community", verdict="WATCH")
        assert enrich.recompute(rec, {"source": "hackernews", "mentions": 9000}) == ("WATCH", None)


class TestSupplyScore:
    def test_ranks_scarce_absent_supply_highest(self):
        assert enrich.supply_score(make_record("a", gap="absent-in-store", comp="low")) == 5
        assert enrich.supply_score(make_record("b", gap="thin", comp="high")) == 1
        assert enrich.supply_score(make_record("c", gap="served", comp="unknown")) == 0


# ───────────────────────── enrich_community.py: run ─────────────────────────


class TestEnrichRun:
    def test_enriches_survivors_and_rewrites_every_record(self, tmp_path, write_jsonl, sources, monkeypatch, capsys):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        records = [
            make_record("speedrun timer", industry="unmapped", channel="community", verdict="CANDIDATE*"),
            make_record("served thing", verdict="REJECT", gap="served"),
            make_record("dog log", industry="pets", channel="app-store", verdict="CANDIDATE"),
        ]
        inp = write_jsonl(tmp_path / "records.jsonl", records)
        out = tmp_path / "enriched.jsonl"
        changed = enrich.run(inp=inp, out=str(out), sleep=0)

        assert changed == [("speedrun timer", "CANDIDATE*", "CANDIDATE", 400, "hackernews")]
        by_kw = {r["canonical_query"]: r for r in read_jsonl(out)}
        assert set(by_kw) == {"speedrun timer", "served thing", "dog log"}
        assert by_kw["speedrun timer"]["verdict_heuristic"] == "CANDIDATE"
        assert by_kw["speedrun timer"]["community_note"] == "community-corroborated"
        assert by_kw["speedrun timer"]["corroboration_count"] == 2
        assert by_kw["dog log"]["demand"]["community_metric"]["source"] == "stackexchange"
        assert by_kw["dog log"]["verdict_heuristic"] == "CANDIDATE"
        assert by_kw["served thing"]["demand"]["community_metric"] is None  # REJECTs are not enriched
        assert "skipping youtube source" in capsys.readouterr().err

    def test_youtube_is_used_when_a_key_is_present(self, tmp_path, write_jsonl, sources, monkeypatch):
        calls, _ = sources
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt")
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record("boss guide", industry="gaming-companions")])
        enrich.run(inp=inp, out=str(tmp_path / "o.jsonl"), sleep=0)
        assert calls == [("youtube", "boss guide")]

    def test_max_n_enriches_only_the_scarcest(self, tmp_path, write_jsonl, sources, monkeypatch):
        calls, _ = sources
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        inp = write_jsonl(
            tmp_path / "r.jsonl",
            [
                make_record("thin one", industry="unmapped", gap="thin", comp="high"),
                make_record("absent one", industry="unmapped", gap="absent-in-store", comp="low"),
            ],
        )
        enrich.run(inp=inp, out=str(tmp_path / "o.jsonl"), max_n=1, sleep=0)
        assert calls == [("hackernews", "absent one")]

    def test_reports_progress_every_50_and_paces(self, tmp_path, write_jsonl, sources, monkeypatch, capsys, sleeps):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record(f"kw {i}", industry="unmapped") for i in range(50)])
        enrich.run(inp=inp, out=str(tmp_path / "o.jsonl"), sleep=0.25)
        assert "50/50" in capsys.readouterr().out
        assert sleeps == [0.25] * 50

    def test_forced_reddit_without_credentials_is_a_stage_error(self, tmp_path, write_jsonl, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record("dog log")])
        out = tmp_path / "o.jsonl"
        with pytest.raises(errors.StageError, match="requires REDDIT_CLIENT_ID"):
            enrich.run(inp=inp, out=str(out), source="reddit", sleep=0)
        assert not out.exists()

    def test_unknown_forced_source_is_a_stage_error(self, tmp_path, write_jsonl):
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record("dog log")])
        out = tmp_path / "o.jsonl"
        with pytest.raises(errors.StageError, match="unknown community source 'stackexchnage'"):
            enrich.run(inp=inp, out=str(out), source="stackexchnage", sleep=0)
        assert not out.exists()

    def test_forced_youtube_without_a_key_is_a_stage_error(self, tmp_path, write_jsonl, monkeypatch):
        monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record("dog log")])
        out = tmp_path / "o.jsonl"
        with pytest.raises(errors.StageError, match="requires YOUTUBE_API_KEY"):
            enrich.run(inp=inp, out=str(out), source="youtube", sleep=0)
        assert not out.exists()

    def test_forced_youtube_with_a_key(self, tmp_path, write_jsonl, sources, monkeypatch):
        calls, _ = sources
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt")
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record("dog log", industry="pets")])
        enrich.run(inp=inp, out=str(tmp_path / "o.jsonl"), source="youtube", sleep=0)
        assert calls == [("youtube", "dog log")]

    def test_forced_reddit_with_credentials(self, tmp_path, write_jsonl, sources, monkeypatch):
        calls, _ = sources
        monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")
        monkeypatch.setattr(enrich, "reddit_token", lambda cid, sec: f"tok-{cid}-{sec}")
        inp = write_jsonl(tmp_path / "r.jsonl", [make_record("dog log")])
        enrich.run(inp=inp, out=str(tmp_path / "o.jsonl"), source="reddit", sleep=0)
        assert calls == [("reddit", "dog log", "tok-id-secret")]


class TestEnrichMain:
    def test_passes_cli_options(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(enrich, "run", lambda **kw: seen.update(kw))
        argv("--source", "hackernews", "--max", "5", "--sleep", "0")
        enrich.main()
        assert seen == {"source": "hackernews", "max_n": 5, "sleep": 0.0}

    def test_source_defaults_from_environment(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(enrich, "run", lambda **kw: seen.update(kw))
        monkeypatch.setenv("DR_COMMUNITY_SOURCE", "stackexchange")
        argv()
        enrich.main()
        assert seen == {"source": "stackexchange", "max_n": 300, "sleep": 0.25}

    def test_default_source_is_auto_route_when_unset(self, monkeypatch):
        monkeypatch.delenv("DR_COMMUNITY_SOURCE", raising=False)
        assert enrich.default_source() == ""


# ───────────────────────── resented_giants.py ─────────────────────────


def review_entry(rating, title="t", body="b"):
    return {"im:rating": {"label": str(rating)}, "title": {"label": title}, "content": {"label": body}}


def leader_record(app, market, app_id=None, kw=None, leader_rating=4.7):
    return make_record(
        kw or f"{app.lower()} kw",
        market=market,
        leader_rating=leader_rating,
        solutions=[{"app": app, "id": app_id, "rating_count": market}],
    )


class TestResentedFetchers:
    def test_get_returns_raw_bytes(self, http):
        http.add("example.test", b"raw-bytes")
        assert rg.get("https://example.test/x") == b"raw-bytes"

    def test_resolve_id_requires_an_exact_title_match(self, http):
        http.add(
            "itunes.apple.com/search",
            {"results": [{"trackId": 1, "trackName": "Quizlet Plus Helper"}, {"trackId": 99, "trackName": "QUIZLET "}]},
        )
        assert rg.resolve_id("Quizlet") == 99
        assert "term=Quizlet" in http.calls[0]

    def test_resolve_id_rejects_a_lookalike_first_hit(self, http):
        http.add("itunes.apple.com/search", {"results": [{"trackId": 1, "trackName": "Quizlet Plus Helper"}]})
        assert rg.resolve_id("Quizlet") is None

    def test_resolve_id_is_none_when_nothing_found_or_request_fails(self, http):
        http.add("term=Nothing", {"results": []})
        http.add("term=Broken", OSError("403"))
        assert rg.resolve_id("Nothing") is None
        assert rg.resolve_id("Broken") is None

    def test_fetch_low_reviews_is_none_when_no_page_can_be_fetched(self, http, sleeps):
        http.add("page=1/id=7", OSError("timed out"))
        assert rg.fetch_low_reviews(7) is None
        assert sleeps == []

    def test_fetch_low_reviews_keeps_1_to_3_stars_and_stops_on_error(self, http, sleeps):
        http.add(
            "page=1/id=7",
            {
                "feed": {
                    "entry": [
                        review_entry(1, "Paywall", "now costs money"),
                        review_entry(5, "Great", "love it"),
                        review_entry(3, "Meh", "ads"),
                        {"title": {"label": "app metadata row, no rating"}},
                    ]
                }
            },
        )
        http.add("page=2/id=7", OSError("403"))
        assert rg.fetch_low_reviews(7) == [(1, "Paywall", "now costs money"), (3, "Meh", "ads")]
        assert sleeps == [0.4]  # paced after page 1 only; page 2 failed

    def test_fetch_low_reviews_reads_both_pages(self, http, sleeps):
        http.add("page=1/id=7", {"feed": {"entry": [review_entry(2)]}})
        http.add("page=2/id=7", {"feed": {}})
        assert rg.fetch_low_reviews(7) == [(2, "t", "b")]
        assert sleeps == [0.4, 0.4]


class TestResentedRun:
    @pytest.fixture
    def scan_inputs(self, monkeypatch):
        """Fake the two network helpers: id lookup by app name, low reviews by track id."""
        paywall = [(1, "Paywall", "subscription only now")] * 4 + [(2, "Bug", "crashes on launch")]
        reviews = {11: paywall, 77: [(1, "Ads", "so many ads")] * 2}
        ids = {"Resolved App": 77}
        asked = {"ids": [], "reviews": []}

        def resolve_id(name):
            asked["ids"].append(name)
            return ids.get(name)

        def fetch_low_reviews(tid):
            asked["reviews"].append(tid)
            return reviews.get(tid, [])

        monkeypatch.setattr(rg, "resolve_id", resolve_id)
        monkeypatch.setattr(rg, "fetch_low_reviews", fetch_low_reviews)
        return asked

    def test_scans_new_leaders_and_flags_the_resented(self, tmp_path, write_jsonl, scan_inputs, capsys):
        records = [
            leader_record("BigApp", 9000, app_id=11, kw="flashcards"),
            leader_record("BigApp", 12000, app_id=11, kw="study cards"),  # bigger market wins the leader slot
            leader_record("Small", 5000, app_id=2),  # below the proven-market floor
            make_record("no leader", market=9000, solutions=[{"app": "X", "id": 3, "rating_count": 1}]),
            make_record("unnamed leader", market=9000, solutions=[{"app": "", "id": 4, "rating_count": 9000}]),
            leader_record("NoId App", 8500),
            leader_record("Resolved App", 8600),
            leader_record("OldDone", 9100, app_id=5),
            *[leader_record(f"Filler {i}", 8000 + i, app_id=100 + i) for i in range(10)],
        ]
        inp = write_jsonl(tmp_path / "records.jsonl", records)
        out = tmp_path / "resented.json"
        out.write_text(json.dumps({"olddone": {"app": "OldDone", "resented": False}}), encoding="utf-8")

        result = rg.run(inp=inp, out_path=str(out), sleep=0)

        assert json.loads(out.read_text(encoding="utf-8")) == result
        big = result["bigapp"]
        assert big["resented"] is True
        assert big["market"] == 12000
        assert big["kw"] == "study cards"
        assert big["switch_hits"] == 4
        assert big["resent_frac"] == 0.8
        assert result["noid app"] == {
            "app": "NoId App",
            "id": None,
            "market": 8500,
            "vert": "pets",
            "kw": "noid app kw",
            "leaderR": 4.7,
            "resented": False,
            "note": "no-id",
        }
        assert result["resolved app"]["id"] == 77
        assert result["resolved app"]["resented"] is False  # 2 switch-gripes is under the floor of 4
        assert result["olddone"] == {"app": "OldDone", "resented": False}  # resumed, not rescanned
        assert "small" not in result
        assert scan_inputs["ids"] == ["NoId App", "Resolved App"]
        assert 5 not in scan_inputs["reviews"]
        stdout = capsys.readouterr().out
        assert "proven-market leaders: 14 | already done: 1 | to process: 13" in stdout
        assert "10/13" in stdout
        assert "RESENTED GIANTS: 1" in stdout
        assert "resent=80% [pricing]  BigApp" in stdout

    def test_leader_with_unfetchable_reviews_is_marked_for_retry(self, tmp_path, write_jsonl, monkeypatch, capsys):
        monkeypatch.setattr(rg, "fetch_low_reviews", lambda tid: None if tid == 1 else [])
        inp = write_jsonl(
            tmp_path / "r.jsonl", [leader_record("Throttled", 9000, app_id=1), leader_record("Fine", 9000, app_id=2)]
        )
        result = rg.run(inp=inp, out_path=str(tmp_path / "resented.json"), sleep=0)
        assert result["throttled"]["note"] == "reviews-unavailable"  # not a completed "not resented" scan
        assert result["throttled"]["resented"] is False
        assert "n_low" not in result["throttled"]
        assert result["fine"]["n_low"] == 0
        assert "1 leader(s) had no fetchable reviews this run" in capsys.readouterr().out

    def test_deferred_leader_is_retried_after_fresh_ones_and_can_recover(
        self, tmp_path, write_jsonl, monkeypatch, capsys
    ):
        asked = []
        monkeypatch.setattr(rg, "fetch_low_reviews", lambda tid: asked.append(tid) or [])
        inp = write_jsonl(
            tmp_path / "r.jsonl",
            [
                leader_record("Deferred", 9000, app_id=1),
                leader_record("Fresh A", 9000, app_id=2),
                leader_record("Fresh B", 9000, app_id=3),
            ],
        )
        out = tmp_path / "resented.json"
        out.write_text(
            json.dumps({"deferred": {"app": "Deferred", "id": 1, "resented": False, "note": "reviews-unavailable"}}),
            encoding="utf-8",
        )
        # a batch of 2: the never-attempted leaders go first, so the deferred one cannot starve them
        rg.run(inp=inp, out_path=str(out), max_n=2, sleep=0)
        assert asked == [2, 3]
        assert "already done: 0 | to process: 2" in capsys.readouterr().out
        # next run: only the deferred leader is left, and a successful fetch replaces the marker
        result = rg.run(inp=inp, out_path=str(out), max_n=2, sleep=0)
        assert asked == [2, 3, 1]
        assert "note" not in result["deferred"]
        assert result["deferred"]["n_low"] == 0

    def test_max_n_bounds_the_batch(self, tmp_path, write_jsonl, scan_inputs):
        inp = write_jsonl(
            tmp_path / "r.jsonl", [leader_record("A", 9000, app_id=1), leader_record("B", 9000, app_id=2)]
        )
        out = tmp_path / "resented.json"
        result = rg.run(inp=inp, out_path=str(out), max_n=1, sleep=0)
        assert list(result) == ["a"]
        assert scan_inputs["reviews"] == [1]

    def test_min_market_raises_the_floor(self, tmp_path, write_jsonl, scan_inputs):
        inp = write_jsonl(tmp_path / "r.jsonl", [leader_record("A", 9000, app_id=1)])
        assert rg.run(inp=inp, out_path=str(tmp_path / "o.json"), min_market=20000, sleep=0) == {}
        assert scan_inputs["reviews"] == []

    def test_main_passes_cli_options(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(rg, "run", lambda **kw: seen.update(kw))
        argv("--min-market", "9000", "--max", "3", "--sleep", "0.5")
        rg.main()
        assert seen == {"min_market": 9000, "max_n": 3, "sleep": 0.5}


# ───────────────────────── export_dashboard.py / rank_starter_list.py ─────────────────────────

LABELS = {
    "labels": [
        {"keyword": "Watermark Remover", "volume": 48},
        {"keyword": "travel journal", "volume": 17},
        {"keyword": "fall alert", "volume": 5},
    ]
}
BROAD = [
    {"keyword": "Watermark Remover", "broad_interest": 8, "app_intent": 1},
    {"keyword": "coin finder", "broad_interest": 2, "app_intent": 1},
    {"keyword": "failed row", "broad_interest": None},
]


def gap_records():
    return [
        make_record("watermark remover", channel="app-store", verdict="CANDIDATE*", gap="absent-in-store"),
        make_record("travel journal", channel="app-store", verdict="WATCH", gap="thin", comp="medium"),
        make_record("fall alert", channel="app-store", gap="nascent"),
        make_record(
            "speedrun timer",
            channel="community",
            gap="absent-in-store",
            community={"mentions": 400, "source": "hackernews"},
        ),
        make_record("coin finder", channel="community", gap="absent-in-store"),
        make_record("dog log", channel="app-store", gap="nascent"),
        make_record("rejected thing", verdict="REJECT", gap="served", comp="high"),
    ]


@pytest.fixture
def project(tmp_path, write_jsonl):
    """A throwaway DemandRadar dir (labels/ + output/) for the HERE-relative stages."""

    def _make(records, enriched=False, aux=True):
        write_jsonl(tmp_path / "output" / ("records.enriched.jsonl" if enriched else "records.jsonl"), records)
        if aux:
            (tmp_path / "labels").mkdir()
            (tmp_path / "labels" / "mobileaction-labels.json").write_text(json.dumps(LABELS), encoding="utf-8")
            write_jsonl(tmp_path / "output" / "keywords.broad.jsonl", BROAD)
        return tmp_path

    return _make


class TestDashboardHelpers:
    def test_cbonus_is_zero_without_a_metric(self):
        assert dash.cbonus(None) == 0

    def test_disruption_without_supply_block(self):
        assert dash.disruption({"canonical_query": "x"}) == (0, None, None, False)

    def test_detector_leader_is_recovered_by_review_count_not_name(self):
        # "Quizlet" is the detector's leader for this query via its description; its name
        # shares no token with the query, so a name-only match would lose it (and with it
        # the resented.json lookup that is keyed on this app).
        rec = make_record(
            "flashcard maker",
            market=600000,
            leader_rating=4.8,
            solutions=[
                {"app": "Flashcard Maker Lite", "rating": 4.2, "rating_count": 900},
                {"app": "Quizlet", "rating": 4.8, "rating_count": 600000},
            ],
        )
        assert dash.disruption(rec) == (600000, 4.8, "Quizlet", False)

    def test_detector_record_without_a_count_match_falls_back_to_name(self):
        rec = make_record(
            "flashcard maker",
            market=600000,
            leader_rating=4.8,
            solutions=[{"app": "Flashcard Maker Lite", "rating": 4.2, "rating_count": 900}],
        )
        assert dash.disruption(rec) == (600000, 4.8, "Flashcard Maker Lite", False)

    def test_zero_market_never_matches_an_unrated_app(self):
        rec = make_record("flashcard maker", market=0, solutions=[{"app": "Unrelated", "rating_count": 0}])
        assert dash.disruption(rec) == (0, None, None, False)

    def test_legacy_disruption_with_no_relevant_app(self):
        rec = {"canonical_query": "mood tracker", "supply": {"solutions": [{"app": "Unrelated", "rating": 4.0}]}}
        assert dash.disruption(rec) == (0, None, None, False)


class TestExportDashboard:
    def export(self, monkeypatch, here):
        monkeypatch.setattr(dash, "HERE", str(here))
        dash.main()
        rows = json.loads((here / "output" / "dashboard-data.json").read_text(encoding="utf-8"))
        return {r["kw"]: r for r in rows}, [r["kw"] for r in rows]

    def test_gap_lens_scoring_labels_and_trust(self, project, monkeypatch):
        by_kw, order = self.export(monkeypatch, project(gap_records()))

        assert "rejected thing" not in by_kw
        assert order[0] == "watermark remover"
        wm = by_kw["watermark remover"]  # 1.0 unverified-absent + 2 low comp + 1 app intent + 8/4 broad + 2 volume
        assert wm["score"] == 8.0
        assert wm["trust"] == "unverified-absent"
        assert wm["magnote"] == "demand-validated"
        assert wm["vol"] == 48
        assert wm["needsMA"] is False
        assert by_kw["travel journal"]["score"] == 3.0  # 1 thin + 1 medium comp + 1 mid volume
        assert by_kw["travel journal"]["magnote"] is None
        assert by_kw["fall alert"]["score"] == 1.0  # 2 nascent + 2 low comp - 3 no store demand
        assert by_kw["fall alert"]["magnote"] == "no-store-demand"
        assert by_kw["speedrun timer"]["score"] == 4.5  # 0.5 nonsense-gated absent + 2 comp + 2 corroborated
        assert by_kw["speedrun timer"]["comm"] == 400
        assert by_kw["speedrun timer"]["commSrc"] == "hackernews"
        assert by_kw["coin finder"]["score"] == 6.5  # absent kept at 3: autocomplete shows app intent
        assert by_kw["dog log"]["needsMA"] is True
        assert by_kw["dog log"]["verdict"] == "CANDIDATE"
        assert by_kw["dog log"]["disrupt"] is False

    def test_disruption_lens_star_and_resented_targets(self, project, monkeypatch):
        star = make_record(
            "mood tracker",
            verdict="REJECT",
            gap="served",
            comp="high",
            market=50000,
            leader_rating=3.9,
            disruption=True,
            solutions=[{"app": "Mood Tracker Pro", "rating": 3.9, "rating_count": 50000, "last_updated_days": 9}],
        )
        resented = make_record(
            "white noise",
            verdict="REJECT",
            gap="served",
            comp="high",
            market=90000,
            leader_rating=4.8,
            solutions=[{"app": "White Noise Deluxe", "rating": 4.8, "rating_count": 90000}],
        )
        legacy = make_record(
            "guitar chords",
            verdict="REJECT",
            gap="served",
            comp="high",
            solutions=[{"app": "Guitar Chords Ultimate", "rating": 3.8, "rating_count": 20000}],
        )
        del legacy["supply"]["market_size"]  # scored before the detector existed
        odd = make_record("odd metric", channel="community", community={"mentions": "12", "source": "reddit"})
        here = project([star, resented, legacy, odd], enriched=True, aux=False)
        (here / "output" / "resented.json").write_text(
            json.dumps(
                {
                    "white noise deluxe": {
                        "resented": True,
                        "resent_frac": 0.5,
                        "cat_hits": {"pricing": 3, "ads": 1, "enshittification": 0, "missing": 2},
                        "gripes": [{"r": 1, "t": "Paywall"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        by_kw, _ = self.export(monkeypatch, here)

        mood = by_kw["mood tracker"]
        assert mood["verdict"] == "DISRUPT"
        assert mood["leaderApp"] == "Mood Tracker Pro"
        assert mood["dScore"] == round(math.log10(50000) * (4.6 - 3.9), 2)
        assert mood["resented"] is False
        assert mood["wedge"] is None
        assert mood["needsMA"] is False
        assert mood["apps"] == [{"n": "Mood Tracker Pro", "r": 3.9, "c": 50000, "u": 9}]

        noise = by_kw["white noise"]
        assert noise["verdict"] == "DISRUPT"
        assert noise["resented"] is True
        assert noise["resentFrac"] == 0.5
        assert noise["resentCats"] == ["pricing", "ads"]
        assert noise["gripes"] == [{"r": 1, "t": "Paywall"}]
        assert noise["dScore"] == round(math.log10(90000) * 0.5, 2)
        assert len(noise["wedge"]) == 3
        assert noise["wedge"][0].startswith("Fix the money model")

        guitar = by_kw["guitar chords"]
        assert guitar["disrupt"] is True
        assert guitar["market"] == 20000
        assert guitar["leaderR"] == 3.8

        assert by_kw["odd metric"]["comm"] is None  # a non-integer mention count is not trusted
        assert by_kw["odd metric"]["vol"] is None


class TestLoadCurrentRecords:
    def test_base_records_overlaid_with_their_enriched_copies(self, tmp_path, write_jsonl):
        enriched_dog = make_record("dog log", community={"mentions": 40, "source": "stackexchange"})
        write_jsonl(tmp_path / "output" / "records.jsonl", [make_record("dog log"), make_record("cat log")])
        write_jsonl(tmp_path / "output" / "records.enriched.jsonl", [enriched_dog])
        rows = records.load_current(str(tmp_path))
        # "cat log" was appended after the last successful enrichment: still reported
        assert [r["canonical_query"] for r in rows] == ["dog log", "cat log"]
        assert rows[0]["demand"]["community_metric"] == {"mentions": 40, "source": "stackexchange"}
        assert rows[1]["demand"]["community_metric"] is None

    def test_same_phrase_in_two_verticals_stays_distinct(self, tmp_path, write_jsonl):
        write_jsonl(
            tmp_path / "output" / "records.jsonl",
            [make_record("medication tracker", industry="pets"), make_record("medication tracker", industry="seniors")],
        )
        write_jsonl(
            tmp_path / "output" / "records.enriched.jsonl",
            [make_record("medication tracker", industry="seniors", verdict="WATCH")],
        )
        rows = records.load_current(str(tmp_path))
        assert [(r["industry"], r["verdict_heuristic"]) for r in rows] == [("pets", "CANDIDATE"), ("seniors", "WATCH")]

    def test_only_one_file_present(self, tmp_path, write_jsonl):
        write_jsonl(tmp_path / "output" / "records.enriched.jsonl", [make_record("dog log")])
        assert [r["canonical_query"] for r in records.load_current(str(tmp_path))] == ["dog log"]

    def test_no_records_at_all_is_an_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            records.load_current(str(tmp_path))


class TestRankStarterList:
    def test_community_bonus_without_a_metric(self):
        assert rank.community_bonus(make_record("x")) == (0, None)

    def test_writes_ranked_markdown_with_worklist(self, project, monkeypatch, capsys):
        here = project(gap_records())
        monkeypatch.setattr(rank, "HERE", str(here))
        rank.main()
        md = (here / "output" / "starter-list.md").read_text(encoding="utf-8")
        rows = [line for line in md.splitlines() if line.startswith("| ") and "keyword" not in line]

        assert "6 non-REJECT candidates from 7 keywords." in md
        assert [r.split(" | ")[1] for r in rows] == [
            "watermark remover",
            "coin finder",
            "speedrun timer",
            "dog log",
            "travel journal",
            "fall alert",
        ]
        assert rows[0].startswith(
            "| 8.0 | watermark remover | pets | app-store | absent-in-store | low | 1/8 | — | 48 |"
        )
        assert rows[0].endswith("| CANDIDATE* | demand-validated · unverified-absent |")
        assert "| 400 | — | CANDIDATE |" in rows[2]
        assert rows[3].endswith("| needs MA ▲ |")
        assert rows[5].endswith("| no store demand |")
        assert "**MobileAction worklist (1 app-store candidates need magnitude):**\n\n`dog log`" in md
        assert "(6 candidates)" in capsys.readouterr().out

    def test_prefers_enriched_records_and_tolerates_missing_aux_files(self, project, monkeypatch):
        here = project([make_record("dog log")], enriched=True, aux=False)
        monkeypatch.setattr(rank, "HERE", str(here))
        rank.main()
        md = (here / "output" / "starter-list.md").read_text(encoding="utf-8")
        assert "| 4.0 | dog log |" in md


# ───────────────────────── deep_dive.py ─────────────────────────


class TestDeepDiveFetchers:
    def test_get_returns_raw_bytes(self, http):
        http.add("example.test", b"raw")
        assert deep_dive.get("https://example.test/") == b"raw"

    def test_load_ma_label(self, tmp_path, monkeypatch):
        monkeypatch.setattr(deep_dive, "HERE", str(tmp_path))
        assert deep_dive.load_ma_label("mood tracker") is None  # no labels file
        (tmp_path / "labels").mkdir()
        (tmp_path / "labels" / "mobileaction-labels.json").write_text(json.dumps(LABELS), encoding="utf-8")
        assert deep_dive.load_ma_label("WATERMARK remover") == {"keyword": "Watermark Remover", "volume": 48}
        assert deep_dive.load_ma_label("unlabelled") is None

    def test_competitors_asks_for_at_least_ten_and_trims_to_top(self, http):
        http.add("itunes.apple.com/search", {"results": [{"trackId": i} for i in range(12)]})
        assert deep_dive.competitors("mood tracker", 3) == [{"trackId": 0}, {"trackId": 1}, {"trackId": 2}]
        assert "limit=10" in http.calls[0]

    def test_reviews_is_none_when_no_page_can_be_fetched(self, http):
        http.add("page=1/id=7", OSError("403"))
        assert deep_dive.reviews(7, 3) is None

    def test_reviews_reads_rated_entries_and_stops_on_error(self, http, sleeps):
        http.add(
            "page=1/id=7",
            {"feed": {"entry": [review_entry(2, "Meh", "ads"), {"title": {"label": "metadata row"}}]}},
        )
        http.add("page=2/id=7", OSError("403"))
        assert deep_dive.reviews(7, 3) == [(2, "Meh", "ads")]
        assert sleeps == [0.4]


class TestSynthWedge:
    def test_only_dominant_known_gripes_make_the_wedge(self):
        wedge = deep_dive.synth_wedge({"pricing / paywall": 5, "ads": 1, "not a template": 9}, {"simple": 3})
        assert len(wedge) == 2
        assert wedge[0].startswith("**Fix the money model** (5 gripes")
        assert wedge[1] == "**Keep what they love:** simple — don't out-feature these into complexity."

    def test_nothing_to_say_without_signal(self):
        assert deep_dive.synth_wedge({}, {}) == []


class TestDeepDiveMain:
    APPS = [
        {
            "trackName": "Daylio",
            "trackId": 1,
            "sellerName": "Habitics",
            "averageUserRating": 4.71,
            "userRatingCount": 5000,
            "formattedPrice": "Free",
            "currentVersionReleaseDate": "2020-01-01T00:00:00Z",
            "primaryGenreName": "Health",
        },
        {"trackName": "Tiny", "trackId": 2, "userRatingCount": 10},
        {"trackName": "NoId", "trackId": None, "userRatingCount": 9000},
    ]
    REVIEWS = [
        (1, "Paywall", "Everything is behind a subscription now. I wish it had a dark mode option."),
        (2, "ads", "so many ads and a subscription"),
        (1, "greedy", "money grab, used to be free"),
        (5, "Love", "So simple and clean, love it"),
        (4, "ok", "easy to use\nI wish there was export to csv please"),
    ]

    @pytest.fixture
    def dive(self, tmp_path, monkeypatch, argv):
        mined = []

        def reviews(tid, pages):
            mined.append((tid, pages))
            return self.REVIEWS

        def _run(apps, *cli):
            monkeypatch.setattr(deep_dive, "HERE", str(tmp_path))
            monkeypatch.setattr(deep_dive, "competitors", lambda kw, top: apps[:top])
            monkeypatch.setattr(deep_dive, "reviews", reviews)
            argv(*cli)
            deep_dive.main()
            return tmp_path / "output" / "deepdive", mined

        return _run

    def test_writes_json_and_markdown_brief(self, tmp_path, dive):
        (tmp_path / "labels").mkdir()
        (tmp_path / "labels" / "mobileaction-labels.json").write_text(
            json.dumps({"labels": [{"keyword": "mood tracker", "volume": 48, "difficulty": 32, "ranked_apps": 234}]}),
            encoding="utf-8",
        )
        outdir, mined = dive(
            self.APPS, "--keyword", "Mood Tracker", "--top", "3", "--pages", "2", "--min-ratings", "100"
        )

        assert mined == [(1, 2)]  # only the credible incumbent with an id is review-mined
        result = json.loads((outdir / "mood-tracker.json").read_text(encoding="utf-8"))
        assert result["keyword"] == "Mood Tracker"
        assert result["mobileaction"]["volume"] == 48
        assert [c["app"] for c in result["competitors"]] == ["Daylio", "Tiny", "NoId"]
        assert result["competitors"][0]["reviews"]["resent_frac"] == 1.0
        assert result["market_gripes"]["pricing / paywall"] == 3
        assert result["market_loves"] == {"simple": 1, "clean": 1, "love": 1, "easy": 1}
        assert result["wishes"] == ["wish it had a dark mode option", "wish there was export to csv please"]
        assert result["wedge"][0].startswith("**Fix the money model** (3 gripes")

        md = (outdir / "mood-tracker.md").read_text(encoding="utf-8")
        assert "**Market demand (MobileAction):** search volume `48` · difficulty `32` · 234 ranked apps." in md
        assert "| Daylio | 4.71 | 5,000 | Free | 2020-01 | 100% |" in md
        assert "| Tiny | 0 | 10 | None |  | — |" in md
        assert "*Aging (no update since" in md
        assert "- **pricing / paywall** — 3 complaint(s) across leaders" in md
        assert '    - *"Paywall"* — Everything is behind a subscription now.' in md
        assert '- "wish there was export to csv please"' in md
        assert "## The wedge — how to win" in md

    def test_market_wishes_draw_from_every_competitor(self, tmp_path, monkeypatch, argv):
        apps = [{"trackName": n, "trackId": i, "userRatingCount": 5000} for i, n in enumerate(["A", "B", "C"], 1)]
        by_app = {i: [(2, "t", f"I wish app {i} had feature number {n} today.") for n in range(6)] for i in (1, 2, 3)}
        monkeypatch.setattr(deep_dive, "HERE", str(tmp_path))
        monkeypatch.setattr(deep_dive, "competitors", lambda kw, top: apps)
        monkeypatch.setattr(deep_dive, "reviews", lambda tid, pages: by_app[tid])
        argv("--keyword", "white noise")
        deep_dive.main()
        result = json.loads((tmp_path / "output" / "deepdive" / "white-noise.json").read_text(encoding="utf-8"))
        assert len(result["wishes"]) == 10
        assert [w.split()[2] for w in result["wishes"]] == ["1", "2", "3", "1", "2", "3", "1", "2", "3", "1"]

    def test_unavailable_reviews_render_as_unknown_not_zero(self, tmp_path, monkeypatch, argv):
        monkeypatch.setattr(deep_dive, "HERE", str(tmp_path))
        monkeypatch.setattr(deep_dive, "competitors", lambda kw, top: self.APPS[:1])
        monkeypatch.setattr(deep_dive, "reviews", lambda tid, pages: None)
        argv("--keyword", "mood tracker")
        deep_dive.main()
        outdir = tmp_path / "output" / "deepdive"
        comp = json.loads((outdir / "mood-tracker.json").read_text(encoding="utf-8"))["competitors"][0]
        assert comp["reviews_unavailable"] is True
        assert "reviews" not in comp
        assert "| Daylio | 4.71 | 5,000 | Free | 2020-01 | n/a |" in (outdir / "mood-tracker.md").read_text(
            encoding="utf-8"
        )

    def test_loves_match_whole_words_only(self):
        rv = deep_dive.analyze_reviews(
            [(5, "ugh", "it freezes but the fastest bestie loved it"), (5, "ok", "free and fast")]
        )
        assert rv["loves"] == {"free": 1, "fast": 1}

    def test_long_excerpts_are_marked_as_clipped(self):
        body = "subscription " * 30
        rv = deep_dive.analyze_reviews([(1, "T" * 80, body)])
        quote = rv["quotes"]["pricing / paywall"][0]
        assert quote["t"] == "T" * 70 + "…"
        assert quote["b"] == body[:160].rstrip() + "…"
        assert deep_dive._clip("short", 70) == "short"

    def test_market_with_no_minable_incumbents(self, dive):
        outdir, mined = dive(self.APPS[1:2], "--keyword", "obscure niche")
        assert mined == []
        result = json.loads((outdir / "obscure-niche.json").read_text(encoding="utf-8"))
        assert result["mobileaction"] is None
        assert result["wedge"] == []
        md = (outdir / "obscure-niche.md").read_text(encoding="utf-8")
        assert "Market demand (MobileAction)" not in md
        assert "## What users love — preserve these\n\n—" in md

    def test_keyword_is_required(self, argv):
        argv()
        with pytest.raises(SystemExit) as exc:
            deep_dive.main()
        assert exc.value.code == 2


# ───────────────────────── pipeline.py ─────────────────────────


class TestPipelineRunStage:
    def test_success(self):
        ran = []
        assert pipeline.run("ok stage", lambda: ran.append(1), fatal=True) is True
        assert ran == [1]

    def test_non_fatal_stage_error_warns_and_continues(self, capsys):
        def stage():
            raise errors.StageError("no credentials")

        assert pipeline.run("enrich", stage, fatal=False) is False
        err = capsys.readouterr().err
        assert "no credentials" in err
        assert "non-fatal: stage 'enrich' failed — continuing" in err
        assert "Traceback" not in err

    def test_non_fatal_crash_keeps_its_traceback(self, capsys):
        def stage():
            raise ValueError("unexpected shape")

        assert pipeline.run("supply", stage, fatal=False) is False
        err = capsys.readouterr().err
        assert "Traceback" in err
        assert "ValueError: unexpected shape" in err

    def test_fatal_stage_failure_exits_1(self, capsys):
        def stage():
            raise errors.StageError("priority file unreadable")

        with pytest.raises(SystemExit) as exc:
            pipeline.run("select priority", stage, fatal=True)
        assert exc.value.code == 1
        assert "FATAL: stage 'select priority' failed" in capsys.readouterr().err


class TestBuildDashboardErrors:
    def test_missing_template_exits_1(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            pipeline.build_dashboard(str(tmp_path / "nope.html"), str(tmp_path / "d.json"), str(tmp_path / "o.html"))
        assert exc.value.code == 1
        assert "Error building dashboard" in capsys.readouterr().err

    def test_unwritable_output_exits_1(self, tmp_path):
        tmpl = tmp_path / "t.html"
        tmpl.write_text("<script>const D=__DATA__;</script>", encoding="utf-8")
        data = tmp_path / "d.json"
        data.write_text("[]", encoding="utf-8")
        out_dir = tmp_path / "dashboard.html"
        out_dir.mkdir()  # a directory where the file should go
        with pytest.raises(SystemExit) as exc:
            pipeline.build_dashboard(str(tmpl), str(data), str(out_dir))
        assert exc.value.code == 1


class TestPipelineMain:
    @pytest.fixture
    def stages(self, monkeypatch):
        """Swap every stage entry point for a recorder; a stage listed in `fail` raises."""
        calls = []
        fail = {}

        def recorder(name):
            def stage(**kw):
                calls.append((name, kw))
                if name in fail:
                    raise fail[name]

            return stage

        monkeypatch.setattr(pipeline.generate_keywords, "run", recorder("generate"))
        monkeypatch.setattr(pipeline.broad_pass, "run", recorder("broad"))
        monkeypatch.setattr(pipeline.select_priority, "run", recorder("select"))
        monkeypatch.setattr(pipeline.extract, "run", recorder("extract"))
        monkeypatch.setattr(pipeline.enrich_community, "run", recorder("enrich"))
        monkeypatch.setattr(pipeline.resented_giants, "run", recorder("resented"))
        monkeypatch.setattr(pipeline.export_dashboard, "main", recorder("export"))
        monkeypatch.setattr(pipeline.rank_starter_list, "main", recorder("rank"))
        monkeypatch.setattr(pipeline, "build_dashboard", recorder("build"))
        monkeypatch.delenv("DR_COMMUNITY_SOURCE", raising=False)
        return calls, fail

    def test_refresh_is_the_default_preset(self, stages, argv, capsys):
        calls, _ = stages
        argv()
        pipeline.main()
        assert calls == [
            ("select", {"per_vertical": 50}),
            ("extract", {"keywords_path": pipeline.extract.PRIORITY_PATH, "workers": 2, "rate": 18, "max_n": 240}),
            ("enrich", {"source": "", "max_n": 240}),
            ("export", {}),
            ("rank", {}),
            ("build", {}),
        ]
        assert "pipeline complete" in capsys.readouterr().out

    def test_full_preset_runs_every_stage_with_cli_options(self, stages, argv, monkeypatch):
        calls, _ = stages
        monkeypatch.setenv("DR_COMMUNITY_SOURCE", "hackernews")
        argv("--preset", "full", "--max", "7", "--rate", "12.5", "--per-vertical", "3", "--engine", "google")
        pipeline.main()
        assert calls == [
            ("generate", {}),
            ("broad", {"workers": 2, "engine": "google"}),
            ("select", {"per_vertical": 3}),
            ("extract", {"keywords_path": pipeline.extract.PRIORITY_PATH, "workers": 2, "rate": 12.5, "max_n": 7}),
            ("enrich", {"source": "hackernews", "max_n": 7}),
            ("resented", {}),
            ("export", {}),
            ("rank", {}),
            ("build", {}),
        ]

    def test_export_preset_touches_no_network_stage(self, stages, argv):
        calls, _ = stages
        argv("--preset", "export")
        pipeline.main()
        assert [name for name, _ in calls] == ["export", "rank", "build"]

    def test_failed_network_stage_still_builds_but_exits_degraded(self, stages, argv, capsys):
        calls, fail = stages
        fail["extract"] = OSError("throttled")
        argv()
        with pytest.raises(SystemExit) as exc:
            pipeline.main()
        assert exc.value.code == 1
        assert [name for name, _ in calls] == ["select", "extract", "enrich", "export", "rank", "build"]
        assert "DEGRADED — 1 stage(s) failed: supply (iTunes)" in capsys.readouterr().err

    def test_failed_fatal_stage_stops_the_run(self, stages, argv):
        calls, fail = stages
        fail["select"] = errors.StageError("broad file unreadable")
        argv()
        with pytest.raises(SystemExit) as exc:
            pipeline.main()
        assert exc.value.code == 1
        assert [name for name, _ in calls] == ["select"]

    def test_rejects_an_unknown_engine(self, stages, argv):
        calls, _ = stages
        argv("--preset", "full", "--engine", "bing; rm -rf /")
        with pytest.raises(SystemExit) as exc:
            pipeline.main()
        assert exc.value.code == 2
        assert calls == []
