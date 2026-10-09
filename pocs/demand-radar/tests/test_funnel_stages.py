"""
Tests for the funnel's I/O layers: keyword generation, the broad autocomplete pass, priority
selection and the iTunes supply extractor.

The network is faked (conftest's `http` router / monkeypatched fetchers) and every file lives
under tmp_path, so these exercise the real read → score → write paths, resume logic, rate
pacing and failure handling without touching the network or the committed output/ data.
"""

import email.message
import json
import time
import urllib.error

import pytest
from helpers import read_jsonl

import broad_pass
import errors
import extract
import generate_keywords
import select_priority

# ───────────────────────── errors.py ─────────────────────────


class TestRunCli:
    def test_returns_the_stage_result(self):
        assert errors.run_cli(lambda a, b=0: a + b, 2, b=3) == 5

    def test_stage_error_becomes_exit_1_with_message(self, capsys):
        def boom():
            raise errors.StageError("input unreadable")

        with pytest.raises(SystemExit) as exc:
            errors.run_cli(boom)
        assert exc.value.code == 1
        assert "input unreadable" in capsys.readouterr().err


# ───────────────────────── generate_keywords.py ─────────────────────────


class TestGenerateKeywords:
    def test_writes_domain_x_tool_grid_per_vertical(self, tmp_path):
        out = tmp_path / "nested" / "keywords.jsonl"
        n = generate_keywords.run(out=str(out), n_tools=2)
        rows = read_jsonl(out)
        assert n == len(rows)
        assert {r["vertical"] for r in rows} == set(generate_keywords.VERTICALS)
        first = rows[0]
        assert first["keyword"].endswith(generate_keywords.TOOLS[0])
        assert set(first) == {"keyword", "vertical", "discovery_channel", "vertical_dynamics"}

    def test_dedups_within_a_vertical_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            generate_keywords,
            "VERTICALS",
            {"a": ("app-store", "mixed", ["dog", "dog", "cat"]), "b": ("community", "mixed", ["dog"])},
        )
        out = tmp_path / "k.jsonl"
        assert generate_keywords.run(out=str(out), n_tools=1) == 3
        assert [(r["vertical"], r["keyword"]) for r in read_jsonl(out)] == [
            ("a", "dog tracker"),
            ("a", "cat tracker"),
            ("b", "dog tracker"),
        ]

    def test_main_passes_tool_cap(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(generate_keywords, "run", lambda **kw: seen.update(kw))
        argv("--tools", "3")
        generate_keywords.main()
        assert seen == {"n_tools": 3}


# ───────────────────────── broad_pass.py ─────────────────────────


class TestBroadPace:
    def test_sleeps_until_the_reserved_slot(self, monkeypatch, sleeps):
        monkeypatch.setattr(broad_pass, "_next_at", [time.time() + 5.0])
        monkeypatch.setattr(broad_pass, "_min_interval", [0.5])
        before = broad_pass._next_at[0]
        broad_pass.pace()
        assert len(sleeps) == 1
        assert 4.0 < sleeps[0] <= 5.0
        assert broad_pass._next_at[0] == pytest.approx(before + 0.5)

    def test_no_sleep_when_slot_is_free(self, monkeypatch, sleeps):
        monkeypatch.setattr(broad_pass, "_next_at", [0.0])
        broad_pass.pace()
        assert sleeps == []


class TestSuggest:
    def test_ddg_returns_suggestion_list(self, http):
        http.add("ac.duckduckgo.com", ["mood tracker", ["mood tracker app", "mood tracker free"]])
        assert broad_pass.suggest("mood tracker") == ["mood tracker app", "mood tracker free"]
        assert "q=mood+tracker" in http.calls[0]

    def test_google_engine_uses_its_own_endpoint(self, http):
        http.add("suggestqueries.google.com", ["x", ["x app"]])
        assert broad_pass.suggest("x", engine="google") == ["x app"]
        assert "client=firefox" in http.calls[0]

    def test_malformed_payload_is_no_suggestions(self, http):
        http.add("ac.duckduckgo.com", ["only-the-query"])
        assert broad_pass.suggest("q") == []


class TestBroadRun:
    @pytest.fixture(autouse=True)
    def fresh_pacer(self, monkeypatch):
        monkeypatch.setattr(broad_pass, "_next_at", [0.0])

    def test_scores_pending_and_resumes_past_scored_rows(self, tmp_path, write_jsonl, monkeypatch):
        inp = write_jsonl(
            tmp_path / "keywords.jsonl",
            [
                {"keyword": "dog tracker", "vertical": "pets"},
                {"keyword": "cat tracker", "vertical": "pets"},
                {"keyword": "dog tracker", "vertical": "seniors"},  # same phrase, other vertical
                {"keyword": "boom", "vertical": "pets"},
            ],
        )
        out = tmp_path / "broad.jsonl"
        out.write_text(
            json.dumps({"keyword": "dog tracker", "vertical": "pets", "broad_interest": 5})
            + "\n"
            + json.dumps({"keyword": "cat tracker", "vertical": "pets", "broad_interest": None})  # failed: retry
            + "\nnot json\n",
            encoding="utf-8",
        )
        asked = []

        def fake_suggest(term, engine="ddg"):
            asked.append((term, engine))
            if term == "boom":
                raise OSError("throttled")
            return [f"{term} app", f"{term} review"]

        monkeypatch.setattr(broad_pass, "suggest", fake_suggest)
        counts = broad_pass.run(inp=inp, out=str(out), workers=2, engine="google")

        assert counts == {"n": 3, "fail": 1}
        assert sorted(asked) == [("boom", "google"), ("cat tracker", "google"), ("dog tracker", "google")]
        appended = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()[3:]]
        new = {(r["vertical"], r["keyword"]): r for r in appended}
        assert new[("seniors", "dog tracker")]["broad_interest"] == 6  # 2 on-topic + app intent
        assert new[("seniors", "dog tracker")]["suggestions"] == ["dog tracker app", "dog tracker review"]
        assert new[("pets", "boom")]["broad_interest"] is None
        assert new[("pets", "boom")]["error"] is True

    def test_reports_progress_every_1000(self, tmp_path, write_jsonl, monkeypatch, capsys):
        inp = write_jsonl(tmp_path / "k.jsonl", [{"keyword": f"kw {i}", "vertical": "v"} for i in range(1000)])
        monkeypatch.setattr(broad_pass, "suggest", lambda term, engine="ddg": [])
        counts = broad_pass.run(inp=inp, out=str(tmp_path / "o.jsonl"), workers=4)
        assert counts["n"] == 1000
        assert "1000/1000" in capsys.readouterr().out

    def test_missing_input_is_a_stage_error(self, tmp_path):
        with pytest.raises(errors.StageError, match="Error reading input keywords"):
            broad_pass.run(inp=str(tmp_path / "nope.jsonl"), out=str(tmp_path / "o.jsonl"))

    def test_malformed_input_is_a_stage_error(self, tmp_path):
        bad = tmp_path / "k.jsonl"
        bad.write_text("{not json\n", encoding="utf-8")
        with pytest.raises(errors.StageError, match="Error reading input keywords"):
            broad_pass.run(inp=str(bad), out=str(tmp_path / "o.jsonl"))

    def test_unreadable_existing_output_is_a_stage_error(self, tmp_path, write_jsonl):
        inp = write_jsonl(tmp_path / "k.jsonl", [{"keyword": "a", "vertical": "v"}])
        out_dir = tmp_path / "broad.jsonl"
        out_dir.mkdir()  # exists but cannot be opened as a file
        with pytest.raises(errors.StageError, match="Error reading existing broad keywords"):
            broad_pass.run(inp=inp, out=str(out_dir))

    def test_main_passes_cli_options(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(broad_pass, "run", lambda **kw: seen.update(kw))
        argv("--workers", "3", "--engine", "google")
        broad_pass.main()
        assert seen == {"workers": 3, "engine": "google"}

    def test_main_rejects_unknown_engine(self, argv):
        argv("--engine", "bing")
        with pytest.raises(SystemExit) as exc:
            broad_pass.main()
        assert exc.value.code == 2


# ───────────────────────── select_priority.py ─────────────────────────


class TestSelectPriority:
    def test_top_k_per_vertical_and_drops_unscored(self, tmp_path, write_jsonl):
        inp = write_jsonl(
            tmp_path / "broad.jsonl",
            [
                {"keyword": "low", "vertical": "pets", "broad_interest": 1, "app_intent": 0, "n_suggestions": 1},
                {"keyword": "high", "vertical": "pets", "broad_interest": 9, "app_intent": 1, "n_suggestions": 8},
                {"keyword": "mid", "vertical": "pets", "broad_interest": 4, "app_intent": 0, "n_suggestions": 4},
                {"keyword": "failed", "vertical": "pets", "broad_interest": None},
                {
                    "keyword": "solo",
                    "vertical": "travel",
                    "broad_interest": 2,
                    "discovery_channel": "community",
                    "vertical_dynamics": "mixed",
                },
            ],
        )
        out = tmp_path / "priority.jsonl"
        assert select_priority.run(inp=inp, out=str(out), per_vertical=2) == 3
        rows = read_jsonl(out)
        assert [r["keyword"] for r in rows] == ["high", "mid", "solo"]
        assert rows[2] == {
            "keyword": "solo",
            "vertical": "travel",
            "discovery_channel": "community",
            "vertical_dynamics": "mixed",
            "broad_interest": 2,
            "app_intent": None,
        }

    def test_negative_limit_is_rejected_not_sliced(self, tmp_path, write_jsonl):
        inp = write_jsonl(tmp_path / "broad.jsonl", [{"keyword": "a", "vertical": "v", "broad_interest": 1}])
        out = tmp_path / "priority.jsonl"
        with pytest.raises(errors.StageError, match="--per-vertical must be >= 0"):
            select_priority.run(inp=inp, out=str(out), per_vertical=-1)
        assert not out.exists()

    def test_main_exits_1_on_negative_limit(self, argv, capsys):
        argv("--per-vertical", "-1")
        with pytest.raises(SystemExit) as exc:
            select_priority.main()
        assert exc.value.code == 1
        assert "--per-vertical must be >= 0 (got -1)" in capsys.readouterr().err

    def test_main_passes_per_vertical(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(select_priority, "run", lambda **kw: seen.update(kw))
        argv("--per-vertical", "7")
        select_priority.main()
        assert seen == {"per_vertical": 7}


# ───────────────────────── extract.py ─────────────────────────


def itunes_app(name, rating=4.8, count=500):
    return {
        "trackName": name,
        "description": "",
        "averageUserRating": rating,
        "userRatingCount": count,
        "currentVersionReleaseDate": "2020-01-01T00:00:00Z",
        "trackId": 42,
        "sellerName": "Acme",
        "formattedPrice": "Free",
    }


class TestExtractPace:
    def test_sleeps_until_the_reserved_slot(self, monkeypatch, sleeps):
        monkeypatch.setattr(extract, "_next_at", [time.time() + 3.0])
        monkeypatch.setattr(extract, "_min_interval", [2.0])
        extract.pace()
        assert len(sleeps) == 1
        assert 2.0 < sleeps[0] <= 3.0

    def test_no_sleep_when_slot_is_free(self, monkeypatch, sleeps):
        monkeypatch.setattr(extract, "_next_at", [0.0])
        extract.pace()
        assert sleeps == []


class TestFetch:
    def test_success_returns_results_and_ok(self, http):
        http.add("itunes.apple.com/search", {"results": [{"trackName": "A"}]})
        assert extract.fetch("mood tracker", country="gb", limit=5) == ([{"trackName": "A"}], True)
        assert "term=mood+tracker" in http.calls[0]
        assert "country=gb" in http.calls[0]
        assert "limit=5" in http.calls[0]

    def test_retries_then_succeeds(self, http, sleeps):
        attempts = []

        def flaky(url):
            attempts.append(url)
            return OSError("403") if len(attempts) < 3 else {"results": []}

        http.add("itunes.apple.com/search", flaky)
        assert extract.fetch("x") == ([], True)
        assert len(attempts) == 3
        assert len(sleeps) == 2
        assert 2.0 <= sleeps[0] < 3.0  # 2s base + sub-second jitter
        assert 4.0 <= sleeps[1] < 5.0

    def test_gives_up_after_retries_without_claiming_success(self, http, sleeps):
        http.add("itunes.apple.com/search", OSError("403"))
        assert extract.fetch("x", retries=2) == ([], False)
        assert len(http.calls) == 2
        assert len(sleeps) == 1

    @pytest.mark.parametrize("code", [403, 429])
    def test_throttle_response_fails_fast_without_retrying(self, http, sleeps, code):
        http.add("itunes.apple.com/search", urllib.error.HTTPError("u", code, "banned", email.message.Message(), None))
        assert extract.fetch("x") == ([], False)
        assert len(http.calls) == 1  # no further requests into an active ban
        assert sleeps == []

    def test_server_error_is_still_retried(self, http, sleeps):
        attempts = []

        def flaky(url):
            attempts.append(url)
            if len(attempts) == 1:
                return urllib.error.HTTPError("u", 503, "unavailable", email.message.Message(), None)
            return {"results": []}

        http.add("itunes.apple.com/search", flaky)
        assert extract.fetch("x") == ([], True)
        assert len(attempts) == 2

    def test_zero_retries_never_calls_out(self, http):
        assert extract.fetch("x", retries=0) == ([], False)
        assert http.calls == []


class TestExtractHelpers:
    def test_days_since_handles_missing_and_garbage(self):
        assert extract.days_since(None) is None
        assert extract.days_since("not-a-date") is None

    def test_relevance_is_full_when_term_has_no_content_tokens(self):
        assert extract.relevance_score("app", {"trackName": "Anything"}) == 1.0

    def test_stale_gap_when_freshest_incumbent_is_old(self):
        sig = extract.analyze("mood tracker", [itunes_app("Mood Tracker", rating=4.1, count=900)])
        assert sig["gap_type"] == "stale"
        assert sig["best_existing_satisfaction"] == "low"
        assert sig["verdict"] == "CANDIDATE"

    def test_low_quality_gap_when_best_rating_is_poor(self):
        fresh = itunes_app("Mood Tracker", rating=3.1, count=900)
        fresh["currentVersionReleaseDate"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sig = extract.analyze("mood tracker", [fresh])
        assert sig["gap_type"] == "low-quality"

    def test_to_record_shapes_an_opportunity_record(self):
        sig = extract.analyze("mood tracker", [itunes_app("Mood Tracker")])
        rec = extract.to_record(
            {"name": "mental-wellness", "discovery_channel": "app-store", "vertical_dynamics": "mixed"},
            "mood tracker",
            sig,
            "2026-07-18T00:00:00Z",
        )
        assert rec["opportunity_id"] == "og_2026_07_mental-wellness_mood-tracker"
        assert rec["industry"] == "mental-wellness"
        assert rec["supply"]["solution_exists"] is True
        assert rec["supply"]["solutions"] == sig["top_apps"]
        assert rec["verdict_heuristic"] == sig["verdict"]


class TestLoadKeywords:
    def test_round_robins_across_verticals_and_skips_blank_lines(self, tmp_path):
        p = tmp_path / "k.jsonl"
        p.write_text(
            json.dumps({"keyword": "a1", "vertical": "a", "discovery_channel": "app-store"})
            + "\n\n"
            + json.dumps({"keyword": "a2", "vertical": "a"})
            + "\n"
            + json.dumps({"keyword": "b1", "vertical": "b", "vertical_dynamics": "mixed"})
            + "\n",
            encoding="utf-8",
        )
        recs = extract.load_keywords(str(p))
        assert [r["keyword"] for r in recs] == ["a1", "b1", "a2"]
        assert recs[0] == {"name": "a", "discovery_channel": "app-store", "vertical_dynamics": None, "keyword": "a1"}

    def test_empty_file_is_no_records(self, tmp_path):
        p = tmp_path / "k.jsonl"
        p.write_text("", encoding="utf-8")
        assert extract.load_keywords(str(p)) == []

    def test_load_groups_json(self, tmp_path):
        p = tmp_path / "groups.json"
        p.write_text(
            json.dumps(
                {
                    "store": "gb",
                    "groups": [
                        {"name": "pets", "discovery_channel": "app-store", "keywords": ["dog log", "cat log"]},
                        {"name": "travel", "vertical_dynamics": "mixed", "keywords": ["trip log"]},
                    ],
                }
            ),
            encoding="utf-8",
        )
        recs, store = extract.load_groups_json(str(p))
        assert store == "gb"
        assert [(r["name"], r["keyword"]) for r in recs] == [
            ("pets", "dog log"),
            ("pets", "cat log"),
            ("travel", "trip log"),
        ]

    def test_load_groups_json_defaults_store_to_us(self, tmp_path):
        p = tmp_path / "groups.json"
        p.write_text(json.dumps({"groups": []}), encoding="utf-8")
        assert extract.load_groups_json(str(p)) == ([], "us")


class TestExtractRun:
    @pytest.fixture(autouse=True)
    def fresh_pacer(self, monkeypatch):
        # run() retunes the module-level pacer from `rate`; give each test its own copy
        monkeypatch.setattr(extract, "_next_at", [0.0])
        monkeypatch.setattr(extract, "_min_interval", [2.0])

    @pytest.fixture
    def keywords(self, tmp_path, write_jsonl):
        def _make(n=3, vertical="pets"):
            return write_jsonl(
                tmp_path / "priority.jsonl",
                [
                    {"keyword": f"mood tracker {i}", "vertical": vertical, "discovery_channel": "app-store"}
                    for i in range(n)
                ],
            )

        return _make

    def test_scores_pending_keywords_and_resumes(self, tmp_path, keywords, monkeypatch):
        out = tmp_path / "out" / "records.jsonl"
        out.parent.mkdir()
        out.write_text(
            json.dumps({"industry": "pets", "canonical_query": "mood tracker 0"}) + "\nnot json\n{}\n",
            encoding="utf-8",
        )
        fetched = []

        def fake_fetch(term, country="us", limit=20):
            fetched.append((term, country, limit))
            return [itunes_app("Mood Tracker")], True

        monkeypatch.setattr(extract, "fetch", fake_fetch)
        counts = extract.run(keywords_path=keywords(3), out_path=str(out), workers=2, limit=7, rate=30.0, country="gb")

        assert counts["ok"] == 2
        assert counts["fail"] == 0
        assert sorted(fetched) == [("mood tracker 1", "gb", 7), ("mood tracker 2", "gb", 7)]
        assert extract._min_interval[0] == pytest.approx(2.0)  # 60s / 30 per minute
        written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()[3:]]
        assert sorted(r["canonical_query"] for r in written) == ["mood tracker 1", "mood tracker 2"]
        assert written[0]["industry"] == "pets"
        assert written[0]["gap"]["gap_type"] == "stale"

    def test_max_n_bounds_the_batch(self, tmp_path, keywords, monkeypatch):
        monkeypatch.setattr(extract, "fetch", lambda term, country="us", limit=20: ([], True))
        out = tmp_path / "records.jsonl"
        counts = extract.run(keywords_path=keywords(5), out_path=str(out), workers=1, max_n=2)
        assert counts["ok"] == 2
        assert len(read_jsonl(out)) == 2

    def test_failed_fetch_is_not_written_so_it_stays_pending(self, tmp_path, keywords, monkeypatch):
        monkeypatch.setattr(extract, "fetch", lambda term, country="us", limit=20: ([], not term.endswith("1")))
        out = tmp_path / "records.jsonl"
        counts = extract.run(keywords_path=keywords(3), out_path=str(out), workers=1)
        assert counts["ok"] == 2
        assert counts["fail"] == 1
        assert sorted(r["canonical_query"] for r in read_jsonl(out)) == ["mood tracker 0", "mood tracker 2"]

    def test_aborts_the_batch_on_a_throttle_storm(self, tmp_path, keywords, monkeypatch, capsys):
        calls = []

        def banned(term, country="us", limit=20):
            calls.append(term)
            return [], False

        monkeypatch.setattr(extract, "fetch", banned)
        out = tmp_path / "records.jsonl"
        counts = extract.run(keywords_path=keywords(40), out_path=str(out), workers=1)
        assert len(calls) == 15  # the 15th consecutive failure trips the breaker
        assert counts["fail"] == 15
        assert counts["ok"] == 0
        assert read_jsonl(out) == []
        assert "403-storm" in capsys.readouterr().out

    def test_reports_progress_every_100(self, tmp_path, keywords, monkeypatch, capsys):
        monkeypatch.setattr(extract, "fetch", lambda term, country="us", limit=20: ([], True))
        counts = extract.run(keywords_path=keywords(100), out_path=str(tmp_path / "r.jsonl"), workers=4)
        assert counts["ok"] == 100
        assert "100 scored / 0 fail" in capsys.readouterr().out

    def test_small_mode_reads_groups_config_and_its_store(self, tmp_path, monkeypatch):
        cfg = tmp_path / "groups.json"
        cfg.write_text(
            json.dumps({"store": "de", "groups": [{"name": "pets", "keywords": ["dog log"]}]}), encoding="utf-8"
        )
        seen = []
        monkeypatch.setattr(extract, "fetch", lambda term, country="us", limit=20: (seen.append(country) or [], True))
        out = tmp_path / "records.jsonl"
        extract.run(config_path=str(cfg), out_path=str(out), workers=1)
        assert seen == ["de"]
        assert [r["canonical_query"] for r in read_jsonl(out)] == ["dog log"]

    def test_a_crash_while_scoring_fails_the_stage_after_the_batch(self, tmp_path, keywords, monkeypatch):
        def fetch(term, country="us", limit=20):
            if term.endswith("1"):
                raise ValueError("unexpected payload shape")
            return [], True

        monkeypatch.setattr(extract, "fetch", fetch)
        out = tmp_path / "records.jsonl"
        with pytest.raises(ValueError, match="unexpected payload shape"):
            extract.run(keywords_path=keywords(3), out_path=str(out), workers=1)
        # the rest of the batch still completed and was written before the failure surfaced
        assert sorted(r["canonical_query"] for r in read_jsonl(out)) == ["mood tracker 0", "mood tracker 2"]

    def test_unreadable_existing_output_is_a_stage_error(self, tmp_path, keywords):
        out_dir = tmp_path / "records.jsonl"
        out_dir.mkdir()
        with pytest.raises(errors.StageError, match="Error reading existing records"):
            extract.run(keywords_path=keywords(1), out_path=str(out_dir))


class TestExtractMain:
    @pytest.mark.parametrize(
        ("source", "expected"),
        [("priority", extract.PRIORITY_PATH), ("all", extract.KEYWORDS_PATH), ("groups", None)],
    )
    def test_source_name_maps_to_a_fixed_path(self, argv, monkeypatch, source, expected):
        seen = {}
        monkeypatch.setattr(extract, "run", lambda **kw: seen.update(kw))
        argv("--source", source, "--workers", "2", "--limit", "9", "--max", "4", "--rate", "18", "--country", "gb")
        extract.main()
        assert seen == {
            "keywords_path": expected,
            "workers": 2,
            "limit": 9,
            "max_n": 4,
            "rate": 18.0,
            "country": "gb",
        }

    def test_defaults_to_small_mode(self, argv, monkeypatch):
        seen = {}
        monkeypatch.setattr(extract, "run", lambda **kw: seen.update(kw))
        argv()
        extract.main()
        assert seen["keywords_path"] is None

    def test_rejects_a_path_as_source(self, argv):
        argv("--source", "/etc/passwd")
        with pytest.raises(SystemExit) as exc:
            extract.main()
        assert exc.value.code == 2

    def test_stage_error_exits_1(self, argv, monkeypatch, capsys):
        def boom(**kw):
            raise errors.StageError("records unreadable")

        monkeypatch.setattr(extract, "run", boom)
        argv()
        with pytest.raises(SystemExit) as exc:
            extract.main()
        assert exc.value.code == 1
        assert "records unreadable" in capsys.readouterr().err
