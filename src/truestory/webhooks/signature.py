"""Webhook signature verification.

Every inbound callback is verified before it touches run state. This is not
optional hardening: the callbacks carry research findings that become verdicts
about real people in a document an underwriter relies on, so an unauthenticated
endpoint that accepts them is an endpoint that lets a stranger write findings
into a legal deliverable.

Three properties, all required:

  * HMAC over the raw request body using a shared secret from Secret Manager
  * Constant time comparison, so the check does not leak the expected value
  * A timestamp window, so a captured valid request cannot be replayed later
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

log = logging.getLogger("truestory.webhooks.signature")

#: Requests older than this are rejected even when the signature is valid.
MAX_SKEW_SECONDS = 300


class SignatureError(ValueError):
    """Verification failed. The request is dropped and logged, never processed."""


def compute(secret: str, timestamp: str, body: bytes) -> str:
    """The expected signature. Timestamp is inside the signed payload.

    Binding the timestamp into the HMAC is what makes the replay window
    meaningful. Without it, an attacker could reuse a captured signature with a
    fresh timestamp header.
    """
    payload = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify(
    secret: str,
    signature_header: str,
    timestamp_header: str,
    body: bytes,
    *,
    max_skew_seconds: int = MAX_SKEW_SECONDS,
) -> bool:
    """Verify one callback. Raises SignatureError with the specific reason."""
    if not secret:
        raise SignatureError(
            "no webhook signing secret is configured. Refusing to accept unverified "
            "callbacks. See the TODO section of the README, item 3."
        )
    if not signature_header or not timestamp_header:
        raise SignatureError("missing signature or timestamp header")

    try:
        sent_at = int(timestamp_header)
    except ValueError as exc:
        raise SignatureError("timestamp header is not an integer") from exc

    skew = abs(time.time() - sent_at)
    if skew > max_skew_seconds:
        raise SignatureError(f"timestamp outside the replay window, skew {skew:.0f}s")

    expected = compute(secret, timestamp_header, body)
    provided = signature_header.removeprefix("sha256=").strip()

    # Constant time. A short circuiting comparison leaks the expected value one
    # byte at a time to anyone willing to measure.
    if not hmac.compare_digest(expected, provided):
        raise SignatureError("signature mismatch")

    return True


def sign_outbound(secret: str, body: bytes) -> dict[str, str]:
    """Sign a callback we send. Used by the local webhook replay tool in tests."""
    timestamp = str(int(time.time()))
    return {
        "x-truestory-timestamp": timestamp,
        "x-truestory-signature": f"sha256={compute(secret, timestamp, body)}",
    }
