"""Tests for register_name.py script."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import common as c
import register_name


class TestBuildContact:
    """Test contact building."""

    @patch.dict("os.environ", {})
    def test_no_contact_when_missing_env(self):
        """Return None when contact env vars are missing."""
        result = register_name.build_contact()
        assert result is None

    @patch.dict(
        "os.environ",
        {
            "REGISTRANT_FIRST_NAME": "John",
            "REGISTRANT_LAST_NAME": "Doe",
            "REGISTRANT_EMAIL": "john@example.com",
            "REGISTRANT_PHONE": "+1234567890",
            "REGISTRANT_ADDRESS": "123 Main St",
            "REGISTRANT_CITY": "Anytown",
            "REGISTRANT_STATE": "CA",
            "REGISTRANT_ZIP": "12345",
            "REGISTRANT_COUNTRY": "US",
        },
    )
    def test_build_contact_complete(self):
        """Build contact when all env vars are set."""
        result = register_name.build_contact()
        assert result is not None
        assert result["first_name"] == "John"
        assert result["last_name"] == "Doe"
        assert result["email"] == "john@example.com"

    @patch.dict(
        "os.environ",
        {
            "REGISTRANT_FIRST_NAME": "John",
            "REGISTRANT_LAST_NAME": "Doe",
            "REGISTRANT_EMAIL": "john@example.com",
            "REGISTRANT_PHONE": "+1234567890",
            "REGISTRANT_ADDRESS": "123 Main St",
            "REGISTRANT_CITY": "Anytown",
            "REGISTRANT_STATE": "CA",
            "REGISTRANT_ZIP": "12345",
            "REGISTRANT_COUNTRY": "US",
            "REGISTRANT_ORG": "ACME Corp",
        },
    )
    def test_build_contact_with_org(self):
        """Include organization when set."""
        result = register_name.build_contact()
        assert result["organization"] == "ACME Corp"


class TestCfRegister:
    """Test Cloudflare registration."""

    def test_dry_run(self):
        """Dry run should not call API."""
        sess = MagicMock()
        result = register_name.cf_register(
            sess, "account123", "token", "example.com", {"email": "test@example.com"}, 1, True
        )
        assert "DRY RUN" in result
        assert "would POST" in result
        sess.post.assert_not_called()

    def test_successful_registration(self):
        """Successful 201 response."""
        sess = MagicMock()
        sess.post.return_value = Mock(status_code=201)
        result = register_name.cf_register(
            sess, "account123", "token", "example.com", {"email": "test@example.com"}, 1, False
        )
        assert "REGISTERED" in result

    def test_successful_registration_200(self):
        """Successful 200 response."""
        sess = MagicMock()
        sess.post.return_value = Mock(status_code=200)
        result = register_name.cf_register(
            sess, "account123", "token", "example.com", {"email": "test@example.com"}, 1, False
        )
        assert "REGISTERED" in result

    def test_failed_registration(self):
        """Failed registration raises error."""
        sess = MagicMock()
        sess.post.return_value = Mock(status_code=400, text="Invalid domain")
        with pytest.raises(RuntimeError, match="HTTP 400"):
            register_name.cf_register(
                sess, "account123", "token", "example.com", {"email": "test@example.com"}, 1, False
            )


class TestGhCreateRepo:
    """Test GitHub repo creation."""

    @patch("register_name._gh_login")
    def test_dry_run(self, mock_login):
        """Dry run should not call API."""
        sess = MagicMock()
        result = register_name.gh_create_repo(sess, "token", None, "acme", True)
        assert "DRY RUN" in result
        sess.post.assert_not_called()

    @patch("register_name._gh_login")
    def test_repo_exists(self, mock_login):
        """Skip if repo already exists."""
        sess = MagicMock()
        sess.get.return_value = Mock(status_code=200)
        mock_login.return_value = "testuser"
        result = register_name.gh_create_repo(sess, "token", None, "acme", False)
        assert "SKIP" in result
        assert "already exists" in result

    @patch("register_name._gh_login")
    def test_successful_creation(self, mock_login):
        """Successfully create repo."""
        sess = MagicMock()
        sess.get.return_value = Mock(status_code=404)  # Doesn't exist
        sess.post.return_value = Mock(
            status_code=201, json=lambda: {"full_name": "testuser/acme"}
        )
        mock_login.return_value = "testuser"
        result = register_name.gh_create_repo(sess, "token", None, "acme", False)
        assert "CREATED" in result

    @patch("register_name._gh_login")
    def test_creation_fails(self, mock_login):
        """Repo creation failure."""
        sess = MagicMock()
        sess.get.return_value = Mock(status_code=404)
        sess.post.return_value = Mock(status_code=400, text="Invalid repo name")
        mock_login.return_value = "testuser"
        with pytest.raises(RuntimeError, match="HTTP 400"):
            register_name.gh_create_repo(sess, "token", None, "acme", False)

    def test_repo_creation_with_org(self):
        """Create repo in organization."""
        sess = MagicMock()
        sess.get.return_value = Mock(status_code=404)
        sess.post.return_value = Mock(
            status_code=201, json=lambda: {"full_name": "orgname/acme"}
        )
        result = register_name.gh_create_repo(sess, "token", "orgname", "acme", False)
        assert "CREATED" in result


class TestGhLogin:
    """Test GitHub login API."""

    def test_get_login(self):
        """Fetch login name from GitHub."""
        sess = MagicMock()
        sess.get.return_value = Mock(status_code=200, json=lambda: {"login": "testuser"})
        result = register_name._gh_login(sess, {})
        assert result == "testuser"


class TestLog:
    """Test logging function."""

    def test_log_appends_summary(self, capsys):
        """Log should print and append to summary."""
        summary = []
        register_name.log(summary, "test message")
        assert "test message" in summary
        captured = capsys.readouterr()
        assert "test message" in captured.out


class TestRegisterNameMain:
    """Test register_name.py main function."""

    @patch("common.make_session")
    @patch("common.cloudflare_domain_check")
    @patch("register_name.cf_register")
    @patch("register_name.gh_create_repo")
    @patch("common.write_summary")
    def test_dry_run(
        self, mock_write, mock_gh, mock_cf_reg, mock_cf_check, mock_session
    ):
        """Test dry run mode."""
        mock_session.return_value = MagicMock()
        mock_cf_check.return_value = {
            "acme.com": c.Result(
                "domain", "acme.com", c.AVAILABLE, price=25.0
            )
        }
        mock_cf_reg.return_value = "DRY RUN — would register"
        mock_gh.return_value = "DRY RUN — would create"

        with patch("sys.argv", ["register_name.py", "Acme"]):
            result = register_name.main()

        assert result == 0

    @patch("common.make_session")
    @patch("sys.stderr")
    def test_confirm_mismatch(self, mock_stderr, mock_session):
        """Test --confirm fails when it doesn't match name."""
        mock_session.return_value = MagicMock()

        with patch("sys.argv", ["register_name.py", "Acme", "--execute", "--confirm", "Other"]):
            result = register_name.main()

        assert result == 2

    @patch("common.make_session")
    @patch("common.cloudflare_domain_check")
    @patch("register_name.cf_register")
    @patch("register_name.build_contact")
    @patch("common.write_summary")
    @patch.dict(
        "os.environ",
        {
            "BRAND_ALLOW_SPEND": "yes",
            "CLOUDFLARE_API_TOKEN": "token",
            "CLOUDFLARE_ACCOUNT_ID": "account",
        },
    )
    def test_execute_with_spend_allowed(
        self, mock_write, mock_contact, mock_cf_reg, mock_cf_check, mock_session
    ):
        """Test execution with spending allowed."""
        mock_session.return_value = MagicMock()
        mock_cf_check.return_value = {
            "acme.com": c.Result(
                "domain", "acme.com", c.AVAILABLE, price=25.0
            )
        }
        mock_contact.return_value = {"email": "test@example.com"}
        mock_cf_reg.return_value = "REGISTERED acme.com"

        with patch("sys.argv", ["register_name.py", "Acme", "--execute", "--confirm", "Acme"]):
            with patch("register_name.gh_create_repo"):
                result = register_name.main()

        assert result == 0
        mock_cf_reg.assert_called()

    @patch("common.make_session")
    @patch("common.cloudflare_domain_check")
    @patch("common.write_summary")
    @patch.dict("os.environ", {})
    def test_price_exceeds_max(self, mock_write, mock_cf_check, mock_session):
        """Test skip domain when price exceeds max."""
        mock_session.return_value = MagicMock()
        mock_cf_check.return_value = {
            "acme.com": c.Result(
                "domain", "acme.com", c.AVAILABLE, price=100.0
            )
        }

        with patch("sys.argv", ["register_name.py", "Acme", "--max-price", "50"]):
            result = register_name.main()

        assert result == 0
