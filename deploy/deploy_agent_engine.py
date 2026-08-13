#!/usr/bin/env python
"""Deploy the ADK pipeline to Vertex AI Agent Engine.

    python deploy/deploy_agent_engine.py --project YOUR_PROJECT --region us-central1

The deployed topology is the same eight stages that run locally. There are not
two code paths: `build_adk_pipeline` wraps the identical stage functions in ADK
workflow agents, so what a judge sees running in the cloud is what the tests
exercise offline.

Minimum instances are set deliberately. A cold start on the one URL a judge
opens is an avoidable loss, and the cost of keeping one instance warm through a
judging window is trivial.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy TRUE STORY to Agent Engine")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--staging-bucket", default=None)
    parser.add_argument("--display-name", default="TRUE STORY pipeline")
    parser.add_argument("--min-instances", type=int, default=1)
    parser.add_argument(
        "--dry-run", action="store_true", help="Build the agent tree without deploying"
    )
    args = parser.parse_args()

    staging = args.staging_bucket or f"gs://{args.project}-truestory-staging"

    from truestory.agents.pipeline import ProjectConfig, build_adk_pipeline

    print(f"building the agent tree for {args.project}")
    root_agent = build_adk_pipeline(ProjectConfig(project_id="default"))

    print(f"  root: {root_agent.name}")
    for stage in getattr(root_agent, "sub_agents", []):
        print(f"    {stage.name} ({type(stage).__name__})")

    if args.dry_run:
        print("\ndry run, nothing deployed")
        return 0

    import vertexai
    from vertexai import agent_engines
    from vertexai.preview import reasoning_engines

    vertexai.init(project=args.project, location=args.region, staging_bucket=staging)

    print(f"\ndeploying to {args.region}, staging at {staging}")

    app = reasoning_engines.AdkApp(agent=root_agent, enable_tracing=True)

    remote = agent_engines.create(
        agent_engine=app,
        display_name=args.display_name,
        description=(
            "A fact and rights engine for based on a true story productions. "
            "Eight stages, four language model decision points, evidence "
            "required for every verdict."
        ),
        requirements=[
            "google-cloud-aiplatform[agent_engines,adk]>=1.101.0",
            "google-genai>=1.0.0",
            "parallel-web>=0.1.0",
            "httpx>=0.27.0",
            "pydantic>=2.9.0",
            "pydantic-settings>=2.5.0",
            "pyyaml>=6.0.2",
            "jsonschema>=4.23.0",
            "jinja2>=3.1.4",
            "reportlab>=4.2.0",
            "pypdf>=5.0.0",
        ],
        # Policy and schemas travel with the agent. They are read at runtime,
        # so a routing change is a redeploy rather than a code change.
        extra_packages=[
            str(REPO_ROOT / "src" / "truestory"),
            str(REPO_ROOT / "policy"),
            str(REPO_ROOT / "schemas"),
        ],
        env_vars={
            "TRUESTORY_MODE": "live",
            "TRUESTORY_ENV": "agent-engine",
            "GOOGLE_CLOUD_PROJECT": args.project,
            "GOOGLE_CLOUD_LOCATION": args.region,
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
        },
        min_instances=args.min_instances,
    )

    print("\ndeployed")
    print(f"  resource name: {remote.resource_name}")
    print("\nadd this to .env:")
    print(f"  AGENT_ENGINE_RESOURCE_NAME={remote.resource_name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
