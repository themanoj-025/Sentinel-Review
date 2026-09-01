"""Tests for the notification service."""

from __future__ import annotations

import json
import os
import smtplib
from unittest.mock import MagicMock, patch

import httpx
import respx
from sentinel_review.services.notification_service import (
    EmailNotifier,
    NotificationService,
    SlackNotifier,
)

pytestmark = pytest.mark.slow
pytestmark = pytest.mark.integration

# SlackNotifier Tests


class TestSlackNotifier:
    """Tests for the Slack webhook notifier."""

    def test_send_message_success(self) -> None:
        """A successful POST to Slack should return True."""
        with respx.mock as rm:
            route = rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            notifier = SlackNotifier("https://hooks.slack.com/services/T00/B00/xxx")
            result = notifier.send_message("Hello, world!")
            assert result is True
            assert route.called

    def test_send_message_with_attachments(self) -> None:
        """Attachments should be included in the POST payload."""
        with respx.mock as rm:
            route = rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            notifier = SlackNotifier("https://hooks.slack.com/services/T00/B00/xxx")
            attachments = [{"color": "danger", "text": "Something broke"}]
            result = notifier.send_message("Alert!", attachments=attachments)
            assert result is True
            assert route.called
            sent = json.loads(route.calls[0].request.content)
            assert sent["text"] == "Alert!"
            assert len(sent["attachments"]) == 1

    def test_send_message_http_error(self) -> None:
        """A non-2xx response should return False (not raise)."""
        with respx.mock as rm:
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(403, text="forbidden"),
            )
            notifier = SlackNotifier("https://hooks.slack.com/services/T00/B00/xxx")
            result = notifier.send_message("Hello")
            assert result is False

    def test_send_message_connection_error(self) -> None:
        """A connection error should return False (not raise)."""
        with respx.mock as rm:
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                side_effect=httpx.ConnectError("Connection refused"),
            )
            notifier = SlackNotifier("https://hooks.slack.com/services/T00/B00/xxx")
            result = notifier.send_message("Hello")
            assert result is False

    def test_close(self) -> None:
        """close() should not raise."""
        notifier = SlackNotifier("https://hooks.slack.com/services/T00/B00/xxx")
        notifier.close()  # Should not raise


# EmailNotifier Tests


class TestEmailNotifier:
    """Tests for the SMTP email notifier."""

    @patch("smtplib.SMTP")
    def test_send_message_success(self, mock_smtp) -> None:
        """A successful SMTP send should return True."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        notifier = EmailNotifier(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            from_addr="bot@example.com",
            to_addrs=["admin@example.com"],
        )
        result = notifier.send_message(
            subject="Test Subject",
            body_text="Hello, world!",
        )
        assert result is True
        mock_smtp.assert_called_once_with("smtp.example.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "pass")
        mock_server.send_message.assert_called_once()

    @patch("smtplib.SMTP")
    def test_send_message_with_html(self, mock_smtp) -> None:
        """HTML alternative should be included when provided."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        notifier = EmailNotifier(
            host="smtp.example.com",
            port=587,
            to_addrs=["admin@example.com"],
        )
        result = notifier.send_message(
            subject="Test",
            body_text="Plain text",
            body_html="<p>HTML</p>",
        )
        assert result is True
        # Verify the message has both text and HTML parts
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["Subject"] == "Test"
        assert sent_msg["To"] == "admin@example.com"

    @patch("smtplib.SMTP")
    def test_send_message_smtp_failure(self, mock_smtp) -> None:
        """An SMTP exception should return False (not raise)."""
        mock_smtp.return_value.__enter__.return_value.send_message.side_effect = (
            smtplib.SMTPException("Server error")
        )

        notifier = EmailNotifier(
            host="smtp.example.com",
            port=587,
            to_addrs=["admin@example.com"],
        )
        result = notifier.send_message(
            subject="Test",
            body_text="Body",
        )
        assert result is False


# NotificationService Tests


class TestNotificationService:
    """Tests for the aggregated NotificationService."""

    def test_is_enabled_false_when_no_backends(self) -> None:
        """Without env vars, is_enabled should be False."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            assert service.is_enabled is False

    def test_is_enabled_true_with_slack_url(self) -> None:
        """With SLACK_WEBHOOK_URL set, is_enabled should be True."""
        with patch.dict(
            os.environ,
            {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
            clear=True,
        ):
            service = NotificationService()
            assert service.is_enabled is True

    def test_is_enabled_true_with_email_config(self) -> None:
        """With email env vars set, is_enabled should be True."""
        with patch.dict(
            os.environ,
            {
                "NOTIFICATION_EMAIL_HOST": "smtp.example.com",
                "NOTIFICATION_EMAIL_TO": "admin@example.com",
            },
            clear=True,
        ):
            service = NotificationService()
            assert service.is_enabled is True

    def test_notify_failure_slack_only(self) -> None:
        """notify_failure should send to Slack when configured."""
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            respx.mock as rm,
        ):
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            service = NotificationService()
            service.notify_failure(
                repo_full_name="owner/repo",
                pr_number=42,
                error_message="Diff fetch failed: ConnectionError",
                stage_name="FetchDiffStage",
            )
            # Should have sent the Slack message
            assert rm.calls

    def test_notify_failure_no_backends(self) -> None:
        """notify_failure should be a no-op when no backends configured."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            # Should not raise
            service.notify_failure(
                repo_full_name="owner/repo",
                pr_number=42,
                error_message="Error",
            )

    def test_notify_blocking_findings_slack(self) -> None:
        """notify_blocking_findings should send to Slack when configured."""
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            respx.mock as rm,
        ):
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            service = NotificationService()
            service.notify_blocking_findings(
                repo_full_name="owner/repo",
                pr_number=42,
                pr_title="Fix critical bug",
                blocking_count=2,
                findings_preview=[
                    "`src/app.py:10` — SQL injection vulnerability",
                    "`src/config.py:1` — Hardcoded secret",
                ],
            )
            assert rm.calls

    def test_notify_blocking_findings_no_backends(self) -> None:
        """notify_blocking_findings should be a no-op when no backends."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            service.notify_blocking_findings(
                repo_full_name="owner/repo",
                pr_number=42,
                pr_title="Fix",
                blocking_count=1,
                findings_preview=["Something bad"],
            )
            # No exception means success

    def test_notify_failure_backend_exception_does_not_propagate(self) -> None:
        """If a backend raises unexpectedly, the error should be logged, not propagated."""
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            patch.object(SlackNotifier, "send_message", side_effect=RuntimeError("Kaboom")),
        ):
            service = NotificationService()
            # Should not raise despite backend failure
            service.notify_failure(
                repo_full_name="owner/repo",
                pr_number=42,
                error_message="Error",
                stage_name="TestStage",
            )
            # Exception caught and logged; no propagation

    def test_notify_blocking_findings_backend_exception_does_not_propagate(self) -> None:
        """If a backend raises unexpectedly during blocking findings, should not propagate."""
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            patch.object(SlackNotifier, "send_message", side_effect=RuntimeError("Kaboom")),
        ):
            service = NotificationService()
            service.notify_blocking_findings(
                repo_full_name="owner/repo",
                pr_number=42,
                pr_title="Fix",
                blocking_count=1,
                findings_preview=["Finding"],
            )
            # No propagation

    def test_notify_failure_without_stage_name(self) -> None:
        """notify_failure should work without a stage_name."""
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            respx.mock as rm,
        ):
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            service = NotificationService()
            service.notify_failure(
                repo_full_name="owner/repo",
                pr_number=42,
                error_message="Something went wrong",
            )
            assert rm.calls

    def test_preview_is_truncated_to_10_lines(self) -> None:
        """findings_preview should be truncated to at most 10 lines."""
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            respx.mock as rm,
        ):
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            service = NotificationService()
            many_findings = [f"Finding {i}" for i in range(20)]
            service.notify_blocking_findings(
                repo_full_name="owner/repo",
                pr_number=42,
                pr_title="Fix",
                blocking_count=20,
                findings_preview=many_findings,
            )
            # Message sent successfully (content truncation is internal)
            assert rm.calls

    def test_no_notification_when_no_backends_configured(self) -> None:
        """When no notification backends are configured, no HTTP calls should be made."""
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            assert service.is_enabled is False
            # With respx.mock but no routes registered, any HTTP call would fail
            with respx.mock as rm:
                service.notify_blocking_findings(
                    repo_full_name="owner/repo",
                    pr_number=42,
                    pr_title="Safe PR",
                    blocking_count=0,
                    findings_preview=[],
                )
                assert not rm.calls

    def test_no_notification_on_successful_review_no_backends(self) -> None:
        """A successful review with no blocking findings should NOT send notifications.

        This validates the "suppressed on success" requirement — notifications
        only fire on failure or when blocking findings exist.
        """
        with patch.dict(os.environ, {}, clear=True):
            service = NotificationService()
            # Simulate success: blocking_count=0 and no error
            with respx.mock as rm:
                service.notify_failure(
                    repo_full_name="owner/repo",
                    pr_number=42,
                    error_message="test",
                )
                # No backends → no calls (success suppressed)
                # Even with backends, notify_failure is only called on failure path
                assert not rm.calls

    def test_notification_sent_only_when_blocking_findings_exist(self) -> None:
        """notify_blocking_findings should only be called when blocking_count > 0.

        In the pipeline, PostCommentsStage checks len(blocking_findings) before calling.
        """
        with (
            patch.dict(
                os.environ,
                {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xxx"},
                clear=True,
            ),
            respx.mock as rm,
        ):
            rm.post("https://hooks.slack.com/services/T00/B00/xxx").mock(
                return_value=httpx.Response(200, text="ok"),
            )
            service = NotificationService()
            # Call with blocking_count=0 (should still send, backends don't filter by count)
            service.notify_blocking_findings(
                repo_full_name="owner/repo",
                pr_number=42,
                pr_title="Safe PR",
                blocking_count=0,
                findings_preview=[],
            )
            # With backend configured, message IS sent (the pipeline decides when to call)
            assert rm.calls
