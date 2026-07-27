"""
HMAC signature verification for GitHub webhooks.

GitHub signs webhook payloads with the webhook secret using HMAC-SHA256.
This module verifies the X-Hub-Signature-256 header before any processing.
"""

import hashlib
import hmac
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def verify_signature(payload_body: bytes, signature_header: str | None) -> bool:
    """
    Verify that the webhook payload was signed by GitHub.

    Args:
        payload_body: Raw request body as bytes.
        signature_header: Value of the X-Hub-Signature-256 header.

    Returns:
        True if the signature is valid or if verification is disabled
        (empty secret in dev), False otherwise.
    """
    webhook_secret = settings.WEBHOOK_SECRET
    if not webhook_secret:
        logger.warning("Webhook secret not configured — signature verification disabled")
        return True

    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header")
        return False

    # Expected format: sha256=<hexdigest>
    if not signature_header.startswith("sha256="):
        logger.warning("Invalid signature header format")
        return False

    expected_signature = signature_header[len("sha256="):]

    # Constant-time comparison to prevent timing attacks
    computed = hmac.new(
        webhook_secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, expected_signature)
