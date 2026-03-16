"""LLM-assisted spec analysis for smarter resource inference.

When invoked with --smart, the LLM analyzes the OpenAPI spec to:
1. Improve CRUD endpoint detection (e.g., POST /search is a list, not create)
2. Suggest better resource groupings and naming
3. Identify sensitive fields the heuristics might miss
4. Generate meaningful attribute descriptions when spec has none
5. Detect which fields should be Computed vs Required when ambiguous

The LLM produces a structured analysis that gets merged into the override config,
keeping the actual code generation fully deterministic.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

# Analysis prompt template
_SYSTEM_PROMPT = """\
You are an expert at Terraform provider development and OpenAPI spec analysis.
You will analyze an OpenAPI spec and produce structured recommendations for
generating a Terraform provider.

Your output must be valid JSON matching the schema below. Do not include any
text outside the JSON object.
"""

_ANALYSIS_PROMPT = """\
Analyze this OpenAPI spec and produce recommendations for Terraform provider generation.

## Spec Summary
Title: {title}
Version: {version}
Base URL: {base_url}
Total paths: {path_count}
Total schemas: {schema_count}

## Endpoints
{endpoints}

## Instructions

For each endpoint group, determine:

1. **resource_type**: Is this group a "resource" (has CRUD), "data_source" (read-only),
   or "action" (RPC-style, should be ignored for Terraform)?

2. **crud_mapping**: For resources, which HTTP method maps to which CRUD operation?
   Be careful with POST endpoints that are actually searches/lists (not creates).

3. **terraform_name**: What should the Terraform resource be named? Strip version
   prefixes (v1_, v2_), use snake_case, singularize correctly.

4. **sensitive_fields**: Which fields contain secrets, tokens, passwords, or keys?

5. **description**: A one-line description for the Terraform resource.

## Output Schema

```json
{{
  "provider_name": "string — suggested provider name",
  "resources": [
    {{
      "path_group": "string — base path like /users",
      "terraform_name": "string — e.g. myapi_user",
      "resource_type": "resource | data_source | action",
      "description": "string — one-line description",
      "crud_mapping": {{
        "create": "POST /path",
        "read": "GET /path/{{id}}",
        "update": "PATCH /path/{{id}}",
        "delete": "DELETE /path/{{id}}",
        "list": "GET /path"
      }},
      "sensitive_fields": ["field_name"],
      "notes": "string — any special handling notes"
    }}
  ],
  "ignore_paths": ["string — paths to skip (health checks, internal, etc.)"]
}}
```

Respond with only the JSON object, no markdown fencing or explanation.
"""


def _get_client():
    """Get the Anthropic client, checking for API key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Error: --smart requires ANTHROPIC_API_KEY environment variable.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  Get a key at: https://console.anthropic.com/",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import anthropic
    except ImportError:
        print(
            "Error: --smart requires the 'anthropic' package.\n"
            "  pip install anthropic",
            file=sys.stderr,
        )
        sys.exit(1)

    return anthropic.Anthropic(api_key=api_key)


def _summarize_endpoints(spec: dict) -> str:
    """Create a concise endpoint summary for the LLM prompt."""
    paths = spec.get("paths", {})
    lines = []
    for path, operations in sorted(paths.items()):
        methods = []
        for method in ("get", "post", "put", "patch", "delete"):
            if method in operations:
                op = operations[method]
                summary = op.get("summary", "")
                op_id = op.get("operationId", "")
                methods.append(f"{method.upper()} — {summary or op_id}")
        if methods:
            lines.append(f"  {path}")
            for m in methods:
                lines.append(f"    {m}")
    return "\n".join(lines)


def analyze_spec(spec: dict) -> dict[str, Any]:
    """Use LLM to analyze an OpenAPI spec and produce structured recommendations.

    Returns a dict matching the analysis schema that can be merged with override config.
    """
    client = _get_client()

    info = spec.get("info", {})
    servers = spec.get("servers", [])
    base_url = servers[0].get("url", "") if servers else ""
    endpoints = _summarize_endpoints(spec)

    # Truncate if too long (keep under ~100k chars for context)
    if len(endpoints) > 80000:
        endpoints = endpoints[:80000] + "\n  ... (truncated)"

    prompt = _ANALYSIS_PROMPT.format(
        title=info.get("title", "Unknown"),
        version=info.get("version", ""),
        base_url=base_url,
        path_count=len(spec.get("paths", {})),
        schema_count=len(spec.get("components", {}).get("schemas", {})),
        endpoints=endpoints,
    )

    logger.info("Sending spec analysis to Claude (%d chars)...", len(prompt))
    print("Analyzing spec with Claude...", end=" ", flush=True)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    print("done.")

    # Parse JSON response
    try:
        # Handle markdown fencing if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        analysis = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response as JSON: %s", e)
        logger.debug("Raw response: %s", raw[:500])
        print("Warning: LLM response was not valid JSON. Falling back to heuristic mode.", file=sys.stderr)
        return {}

    return analysis


def merge_analysis_into_config(analysis: dict, config_path: str) -> None:
    """Merge LLM analysis results into an override config file.

    Creates or updates the config file with LLM recommendations as comments
    that the user can review and enable.
    """
    from pathlib import Path
    import yaml

    path = Path(config_path)

    if path.exists():
        with open(path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Apply provider name suggestion
    if "provider_name" in analysis:
        config.setdefault("provider", {})["name"] = analysis["provider_name"]

    # Apply ignore paths
    if "ignore_paths" in analysis:
        config["ignore_paths"] = analysis["ignore_paths"]

    # Write back with LLM annotations
    with open(path, "w") as f:
        f.write("# api2tf override configuration (LLM-enhanced)\n")
        f.write("# Generated with --smart flag using Claude analysis.\n")
        f.write("# Review and adjust before running 'api2tf generate'.\n\n")

        if "provider" in config:
            f.write(f"provider:\n  name: {config['provider'].get('name', 'unknown')}\n\n")

        if "resources" in analysis:
            f.write("resources:\n")
            for r in analysis["resources"]:
                tf_name = r.get("terraform_name", "unknown")
                rtype = r.get("resource_type", "resource")
                desc = r.get("description", "")
                notes = r.get("notes", "")
                sensitive = r.get("sensitive_fields", [])

                f.write(f"  {tf_name}:\n")
                f.write(f"    enabled: {'true' if rtype == 'resource' else 'false'}")
                f.write(f"  # {rtype}")
                if desc:
                    f.write(f" — {desc}")
                f.write("\n")

                if r.get("crud_mapping"):
                    crud = r["crud_mapping"]
                    for op, endpoint in crud.items():
                        if endpoint:
                            f.write(f"    # {op}: {endpoint}\n")

                if sensitive:
                    f.write(f"    sensitive_fields: {sensitive}\n")

                if notes:
                    f.write(f"    # NOTE: {notes}\n")
            f.write("\n")

        if analysis.get("ignore_paths"):
            f.write("ignore_paths:\n")
            for p in analysis["ignore_paths"]:
                f.write(f"  - {p}\n")

    print(f"Updated {config_path} with LLM analysis.")
