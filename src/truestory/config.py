"""Runtime configuration.

Single source of truth for every tunable. Values resolve in this order:

    1. Explicit constructor argument (tests)
    2. Environment variable
    3. .env file, local development only
    4. Declared default

Secrets follow a different path. In any deployed environment `secret_ref`
returns a Secret Manager resource name and `truestory.storage.secrets` resolves
it at call time, so a key never lands in an environment variable, a log line, a
container image, or this repository.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = REPO_ROOT / "policy"
SCHEMA_DIR = REPO_ROOT / "schemas"
DEMO_DIR = REPO_ROOT / "demo"
EVAL_DIR = REPO_ROOT / "eval"
FIXTURE_DIR = EVAL_DIR / "fixtures"


class Mode(StrEnum):
    """How the provider layer behaves.

    MOCK   deterministic fixtures, no network, no spend. The default so that a
           fresh clone runs the whole pipeline with zero credentials.
    CACHED replay recorded responses, fall through to live on a cache miss.
           This is the mode the demo is recorded in: warm once, then every take
           is free and byte identical.
    LIVE   real Parallel and real Vertex AI. Costs money, governed by
           BudgetGovernor.
    """

    MOCK = "mock"
    CACHED = "cached"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── runtime ──────────────────────────────────────────────────────────────
    mode: Mode = Field(default=Mode.MOCK, alias="TRUESTORY_MODE")
    log_level: str = Field(default="info", alias="TRUESTORY_LOG_LEVEL")
    env_name: str = Field(default="local", alias="TRUESTORY_ENV")

    # ── google cloud ─────────────────────────────────────────────────────────
    gcp_project: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    # Vertex AI only. Firestore, Cloud Storage and BigQuery carry their own
    # locations and are unaffected by this.
    #
    # `global` rather than a region, and the difference is not cosmetic. Every
    # Gemini 3 model returns 404 NOT_FOUND from `us-central1` on this project
    # while serving normally from `global`:
    #
    #     us-central1   gemini-3.7-flash        404 NOT_FOUND
    #                   gemini-3.1-pro-preview  404 NOT_FOUND
    #                   gemini-2.5-pro          ok
    #     global        all four                ok
    #
    # Verified 1 September 2026 against project gen-lang-client-0569749083. The
    # older 2.5 models serve from both, which is why a regional value worked
    # for months and then silently capped the project at the previous
    # generation the moment the newer names were configured.
    gcp_location: str = Field(default="global", alias="GOOGLE_CLOUD_LOCATION")
    google_credentials: str = Field(default="", alias="GOOGLE_APPLICATION_CREDENTIALS")
    use_vertex: bool = Field(default=True, alias="GOOGLE_GENAI_USE_VERTEXAI")

    # ── models, one slot per decision point ──────────────────────────────────
    #
    # Four judgement points and three supporting ones, each named separately so
    # a model can be changed where it matters without moving the others. An
    # unavailable name degrades through `providers.model_fallback` rather than
    # ending the run, which is what makes a preview model a safe default.
    #
    # **These assignments are reasoned, not measured.** The 2.5 generation is
    # what this project's prompts were written and debugged against. Confirm a
    # change against `demo/screenplay/forty_five_minutes.fountain`, whose
    # expected verdicts are the only ground truth here, before quoting any
    # accuracy number that depends on it. `truestory doctor` reports which of
    # these a project can actually serve.

    # Per scene structured extraction under a JSON schema, at the highest
    # volume of any stage on a feature. Flash is the right shape for it and the
    # newest one is materially better at schema adherence, which is the
    # failure mode that costs recall here.
    model_ingest: str = Field(default="gemini-3.7-flash", alias="TRUESTORY_MODEL_INGEST")
    # The ceiling on the entire system. Every verdict downstream is a judgement
    # about a claim this stage either found or missed, so it gets the strongest
    # reasoning model available.
    model_claims: str = Field(default="gemini-3.1-pro-preview", alias="TRUESTORY_MODEL_CLAIMS")
    # The verdict itself, under forced function calling. Highest volume of the
    # judgement stages and the one whose mistakes reach the deliverable, so it
    # takes reasoning over latency.
    model_adjudicator: str = Field(
        default="gemini-3.1-pro-preview", alias="TRUESTORY_MODEL_ADJUDICATOR"
    )
    model_remedy: str = Field(default="gemini-3.7-flash", alias="TRUESTORY_MODEL_REMEDY")
    # The attribution gate runs once per subject over a handful of short texts.
    # It is reading comprehension rather than judgement, and a deterministic
    # quote check catches its mistakes, so it takes the fast model and stays
    # cheap enough to run on every source of every claim.
    model_attribution: str = Field(default="gemini-3.7-flash", alias="TRUESTORY_MODEL_ATTRIBUTION")
    # Identity resolution: is this name a real person or an invention.
    model_identity: str = Field(default="gemini-3.7-flash", alias="TRUESTORY_MODEL_IDENTITY")
    # The grounded fallback, and the one model choice here that is not about
    # capability. Measured on the same question and the same prompt, 2.5-pro
    # returned zero grounding chunks and answered from parametric knowledge,
    # while 2.5-flash searched and returned five to seven. A fallback that does
    # not retrieve is worse than no fallback: it produces a confident answer
    # with nothing to cite, which this system must then discard, so the claim
    # ends UNSUPPORTED having looked like it was researched.
    #
    # Stays on a flash model for that measured reason. Moving it to a pro model
    # needs the grounding chunk count checked first, not assumed.
    model_grounded: str = Field(default="gemini-3.7-flash", alias="TRUESTORY_MODEL_GROUNDED")

    @property
    def models_in_use(self) -> dict[str, str]:
        """Every configured model, by the decision point it serves."""
        return {
            "ingest": self.model_ingest,
            "claims": self.model_claims,
            "adjudicator": self.model_adjudicator,
            "remedy": self.model_remedy,
            "attribution": self.model_attribution,
            "identity": self.model_identity,
            "grounded": self.model_grounded,
        }

    agent_engine_resource: str = Field(default="", alias="AGENT_ENGINE_RESOURCE_NAME")
    agent_engine_staging: str = Field(default="", alias="AGENT_ENGINE_STAGING_BUCKET")

    # ── parallel ─────────────────────────────────────────────────────────────
    parallel_api_key: str = Field(default="", alias="PARALLEL_API_KEY")
    parallel_api_base: str = Field(default="https://api.parallel.ai", alias="PARALLEL_API_BASE")
    parallel_timeout_seconds: int = Field(default=120, alias="PARALLEL_TIMEOUT_SECONDS")
    # How long to keep long polling one Task run before parking it. The result
    # endpoint answers 408 "Run still active" whenever its window elapses, which
    # for anything deeper than a lite lookup is the normal first answer, so this
    # is the number that decides whether deep research completes at all rather
    # than a safety valve. Generous on purpose: a parked subject becomes an
    # amber finding about a record nobody read.
    parallel_result_deadline_seconds: int = Field(
        default=420, alias="PARALLEL_RESULT_DEADLINE_SECONDS"
    )
    parallel_use_fast: bool = Field(default=True, alias="PARALLEL_USE_FAST_VARIANTS")
    parallel_webhook_secret: str = Field(default="", alias="PARALLEL_WEBHOOK_SECRET")
    parallel_webhook_url: str = Field(default="", alias="PARALLEL_WEBHOOK_URL")

    # ── storage ──────────────────────────────────────────────────────────────
    firestore_database: str = Field(default="(default)", alias="FIRESTORE_DATABASE")
    firestore_emulator: str = Field(default="", alias="FIRESTORE_EMULATOR_HOST")
    bucket_scripts: str = Field(default="", alias="GCS_BUCKET_SCRIPTS")
    bucket_evidence: str = Field(default="", alias="GCS_BUCKET_EVIDENCE")
    bucket_reports: str = Field(default="", alias="GCS_BUCKET_REPORTS")
    bq_dataset: str = Field(default="truestory", alias="BIGQUERY_DATASET")
    bq_table_cost: str = Field(default="cost_telemetry", alias="BIGQUERY_TABLE_COST")
    bq_table_eval: str = Field(default="eval_results", alias="BIGQUERY_TABLE_EVAL")
    bq_table_precedent: str = Field(default="precedent_corpus", alias="BIGQUERY_TABLE_PRECEDENT")

    # ── async plane ──────────────────────────────────────────────────────────
    topic_research: str = Field(default="truestory-research", alias="PUBSUB_TOPIC_RESEARCH")
    topic_alerts: str = Field(default="truestory-alerts", alias="PUBSUB_TOPIC_ALERTS")
    tasks_queue: str = Field(default="truestory-retry", alias="CLOUD_TASKS_QUEUE")
    tasks_location: str = Field(default="us-central1", alias="CLOUD_TASKS_LOCATION")
    stale_sweep_minutes: int = Field(default=15, alias="STALE_RUN_SWEEP_MINUTES")

    # ── budget ───────────────────────────────────────────────────────────────
    budget_per_script_usd: float = Field(default=5.00, alias="BUDGET_PER_SCRIPT_USD")
    budget_reserve_critical_usd: float = Field(default=1.50, alias="BUDGET_RESERVE_CRITICAL_USD")
    budget_degrade_on_exceed: bool = Field(default=True, alias="BUDGET_DEGRADE_ON_EXCEED")
    # Concurrent research subjects in flight. **This is a concurrency limit, not
    # a rate limit, and the two were confused.** The swarm was set to 32 on the
    # reasoning that Parallel's Task API accepts roughly two thousand requests a
    # minute, which is true and is about arrival rate. The binding constraint is
    # how many runs an account may have *active* at once, and it is far lower.
    #
    # Measured against this account on 2 September, twelve identical base
    # subjects:
    #
    #     concurrency 32   0 of 35 completed; every run parked at the 420s
    #                      deadline and the whole run fell through to the
    #                      grounded fallback
    #     concurrency  6   12 of 12 completed, 141s wall, slowest 141s
    #
    # In isolation the same lookup takes 25 to 98 seconds. Over-dispatching does
    # not fail loudly; it queues, every subject ages out, and the report is
    # carried entirely by the fallback while Parallel is billed for runs nobody
    # collected. Eight leaves margin without re-entering that regime.
    swarm_max_concurrency: int = Field(default=8, alias="SWARM_MAX_CONCURRENCY")
    # The two model stages that run per scene and per span. Both were serial
    # loops, which is what made a feature length script take tens of minutes
    # before a single subject had been dispatched. Bounded rather than
    # unbounded so a long script does not open two hundred sockets at once.
    ingest_max_concurrency: int = Field(default=12, alias="INGEST_MAX_CONCURRENCY")
    claims_max_concurrency: int = Field(default=16, alias="CLAIMS_MAX_CONCURRENCY")

    # ── freshness ────────────────────────────────────────────────────────────
    # How old a cached research answer may be before a live run re researches
    # it. Applies to live runs only: replay and mock keep every entry so a
    # recorded demo and the eval set stay byte identical.
    cache_max_age_days: int = Field(default=30, alias="TRUESTORY_CACHE_MAX_AGE_DAYS")

    # ── alerting ─────────────────────────────────────────────────────────────
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    alert_email_to: str = Field(default="", alias="ALERT_EMAIL_TO")

    # ── derived ──────────────────────────────────────────────────────────────
    @property
    def is_live(self) -> bool:
        return self.mode is Mode.LIVE

    @property
    def offline(self) -> bool:
        """True when no outbound call may be made under any circumstance."""
        return self.mode is Mode.MOCK

    @property
    def cache_dir(self) -> Path:
        return REPO_ROOT / ".truestory_cache"

    def secret_ref(self, name: str) -> str:
        """Fully qualified Secret Manager resource name for `name`."""
        return f"projects/{self.gcp_project}/secrets/{name}/versions/latest"

    def processor(self, tier_processor: str) -> str:
        """Map a logical processor to the concrete Parallel processor string.

        The `-fast` variants cost the same as the standard ones and skip live
        crawling, which keeps the on camera run synchronous. They are the
        default for anything interactive and are disabled for batch monitors.
        """
        if self.parallel_use_fast and tier_processor in {"lite", "base", "core"}:
            return f"{tier_processor}-fast"
        return tier_processor

    @model_validator(mode="after")
    def _export_google_credentials(self) -> Settings:
        """Publish the key path into the process environment.

        google-auth reads `GOOGLE_APPLICATION_CREDENTIALS` from os.environ and
        knows nothing about this settings object, so a path that lives only in
        .env never reaches it. Without this, local Vertex auth fails with
        "default credentials were not found" while the value sits right there
        in the file. An explicit env var still wins: it is never overwritten.
        """
        if self.google_credentials and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            key = Path(self.google_credentials).expanduser()
            if not key.is_file():
                # A stale path in .env, typically one checked out on another
                # machine, used to abort settings construction and take down
                # every entrypoint including mock mode and the test suite. The
                # condition is worth a loud warning and nothing more: Vertex
                # will fail its own auth clearly if it is actually needed.
                import warnings

                warnings.warn(
                    f"GOOGLE_APPLICATION_CREDENTIALS points at {key}, which does not "
                    "exist. Ignoring it. Vertex AI calls will fall back to "
                    "application default credentials.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                return self
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(key)
        return self

    @model_validator(mode="after")
    def _guard_live_mode(self) -> Settings:
        """Fail loudly rather than silently degrading to a useless run."""
        if self.mode is Mode.LIVE:
            missing = [
                name
                for name, value in (
                    ("PARALLEL_API_KEY", self.parallel_api_key),
                    ("GOOGLE_CLOUD_PROJECT", self.gcp_project),
                )
                if not value or value.startswith("PLACEHOLDER")
            ]
            if missing:
                raise ValueError(
                    "TRUESTORY_MODE=live requires: "
                    + ", ".join(missing)
                    + ". See the build status section of the README for how to obtain each."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process wide settings singleton. Call `get_settings.cache_clear()` in tests."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
