"""Signed callback receiver.

Deployed as its own Cloud Run service because it must stay up while the
pipeline is idle. Deep research tasks return minutes later, and Living
Clearance monitors fire weeks or months later, long after the run that created
them has finished.
"""

from truestory.webhooks.signature import SignatureError, compute, sign_outbound, verify

__all__ = ["SignatureError", "compute", "sign_outbound", "verify"]
