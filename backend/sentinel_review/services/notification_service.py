"""
Notification service for Sentinel Review.

Sends notifications on pipeline events via configurable backends:
- Slack webhook (POST JSON to Incoming Webhook URL)
- Email (SMTP)

Configuration via environment variables:
    SLACK_WEBHOOK_URL          — Slack Incoming Webhook URL (optional)
    NOTIFICATION_EMAIL_HOST    — SMTP server hostname (optional)
    NOTIFICATION_EMAIL_PORT    — SMTP server port (default: 587)
    NOTIFICATION_EMAIL_USER    — SMTP username
    NOTIFICATION_EMAIL_PASSWORD— SMTP password
    NOTIFICATION_EMAIL_FROM    — From address
    NOTIFICATION_EMAIL_TO      — Comma-separated recipient addresses

Usage:
    notifier = NotificationService()
    notifier.notify_failure(repo="owner/repo", pr=42, error="...")
    notifier.notify_blocking_findings(repo="owner/repo", pr=42, count=3,
                                       summary_lines=["...", "..."])
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# Slack Notifier


class SlackNotifier:
    """Sends notifications via a Slack Incoming Webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url
        self._client = httpx.Client(timeout=10.0)

    def send_message(self, text: str, attachments: list[dict[str, Any]] | None = None) -> bool:
        """Send a message to Slack. Returns True on success."""
        try:
            payload: dict[str, Any] = {"text": text}
            if attachments:
                payload["attachments"] = attachments
            response = self._client.post(
                self._webhook_url,
                json=payload,
            )
            response.raise_for_status()
            logger.debug("Slack notification sent successfully (status=%d)", response.status_code)
            return True
        except (httpx.HTTPStatusError, httpx.RequestError, ConnectionError) as e:
            logger.warning("Failed to send Slack notification: %s", e)
            return False

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


# Email Notifier


class EmailNotifier:
    """Sends notifications via SMTP email."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_addr: str | None = None,
        to_addrs: list[str] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from = from_addr or "sentinel-review@localhost"
        self._to = to_addrs or []

    def send_message(
        self,
        subject: str,
        body_text: str,
        body_html: str | None = None,
    ) -> bool:
        """Send an email notification. Returns True on success."""
        try:
            msg = EmailMessage()
            msg.set_content(body_text)
            if body_html:
                msg.add_alternative(body_html, subtype="html")
            msg["Subject"] = subject
            msg["From"] = self._from
            msg["To"] = ", ".join(self._to)

            with smtplib.SMTP(self._host, self._port) as server:
                server.starttls()
                if self._username and self._password:
                    server.login(self._username, self._password)
                server.send_message(msg)

            logger.debug(
                "Email notification sent to %s (subject=%s)",
                ", ".join(self._to),
                subject,
            )
            return True
        except (smtplib.SMTPException, ConnectionError, OSError) as e:
            logger.warning("Failed to send email notification: %s", e)
            return False


# Notification Service


class NotificationService:
    """Aggregates notification backends and sends notifications on pipeline events.

    Notifications are fire-and-forget: failures to send are logged but
    never raise exceptions to the caller.
    """

    def __init__(self) -> None:
        self._backends: list[SlackNotifier | EmailNotifier] = []

        # Initialize Slack backend (if configured)
        slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
        if slack_url:
            self._backends.append(SlackNotifier(slack_url))
            logger.info("Slack notification backend enabled")

        # Initialize Email backend (if configured)
        email_host = os.environ.get("NOTIFICATION_EMAIL_HOST", "")
        if email_host:
            email_port = int(os.environ.get("NOTIFICATION_EMAIL_PORT", "587"))
            email_user = os.environ.get("NOTIFICATION_EMAIL_USER", "")
            email_pass = os.environ.get("NOTIFICATION_EMAIL_PASSWORD", "")
            email_from = os.environ.get("NOTIFICATION_EMAIL_FROM", "")
            email_to_raw = os.environ.get("NOTIFICATION_EMAIL_TO", "")
            email_to = [addr.strip() for addr in email_to_raw.split(",") if addr.strip()]

            if email_to:
                self._backends.append(
                    EmailNotifier(
                        host=email_host,
                        port=email_port,
                        username=email_user or None,
                        password=email_pass or None,
                        from_addr=email_from or None,
                        to_addrs=email_to,
                    )
                )
                logger.info("Email notification backend enabled (to: %s)", ", ".join(email_to))

    @property
    def is_enabled(self) -> bool:
        """True if at least one notification backend is configured."""
        return len(self._backends) > 0

    def notify_failure(
        self,
        repo_full_name: str,
        pr_number: int,
        error_message: str,
        stage_name: str | None = None,
    ) -> None:
        """Send a notification that a pipeline review failed.

        Args:
            repo_full_name: "owner/repo"
            pr_number: Pull request number
            error_message: Error description
            stage_name: Name of the stage that failed (optional)
        """
        if not self._backends:
            return

        title = f"🚨 Sentinel Review Failed — {repo_full_name}#{pr_number}"
        text = (
            f"*Sentinel Review — Pipeline Failure*\n\n"
            f"Repository: `{repo_full_name}`\n"
            f"Pull Request: #{pr_number}\n"
            f"Stage: `{stage_name or 'unknown'}`\n\n"
            f"*Error:*\n```\n{error_message[:2000]}\n```"
        )

        for backend in self._backends:
            try:
                if isinstance(backend, SlackNotifier):
                    backend.send_message(text)
                elif isinstance(backend, EmailNotifier):
                    body = (
                        f"Sentinel Review — Pipeline Failure\n\n"
                        f"Repository: {repo_full_name}\n"
                        f"Pull Request: #{pr_number}\n"
                        f"Stage: {stage_name or 'unknown'}\n\n"
                        f"Error:\n{error_message[:5000]}"
                    )
                    backend.send_message(
                        subject=title,
                        body_text=body,
                    )
            except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError):
                logger.exception("Notification backend failed unexpectedly")

    def notify_blocking_findings(
        self,
        repo_full_name: str,
        pr_number: int,
        pr_title: str,
        blocking_count: int,
        findings_preview: list[str],
    ) -> None:
        """Send a notification that blocking-severity findings were posted.

        Args:
            repo_full_name: "owner/repo"
            pr_number: Pull request number
            pr_title: Pull request title
            blocking_count: Number of blocking findings
            findings_preview: Short description lines (one per finding)
        """
        if not self._backends:
            return

        title = f"🔴 Sentinel Review — {blocking_count} Blocking Finding(s) in {repo_full_name}#{pr_number}"
        preview_text = "\n".join(f"• {line}" for line in findings_preview[:10])
        text = (
            f"*Sentinel Review — Blocking Findings Detected*\n\n"
            f"Repository: `{repo_full_name}`\n"
            f"Pull Request: #{pr_number} — _{pr_title}_\n"
            f"Blocking Findings: *{blocking_count}*\n\n"
            f"*Findings:*\n{preview_text}"
        )

        for backend in self._backends:
            try:
                if isinstance(backend, SlackNotifier):
                    backend.send_message(text)
                elif isinstance(backend, EmailNotifier):
                    body = (
                        f"Sentinel Review — Blocking Findings Detected\n\n"
                        f"Repository: {repo_full_name}\n"
                        f"Pull Request: #{pr_number} — {pr_title}\n"
                        f"Blocking Findings: {blocking_count}\n\n"
                        f"Findings:\n{preview_text}"
                    )
                    backend.send_message(
                        subject=title,
                        body_text=body,
                    )
            except (OSError, ConnectionError, TimeoutError, ValueError, RuntimeError):
                logger.exception("Notification backend failed unexpectedly")
