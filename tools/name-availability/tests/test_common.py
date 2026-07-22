"""Tests for common.py availability check functions."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import common as c


@pytest.fixture
def session():
    """Mock requests session."""
    return MagicMock(spec=requests.Session)


class TestSlugify:
    """Test name slugification."""

    def test_simple_name(self):
        assert c.slugify("Acme") == "acme"

    def test_name_with_spaces(self):
        assert c.slugify("Acme Co") == "acmeco"

    def test_name_with_special_chars(self):
        assert c.slugify("Acme-Co, Inc.") == "acmecoinc"

    def test_empty_string(self):
        assert c.slugify("") == ""


class TestRdapDomain:
    """Test RDAP domain availability checks."""

    def test_available_domain(self, session):
        """404 status means domain is available."""
        session.get.return_value = Mock(status_code=404)
        result = c.rdap_domain(session, "example.com")
        assert result.status == c.AVAILABLE
        assert result.channel == "domain"
        session.get.assert_called_once()
        call_args = session.get.call_args
        assert call_args.kwargs["allow_redirects"] is False

    def test_taken_domain(self, session):
        """200 status means domain is registered."""
        session.get.return_value = Mock(status_code=200)
        result = c.rdap_domain(session, "example.com")
        assert result.status == c.TAKEN
        assert result.channel == "domain"

    def test_unknown_status(self, session):
        """Other status codes mean unknown."""
        session.get.return_value = Mock(status_code=500)
        result = c.rdap_domain(session, "example.com")
        assert result.status == c.UNKNOWN

    def test_request_exception(self, session):
        """Request errors return UNKNOWN."""
        session.get.side_effect = requests.RequestException("Connection failed")
        result = c.rdap_domain(session, "example.com")
        assert result.status == c.UNKNOWN


class TestCloudflareCheck:
    """Test Cloudflare domain check."""

    def test_available_domain(self, session):
        """Parse Cloudflare response for available domain."""
        session.post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "result": [
                    {
                        "domain": "example.com",
                        "available": True,
                        "price": 25.50,
                    }
                ]
            },
        )
        results = c.cloudflare_domain_check(session, "account123", "token", ["example.com"])
        assert "example.com" in results
        assert results["example.com"].status == c.AVAILABLE
        assert results["example.com"].price == 25.50

    def test_taken_domain(self, session):
        """Parse Cloudflare response for taken domain."""
        session.post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "result": [{"domain": "example.com", "available": False, "price": None}]
            },
        )
        results = c.cloudflare_domain_check(session, "account123", "token", ["example.com"])
        assert results["example.com"].status == c.TAKEN

    def test_invalid_price(self, session):
        """Handle invalid price values."""
        session.post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "result": [
                    {"domain": "example.com", "available": True, "price": "invalid"}
                ]
            },
        )
        results = c.cloudflare_domain_check(session, "account123", "token", ["example.com"])
        assert results["example.com"].price is None

    def test_success_false_raises(self, session):
        """Cloudflare success=false raises RuntimeError."""
        session.post.return_value = Mock(
            status_code=200,
            json=lambda: {"success": False, "errors": [{"code": 1003, "message": "Invalid account"}]},
        )
        with pytest.raises(RuntimeError, match="Cloudflare API error"):
            c.cloudflare_domain_check(session, "account123", "token", ["example.com"])

    def test_item_without_name_skipped(self, session):
        """Items with no domain/name field are skipped."""
        session.post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "success": True,
                "result": [
                    {"available": True},  # no domain or name
                    {"domain": "ok.com", "available": True, "price": 10.0},
                ],
            },
        )
        results = c.cloudflare_domain_check(session, "account123", "token", ["ok.com"])
        assert None not in results
        assert "ok.com" in results


class TestGitHubHandle:
    """Test GitHub handle availability checks."""

    def test_available_handle(self, session):
        """404 means handle is available."""
        session.get.return_value = Mock(status_code=404)
        result = c.github_handle(session, "acme", None)
        assert result.status == c.AVAILABLE

    def test_taken_handle(self, session):
        """200 means handle is taken."""
        session.get.return_value = Mock(
            status_code=200, json=lambda: {"type": "Organization"}
        )
        result = c.github_handle(session, "acme", None)
        assert result.status == c.TAKEN

    def test_rate_limited(self, session):
        """403 means rate limited."""
        session.get.return_value = Mock(status_code=403)
        result = c.github_handle(session, "acme", None)
        assert result.status == c.UNKNOWN

    def test_with_token(self, session):
        """Token should be passed to headers."""
        session.get.return_value = Mock(status_code=404)
        c.github_handle(session, "acme", "token123")
        call_args = session.get.call_args
        assert "Authorization" in call_args.kwargs["headers"]


class TestPackageRegistries:
    """Test npm and PyPI package checks."""

    def test_npm_available(self, session):
        """404 on npm means package is available."""
        session.get.return_value = Mock(status_code=404)
        result = c.npm_package(session, "acme")
        assert result.status == c.AVAILABLE
        assert result.channel == "npm"

    def test_npm_taken(self, session):
        """200 on npm means package exists."""
        session.get.return_value = Mock(status_code=200)
        result = c.npm_package(session, "acme")
        assert result.status == c.TAKEN

    def test_pypi_available(self, session):
        """404 on PyPI means package is available."""
        session.get.return_value = Mock(status_code=404)
        result = c.pypi_package(session, "acme")
        assert result.status == c.AVAILABLE
        assert result.channel == "pypi"


class TestSocialHandle:
    """Test social handle checks."""

    def test_available_handle(self, session):
        """404 means handle is available."""
        session.get.return_value = Mock(status_code=404)
        result = c.social_handle(session, "x", "acme")
        assert result.status == c.AVAILABLE
        assert result.channel == "social"
        assert result.confidence == "low"
        # Verify redirects are disabled for security
        call_args = session.get.call_args
        assert call_args.kwargs["allow_redirects"] is False

    def test_taken_handle(self, session):
        """200 means handle is taken."""
        session.get.return_value = Mock(status_code=200)
        result = c.social_handle(session, "instagram", "acme")
        assert result.status == c.TAKEN

    def test_request_error(self, session):
        """Request errors return UNKNOWN."""
        session.get.side_effect = requests.RequestException("Connection failed")
        result = c.social_handle(session, "x", "acme")
        assert result.status == c.UNKNOWN


class TestVerdict:
    """Test critical channel verification."""

    def test_all_available(self):
        """All critical channels available."""
        results = [
            c.Result("domain", "acme.com", c.AVAILABLE),
            c.Result("github", "acme", c.AVAILABLE),
        ]
        ok, detail = c.verdict(results, ["domain:com", "github"])
        assert ok is True

    def test_domain_taken(self):
        """Domain taken fails verdict."""
        results = [
            c.Result("domain", "acme.com", c.TAKEN),
            c.Result("github", "acme", c.AVAILABLE),
        ]
        ok, detail = c.verdict(results, ["domain:com", "github"])
        assert ok is False
        assert "domain:com" in detail

    def test_empty_critical_list(self):
        """Empty critical list always passes."""
        results = [c.Result("domain", "acme.com", c.TAKEN)]
        ok, detail = c.verdict(results, [])
        assert ok is True


class TestToMarkdown:
    """Test markdown output formatting."""

    def test_basic_output(self):
        """Generate markdown summary."""
        results = [
            c.Result("domain", "acme.com", c.AVAILABLE, "Available", "https://acme.com"),
            c.Result(
                "github", "acme", c.TAKEN, "Taken", "https://github.com/acme"
            ),
        ]
        md = c.to_markdown("Acme", "acme", results)
        assert "Acme" in md
        assert "acme.com" in md
        assert "AVAILABLE" in md
        assert "TAKEN" in md

    def test_price_formatting(self):
        """Format prices in output."""
        results = [
            c.Result(
                "domain", "acme.com", c.AVAILABLE, "Available", "https://acme.com", price=25.50
            ),
        ]
        md = c.to_markdown("Acme", "acme", results)
        assert "$26" in md or "$25" in md


class TestMakeSession:
    """Test session creation."""

    def test_user_agent_set(self):
        """Session should have proper User-Agent."""
        sess = c.make_session()
        assert sess.headers["User-Agent"] == c.USER_AGENT


class TestWriteSummary:
    """Test writing to GitHub step summary."""

    @patch.dict("os.environ", {})
    def test_no_summary_path(self):
        """No error when GITHUB_STEP_SUMMARY not set."""
        c.write_summary("test content")

    @patch("builtins.open", create=True)
    @patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": "/tmp/summary"})
    def test_write_summary(self, mock_open):
        """Write to summary file when path is set."""
        c.write_summary("test content")
        mock_open.assert_called_once()


class TestDumpJson:
    """Test JSON output."""

    @patch("builtins.open", create=True)
    def test_dump_json(self, mock_open, tmp_path):
        """Write results to JSON file."""
        results = [
            c.Result("domain", "acme.com", c.AVAILABLE, "Available"),
        ]
        c.dump_json(str(tmp_path / "out.json"), "Acme", "acme", results)
        mock_open.assert_called_once()


class TestResult:
    """Test Result dataclass."""

    def test_basic_result(self):
        """Create basic result."""
        r = c.Result("domain", "example.com", c.AVAILABLE)
        assert r.channel == "domain"
        assert r.target == "example.com"
        assert r.status == c.AVAILABLE

    def test_result_with_price(self):
        """Result can include price."""
        r = c.Result("domain", "example.com", c.AVAILABLE, price=25.50)
        assert r.price == 25.50

    def test_result_confidence(self):
        """Result has confidence level."""
        r = c.Result("social", "x:acme", c.AVAILABLE, confidence="low")
        assert r.confidence == "low"
