"""Every Gemini call carries a deadline.

There was none. Two live runs of a two page script hung on an open Vertex
socket with no error and no retry — fifty five minutes on the first before it
was killed — because seven modules each built their own `genai.Client` from the
same three settings and not one of them set a timeout. Every other outbound
call in this system has a deadline; the most numerous calls had none.

The regression this guards is not "the timeout is 180 seconds". It is that a
new stage can be added tomorrow that builds its own client and reintroduces the
hang, so the test asserts that nobody constructs one directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from truestory.config import settings
from truestory.providers import model_fallback

SRC = Path(__file__).resolve().parents[1] / "src" / "truestory"


def test_the_factory_sets_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The factory passes a deadline through to the SDK.

    The kwargs are captured rather than a real client being built, because
    constructing one resolves credentials and CI has none — an earlier version
    of this test passed only on a machine with a populated `.env`.
    """
    from google import genai

    captured: dict[str, object] = {}

    def fake_client(**kwargs: object) -> str:
        captured.update(kwargs)
        return "client"

    monkeypatch.setattr(genai, "Client", fake_client)

    assert model_fallback.genai_client() == "client"

    http_options = captured.get("http_options")
    assert http_options is not None, "the shared client was built without http_options"
    # The SDK takes milliseconds.
    assert http_options.timeout == settings.model_timeout_seconds * 1000


def test_nobody_constructs_a_client_around_the_factory() -> None:
    """`genai.Client(...)` appears in exactly one place: the factory itself."""
    offenders: list[str] = []

    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "Client"
                and isinstance(func.value, ast.Name)
                and func.value.id == "genai"
                and path.name != "model_fallback.py"
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")

    assert not offenders, (
        "these build a Gemini client directly and so bypass the deadline; "
        f"use model_fallback.genai_client(): {offenders}"
    )
