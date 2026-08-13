"""The tool boundary.

Agents see verbs from the clearance trade, not vendor endpoints. That is the
whole design of this package, and it buys vendor swappability, better tool
selection by the model, and a clean test seam in one move.
"""

from truestory.mcp.server import ClearanceToolServer, build_http_app, build_mcp_server
from truestory.mcp.tools import TOOL_MANIFEST, ClearanceTools

__all__ = [
    "TOOL_MANIFEST",
    "ClearanceToolServer",
    "ClearanceTools",
    "build_http_app",
    "build_mcp_server",
]
