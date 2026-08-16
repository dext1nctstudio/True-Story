"""Secret Manager.

Never environment variables, never the repository, never a container image.
The Parallel key and the webhook signing secret are resolved at call time from
Secret Manager using the service identity attached to the runtime, and they are
cached in process for the lifetime of the container rather than baked into it.

Locally the resolution falls through to the environment so that development
works, and that fallback logs at debug level so it is visible when it happens.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from truestory.config import settings

log = logging.getLogger("truestory.storage.secrets")

#: Logical name to the Secret Manager secret id and the local fallback variable.
SECRETS: dict[str, tuple[str, str]] = {
    "parallel_api_key": ("truestory-parallel-api-key", "PARALLEL_API_KEY"),
    "parallel_webhook_secret": ("truestory-parallel-webhook-secret", "PARALLEL_WEBHOOK_SECRET"),
    "api_internal_token": ("truestory-api-internal-token", "API_INTERNAL_TOKEN"),
    "slack_webhook_url": ("truestory-slack-webhook-url", "SLACK_WEBHOOK_URL"),
}


class SecretResolver:
    def __init__(self, client: Any = None) -> None:
        self._client = client

    def _sm(self) -> Any:
        if self._client is None:
            from google.cloud import secretmanager

            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    def resolve(self, logical_name: str) -> str:
        """Secret Manager first, environment second, empty string last.

        Returning empty rather than raising is deliberate. Mock mode and CI run
        with no secrets at all, and the live mode guard in `config` is the
        place that refuses to start without them.
        """
        if logical_name not in SECRETS:
            raise KeyError(f"unknown secret: {logical_name}")

        secret_id, env_var = SECRETS[logical_name]

        if not settings.offline and settings.gcp_project:
            try:
                name = f"projects/{settings.gcp_project}/secrets/{secret_id}/versions/latest"
                response = self._sm().access_secret_version(request={"name": name})
                return response.payload.data.decode("utf-8").strip()
            except Exception as exc:
                log.debug("secret manager lookup failed for %s: %s", secret_id, exc)

        value = os.environ.get(env_var, "")
        if value.startswith("PLACEHOLDER"):
            log.debug("secret %s is still a placeholder", env_var)
            return ""
        if value:
            log.debug("resolved %s from the environment", logical_name)
        return value


_resolver = SecretResolver()


@lru_cache(maxsize=8)
def get_secret(logical_name: str) -> str:
    """Cached for the lifetime of the container. Call `get_secret.cache_clear()` to rotate."""
    return _resolver.resolve(logical_name)


def redact(value: str, keep: int = 4) -> str:
    """Never log a secret. Use this anywhere one might appear."""
    if not value:
        return "(empty)"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"
