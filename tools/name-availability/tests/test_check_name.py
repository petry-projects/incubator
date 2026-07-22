"""Tests for check_name.py script."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import check_name
import common as c


@pytest.fixture
def mock_session():
    """Mock requests session."""
    return MagicMock()


class TestCheckNameMain:
    """Test check_name.py main function."""

    @patch("common.make_session")
    @patch("common.rdap_domain")
    @patch("common.github_handle")
    @patch("common.npm_package")
    @patch("common.pypi_package")
    @patch("common.to_markdown")
    @patch("common.write_summary")
    @patch("builtins.print")
    def test_basic_check(
        self,
        mock_print,
        mock_write_summary,
        mock_to_markdown,
        mock_pypi,
        mock_npm,
        mock_gh,
        mock_rdap,
        mock_session_fn,
    ):
        """Test basic name check flow."""
        mock_session_fn.return_value = MagicMock()
        mock_rdap.return_value = c.Result("domain", "acme.com", c.AVAILABLE)
        mock_gh.return_value = c.Result("github", "acme", c.AVAILABLE)
        mock_npm.return_value = c.Result("npm", "acme", c.AVAILABLE)
        mock_pypi.return_value = c.Result("pypi", "acme", c.AVAILABLE)
        mock_to_markdown.return_value = "# Results"

        with patch("sys.argv", ["check_name.py", "Acme"]):
            result = check_name.main()

        assert result == 0
        mock_write_summary.assert_called()
        mock_print.assert_called()

    @patch("common.make_session")
    @patch("common.rdap_domain")
    @patch("common.github_handle")
    @patch("common.npm_package")
    @patch("common.pypi_package")
    @patch("common.to_markdown")
    @patch("common.write_summary")
    @patch("builtins.print")
    def test_check_with_json_output(
        self,
        mock_print,
        mock_write_summary,
        mock_to_markdown,
        mock_pypi,
        mock_npm,
        mock_gh,
        mock_rdap,
        mock_session_fn,
    ):
        """Test check with JSON output."""
        mock_session_fn.return_value = MagicMock()
        mock_rdap.return_value = c.Result("domain", "acme.com", c.AVAILABLE)
        mock_gh.return_value = c.Result("github", "acme", c.AVAILABLE)
        mock_npm.return_value = c.Result("npm", "acme", c.AVAILABLE)
        mock_pypi.return_value = c.Result("pypi", "acme", c.AVAILABLE)
        mock_to_markdown.return_value = "# Results"

        with patch("sys.argv", ["check_name.py", "Acme", "--json", "result.json"]):
            with patch("common.dump_json") as mock_dump:
                result = check_name.main()

        assert result == 0
        mock_dump.assert_called_once()

    @patch("common.make_session")
    @patch("common.rdap_domain")
    @patch("common.github_handle")
    @patch("common.npm_package")
    @patch("common.pypi_package")
    @patch("common.to_markdown")
    @patch("common.write_summary")
    @patch("builtins.print")
    def test_check_with_fail_on(
        self,
        mock_print,
        mock_write_summary,
        mock_to_markdown,
        mock_pypi,
        mock_npm,
        mock_gh,
        mock_rdap,
        mock_session_fn,
    ):
        """Test check with fail-on critical channels."""
        mock_session_fn.return_value = MagicMock()
        mock_rdap.return_value = c.Result("domain", "acme.com", c.TAKEN)  # Taken!
        mock_gh.return_value = c.Result("github", "acme", c.AVAILABLE)
        mock_npm.return_value = c.Result("npm", "acme", c.AVAILABLE)
        mock_pypi.return_value = c.Result("pypi", "acme", c.AVAILABLE)
        mock_to_markdown.return_value = "# Results"

        with patch("sys.argv", ["check_name.py", "Acme", "--fail-on", "domain:com,github"]):
            result = check_name.main()

        # Should fail because domain is taken
        assert result == 1

    @patch("common.make_session")
    @patch("common.rdap_domain")
    @patch("common.github_handle")
    @patch("common.npm_package")
    @patch("common.pypi_package")
    @patch("common.to_markdown")
    @patch("common.write_summary")
    @patch("builtins.print")
    def test_check_no_social(
        self,
        mock_print,
        mock_write_summary,
        mock_to_markdown,
        mock_pypi,
        mock_npm,
        mock_gh,
        mock_rdap,
        mock_session_fn,
    ):
        """Test check without social handles."""
        mock_session_fn.return_value = MagicMock()
        mock_rdap.return_value = c.Result("domain", "acme.com", c.AVAILABLE)
        mock_gh.return_value = c.Result("github", "acme", c.AVAILABLE)
        mock_npm.return_value = c.Result("npm", "acme", c.AVAILABLE)
        mock_pypi.return_value = c.Result("pypi", "acme", c.AVAILABLE)
        mock_to_markdown.return_value = "# Results"

        with patch("sys.argv", ["check_name.py", "Acme", "--no-social"]):
            with patch("common.social_handle") as mock_social:
                result = check_name.main()

        assert result == 0
        # social_handle should not be called
        mock_social.assert_not_called()

    def test_empty_slug_exits_with_error(self, capsys):
        """Empty slug after slugification exits non-zero."""
        with patch("sys.argv", ["check_name.py", "!!!"]):
            result = check_name.main()
        assert result == 1
        captured = capsys.readouterr()
        assert "empty slug" in captured.err

    @patch("common.make_session")
    @patch("common.cloudflare_domain_check")
    def test_cloudflare_fallback_on_error(
        self, mock_cf, mock_session_fn
    ):
        """Test fallback to RDAP when Cloudflare fails."""
        mock_session_fn.return_value = MagicMock()
        mock_cf.side_effect = Exception("API error")

        with patch("common.rdap_domain") as mock_rdap:
            mock_rdap.return_value = c.Result("domain", "acme.com", c.AVAILABLE)
            with patch("common.github_handle") as mock_gh:
                mock_gh.return_value = c.Result("github", "acme", c.AVAILABLE)
                with patch("common.npm_package") as mock_npm:
                    mock_npm.return_value = c.Result("npm", "acme", c.AVAILABLE)
                    with patch("common.pypi_package") as mock_pypi:
                        mock_pypi.return_value = c.Result("pypi", "acme", c.AVAILABLE)
                        with patch("common.to_markdown"):
                            with patch("common.write_summary"):
                                with patch("builtins.print"):
                                    with patch("sys.argv", ["check_name.py", "Acme"]):
                                        result = check_name.main()

        # Should still succeed and fall back to RDAP
        assert result == 0
