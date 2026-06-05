#!/usr/bin/env python3
"""
scripts/validate.py — JSON Schema validation for the Agent Presentation
Protocol spec repo.

Runs two checks:

  1. Meta-validates the three schema files (agent-card, messages,
     presence_state) against the JSON Schema Draft-07 meta-schema.
  2. Validates every line of each examples/<name>/app.expected.jsonl
     fixture against messages.schema.json (which has sibling-file
     $refs into agent-card.schema.json and presence_state.json).

Usage:
    python3 scripts/validate.py

Exit codes: 0 on full pass; 1 on any failure.

Requires: jsonschema >= 4.18 (uses the referencing-library Registry API).
Verified against jsonschema 4.25.1 on Python 3.9.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urljoin

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"

SCHEMA_FILES = [
    "agent-card.schema.json",
    "messages.schema.json",
    "presence_state.json",
]


def load_schema(path):
    return json.loads(path.read_text())


def meta_validate(schemas):
    failures = []
    for name, schema in schemas.items():
        try:
            Draft7Validator.check_schema(schema)
        except SchemaError as exc:
            failures.append((name, exc.message))
    return failures


def build_registry(schemas):
    """
    Register each schema at every URI under which it might be looked up:
      - its declared $id (e.g. https://chitin.net/protocol/schemas/agent-card.json)
      - the URI produced by resolving its filename relative to
        messages.schema.json's $id (e.g. .../agent-card.schema.json)
    The dual registration handles the sibling-$ref pattern used by
    messages.schema.json without depending on URI normalization quirks.
    """
    resources = []
    base = schemas["messages.schema.json"].get("$id", "")
    for filename, schema in schemas.items():
        resource = Resource.from_contents(schema, default_specification=DRAFT7)
        if schema.get("$id"):
            resources.append((schema["$id"], resource))
        if base:
            resources.append((urljoin(base, filename), resource))
    return Registry().with_resources(resources)


def validate_fixtures(messages_schema, registry):
    validator = Draft7Validator(messages_schema, registry=registry)
    failures = []
    fixtures = sorted((REPO_ROOT / "examples").glob("*/app.expected.jsonl"))
    if not fixtures:
        return ["(no fixtures matched examples/*/app.expected.jsonl)"], 0
    total_lines = 0
    for fixture in fixtures:
        rel = fixture.relative_to(REPO_ROOT)
        lines_validated = 0
        for line_no, raw in enumerate(fixture.read_text().splitlines(), start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError as exc:
                failures.append(f"{rel}:{line_no}  JSON parse error: {exc}")
                continue
            errors = list(validator.iter_errors(msg))
            if errors:
                err = errors[0]
                path = "/".join(str(p) for p in err.path) or "<root>"
                failures.append(
                    f"{rel}:{line_no}  validation error at {path}: {err.message}"
                )
            lines_validated += 1
        total_lines += lines_validated
        print(f"  {rel}  ({lines_validated} lines)")
    return failures, total_lines


def main():
    print(f"REPO_ROOT: {REPO_ROOT}")
    schemas = {name: load_schema(SCHEMA_DIR / name) for name in SCHEMA_FILES}

    print("\n[1/2] Meta-validating schemas against JSON Schema Draft-07 ...")
    meta_failures = meta_validate(schemas)
    for name in SCHEMA_FILES:
        status = "OK " if not any(n == name for n, _ in meta_failures) else "FAIL"
        print(f"  {status}  schemas/{name}")
    if meta_failures:
        print(f"\n  FAIL: {len(meta_failures)} schema(s) failed meta-validation:")
        for name, msg in meta_failures:
            print(f"    schemas/{name}: {msg}")
        return 1

    print("\n[2/2] Validating fixtures against messages.schema.json ...")
    registry = build_registry(schemas)
    result = validate_fixtures(schemas["messages.schema.json"], registry)
    if isinstance(result, tuple):
        failures, total_lines = result
    else:
        failures, total_lines = result, 0
    if failures:
        print(f"\n  FAIL: {len(failures)} fixture line(s) failed validation:")
        for f in failures:
            print(f"    {f}")
        return 1

    print(f"\nAll checks passed ({len(SCHEMA_FILES)} schemas meta-valid; "
          f"{total_lines} fixture lines validated).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
