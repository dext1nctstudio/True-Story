"""The service tier. Thin on purpose.

Every endpoint validates, delegates, shapes the response for the caller's role,
and returns. No domain logic lives in this package, which is why the whole
pipeline is testable without ever starting a web server.
"""

from truestory.api.security import (
    FIRESTORE_RULES,
    VIEW_MATRIX,
    Principal,
    apply_view,
    can,
    dev_principal,
)

__all__ = [
    "FIRESTORE_RULES",
    "VIEW_MATRIX",
    "Principal",
    "apply_view",
    "can",
    "dev_principal",
]
