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

app = FastAPI(
    title="TRUE STORY",
    description=(
        "A fact and rights engine for based on a true story productions. "
        "Decision support for a clearance attorney. Not legal advice."
    ),
    version="0.1.0",
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


# =============================================================================
# health
# =============================================================================


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": str(settings.mode),
        "env": settings.env_name,
        "version": app.version,
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
    was effectively lost. `_RUNS` is in memory only, so this list is also
    reset by every API restart, same as everything else in it.
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
    rows.sort(key=lambda r: r["started_at"], reverse=True)
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
    _RUNS[run_id] = RunState(run_id=run_id, project_id=config.project_id)

    async def on_progress(payload: dict[str, Any]) -> None:
        if queue is not None:
            await queue.put(payload)

    def on_state(state: Any) -> None:
        # Swap the placeholder for the real state as soon as ingest lands, so
        # the overlay, claims and counters are readable while the run is still
        # going rather than only after it ends.
        _RUNS[run_id] = state

    pipeline = TrueStoryPipeline(config, on_progress=on_progress)
    try:
        state = await pipeline.run(
            source,
            draft_version=draft_version,
            parent_run_id=parent_run_id,
            run_id=run_id,
            on_state=on_state,
        )
        _RUNS[run_id] = state
        get_store().create_run(config.project_id, run_id, state.to_dict())
    except Exception as exc:
        log.exception("run %s failed", run_id)
        if queue is not None:
            await queue.put({"event": "run_failed", "error": str(exc)})
    finally:
        if queue is not None:
            await queue.put({"event": "stream_end"})
        if isinstance(source, Path):
            source.unlink(missing_ok=True)


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    state = _RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="run not found")
    _require_project(principal, state.project_id)
    return apply_view(state.to_dict(), principal)


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
    state = _state_or_404(run_id, principal)
    if not can(principal, "overlay"):
        raise HTTPException(status_code=403, detail="role may not view the overlay")
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
    state = _state_or_404(run_id, principal)
    remedies = [r.to_dict() for r in state.remedies]
    return apply_view({"remedies": remedies, "total": len(remedies)}, principal)


@app.get("/v1/runs/{run_id}/elements")
async def get_elements(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    state = _state_or_404(run_id, principal)
    elements = [
        e.to_dict(
            include_evidence=principal.may_see_evidence(),
            unmasked=can(principal, "unmasked"),
        )
        for e in state.elements
    ]
    return apply_view({"elements": elements, "total": len(elements)}, principal)


@app.get("/v1/runs/{run_id}/register")
async def get_claim_register(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    """Per person claim table, including the amber density meter."""
    state = _state_or_404(run_id, principal)
    return apply_view(state.artifacts.get("report", {}).get("claim_register", {}), principal)


@app.get("/v1/runs/{run_id}/report")
async def get_eo_report(
    run_id: str, principal: Principal = Depends(current_principal)
) -> dict[str, Any]:
    state = _state_or_404(run_id, principal)
    if not can(principal, "reports"):
        raise HTTPException(status_code=403, detail="role may not view reports")
    return apply_view(state.artifacts.get("report", {}).get("eo_report", {}), principal)


@app.get("/v1/runs/{run_id}/clearance_log.csv", response_class=PlainTextResponse)
async def get_clearance_log(
    run_id: str, principal: Principal = Depends(current_principal)
) -> Response:
    """The insurer checklist. Every visible piece of IP and its status."""
    state = _state_or_404(run_id, principal)
    if not can(principal, "reports"):
        raise HTTPException(status_code=403, detail="role may not view reports")
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
    state = _state_or_404(run_id, principal)
    if not can(principal, "reports"):
        raise HTTPException(status_code=403, detail="role may not view reports")

    from truestory.reports.eo_report import render_pdf

    pdf = render_pdf(
        state.artifacts.get("report", {}).get("eo_report", {}),
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
