"""Convert a JSON Schema into the subset Vertex controlled generation accepts.

The eleven schemas in `schemas/` are written as strict JSON Schema 2020-12
because that is what Parallel's Task API takes, and Parallel is the primary
research path. Vertex's controlled generation takes a narrower dialect, and it
does not degrade politely when handed something outside it: the SDK raises
before the request leaves the machine, with a wall of pydantic validation
errors naming fields rather than the construct at fault.

This project has already lost a stage to exactly that. README §14.1 records
adjudication silently failing on **every** claim because `subject_alive` was
declared as the union `["boolean", "null"]`, which a Gemini function
declaration rejects, so every claim fell back to UNSUPPORTED and the report
came out amber with no verdict behind it. The same class of rejection then took
out the grounded fallback's structuring step with "11 validation errors".

The rules below are small, and the reason they live in one place is that the
next schema to hit this will not be one somebody remembered to test.

Nothing here changes meaning. Constraints Vertex cannot express are dropped
rather than approximated, because a silently loosened schema is worse than an
absent one: the structuring step is already constrained to retrieved text, and
a dropped `maxLength` costs nothing, while a mistranslated `enum` would let a
verdict through that the pipeline does not recognise.
"""

from __future__ import annotations

from typing import Any

#: Vocabulary Vertex has no field for. Dropped rather than translated.
#: `additionalProperties` is the one that matters most: every schema in this
#: repository sets it to false, and it alone is enough to fail the request.
_UNSUPPORTED_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "additionalProperties",
        "unevaluatedProperties",
        "patternProperties",
        "dependentRequired",
        "dependentSchemas",
        "allOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "const",
        "examples",
        "default",
        "readOnly",
        "writeOnly",
        "deprecated",
        "contentMediaType",
        "contentEncoding",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "uniqueItems",
        "title",
    }
)

#: Kept, because Vertex understands them and they carry real meaning.
_KEPT_KEYS = frozenset(
    {
        "type",
        "description",
        "enum",
        "properties",
        "items",
        "required",
        "nullable",
        "format",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "propertyOrdering",
    }
)


#: How deep a `$ref` chain may be inlined before it is treated as recursive.
#: A self referential definition cannot be expressed at all in a dialect with
#: no `$ref`, so it is truncated to a bare object rather than expanded forever.
_MAX_REF_DEPTH = 6


def to_vertex_schema(schema: Any) -> Any:
    """Return `schema` rewritten into the dialect Vertex will accept.

    Recursive and non destructive: the caller's dictionary is not modified,
    because the same schema object is handed to Parallel on the primary path
    and must stay strict there.
    """
    definitions = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    return _convert(schema, definitions if isinstance(definitions, dict) else {}, 0)


def _convert(schema: Any, definitions: dict[str, Any], depth: int) -> Any:
    if not isinstance(schema, dict):
        return schema

    # `$ref` is not part of the Vertex dialect in any form, so a reference is
    # inlined into the place that uses it. `claim_verification_v1` refers to a
    # shared `fact` definition from both `supporting_facts` and
    # `contradicting_facts`, and passing either through unresolved fails the
    # whole request with "Extra inputs are not permitted".
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if depth >= _MAX_REF_DEPTH:
            return {"type": "object"}
        target = _resolve_ref(ref, definitions)
        if target is None:
            return {"type": "object"}
        merged = {k: v for k, v in schema.items() if k != "$ref"}
        return _convert({**target, **merged}, definitions, depth + 1)

    out: dict[str, Any] = {}

    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYS or key in {"$defs", "definitions"}:
            continue
        if key not in _KEPT_KEYS:
            # Unknown vocabulary is dropped rather than passed through. The SDK
            # rejects the whole request over one unrecognised field, so an
            # extension nobody anticipated should cost a constraint and not a
            # stage.
            continue

        if key == "properties" and isinstance(value, dict):
            out[key] = {name: _convert(sub, definitions, depth) for name, sub in value.items()}
        elif key == "items":
            out[key] = _convert(value, definitions, depth)
        else:
            out[key] = value

    _normalise_type(out)
    _normalise_enum(out)

    # A required entry naming a property that no longer exists is itself a
    # validation error, so the list is narrowed to what survived.
    if isinstance(out.get("required"), list) and isinstance(out.get("properties"), dict):
        present = set(out["properties"])
        out["required"] = [name for name in out["required"] if name in present]
        if not out["required"]:
            out.pop("required")

    return out


def _normalise_type(node: dict[str, Any]) -> None:
    """Rewrite a union type into a single type plus `nullable`.

    JSON Schema writes an optional boolean as `["boolean", "null"]`. Vertex
    writes it as `{"type": "boolean", "nullable": true}` and rejects the list
    form outright. This is the specific construct that silently disabled
    adjudication on every claim in this system once already.
    """
    declared = node.get("type")
    if not isinstance(declared, list):
        return

    concrete = [t for t in declared if t != "null"]
    if not concrete:
        node.pop("type", None)
        return

    node["type"] = concrete[0]
    if "null" in declared:
        node["nullable"] = True


def _normalise_enum(node: dict[str, Any]) -> None:
    """Make an enum a list of strings, which is the only form Vertex takes.

    Eight of the eleven schemas in this repository declare an optional
    controlled value the natural JSON Schema way, as an enum whose last member
    is `null`:

        "enum": ["primary", "secondary", "tertiary", null]

    Vertex rejects the whole request with "Input should be a valid string",
    naming the index rather than the cause. The null is the optionality, so it
    is moved to `nullable` where Vertex expects to find it and the remaining
    members are kept exactly as written. The permitted values do not change,
    which matters more here than anywhere else in this module: an enum that
    silently gained or lost a member would let a verdict through that the
    pipeline has no branch for.
    """
    values = node.get("enum")
    if not isinstance(values, list):
        return

    kept = [v for v in values if v is not None]
    if len(kept) != len(values):
        node["nullable"] = True

    # A non string member cannot be expressed either. Stringifying is safe for
    # the numbers and booleans that appear in practice and keeps the member
    # count identical, so nothing becomes silently permitted or forbidden.
    node["enum"] = [v if isinstance(v, str) else str(v) for v in kept]
    if not node["enum"]:
        node.pop("enum")


def _resolve_ref(ref: str, definitions: dict[str, Any]) -> dict[str, Any] | None:
    """Look up a local `#/$defs/name` pointer. Anything remote is unresolvable."""
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        return None
    target = definitions.get(ref[len(prefix) :])
    return target if isinstance(target, dict) else None
