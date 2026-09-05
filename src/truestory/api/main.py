"""The REST and SSE surface.

Thin by design. Every endpoint validates, delegates to the pipeline or the
store, shapes the response for the caller's role, and returns. No domain logic
lives here.

The stream endpoint is what makes the demo kinetic. Verdicts arrive as the
swarm completes them, so the page fills in live rather than showing a spinner
and then a wall of results.

    uvicorn truestory.api.main:app --reload --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from truestory.agents.pipeline import ProjectConfig, RunState, TrueStoryPipeline
from truestory.agents.report import ReportAgent
from truestory.api.security import (
    Principal,
    apply_view,
    can,
    record_override,
    record_remedy_applied,
    unmask,
)
from truestory.config import settings
from truestory.models.enums import Role, RunStatus
from truestory.storage import get_store

log = logging.getLogger("truestory.api")


def _reconcile_orphaned_runs() -> None:
    """Fail every run this process finds still in flight at boot.

    A run's actual work happens inside a `BackgroundTasks` callback in this
    same process, not a durable job queue -- nothing resumes it if the
    process that owned it is gone. A redeploy or a free tier restart mid run
    abandons that callback with no trace, and the run's stored status just
    stays wherever it last landed: QUEUED forever if the process died before
    ingest even produced a state, since nothing else ever revisits it. Any
    run still non terminal when a fresh process starts up is, by
    construction, one of those -- mark it FAILED so the dashboard reflects
    reality and the user can resubmit, instead of it sitting there forever
    looking like work is happening.
    """
    try:
        store = get_store()
        runs = store.list_all_runs()
    except Exception:
        log.warning("could not reconcile orphaned runs at startup", exc_info=True)
        return

    terminal = {str(RunStatus.COMPLETE), str(RunStatus.FAILED)}
    for run in runs:
        status = run.get("status")
        if status in terminal:
            continue
        project_id, run_id = run.get("project_id"), run.get("run_id")
        if not project_id or not run_id:
            continue
        try:
            store.update_run(
                project_id,
                run_id,
                {
                    "status": str(RunStatus.FAILED),
                    "error": (
                        f"Interrupted while {status or 'QUEUED'}: the server restarted "
                        "before this run finished. Please resubmit."
                    ),
                },
            )
            log.warning("marked orphaned run %s (was %s) as failed on startup", run_id, status)
        except Exception:
            log.warning("could not mark orphaned run %s as failed", run_id, exc_info=True)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _reconcile_orphaned_runs()
    yield


app = FastAPI(
    title="TRUE STORY",
    description=(
        "A fact and rights engine for based on a true story productions. "
        "Decision support for a clearance attorney. Not legal advice."
    ),
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.env_name == "local" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In process run registry. Deployed, this lives in Firestore and the streams
# are driven by real time listeners rather than these queues.
_RUNS: dict[str, RunState] = {}
_STREAMS: dict[str, asyncio.Queue[dict[str, Any]]] = {}
#: The pipeline behind each run, kept so the cost endpoint can read the
#: governor's ledger rather than a rounded figure copied onto the summary.
#: Process memory, like _RUNS: a restarted API answers 404 for cost detail on
#: an old run instead of inventing one.
_PIPELINES: dict[str, TrueStoryPipeline] = {}
_PROJECTS: dict[str, ProjectConfig] = {}


# =============================================================================
# auth
# =============================================================================


async def current_principal(
    x_truestory_role: str = Header(default="truestory.counsel"),
    x_truestory_subject: str = Header(default="dev@localhost"),
    x_truestory_projects: str = Header(default="demo"),
) -> Principal:
    """Resolve the caller.

    Header based for local development. In deployment this validates the
    identity token that Cloud Run puts in front of the service and reads the
    role from a verified custom claim, never from a client supplied header.
    """
    if settings.env_name == "local":
        try:
            role = Role(x_truestory_role)
        except ValueError:
            role = Role.COUNSEL
        return Principal(
            subject=x_truestory_subject,
            role=role,
            project_ids=tuple(p.strip() for p in x_truestory_projects.split(",") if p.strip()),
        )

    raise HTTPException(
        status_code=501,
        detail=(
            "Identity token verification is not wired yet. See the build status "
            "section of the README, item 4."
        ),
    )


def _require_project(principal: Principal, project_id: str) -> None:
    if not principal.may_access_project(project_id):
        raise HTTPException(status_code=403, detail="no access to this project")


# =============================================================================
# models
# =============================================================================


class CreateProject(BaseModel):
    title: str
    shoot_territories: list[str] = Field(default_factory=lambda: ["US"])
    distribution_territories: list[str] = Field(default_factory=lambda: ["US"])
    budget_usd: float | None = None
    truth_claim_framing: bool | None = Field(
        default=None,
        description=(
            "Normally detected from the script. Set explicitly when the "
            "production has already decided how it will present itself."
        ),
    )


class StartRun(BaseModel):
    draft_version: str = "v1"
    parent_run_id: str | None = Field(
        default=None,
        description=(
            "Chains lineage for a revision. Content addressed identifiers mean "
            "only the delta is researched, roughly a ninety five percent "
            "reduction on a typical redraft."
        ),
    )
    script_text: str | None = None
    script_path: str | None = None


class OverrideRequest(BaseModel):
    new_verdict: str
    reason: str


class UnmaskRequest(BaseModel):
    reason: str


class InterrogateRequest(BaseModel):
    """One ad hoc question about one subject, asked while reading the overlay."""

    question: str = Field(min_length=3, max_length=400)
    subject_id: str = Field(default="", max_length=120)
    subject: str = Field(default="", max_length=200)


# =============================================================================
# health
# =============================================================================


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    """Liveness, plus which run store actually answered.

    Added after a deployment returned `{"runs": []}` with no error anywhere
    -- the ambiguous result get_store() produces both when there is a real
    project with zero runs in it and when nothing is configured for it to
    try. Distinguishing those from outside the process meant reading log
    scrollback for a warning that only fires on an actual exception, which
    said nothing when the true cause was a variable that was simply never
    set. `store` here names the class directly, so the answer is one request
    rather than a log archaeology exercise, and it never raises: a failure
    to even construct the store is itself the finding, reported as its own
    string rather than turning a liveness probe into a 500.
    """
    try:
        store_name = type(get_store()).__name__
    except Exception as exc:
        store_name = f"unavailable: {type(exc).__name__}: {exc}"

    return {
        "ok": True,
        "mode": str(settings.mode),
        "env": settings.env_name,
        "version": app.version,
        "store": store_name,
        "gcp_project": settings.gcp_project or None,
    }


@app.get("/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    """The A2A AgentCard.

    Published as a documented spec in this build. A2A belongs at
    organisational boundaries, where an insurer, a studio or a law firm agent
    calls this system from outside our trust boundary. Using it for internal
    control flow would add latency and buy nothing.
    """
    card_path = Path(__file__).resolve().parents[3] / "a2a" / "agent_card.json"
    if card_path.exists():
        return json.loads(card_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="agent card not found")


# =============================================================================
# projects
# =============================================================================


@app.post("/v1/projects", status_code=201)
async def create_project(
    body: CreateProject, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    project_id = f"prj_{uuid.uuid4().hex[:12]}"
    config = ProjectConfig(
        project_id=project_id,
        title=body.title,
        shoot_territories=body.shoot_territories,
        distribution_territories=body.distribution_territories,
        budget_usd=body.budget_usd,
        truth_claim_framing_override=body.truth_claim_framing,
    )
    _PROJECTS[project_id] = config

    get_store().audit("create_project", principal.subject, project_id, {"title": body.title})

    return {
        "project_id": project_id,
        "title": body.title,
        "jurisdictions": config.jurisdictions(),
        "budget_usd": body.budget_usd or settings.budget_per_script_usd,
    }


@app.get("/v1/projects/{project_id}/runs")
async def list_runs(
    project_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """Every run this project has seen, newest first.

    There was previously no way to discover a run's id except being handed it
    at upload time, so a run that finished while you were away from that URL
    was effectively lost.

    In process runs come first because only they carry live status for a run
    still executing. Completed runs are then merged in from the store, which
    is what makes the list survive a restart: Firestore was being written on
    completion but never read back, so every restart presented an empty
    dashboard even though the runs were sitting in the database.
    """
    _require_project(principal, project_id)
    rows = [
        {
            "run_id": state.run_id,
            "status": str(state.status),
            "script_title": state.document.title if state.document else None,
            "started_at": state.started_at.isoformat(),
            "verdicts": (
                {
                    "green": state.summary.green,
                    "amber": state.summary.amber,
                    "red": state.summary.red,
                    "grey": state.summary.grey,
                }
                if state.summary
                else None
            ),
            "cost_usd": (state.summary.cost_cents / 100) if state.summary else None,
            "error": state.error,
        }
        for state in _RUNS.values()
        if state.project_id == project_id
    ]

    live = {r["run_id"] for r in rows}
    try:
        for stored in get_store().list_runs(project_id):
            run_id = stored.get("run_id")
            if not run_id or run_id in live:
                continue
            summary = stored.get("summary") or {}
            script = stored.get("script") or {}
            created = stored.get("created_at")
            rows.append(
                {
                    "run_id": run_id,
                    "status": stored.get("status") or "COMPLETE",
                    "script_title": script.get("title"),
                    "started_at": created.isoformat() if hasattr(created, "isoformat") else created,
                    "verdicts": summary.get("verdicts"),
                    "cost_usd": summary.get("cost_usd"),
                    "error": stored.get("error"),
                    "restored": True,
                }
            )
    except Exception:
        log.warning("could not read persisted runs for %s", project_id, exc_info=True)

    rows.sort(key=lambda r: str(r["started_at"] or ""), reverse=True)
    return {"runs": rows}


@app.get("/v1/projects/{project_id}/monitors")
async def list_monitors(
    project_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    _require_project(principal, project_id)
    if not can(principal, "monitors"):
        raise HTTPException(status_code=403, detail="role may not view monitors")
    return {"monitors": get_store().list_monitors(project_id)}


# =============================================================================
# runs
# =============================================================================


@app.post("/v1/projects/{project_id}/runs", status_code=202)
async def start_run(
    project_id: str,
    body: StartRun,
    background: BackgroundTasks,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Upload a draft and start the pipeline. Returns immediately with a run id."""
    _require_project(principal, project_id)

    config = _PROJECTS.get(project_id) or ProjectConfig(project_id=project_id)
    source = body.script_text or body.script_path
    if not source:
        raise HTTPException(status_code=400, detail="provide script_text or script_path")

    run_id = f"run_{uuid.uuid4().hex[:16]}"
    _STREAMS[run_id] = asyncio.Queue()

    background.add_task(
        _execute_run, config, run_id, source, body.draft_version, body.parent_run_id
    )

    return {
        "run_id": run_id,
        "project_id": project_id,
        "status": str(RunStatus.QUEUED),
        "stream": f"/v1/runs/{run_id}/stream",
    }


@app.post("/v1/projects/{project_id}/runs/upload", status_code=202)
async def upload_run(
    project_id: str,
    background: BackgroundTasks,
    file: UploadFile,
    draft_version: str = "v1",
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """The drag and drop path. Accepts fdx, fountain, pdf and plain text.

    `_read_source` in the ingest agent routes on a file suffix, and the fdx
    branch only strips FDX markup for that same suffix. Decoding straight to
    UTF-8 text here loses both: a PDF's bytes are corrupted before pypdf ever
    sees them, and an uploaded .fdx never gets its markup stripped, because
    neither reaches ingest as a path with the original extension. A temp file
    with the real suffix restores the same routing a CLI run gets for free.
    """
    _require_project(principal, project_id)

    raw = await file.read()
    suffix = Path(file.filename or "").suffix.lower()

    config = _PROJECTS.get(project_id) or ProjectConfig(project_id=project_id)
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    _STREAMS[run_id] = asyncio.Queue()

    source: Path | str
    if suffix in {".pdf", ".fdx"}:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)  # noqa: SIM115
        tmp.write(raw)
        tmp.close()
        source = Path(tmp.name)
    else:
        source = raw.decode("utf-8", errors="replace")

    background.add_task(_execute_run, config, run_id, source, draft_version, None)

    return {
        "run_id": run_id,
        "filename": file.filename,
        "bytes": len(raw),
        "stream": f"/v1/runs/{run_id}/stream",
    }


async def _execute_run(
    config: ProjectConfig,
    run_id: str,
    source: Path | str,
    draft_version: str,
    parent_run_id: str | None,
) -> None:
    queue = _STREAMS.get(run_id)

    # Register the run before the first stage starts. Ingest is minutes of
    # model calls on a feature length script, and until it finished the run
    # existed nowhere the API could see: the dashboard listed nothing and
    # every read 404'd, so a run that was busy working looked like a run that
    # had never been started. The placeholder is replaced by the real state
    # the moment ingest produces one.
    initial = RunState(run_id=run_id, project_id=config.project_id)
    _RUNS[run_id] = initial
    try:
        get_store().create_run(config.project_id, run_id, initial.to_dict())
    except Exception:
        log.warning("could not persist queued run %s", run_id, exc_info=True)

    async def on_progress(payload: dict[str, Any]) -> None:
        if queue is not None:
            await queue.put(payload)

    def on_state(state: Any) -> None:
        # Swap the placeholder for the real state as soon as ingest lands, so
        # the overlay, claims and counters are readable while the run is still
        # going rather than only after it ends.
        _RUNS[run_id] = state

    pipeline = TrueStoryPipeline(config, on_progress=on_progress)
    _PIPELINES[run_id] = pipeline
    try:
        state = await pipeline.run(
            source,
            draft_version=draft_version,
            parent_run_id=parent_run_id,
            run_id=run_id,
            on_state=on_state,
        )
        _RUNS[run_id] = state
        get_store().update_run(config.project_id, run_id, state.to_dict())
        _persist_artifacts(config.project_id, run_id, state)
    except Exception as exc:
        log.exception("run %s failed", run_id)
        failed = _RUNS.get(run_id) or initial
        failed.status = RunStatus.FAILED
        failed.error = str(exc)
        try:
            get_store().update_run(config.project_id, run_id, failed.to_dict())
        except Exception:
            log.warning("could not persist failed run %s", run_id, exc_info=True)
        if queue is not None:
            await queue.put({"event": "run_failed", "error": str(exc)})
    finally:
        if queue is not None:
            await queue.put({"event": "stream_end"})
        if isinstance(source, Path):
            source.unlink(missing_ok=True)


def _persist_artifacts(project_id: str, run_id: str, state: RunState) -> None:
    """Write the run's contents, not just its counters.

    Persisting only the run record meant a restored run could report its
    verdicts but never show the annotated script, because the claims, the
    elements and the overlay lived solely in this process. The overlay is
    stored as one document per run; the rest go to subcollections, which is
    what `batch_put_subjects` was built for and nothing had used.

    Failure here is logged and swallowed: the run itself has already
    succeeded, and losing durability must not turn that into a failed run.
    """
    store = get_store()
    try:
        for kind, subjects in (
            ("claims", {c.claim_id: c.to_dict() for c in state.claims}),
            ("elements", {e.element_id: e.to_dict() for e in state.elements}),
            ("remedies", {r.remedy_id: r.to_dict() for r in state.remedies}),
            # One record per finding, keyed the same way the assessment itself
            # is keyed, so a restored run can look either up by subject id
            # exactly as the in process path does.
            (
                "exposure",
                {
                    a["subject_id"]: a
                    for a in state.exposure.get("assessments", [])
                    if a.get("subject_id")
                },
            ),
            (
                # `list_subjects` returns only the stored values, not the key
                # each is stored under (both backends: a document's own id is
                # never part of `.to_dict()`), which is why claims and
                # elements already carry their own id field. This one needs
                # the same treatment or a restored run cannot tell which
                # finding each match list belongs to.
                "precedents",
                {
                    subject_id: {"subject_id": subject_id, "matches": matches}
                    for subject_id, matches in state.precedents.items()
                },
            ),
        ):
            if subjects:
                store.batch_put_subjects(project_id, run_id, kind, subjects)

        overlay = state.artifacts.get("report", {}).get("overlay")
        if overlay:
            store.put_subject(project_id, run_id, "artifacts", "overlay", overlay)

        claim_register = state.artifacts.get("report", {}).get("claim_register")
        if claim_register:
            store.put_subject(project_id, run_id, "artifacts", "claim_register", claim_register)

        eo_report = state.artifacts.get("report", {}).get("eo_report")
        if eo_report:
            store.put_subject(project_id, run_id, "artifacts", "eo_report", eo_report)

        clearance_log = state.artifacts.get("report", {}).get("clearance_log_csv")
        if clearance_log:
            store.put_subject(
                project_id,
                run_id,
                "artifacts",
                "clearance_log_csv",
                {"artifact_kind": "clearance_log_csv", "content": clearance_log},
            )

        # The rollup fields (by_band, costs and research summary)
        # live only on the aggregate, not on any one assessment, so they are
        # stored once here rather than reconstructed by summing persisted
        # per finding records back up on every read.
        if state.exposure:
            store.put_subject(
                project_id,
                run_id,
                "artifacts",
                "exposure_summary",
                {k: v for k, v in state.exposure.items() if k != "assessments"},
            )
    except Exception:
        log.warning("could not persist artifacts for run %s", run_id, exc_info=True)


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    state = _RUNS.get(run_id)
    if state is not None:
        _require_project(principal, state.project_id)
        return apply_view(state.to_dict(), principal)

    # Not in this process. It may still be a run from before the last restart,
    # so fall back to the store rather than reporting a run that plainly
    # exists as missing. Detailed artifacts are restored by their endpoints.
    stored = _stored_run(run_id, principal)
    if stored is None:
        raise HTTPException(status_code=404, detail="run not found")
    return apply_view({**stored, "restored": True}, principal)


def _stored_run(run_id: str, principal: Principal) -> dict[str, Any] | None:
    """Find a persisted run across the projects this caller may access."""
    store = get_store()
    for project_id in principal.project_ids:
        try:
            found = store.get_run(project_id, run_id)
        except Exception:
            log.warning("store lookup failed for %s", run_id, exc_info=True)
            return None
        if found:
            return found
    return None


@app.get("/v1/runs/{run_id}/stream")
async def stream_run(run_id: str) -> EventSourceResponse:
    """Server sent events for the live overlay.

    Verdicts arrive as the swarm completes them and the cost meter ticks in
    cents alongside. This is the demo's kinetic energy and it costs nothing
    extra: the pipeline already emits these events for its own logging.
    """
    queue = _STREAMS.get(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="no active stream for this run")

    async def generator() -> Any:
        while True:
            payload = await queue.get()
            if payload.get("event") == "stream_end":
                yield {"event": "end", "data": json.dumps({"run_id": run_id})}
                break
            yield {
                "event": payload.get("event", "message"),
                "data": json.dumps(payload, default=str),
            }

    return EventSourceResponse(generator())


# =============================================================================
# artifacts
# =============================================================================


def _stored_subjects(run_id: str, principal: Principal, kind: str) -> list[dict[str, Any]] | None:
    """Subjects for a run restored from the store, or None if it is not there."""
    store = get_store()
    for project_id in principal.project_ids:
        try:
            if store.get_run(project_id, run_id):
                return store.list_subjects(project_id, run_id, kind)
        except Exception:
            log.warning("store lookup failed for %s/%s", run_id, kind, exc_info=True)
            return None
    return None


def _state_or_404(run_id: str, principal: Principal) -> RunState:
    state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run not found")
    _require_project(principal, state.project_id)
    return state


@app.get("/v1/runs/{run_id}/overlay")
async def get_overlay(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """The verdict annotated script. The money shot."""
    if not can(principal, "overlay"):
        raise HTTPException(status_code=403, detail="role may not view the overlay")

    # A run this process no longer holds is served from the store, so a
    # restored run opens as the annotated script rather than as a bare
    # summary. The overlay is rendered once at stage 8 and stored whole.
    if run_id not in _RUNS:
        stored = _stored_subjects(run_id, principal, "artifacts")
        if stored is None:
            raise HTTPException(status_code=404, detail="run not found")
        for record in stored:
            if record.get("scenes"):
                return apply_view(record, principal)
        return apply_view({}, principal)

    state = _state_or_404(run_id, principal)
    overlay = state.artifacts.get("report", {}).get("overlay", {})
    if not overlay and state.document is not None:
        # The report artifact only exists at stage 8. Build the overlay from
        # current state so a run in flight renders the script and lights lines
        # up as verdicts land, rather than returning {} for its whole duration.
        overlay = ReportAgent().verdict_overlay(state.document, state.claims, state.elements)
    return apply_view(overlay, principal)


@app.get("/v1/runs/{run_id}/claims")
async def get_claims(
    run_id: str,
    verdict: str | None = None,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    if run_id not in _RUNS:
        stored = _stored_subjects(run_id, principal, "claims")
        if stored is None:
            raise HTTPException(status_code=404, detail="run not found")
        rows = [c for c in stored if verdict is None or c.get("verdict") == verdict]
        return apply_view({"claims": rows, "total": len(rows)}, principal)

    state = _state_or_404(run_id, principal)
    claims = [
        c.to_dict(include_evidence=principal.may_see_evidence())
        for c in state.claims
        if verdict is None or str(c.verdict) == verdict
    ]
    return apply_view({"claims": claims, "total": len(claims)}, principal)


@app.get("/v1/runs/{run_id}/remedies")
async def get_remedies(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """Proposed rewrites, each re verified against the record before listing.

    `apply_remedy` was the only remedy endpoint, so the frontend had a claim's
    `remedy_id` and no way to fetch what that id actually proposed.
    """
    if run_id not in _RUNS:
        stored = _stored_subjects(run_id, principal, "remedies")
        if stored is None:
            raise HTTPException(status_code=404, detail="run not found")
        return apply_view({"remedies": stored, "total": len(stored)}, principal)

    state = _state_or_404(run_id, principal)
    remedies = [r.to_dict() for r in state.remedies]
    return apply_view({"remedies": remedies, "total": len(remedies)}, principal)


@app.get("/v1/runs/{run_id}/elements")
async def get_elements(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    if run_id not in _RUNS:
        stored = _stored_subjects(run_id, principal, "elements")
        if stored is None:
            raise HTTPException(status_code=404, detail="run not found")
        return apply_view({"elements": stored, "total": len(stored)}, principal)

    state = _state_or_404(run_id, principal)
    elements = [
        e.to_dict(
            include_evidence=principal.may_see_evidence(),
            unmasked=can(principal, "unmasked"),
        )
        for e in state.elements
    ]
    return apply_view({"elements": elements, "total": len(elements)}, principal)


@app.get("/v1/runs/{run_id}/exposure")
async def get_exposure(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """Severity band, statutory anchors, cost to cure, and the modelled
    exposure figure, per finding, plus the run wide rollup.

    Gated on the same "cost" capability as `cost_cents` and `budget`. This is
    a dollar figure about the production's own risk, and a role that may not
    see the cost meter should not see a modelled lawsuit exposure either.
    """
    if not can(principal, "cost"):
        raise HTTPException(status_code=403, detail="role may not view exposure")

    if run_id not in _RUNS:
        assessments = _stored_subjects(run_id, principal, "exposure")
        if assessments is None:
            raise HTTPException(status_code=404, detail="run not found")
        summary_rows = _stored_subjects(run_id, principal, "artifacts") or []
        summary = next((r for r in summary_rows if "by_band" in r), {})
        payload = {**summary, "assessments": assessments}
        return apply_view(payload, principal)

    state = _state_or_404(run_id, principal)
    return apply_view(dict(state.exposure), principal)


@app.get("/v1/runs/{run_id}/precedents")
async def get_precedents(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """Published disputes of the same failure shape, keyed by finding.

    Never gated on "cost" or "evidence": a precedent carries no dollar figure
    and no masked identity of its own, only a matched shape and a citation to
    a public matter, and it is exactly the context a writer benefits from as
    much as counsel does.
    """
    if run_id not in _RUNS:
        rows = _stored_subjects(run_id, principal, "precedents")
        if rows is None:
            raise HTTPException(status_code=404, detail="run not found")
        precedents = {
            row["subject_id"]: row.get("matches", []) for row in rows if row.get("subject_id")
        }
        return apply_view({"precedents": precedents}, principal)

    state = _state_or_404(run_id, principal)
    return apply_view({"precedents": state.precedents}, principal)


@app.get("/v1/runs/{run_id}/register")
async def get_claim_register(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """Per person claim table, including the amber density meter.

    Counsel and the producer only. The register names living people and totals
    what the record failed to support about each of them, which is a heavier
    document than the overlay and not something a writer or an external
    underwriter is given. The client already assumed this endpoint was gated;
    it was not, so the assumption is now enforced here rather than believed.
    """
    if not can(principal, "review_queue"):
        raise HTTPException(status_code=403, detail="role may not view the person register")
    if run_id not in _RUNS:
        artifacts = _stored_subjects(run_id, principal, "artifacts")
        if artifacts is None:
            raise HTTPException(status_code=404, detail="run not found")
        register = next((r for r in artifacts if "persons" in r), {})
        return apply_view(register, principal)

    state = _state_or_404(run_id, principal)
    return apply_view(state.artifacts.get("report", {}).get("claim_register", {}), principal)


@app.post("/v1/runs/{run_id}/interrogate")
async def interrogate(
    run_id: str,
    body: InterrogateRequest,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Ask the record a question about one line, and get the passages back.

    The single most common thing a reviewer does with a red line is ask why,
    and until now the only answer was the evidence the run happened to collect.
    This is a live search round trip, priced at a tenth of a cent, whose result
    is explicitly a lead rather than a finding: it never enters adjudication,
    never changes a verdict, and is stamped at the provider's own low
    confidence so it cannot present as a verification run.

    Evidence bearing roles only. A search result is research, and the roles
    that are not given research are not given this either.
    """
    if not can(principal, "evidence"):
        raise HTTPException(status_code=403, detail="role may not run research")

    state = _state_or_404(run_id, principal)
    pipeline = _PIPELINES.get(run_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="this run is no longer live in this process")

    # Named subjects only. An open text box that reaches a research API is a
    # way to spend somebody else's money on somebody else's question, so the
    # subject has to be one this run actually researched.
    subject_id = body.subject_id or "interrogation"
    if body.subject_id:
        known = {c.claim_id for c in state.claims} | {e.element_id for e in state.elements}
        if body.subject_id not in known:
            raise HTTPException(status_code=404, detail="unknown subject for this run")

    payload = await pipeline.tools.interrogate(
        subject_id=subject_id,
        question=body.question,
        subject=body.subject,
    )
    get_store().audit(
        "interrogate",
        principal.subject,
        subject_id,
        {"run_id": run_id, "question": body.question[:200]},
    )
    return apply_view(payload, principal)


# =============================================================================
# cost
# =============================================================================


@app.get("/v1/runs/{run_id}/cost")
async def get_run_cost(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """The full cost breakdown for one run.

    Research and model spend are two different bills and are never blended
    into one figure here: the research ceiling governs research only, and a
    number that mixes them cannot be checked against either invoice.
    """
    if not can(principal, "cost"):
        raise HTTPException(status_code=403, detail="role may not view cost")

    state = _state_or_404(run_id, principal)
    pipeline = _PIPELINES.get(run_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="cost detail is not retained for this run")

    budget = pipeline.budget
    pages = float(state.document.page_count) if state.document else 0.0
    researched = len([e for e in state.elements if e.evidence]) + len(
        [c for c in state.claims if c.evidence]
    )
    return {
        "run_id": run_id,
        "snapshot": budget.snapshot(),
        "economics": budget.economics(subjects=researched, claims=len(state.claims), pages=pages),
        "pricing": _pricing_payload(),
        "counts": {
            "researched_subjects": researched,
            "claims": len(state.claims),
            "elements": len(state.elements),
            "pages": pages,
        },
    }


@app.get("/v1/pricing")
async def get_pricing() -> dict[str, Any]:
    """Published unit prices, so nothing downstream restates a rate.

    The UI cost calculator, the report footer and the projection all read from
    here. One place holds a price, and one date says when it was verified.
    """
    return _pricing_payload()


class EstimateRequest(BaseModel):
    """A pre flight estimate for a script nobody has uploaded yet."""

    pages: int = Field(default=100, ge=1, le=400)
    truth_claim_framing: bool = Field(
        default=True,
        description="A true story assertion escalates every person adjacent subject one tier.",
    )
    drafts: int = Field(default=1, ge=1, le=20, description="Drafts over the life of the title.")
    cache_hit_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=0.99,
        description="Expected share of subjects unchanged from the previous draft.",
    )


@app.post("/v1/estimate")
async def estimate(body: EstimateRequest) -> dict[str, Any]:
    """What a script of this size would cost, before anything is uploaded.

    Built from the same processor prices and the same per page subject density
    the router actually produces, so the number on the marketing surface and
    the number on the meter come from one source. Densities are measured from
    the demo screenplay and stated as such rather than presented as a law.
    """
    return _estimate(body)


@app.get("/v1/runs/{run_id}/report")
async def get_eo_report(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    if not can(principal, "reports"):
        raise HTTPException(status_code=403, detail="role may not view reports")

    if run_id not in _RUNS:
        artifacts = _stored_subjects(run_id, principal, "artifacts")
        if artifacts is None:
            raise HTTPException(status_code=404, detail="run not found")
        report = next((r for r in artifacts if "title_page" in r), {})
        return apply_view(report, principal)

    state = _state_or_404(run_id, principal)
    return apply_view(state.artifacts.get("report", {}).get("eo_report", {}), principal)


@app.get("/v1/runs/{run_id}/clearance_log.csv", response_class=PlainTextResponse)
async def get_clearance_log(
    run_id: str, principal: Principal = Depends(current_principal)
) -> Response:
    """The insurer checklist. Every visible piece of IP and its status."""
    if not can(principal, "reports"):
        raise HTTPException(status_code=403, detail="role may not view reports")

    if run_id not in _RUNS:
        artifacts = _stored_subjects(run_id, principal, "artifacts")
        if artifacts is None:
            raise HTTPException(status_code=404, detail="run not found")
        record = next(
            (r for r in artifacts if r.get("artifact_kind") == "clearance_log_csv"),
            {},
        )
        csv_text = str(record.get("content") or "")
    else:
        state = _state_or_404(run_id, principal)
        csv_text = state.artifacts.get("report", {}).get("clearance_log_csv", "")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="clearance_log_{run_id}.csv"'},
    )


@app.get("/v1/runs/{run_id}/report.pdf")
async def get_report_pdf(
    run_id: str, principal: Principal = Depends(current_principal)
) -> Response:
    if not can(principal, "reports"):
        raise HTTPException(status_code=403, detail="role may not view reports")

    if run_id not in _RUNS:
        artifacts = _stored_subjects(run_id, principal, "artifacts")
        if artifacts is None:
            raise HTTPException(status_code=404, detail="run not found")
        report = next((r for r in artifacts if "title_page" in r), {})
    else:
        state = _state_or_404(run_id, principal)
        report = state.artifacts.get("report", {}).get("eo_report", {})

    from truestory.reports.eo_report import render_pdf

    pdf = render_pdf(
        report,
        watermark="UNDERWRITER COPY" if principal.role is Role.UNDERWRITER else None,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"content-disposition": f'inline; filename="eo_clearance_{run_id}.pdf"'},
    )


# =============================================================================
# governed actions
# =============================================================================


@app.post("/v1/claims/{claim_id}/apply_remedy")
async def apply_remedy(
    claim_id: str,
    run_id: str,
    remedy_id: str,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Write the redline. Audited.

    Only remedies that came back verified through the same research path are
    applyable. A proposal that never verified is not a fix.
    """
    state = _state_or_404(run_id, principal)
    if not principal.may_apply_remedy():
        raise HTTPException(status_code=403, detail="role may not apply remedies")

    remedy = next((r for r in state.remedies if r.remedy_id == remedy_id), None)
    if remedy is None:
        raise HTTPException(status_code=404, detail="remedy not found")
    if not remedy.verified:
        raise HTTPException(
            status_code=409,
            detail="remedy did not verify against the record and cannot be applied",
        )

    record_remedy_applied(principal, claim_id, remedy_id)
    return {"applied": True, "claim_id": claim_id, "remedy": remedy.to_dict()}


@app.post("/v1/subjects/{subject_id}/override")
async def override_verdict(
    subject_id: str,
    run_id: str,
    body: OverrideRequest,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Counsel overriding the machine. Permitted, and permanently recorded."""
    state = _state_or_404(run_id, principal)
    if not principal.may_override():
        raise HTTPException(status_code=403, detail="only counsel may override a verdict")

    claim = next((c for c in state.claims if c.claim_id == subject_id), None)
    previous = str(claim.verdict) if claim else "unknown"

    record_override(principal, subject_id, previous, body.new_verdict, body.reason)
    return {"overridden": True, "from": previous, "to": body.new_verdict}


@app.post("/v1/elements/{element_id}/unmask")
async def unmask_element(
    element_id: str,
    run_id: str,
    body: UnmaskRequest,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """Reveal a masked identity. Counsel only, reason required, always audited."""
    state = _state_or_404(run_id, principal)

    if not unmask(principal, state.project_id, element_id, body.reason):
        raise HTTPException(status_code=403, detail="only counsel may unmask an identity")

    element = next((e for e in state.elements if e.element_id == element_id), None)
    if element is None:
        raise HTTPException(status_code=404, detail="element not found")

    return {"unmasked": True, "element": element.to_dict(unmasked=True)}


@app.get("/v1/review_queue")
async def review_queue(
    project_id: str | None = None, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """The human review queue.

    Visible on purpose. Every real clearance workflow ends with an attorney,
    and a system that knows its own uncertainty is the one an enterprise buyer
    trusts. Hiding this would be a worse product and a worse pitch.
    """
    if not can(principal, "review_queue"):
        raise HTTPException(status_code=403, detail="role may not view the review queue")
    return {"items": get_store().list_review_queue(project_id)}


# =============================================================================
# pricing and estimation
# =============================================================================
# One place holds a unit price. The cost meter, the projection, the report
# footer and the marketing calculator all read from here, so a rate cannot be
# right in one surface and stale in another.

#: Subjects per page, measured on the demo screenplay and on the upload test
#: script rather than assumed. Stated as a measurement so the number can be
#: argued with: a dialogue heavy true story piece runs hot, a genre script with
#: few real people runs well under it.
_DENSITY = {
    "claims_per_page": 1.6,
    "elements_per_page": 0.5,
    # Share of claims that land at each depth once the router has run. Derived
    # from the routing table: negative claims about living people go to core,
    # quotes and ordinary claims to base, background elements to lite.
    "mix_core": 0.18,
    "mix_base": 0.62,
    "mix_lite": 0.20,
    # A true story assertion escalates person adjacent subjects one tier, which
    # moves roughly this share of base work up to core.
    "framing_uplift": 0.25,
    "source": "measured on demo/screenplay/the_long_shadow.fountain",
}


def _pricing_payload() -> dict[str, Any]:
    from truestory.models.enums import Processor
    from truestory.policy import load_routing
    from truestory.providers.model_cost import price_table

    budget_policy = load_routing().budget_policy
    return {
        "verified_on": "2026-08-19",
        "research": {
            "task_processors_usd_per_run": {str(p): p.usd_per_run for p in Processor},
            "search_usd_per_request": {"turbo": 0.001, "advanced": 0.005},
            "extract_usd_per_url": 0.001,
            "findall_usd": {
                "preview": {"fixed": 0.10, "per_match": 0.0},
                "base": {"fixed": 0.25, "per_match": 0.03},
                "core": {"fixed": 2.00, "per_match": 0.15},
            },
            "monitor_usd_per_check": {"lite": 0.003, "base": 0.010},
            "source": "https://docs.parallel.ai/getting-started/pricing",
        },
        "models_usd_per_million_tokens": price_table(),
        "models_source": "https://ai.google.dev/gemini-api/docs/pricing",
        "budget": {
            "per_script_ceiling_usd": budget_policy.get("per_script_ceiling_usd", 5.0),
            "reserve_for_critical_usd": budget_policy.get("reserve_for_critical_usd", 1.5),
        },
        "manual_baseline": budget_policy.get("manual_baseline", {}),
        "density": _DENSITY,
    }


def _estimate(body: EstimateRequest) -> dict[str, Any]:
    """Project the cost of a script of this size, in the same units as a run."""
    from truestory.models.enums import Processor
    from truestory.policy import load_routing

    pages = float(body.pages)
    claims = pages * _DENSITY["claims_per_page"]
    elements = pages * _DENSITY["elements_per_page"]
    subjects = claims + elements

    uplift = _DENSITY["framing_uplift"] if body.truth_claim_framing else 0.0
    core_share = _DENSITY["mix_core"] + _DENSITY["mix_base"] * uplift
    base_share = _DENSITY["mix_base"] * (1 - uplift)
    lite_share = _DENSITY["mix_lite"]

    by_processor = {
        "core": subjects * core_share,
        "base": subjects * base_share,
        "lite": subjects * lite_share,
    }
    research_usd = sum(count * Processor(name).usd_per_run for name, count in by_processor.items())

    # Model spend: the script is read once per model stage, and the adjudicator
    # reads evidence per subject. Estimated from tokens rather than guessed at,
    # because on a short script the model half is the larger of the two bills
    # and a projection that omits it is wrong by an order of magnitude.
    from truestory.providers.model_cost import cost_cents

    script_tokens = pages * 450  # ~450 tokens per formatted screenplay page
    ingest_usd = cost_cents(settings.model_ingest, int(script_tokens), int(pages * 120)) / 100
    claims_usd = cost_cents(settings.model_claims, int(script_tokens), int(claims * 90)) / 100
    adjudicate_usd = (
        cost_cents(settings.model_adjudicator, int(subjects * 1400), int(subjects * 120)) / 100
    )
    remedy_usd = cost_cents(settings.model_remedy, int(claims * 0.15 * 900), int(claims * 40)) / 100
    model_usd = ingest_usd + claims_usd + adjudicate_usd + remedy_usd

    first_draft = research_usd + model_usd
    # Later drafts only research what changed, because element and claim
    # identifiers are content hashes. The model half does not get the same
    # discount and it would be dishonest to give it one: a redraft is re read
    # end to end whatever changed in it, so ingest and claim extraction are
    # paid in full again and only adjudication and remedy scale with the delta.
    unchanged = body.cache_hit_rate
    later_draft = (
        research_usd * (1 - unchanged)
        + ingest_usd
        + claims_usd
        + (adjudicate_usd + remedy_usd) * (1 - unchanged)
    )
    total = first_draft + later_draft * max(0, body.drafts - 1)

    baseline = load_routing().budget_policy.get("manual_baseline", {})
    manual_low = float(baseline.get("report_usd_low", 1000))
    manual_total = manual_low * body.drafts

    return {
        "input": body.model_dump(),
        "subjects": {
            "claims": round(claims),
            "elements": round(elements),
            "total": round(subjects),
            "by_processor": {k: round(v) for k, v in by_processor.items()},
        },
        "research_usd": round(research_usd, 4),
        "model_usd": round(model_usd, 4),
        "model_breakdown_usd": {
            "ingest": round(ingest_usd, 4),
            "claim_extraction": round(claims_usd, 4),
            "adjudication": round(adjudicate_usd, 4),
            "remedy": round(remedy_usd, 4),
        },
        "first_draft_usd": round(first_draft, 4),
        "later_draft_usd": round(later_draft, 4),
        "total_usd": round(total, 4),
        "manual_baseline_usd": round(manual_total, 2),
        "savings_usd": round(manual_total - total, 2),
        "times_cheaper": round(manual_total / total, 1) if total > 0 else None,
        "assumptions": _DENSITY,
        "caveat": (
            "An estimate from measured subject density, not a quote. A script's "
            "real cost depends on how many real people it names and how much of "
            "the record already sits in the cache."
        ),
    }
