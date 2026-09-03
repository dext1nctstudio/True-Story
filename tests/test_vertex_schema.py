"""Every shipped schema must survive conversion to the Vertex dialect.

Two stages of this system have already been silently disabled by a schema
construct Vertex rejects before the request leaves the machine:

  * adjudication, on every claim, because `subject_alive` was the union
    `["boolean", "null"]` — recorded in README §14.1;
  * the grounded fallback's structuring step, on every call, first with "11
    validation errors" from `$schema`/`additionalProperties`, then with 6 from
    `$ref`/`$defs`, then with 3 from enums containing `null`.

Each was found by a person noticing an odd result, not by a test. The point of
this file is that the next one is found here instead.

The important property is not that conversion succeeds. It is that conversion
does not quietly change what the schema permits: an enum that gained or lost a
member would let a verdict through that the pipeline has no branch for.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from truestory.providers.vertex_schema import to_vertex_schema

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_FILES = sorted(SCHEMA_DIR.glob("*.json"))


def test_there_are_schemas_to_check():
    """A glob that silently matches nothing would make every test below vacuous."""
    assert len(SCHEMA_FILES) >= 11, (
        f"expected the eleven shipped schemas, found {len(SCHEMA_FILES)}"
    )


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_every_shipped_schema_is_accepted_by_vertex(path):
    """The whole point. All eleven, every time, not the one being worked on."""
    types = pytest.importorskip("google.genai.types")
    converted = to_vertex_schema(json.loads(path.read_text(encoding="utf-8")))
    types.Schema(**converted)  # raises on any unsupported construct


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_conversion_does_not_mutate_the_original(path):
    """The same schema object goes to Parallel on the primary path.

    Parallel takes strict JSON Schema and must keep receiving it, so converting
    for Vertex must not reach back and loosen the primary request.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    before = json.dumps(raw, sort_keys=True)
    to_vertex_schema(raw)
    assert json.dumps(raw, sort_keys=True) == before


# =============================================================================
# the specific constructs, each tied to the failure it caused
# =============================================================================


def test_union_with_null_becomes_nullable():
    """The construct that disabled adjudication on every claim."""
    out = to_vertex_schema(
        {"type": "object", "properties": {"alive": {"type": ["boolean", "null"]}}}
    )
    field = out["properties"]["alive"]
    assert field["type"] == "boolean"
    assert field["nullable"] is True


def test_schema_and_additional_properties_are_dropped():
    """`additionalProperties: false` alone fails the request. Every schema sets it."""
    out = to_vertex_schema(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://truestory.dev/x.json",
            "additionalProperties": False,
            "type": "object",
            "properties": {"a": {"type": "string"}},
        }
    )
    assert "$schema" not in out
    assert "$id" not in out
    assert "additionalProperties" not in out
    assert out["properties"]["a"]["type"] == "string"


def test_refs_are_inlined():
    """`claim_verification_v1` refers to one shared `fact` from two places."""
    out = to_vertex_schema(
        {
            "type": "object",
            "$defs": {"fact": {"type": "object", "properties": {"url": {"type": "string"}}}},
            "properties": {
                "supporting": {"type": "array", "items": {"$ref": "#/$defs/fact"}},
                "contradicting": {"type": "array", "items": {"$ref": "#/$defs/fact"}},
            },
        }
    )
    assert "$defs" not in out
    for side in ("supporting", "contradicting"):
        item = out["properties"][side]["items"]
        assert "$ref" not in item
        assert item["properties"]["url"]["type"] == "string"


def test_a_recursive_ref_terminates():
    """A self referential definition cannot be expressed without `$ref` at all.

    It must be truncated rather than expanded until the process dies.
    """
    out = to_vertex_schema(
        {
            "type": "object",
            "$defs": {
                "node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/node"}}}
            },
            "properties": {"root": {"$ref": "#/$defs/node"}},
        }
    )
    assert out["properties"]["root"]["type"] == "object"


def test_an_unresolvable_ref_degrades_rather_than_raising():
    out = to_vertex_schema({"type": "object", "properties": {"x": {"$ref": "#/$defs/missing"}}})
    assert out["properties"]["x"] == {"type": "object"}


# =============================================================================
# enums, where a silent change would be worst
# =============================================================================


def test_null_in_an_enum_becomes_nullable_and_keeps_every_other_member():
    """Eight of the eleven schemas declare optionality this way."""
    out = to_vertex_schema({"type": "string", "enum": ["primary", "secondary", "tertiary", None]})
    assert out["enum"] == ["primary", "secondary", "tertiary"]
    assert out["nullable"] is True


@pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
def test_no_enum_member_is_invented_or_lost(path):
    """The property that actually matters.

    A verdict enum that gained a member would let the model return a value the
    pipeline has no branch for; one that lost a member would forbid a legitimate
    answer. Null is the only member permitted to move, and it moves to
    `nullable`.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    before = _enums(raw)
    after = _enums(to_vertex_schema(raw))

    for key, original in before.items():
        if key not in after:
            continue  # the property was dropped wholesale, checked elsewhere
        expected = [v if isinstance(v, str) else str(v) for v in original if v is not None]
        assert after[key] == expected, f"{path.name}:{key} enum changed"


def test_every_enum_member_survives_as_a_string():
    out = to_vertex_schema({"type": "string", "enum": ["a", 2, True, None]})
    assert out["enum"] == ["a", "2", "True"]
    assert out["nullable"] is True


def _enums(node, trail="") -> dict[str, list]:
    """Every enum in the tree, keyed by its path, so two can be compared."""
    found: dict[str, list] = {}
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            found[trail] = node["enum"]
        for key, value in node.items():
            if key in {"properties", "$defs"} and isinstance(value, dict):
                for name, sub in value.items():
                    found.update(_enums(sub, f"{trail}/{name}"))
            elif key == "items":
                found.update(_enums(value, f"{trail}[]"))
    return found


# =============================================================================
# required
# =============================================================================


def test_required_never_names_a_dropped_property():
    """A required entry pointing at nothing is itself a validation error."""
    out = to_vertex_schema(
        {
            "type": "object",
            "required": ["kept", "dropped"],
            "properties": {"kept": {"type": "string"}},
        }
    )
    assert out["required"] == ["kept"]


def test_required_is_removed_when_nothing_survives():
    out = to_vertex_schema({"type": "object", "required": ["gone"], "properties": {}})
    assert "required" not in out
