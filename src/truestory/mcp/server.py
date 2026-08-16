"""clearance-tool-server. The MCP boundary, deployed on Cloud Run.

Every tool returns the same uniform Evidence envelope, which is what lets the
Adjudicator treat a music rights answer and a claim verification answer with
the same post checks and the same confidence gates.

On Parallel's own hosted MCP servers: they are OAuth based and built for
interactive clients such as an IDE assistant, which makes them excellent for
developer exploration and wrong for a two hundred subject fan out under budget
governance. This server uses the Parallel SDK directly inside our own process,
where retries, idempotency keys, concurrency caps and the budget reserve are
ours to control.

Run locally:

    python -m truestory.mcp.server --port 8081
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
from typing import Any

from truestory.config import settings
from truestory.mcp.tools import TOOL_MANIFEST, ClearanceTools
from truestory.providers import BudgetGovernor, ProviderRegistry

log = logging.getLogger("truestory.mcp")


# =============================================================================
# tool schemas, advertised to any MCP client
# =============================================================================

_SCHEMAS: dict[str, dict[str, Any]] = {
    "verify_factual_claim": {
        "type": "object",
        "required": ["subject_id", "subject", "claim"],
        "properties": {
            "subject_id": {"type": "string", "description": "Stable claim identifier."},
            "subject": {
                "type": "string",
                "description": "The real person or event the claim is about.",
            },
            "claim": {
                "type": "string",
                "description": "One atomic assertion. Decompose compound claims before calling.",
            },
            "polarity": {"type": "string", "enum": ["positive", "neutral", "negative"]},
            "subject_alive": {"type": ["boolean", "null"]},
            "jurisdiction": {"type": ["string", "null"]},
        },
    },
    "attribute_quote": {
        "type": "object",
        "required": ["subject_id", "quote", "purported_speaker"],
        "properties": {
            "subject_id": {"type": "string"},
            "quote": {"type": "string"},
            "purported_speaker": {"type": "string"},
            "era": {"type": "string"},
        },
    },
    "check_person_collision": {
        "type": "object",
        "required": ["subject_id", "name"],
        "properties": {
            "subject_id": {"type": "string"},
            "name": {"type": "string"},
            "profession": {"type": "string"},
            "city": {"type": "string"},
            "occurrence_count": {"type": "integer"},
        },
    },
    "check_person_identifiability": {
        "type": "object",
        "required": ["subject_id", "attributes"],
        "properties": {
            "subject_id": {"type": "string"},
            "attributes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Profession, city, physical description, relationship. No name required.",
            },
        },
    },
    "check_entity_registration": {
        "type": "object",
        "required": ["subject_id", "name", "jurisdiction"],
        "properties": {
            "subject_id": {"type": "string"},
            "name": {"type": "string"},
            "jurisdiction": {"type": "string"},
            "classes": {"type": "string"},
        },
    },
    "check_trademark_status": {
        "type": "object",
        "required": ["subject_id", "mark"],
        "properties": {
            "subject_id": {"type": "string"},
            "mark": {"type": "string"},
            "classes": {"type": "string"},
            "territories": {"type": "string"},
            "depiction": {"type": "string"},
        },
    },
    "check_entity": {
        "type": "object",
        "required": ["subject_id", "name"],
        "properties": {
            "subject_id": {"type": "string"},
            "name": {"type": "string"},
            "kind": {"type": "string"},
            "jurisdiction": {"type": "string"},
            "depiction": {"type": "string"},
        },
    },
    "check_music_rights": {
        "type": "object",
        "required": ["subject_id", "title"],
        "properties": {
            "subject_id": {"type": "string"},
            "title": {"type": "string"},
            "artist": {"type": "string"},
            "year": {"type": "string"},
        },
    },
    "check_publicity_rights": {
        "type": "object",
        "required": ["subject_id", "person"],
        "properties": {
            "subject_id": {"type": "string"},
            "person": {"type": "string"},
            "domicile": {"type": "string"},
        },
    },
    "check_visual_copyright": {
        "type": "object",
        "required": ["subject_id", "description"],
        "properties": {
            "subject_id": {"type": "string"},
            "description": {"type": "string"},
            "creator_hint": {"type": "string"},
            "appearance": {"type": "string"},
        },
    },
    "check_public_domain": {
        "type": "object",
        "required": ["subject_id", "work"],
        "properties": {
            "subject_id": {"type": "string"},
            "work": {"type": "string"},
            "jurisdiction": {"type": "string"},
        },
    },
    "enumerate_matching_entities": {
        "type": "object",
        "required": ["subject_id", "pattern"],
        "properties": {
            "subject_id": {"type": "string"},
            "pattern": {"type": "string"},
            "jurisdiction": {"type": "string"},
        },
    },
    "capture_evidence_page": {
        "type": "object",
        "required": ["subject_id", "url"],
        "properties": {
            "subject_id": {"type": "string"},
            "url": {"type": "string", "format": "uri"},
        },
    },
    "watch_subject": {
        "type": "object",
        "required": ["subject_id", "query"],
        "properties": {
            "subject_id": {"type": "string"},
            "query": {"type": "string"},
            "cadence": {"type": "string", "enum": ["daily", "weekly", "monthly", "quarterly"]},
            "reason": {"type": "string"},
        },
    },
}


# =============================================================================
# server
# =============================================================================


class ClearanceToolServer:
    """Wraps ClearanceTools as an MCP server and as a plain HTTP service.

    The plain HTTP surface exists because the ADK swarm calls these tools
    several hundred times per run inside our own trust boundary, where the MCP
    session handshake buys nothing. Both surfaces dispatch into the identical
    method, so there is one code path and one set of tests.
    """

    def __init__(self, tools: ClearanceTools | None = None) -> None:
        self.registry = ProviderRegistry(budget=BudgetGovernor())
        self.tools = tools or ClearanceTools(self.registry)

    def manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": description,
                "inputSchema": _SCHEMAS.get(name, {"type": "object"}),
            }
            for name, description in TOOL_MANIFEST.items()
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one tool call. Never raises to the transport."""
        method = getattr(self.tools, name, None)
        if method is None or not callable(method):
            return {"error": f"unknown tool: {name}", "available": list(TOOL_MANIFEST)}

        try:
            result = method(**arguments)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, dict) else {"results": result}
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}
        except Exception as exc:
            log.exception("tool %s failed", name)
            return {"error": f"{type(exc).__name__}: {exc}", "tool": name}

    def stats(self) -> dict[str, Any]:
        return self.registry.stats()

    async def aclose(self) -> None:
        await self.registry.aclose()


# =============================================================================
# mcp transport
# =============================================================================


def build_mcp_server(server: ClearanceToolServer) -> Any:
    """Construct the MCP server object with every domain tool registered."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    mcp_server = Server("clearance-tool-server")

    @mcp_server.list_tools()  # type: ignore[misc]
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=entry["name"],
                description=entry["description"],
                inputSchema=entry["inputSchema"],
            )
            for entry in server.manifest()
        ]

    @mcp_server.call_tool()  # type: ignore[misc]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        result = await server.call(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    return mcp_server


# =============================================================================
# http transport
# =============================================================================


def build_http_app(server: ClearanceToolServer) -> Any:
    """A plain FastAPI surface over the same tools, used by the swarm."""
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(
        title="clearance-tool-server",
        description="Domain clearance tools. Uniform Evidence envelope out.",
        version="0.1.0",
    )

    class ToolCall(BaseModel):
        name: str
        arguments: dict[str, Any] = {}

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "mode": str(settings.mode), "tools": len(TOOL_MANIFEST)}

    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        return {"tools": server.manifest()}

    @app.post("/tools/call")
    async def call_tool(body: ToolCall) -> dict[str, Any]:
        return await server.call(body.name, body.arguments)

    @app.get("/stats")
    async def stats() -> dict[str, Any]:
        return server.stats()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await server.aclose()

    return app


# =============================================================================
# entrypoint
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="TRUE STORY clearance tool server")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default="http",
        help="http for the swarm and Cloud Run, stdio for an interactive MCP client",
    )
    args = parser.parse_args()

    logging.basicConfig(level=settings.log_level.upper())
    server = ClearanceToolServer()

    if args.transport == "stdio":
        from mcp.server.stdio import stdio_server

        async def _run() -> None:
            mcp_server = build_mcp_server(server)
            async with stdio_server() as (read, write):
                await mcp_server.run(read, write, mcp_server.create_initialization_options())

        asyncio.run(_run())
        return

    import uvicorn

    log.info("clearance-tool-server on %s:%s, mode=%s", args.host, args.port, settings.mode)
    uvicorn.run(build_http_app(server), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
