"""Command line entry point.

    truestory run demo/screenplay/the_long_shadow.fountain --report
    truestory explain REAL_PERSON_DEPICTED
    truestory warm-cache demo/screenplay/the_long_shadow.fountain
    truestory doctor

Everything defaults to mock mode, so a fresh clone runs the whole pipeline and
produces a real report with no credentials, no network, and no spend.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from truestory import __version__
from truestory.agents.pipeline import ProjectConfig, TrueStoryPipeline
from truestory.config import Mode, settings
from truestory.models.enums import Verdict
from truestory.observability import init as init_observability

app = typer.Typer(
    name="truestory",
    help="A fact and rights engine for based on a true story productions.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


# =============================================================================
# run
# =============================================================================


@app.command()
def run(
    script: Path = typer.Argument(..., help="Path to a fdx, fountain, pdf or txt draft"),
    project: str = typer.Option("demo", help="Project identifier"),
    draft: str = typer.Option("v1", help="Draft version label"),
    territories: str = typer.Option("US", help="Comma separated distribution territories"),
    budget: float = typer.Option(None, help="Per script ceiling in US dollars"),
    report: bool = typer.Option(False, "--report", help="Write artifacts to disk"),
    out: Path = typer.Option(Path("artifacts"), help="Artifact output directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the eight stage pipeline over a draft."""
    init_observability()

    if not script.exists():
        console.print(f"[red]script not found:[/red] {script}")
        raise typer.Exit(1)

    config = ProjectConfig(
        project_id=project,
        title=script.stem.replace("_", " ").title(),
        distribution_territories=[t.strip() for t in territories.split(",") if t.strip()],
        budget_usd=budget,
    )

    console.print(
        Panel.fit(
            f"[bold]TRUE STORY[/bold] v{__version__}\n"
            f"script      {script.name}\n"
            f"project     {project}\n"
            f"mode        {settings.mode}\n"
            f"budget      ${budget or settings.budget_per_script_usd:.2f}\n"
            f"territories {', '.join(config.jurisdictions())}",
            title="run",
        )
    )

    state = asyncio.run(_run_async(config, script, draft, verbose))

    if state.error:
        console.print(f"[red]run failed:[/red] {state.error}")
        raise typer.Exit(1)

    _print_summary(state)

    if report:
        _write_artifacts(state, out)


async def _run_async(config: ProjectConfig, script: Path, draft: str, verbose: bool) -> Any:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=not verbose,
    ) as progress:
        task = progress.add_task("starting", total=None)

        async def on_progress(payload: dict[str, Any]) -> None:
            event = payload.get("event", "")
            if event == "stage":
                progress.update(task, description=f"{payload.get('stage')} ...")
            elif event == "ingest_complete":
                framing = (
                    " [yellow]TRUE STORY ASSERTED[/yellow]"
                    if payload.get("truth_claim_framing")
                    else ""
                )
                progress.console.print(
                    f"  ingest    {payload['scenes']} scenes, {payload['spans']} spans{framing}"
                )
            elif event == "claims_extracted":
                progress.console.print(
                    f"  claims    {payload['claims']} extracted, "
                    f"{payload['opinions']} opinions filtered"
                )
            elif event == "ledger_built":
                progress.console.print(
                    f"  ledger    {payload['elements']} elements "
                    f"({payload['reduction']}x reduction)"
                )
            elif event == "plan_ready":
                progress.console.print(
                    f"  routing   {payload['researched_subjects']} subjects, "
                    f"projected [green]${payload['projected_cost_usd']:.2f}[/green]"
                )
            elif event == "adjudication_complete":
                progress.console.print(
                    f"  verdicts  [green]{payload['green']} green[/green] · "
                    f"[yellow]{payload['amber']} amber[/yellow] · "
                    f"[red]{payload['red']} red[/red] · "
                    f"{payload['grey']} grey · {payload['counsel']} counsel"
                )
            elif event == "remedies_ready":
                progress.console.print(
                    f"  remedies  {payload['verified']} verified of {payload['proposed']} proposed"
                )
            elif verbose:
                progress.console.print(f"  [dim]{event}[/dim]")

        pipeline = TrueStoryPipeline(config, on_progress=on_progress)
        try:
            return await pipeline.run(script, draft_version=draft)
        finally:
            await pipeline.aclose()


def _print_summary(state: Any) -> None:
    summary = state.summary
    if summary is None:
        return

    table = Table(title="run summary", show_header=False, box=None)
    table.add_column(style="dim", width=24)
    table.add_column()

    table.add_row("script", f"{summary.script_title} ({summary.draft_version})")
    table.add_row("truth claim framing", "YES" if summary.truth_claim_framing else "no")
    table.add_row("research subjects", str(summary.research_subjects))
    table.add_row(
        "verdicts",
        f"[green]{summary.green} verified[/green] · "
        f"[yellow]{summary.amber} unsupported[/yellow] · "
        f"[red]{summary.red} contradicted[/red] · {summary.grey} opinion",
    )
    table.add_row("counsel items", str(summary.counsel_items))
    table.add_row("remedies verified", str(summary.remedies_verified))
    table.add_row("monitors opened", str(summary.monitors_created))
    # Research spend and model spend, then the total, because printing only
    # the first understated a run by 69x on measurement — $0.0100 shown against
    # $0.6873 actually spent — and cost per script is a number this project
    # quotes publicly.
    table.add_row(
        "cost",
        f"${summary.total_cost_usd:.4f}  "
        f"[dim]research ${summary.cost_usd:.4f} + model ${summary.model_cost_usd:.4f}[/dim]",
    )
    table.add_row("elapsed", f"{summary.duration_seconds:.1f}s")
    table.add_row("cache hit rate", f"{summary.cache_hit_rate:.0%}")

    console.print(table)

    for warning in summary.coverage_warnings:
        console.print(f"[yellow]coverage:[/yellow] {warning}")

    if settings.mode is Mode.MOCK:
        console.print(
            "\n[dim]Mock mode. Every finding above was synthesised offline and carries "
            "no research value. Set TRUESTORY_MODE=live for real verification.[/dim]"
        )

    reds = [c for c in state.claims if c.verdict is Verdict.CONTRADICTED]
    if reds:
        console.print("\n[red bold]contradicted claims[/red bold]")
        for claim in reds[:8]:
            page = claim.first_occurrence.page_eighths if claim.first_occurrence else "?"
            console.print(f"  p{page:>6}  {claim.subject_name}: {claim.claim_text[:80]}")


def _write_artifacts(state: Any, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    report = state.artifacts.get("report", {})

    written: list[Path] = []
    for name, payload in [
        ("overlay.json", report.get("overlay")),
        ("claim_register.json", report.get("claim_register")),
        ("eo_report.json", report.get("eo_report")),
        ("monitor_manifest.json", report.get("monitor_manifest")),
        ("summary.json", state.summary.to_dict() if state.summary else {}),
    ]:
        if payload is None:
            continue
        path = out / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        written.append(path)

    csv_text = report.get("clearance_log_csv")
    if csv_text:
        path = out / "clearance_log.csv"
        path.write_text(csv_text, encoding="utf-8")
        written.append(path)

    try:
        from truestory.reports.eo_report import render_pdf

        path = out / "eo_clearance_report.pdf"
        path.write_bytes(render_pdf(report.get("eo_report", {})))
        written.append(path)
    except Exception as exc:
        console.print(f"[yellow]pdf rendering skipped:[/yellow] {exc}")

    console.print(f"\nwrote {len(written)} artifacts to {out}/")
    for path in written:
        console.print(f"  [dim]{path}[/dim]")


# =============================================================================
# utilities
# =============================================================================


@app.command()
def explain(
    subject_type: str = typer.Argument(..., help="Element type or 'claim'"),
    occurrences: int = typer.Option(1, help="Occurrence count, some rules depend on it"),
    polarity: str = typer.Option("neutral"),
    alive: bool = typer.Option(False, help="Subject is living"),
    framing: bool = typer.Option(False, help="Project asserts a true story"),
) -> None:
    """Explain why a subject would be routed the way it is."""
    from truestory.agents.router import RiskRouter

    router = RiskRouter()
    subject = (
        {"kind": "claim", "polarity": polarity, "subject_alive": alive}
        if subject_type.lower() == "claim"
        else {"type": subject_type.upper(), "occurrence_count": occurrences}
    )

    decision = router.policy.match(subject)
    if framing:
        decision = router.policy.apply_project_escalations(
            decision, subject, {"truth_claim_framing": True}
        )

    console.print(Panel(router.explain(subject), title=f"routing: {subject_type}"))
    console.print(f"estimated cost: ${decision.estimated_cost_usd:.4f}")
    if decision.escalated_by:
        console.print(f"[yellow]escalated by:[/yellow] {', '.join(decision.escalated_by)}")


@app.command(name="warm-cache")
def warm_cache(
    script: Path = typer.Argument(...),
    project: str = typer.Option("demo"),
) -> None:
    """One paid live run that warms the cache. Every later run is free.

    This is how the demo is recorded. Warm once, then every take costs nothing
    and returns byte identical results, which removes the single largest source
    of demo day fragility.
    """
    if settings.mode is not Mode.LIVE:
        console.print(
            "[yellow]warm-cache needs TRUESTORY_MODE=live.[/yellow] This run costs real money."
        )
        raise typer.Exit(1)

    console.print("[bold]warming the cache with one live run[/bold]")
    config = ProjectConfig(project_id=project, title=script.stem)
    state = asyncio.run(_run_async(config, script, "cache-warm", False))

    if state.summary:
        console.print(
            f"cache warmed. This run cost ${state.summary.total_cost_usd:.4f}. "
            "Subsequent runs in cached mode are free and deterministic."
        )


@app.command()
def doctor(
    models: bool = typer.Option(
        False, "--models", help="Also probe every configured Gemini model with one live call"
    ),
) -> None:
    """Check the environment and report exactly what is still unwired."""
    from truestory.policy import load_routing, load_rubric

    table = Table(title="environment", show_header=True)
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail", style="dim")

    def row(name: str, ok: bool, detail: str = "") -> None:
        table.add_row(name, "[green]ok[/green]" if ok else "[red]missing[/red]", detail)

    row("mode", True, str(settings.mode))
    row(
        "parallel api key",
        bool(settings.parallel_api_key) and not settings.parallel_api_key.startswith("PLACEHOLDER"),
        "README build status, item 1",
    )
    row(
        "google cloud project",
        bool(settings.gcp_project) and not settings.gcp_project.startswith("PLACEHOLDER"),
        "README build status, item 2",
    )
    row(
        "webhook secret",
        bool(settings.parallel_webhook_secret)
        and not settings.parallel_webhook_secret.startswith("PLACEHOLDER"),
        "README build status, item 3",
    )
    row("agent engine", bool(settings.agent_engine_resource), "README build status, item 6")

    try:
        policy = load_routing()
        problems = policy.validate()
        row(
            "routing policy", not problems, f"{len(policy.rules)} rules, {len(problems)} advisories"
        )
    except Exception as exc:
        row("routing policy", False, str(exc))

    try:
        load_rubric()
        row("rubric", True)
    except Exception as exc:
        row("rubric", False, str(exc))

    # Everything above asks whether a value is present. Nothing above asked
    # whether it works, and the difference is not academic: this table printed
    # seven green rows on a machine where the credentials path pointed at
    # another operating system, the configured region served none of the
    # configured models, and the research account was out of credit. Three
    # independent live blockers, no red rows, and the first symptom was a run
    # that hung. In live mode the checks that can be settled cheaply are
    # settled here instead.
    if settings.mode is Mode.LIVE:
        creds = settings.google_credentials
        if creds:
            row(
                "credentials file",
                Path(creds).exists(),
                creds if Path(creds).exists() else f"{creds} does not exist",
            )
        else:
            row(
                "credentials file",
                True,
                "unset, falling back to application default credentials",
            )

        row(
            "vertex region",
            settings.gcp_location == "global",
            f"{settings.gcp_location}"
            + (
                "" if settings.gcp_location == "global" else " serves no Gemini 3 model, use global"
            ),
        )

        ok, detail = _probe_parallel_credit()
        row("parallel credit", ok, detail)

    console.print(table)
    console.print(
        "\n[dim]Mock mode needs none of the above. Every red row is a live mode "
        "prerequisite and each maps to a numbered item in the README build status.[/dim]"
    )

    if models:
        _probe_models()


def _probe_parallel_credit() -> tuple[bool, str]:
    """One cheap call that distinguishes a funded account from an empty one.

    A drained account answers every research request with HTTP 402, and the
    pipeline turns that into "no record found either way" on every subject —
    a report that reads exactly like a clean one. Finding that out before the
    run rather than after it is the whole point of this command.
    """
    import httpx

    try:
        resp = httpx.post(
            f"{settings.parallel_api_base.rstrip('/')}/v1/tasks/runs",
            headers={"x-api-key": settings.parallel_api_key},
            json={"input": "ping", "processor": "lite"},
            timeout=20.0,
        )
    except Exception as exc:
        return False, f"could not reach Parallel: {type(exc).__name__}"

    if resp.status_code == 402:
        return False, "insufficient credit, top up before any live run"
    if resp.status_code in (401, 403):
        return False, f"key rejected (HTTP {resp.status_code})"
    if resp.status_code >= 400:
        return False, f"HTTP {resp.status_code}"
    return True, "account is funded"


def _probe_models() -> None:
    """One real call per configured model, so a bad name is found here.

    A model identifier is configuration, and the failure mode is that it looks
    correct and is not served in this project or region. Without this the first
    place anyone learns that is the middle of a run, and the newest models are
    exactly the ones most likely to be unavailable somewhere.
    """
    from truestory.providers import model_fallback

    table = Table(title="models", show_header=True)
    table.add_column("decision point")
    table.add_column("model")
    table.add_column("status")
    table.add_column("detail", style="dim")

    try:
        from truestory.providers import model_fallback

        client = model_fallback.genai_client()
    except Exception as exc:
        console.print(f"\n[red]could not build a Gemini client:[/red] {exc}")
        return

    probed: dict[str, tuple[str, str]] = {}
    for point, model in settings.models_in_use.items():
        if model in probed:
            status, detail = probed[model]
        else:
            try:
                client.models.generate_content(model=model, contents="Reply with: ok")
                status, detail = "[green]available[/green]", ""
            except Exception as exc:
                if model_fallback.is_model_unavailable(exc):
                    chain = model_fallback.chain_for(model)[1:]
                    status = "[yellow]unavailable[/yellow]"
                    detail = f"would fall back to {chain[0] if chain else 'nothing'}"
                else:
                    status, detail = "[red]error[/red]", f"{type(exc).__name__}: {exc}"[:70]
            probed[model] = (status, detail)
        table.add_row(point, model, status, detail)

    console.print()
    console.print(table)
    console.print(
        "\n[dim]An unavailable model degrades through the fallback chain rather than "
        "ending a run, so a yellow row costs quality and not the demo. A red row is a "
        "credentials or quota problem and is not about the model.[/dim]"
    )


@app.command()
def version() -> None:
    console.print(f"truestory {__version__}")


if __name__ == "__main__":
    app()
