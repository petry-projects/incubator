"""
Unit tests for the DemandRadar pipeline's PURE logic (no network).

Every stage's fetch layer is I/O; its scoring/classification/synthesis is pure and is
where the behavior we tuned lives (gap classification, the disruption thresholds, review
resentment scoring, relevance, wedges). These lock that behavior in.

    cd pocs/demand-radar && python -m pytest tests/ -q
"""
from datetime import datetime, timedelta, timezone

import broad_pass
import deep_dive
import enrich_community as enrich
import export_dashboard as dash
import extract
import rank_starter_list as rank
import resented_giants as rg


def iso_days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def app(name, rating=None, count=0, days=15, desc=""):
    return {"trackName": name, "description": desc, "averageUserRating": rating,
            "userRatingCount": count, "currentVersionReleaseDate": iso_days_ago(days),
            "trackId": 1, "sellerName": "Acme", "formattedPrice": "Free"}


# ───────────────────────── extract.py ─────────────────────────

class TestRelevance:
    def test_content_tokens_drops_stopwords_and_short(self):
        assert extract.content_tokens("the best mood tracker app") == ["mood", "tracker"]

    def test_both_tokens_in_name_is_relevant(self):
        assert extract.relevance_score("mood tracker", app("Mood Tracker Pro")) == 1.0
        assert extract.is_relevant("mood tracker", app("Mood Tracker Pro"))

    def test_single_token_match_below_threshold(self):
        # "Workout Trainer" matches only 'trainer' of {combo,trainer} -> 0.5 < 0.6
        assert not extract.is_relevant("combo trainer", app("Workout Trainer AI"))

    def test_token_collision_excluded(self):
        # 'raid dps meter' -> tokens {raid, meter}; a decibel meter matches only 'meter'
        assert not extract.is_relevant("raid dps meter", app("Decibel Meter Pro"))

    def test_description_carries_relevance(self):
        a = app("Zap", desc="the best reference / citation manager for students")
        assert extract.relevance_score("citation manager", a) >= 0.6
        assert extract.is_relevant("citation manager", a)


class TestAnalyze:
    def test_absent_in_store_when_nothing_relevant(self):
        sig = extract.analyze("mood tracker", [app("Tiny Tower"), app("Land Builder")])
        assert sig["gap_type"] == "absent-in-store"
        assert sig["relevant_incumbents"] == 0
        assert sig["disruption"] is False
        assert sig["verdict"] == "CANDIDATE*"  # unverified-absent on default (non-community) channel

    def test_served_market_rejects(self):
        res = [app("Mood Tracker Plus", rating=4.8, count=5000, days=10),
               app("Daily Mood Tracker", rating=4.7, count=3000, days=20)]
        sig = extract.analyze("mood tracker", res)
        assert sig["gap_type"] == "served"
        assert sig["verdict"] == "REJECT"
        assert sig["disruption"] is False  # market_size 5000 < 8000

    def test_nascent_when_relevant_but_tiny(self):
        sig = extract.analyze("mood tracker", [app("Moodly Tracker", rating=5.0, count=8, days=10)])
        assert sig["gap_type"] == "nascent"
        assert sig["credible_incumbents"] == 0

    def test_disruption_flag_on_big_mediocre_leader(self):
        sig = extract.analyze("mood tracker", [app("Mood Tracker Pro", rating=4.1, count=50000, days=10)])
        assert sig["market_size"] == 50000
        assert sig["leader_rating"] == 4.1
        assert sig["disruption"] is True
        assert sig["verdict"] == "DISRUPT"

    def test_well_rated_giant_is_NOT_star_disruption(self):
        # The documented finding: stars can't see the resented giant (4.7 > 4.2 gate).
        sig = extract.analyze("mood tracker", [app("Mood Tracker", rating=4.7, count=100000, days=10)])
        assert sig["market_size"] == 100000
        assert sig["disruption"] is False

    def test_community_channel_absent_is_candidate_star(self):
        sig = extract.analyze("valheim base builder", [app("Random Game")], discovery_channel="community")
        assert sig["supply_confidence"] == "low"
        assert sig["verdict"] == "CANDIDATE*"


# ───────────────────────── resented_giants.py ─────────────────────────

class TestResentScan:
    def test_scores_pricing_and_ads_gripes(self):
        reviews = [
            (1, "Paywall", "everything is behind a paywall now, have to pay for basics"),
            (1, "Ads", "so many ads, an ad every entry"),
            (2, "meh", "it is fine i guess"),
            (1, "Greedy", "cash grab subscription, used to be free"),
        ]
        out = rg.scan(reviews)
        assert out["n_low"] == 4
        assert out["cat_hits"]["pricing"] >= 2
        assert out["cat_hits"]["ads"] >= 1
        assert out["switch_hits"] == 3          # 3 of 4 reviews carry a switch-driving gripe
        assert out["resent_frac"] == 0.75
        assert len(out["gripes"]) >= 1

    def test_empty_reviews(self):
        out = rg.scan([])
        assert out["resent_frac"] == 0.0 and out["gripes"] == []


# ───────────────────────── broad_pass.py ─────────────────────────

class TestBroadScore:
    def test_app_intent_and_on_topic(self):
        s = broad_pass.score("mood tracker", ["mood tracker app", "mood tracker free", "mood tracker online"])
        assert s["app_intent"] == 1
        assert s["on_topic"] == 3
        assert s["broad_interest"] == 3 + 4 * 1

    def test_word_boundary_not_substring(self):
        # 'counter' must not match inside 'counterargument'
        s = broad_pass.score("counter widget", ["counterargument essays", "counterculture"])
        assert s["on_topic"] == 0
        assert s["app_intent"] == 0


# ───────────────────────── export_dashboard.py ─────────────────────────

class TestExportPure:
    def test_toks_and_name_rel(self):
        assert dash.toks("the mood tracker app") == ["mood", "tracker"]
        assert dash.name_rel("Mood Tracker Pro", "mood tracker")
        assert not dash.name_rel("Tiny Tower", "mood tracker")

    def test_cbonus_thresholds(self):
        assert (dash.cbonus(None), dash.cbonus(10), dash.cbonus(100), dash.cbonus(500)) == (0, 0, 1, 2)

    def test_disruption_uses_detector_fields(self):
        rec = {"canonical_query": "x", "supply": {"market_size": 50000, "leader_rating": 4.1,
               "disruption": True, "solutions": [{"app": "Big", "rating_count": 50000}]}}
        assert dash.disruption(rec) == (50000, 4.1, "Big", True)

    def test_disruption_legacy_derivation(self):
        rec = {"canonical_query": "mood tracker", "supply": {"solutions": [
            {"app": "Mood Tracker Pro", "rating": 4.1, "rating_count": 50000},
            {"app": "Unrelated", "rating": 5.0, "rating_count": 999999}]}}
        ms, lr, lapp, tgt = dash.disruption(rec)
        assert ms == 50000 and lapp == "Mood Tracker Pro" and tgt is True

    def test_wedge_from(self):
        assert dash.wedge_from(None) is None
        assert dash.wedge_from({"cat_hits": {}}) is None
        w = dash.wedge_from({"cat_hits": {"pricing": 5, "ads": 2}})
        assert len(w) == 2 and "money model" in w[0]  # pricing ranked first


# ───────────────────────── enrich_community.py ─────────────────────────

class TestRecompute:
    def _rec(self, verdict="CANDIDATE", ch="community"):
        return {"discovery_channel": ch, "verdict_heuristic": verdict}

    def test_corroborated(self):
        assert enrich.recompute(self._rec(), {"source": "hackernews", "mentions": 500}) == \
            ("CANDIDATE", "community-corroborated")

    def test_too_thin(self):
        assert enrich.recompute(self._rec(), {"source": "hackernews", "mentions": 10})[0] == "REJECT"

    def test_weak(self):
        assert enrich.recompute(self._rec(), {"source": "hackernews", "mentions": 100})[0] == "WATCH"

    def test_non_community_untouched(self):
        assert enrich.recompute(self._rec(ch="app-store"), {"source": "hackernews", "mentions": 5})[0] == "CANDIDATE"

    def test_youtube_uses_view_thresholds(self):
        # youtube corroborate = 50k views; 40k is only 'weak'
        assert enrich.recompute(self._rec(), {"source": "youtube", "mentions": 40000})[0] == "WATCH"
        assert enrich.recompute(self._rec(), {"source": "youtube", "mentions": 60000})[0] == "CANDIDATE"


# ───────────────────────── rank_starter_list.py ─────────────────────────

class TestCommunityBonus:
    def _rec(self, m):
        return {"demand": {"community_metric": {"mentions": m}}}

    def test_bonus_tiers(self):
        assert rank.community_bonus(self._rec(500)) == (2, 500)
        assert rank.community_bonus(self._rec(100)) == (1, 100)
        assert rank.community_bonus(self._rec(10)) == (0, 10)
        assert rank.community_bonus({}) == (0, None)


# ───────────────────────── deep_dive.py ─────────────────────────

class TestSynthWedge:
    def test_magnitude_ordered_and_thresholded(self):
        w = deep_dive.synth_wedge({"pricing / paywall": 10, "ads": 5, "missing / limited": 1}, {"simple": 3})
        assert "money model" in w[0]           # pricing dominant -> first
        assert "ad-free" in w[1].lower()        # ads second
        assert not any("feature gaps" in b for b in w)  # missing=1 below threshold
        assert "Keep what they love" in w[-1]

    def test_no_gripes_no_loves(self):
        assert deep_dive.synth_wedge({"missing / limited": 1}, {}) == []
