"""OpenAPI spec loading, $ref resolution, and validation."""

from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def resolve_refs(spec: dict) -> dict:
    """Recursively resolve all $ref pointers in an OpenAPI spec.

    Handles circular references by tracking visited refs.
    """
    spec = copy.deepcopy(spec)

    def _resolve(node: Any, root: dict, seen: frozenset[str]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref in seen:
                    return node  # break circular ref
                seen = seen | {ref}
                if ref.startswith("#/"):
                    parts = ref[2:].split("/")
                    target = root
                    for p in parts:
                        target = target[p]
                    return _resolve(copy.deepcopy(target), root, seen)
                return node  # external ref -- leave as-is
            return {k: _resolve(v, root, seen) for k, v in node.items()}
        if isinstance(node, list):
            return [_resolve(item, root, seen) for item in node]
        return node

    return _resolve(spec, spec, frozenset())


def load_spec(source: str) -> dict:
    """Load an OpenAPI spec from a file path or URL.

    Supports JSON and YAML formats.
    """
    is_url = source.startswith("http://") or source.startswith("https://")

    if is_url:
        import httpx

        with httpx.Client(timeout=30) as client:
            resp = client.get(source)
            resp.raise_for_status()
            raw = resp.text
    else:
        path = Path(source)
        if not path.exists():
            print(f"Error: spec file not found: {source}", file=sys.stderr)
            sys.exit(1)
        raw = path.read_text()

    # Parse JSON or YAML
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        import yaml

        spec = yaml.safe_load(raw)

    if not isinstance(spec, dict):
        print("Error: spec must be a JSON/YAML object", file=sys.stderr)
        sys.exit(1)

    # Validate minimum structure
    if "paths" not in spec:
        print("Error: spec must contain 'paths'", file=sys.stderr)
        sys.exit(1)

    openapi_version = spec.get("openapi", "")
    if not openapi_version.startswith("3."):
        logger.warning("Expected OpenAPI 3.x, got: %s", openapi_version)

    return resolve_refs(spec)


def get_spec_info(spec: dict) -> dict[str, str]:
    """Extract basic info from a loaded spec."""
    info = spec.get("info", {})
    return {
        "title": info.get("title", ""),
        "version": info.get("version", ""),
        "description": info.get("description", ""),
    }


def get_base_url(spec: dict) -> str:
    """Extract the first server URL from the spec."""
    servers = spec.get("servers", [])
    if servers and isinstance(servers, list):
        url = servers[0].get("url", "")
        # Remove trailing slash
        return url.rstrip("/")
    return ""


def get_security_schemes(spec: dict) -> dict[str, dict]:
    """Extract securitySchemes from components."""
    return spec.get("components", {}).get("securitySchemes", {})


def get_paths(spec: dict) -> dict[str, dict]:
    """Extract paths from the spec."""
    return spec.get("paths", {})


def get_schema_properties(schema: dict) -> dict[str, dict]:
    """Extract properties from a schema, handling allOf merging."""
    if "allOf" in schema:
        merged: dict[str, dict] = {}
        for sub in schema["allOf"]:
            merged.update(get_schema_properties(sub))
        return merged
    return schema.get("properties", {})


def get_required_fields(schema: dict) -> set[str]:
    """Extract required field names from a schema, handling allOf."""
    if "allOf" in schema:
        required: set[str] = set()
        for sub in schema["allOf"]:
            required.update(get_required_fields(sub))
        return required
    return set(schema.get("required", []))


def get_request_body_schema(operation: dict) -> dict:
    """Extract the JSON request body schema from an operation."""
    return (
        operation.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
    )


def get_success_response_schema(operation: dict) -> dict:
    """Extract the JSON response schema from the first 2xx response."""
    responses = operation.get("responses", {})
    for code in ["200", "201", "202"]:
        if code in responses:
            return (
                responses[code]
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
    # Fallback: try any 2xx
    for code, resp in responses.items():
        if code.startswith("2"):
            return (
                resp.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
    return {}


def get_path_parameters(path: str) -> list[str]:
    """Extract parameter names from a path template.

    >>> get_path_parameters("/pets/{petId}/vaccinations/{vacId}")
    ['petId', 'vacId']
    """
    import re

    return re.findall(r"\{(\w+)\}", path)


def is_detail_path(path: str) -> bool:
    """Check if a path ends with a path parameter (detail endpoint).

    >>> is_detail_path("/pets/{petId}")
    True
    >>> is_detail_path("/pets")
    False
    """
    stripped = path.rstrip("/")
    return stripped.endswith("}")
