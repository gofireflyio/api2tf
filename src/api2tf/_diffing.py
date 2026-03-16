"""Spec diffing and safe regeneration support."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from api2tf._types import GenerationState, ProviderDef

logger = logging.getLogger(__name__)

STATE_FILENAME = ".api2tf.state.json"


def compute_spec_hash(spec: dict) -> str:
    """Compute a stable SHA-256 hash of a spec."""
    raw = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def load_state(output_dir: Path) -> GenerationState | None:
    """Load generation state from a previous run."""
    state_file = output_dir / STATE_FILENAME
    if not state_file.exists():
        return None
    data = json.loads(state_file.read_text())
    return GenerationState(
        spec_hash=data.get("spec_hash", ""),
        generated_at=data.get("generated_at", ""),
        api2tf_version=data.get("api2tf_version", ""),
        resources=data.get("resources", {}),
        data_sources=data.get("data_sources", {}),
        override_files=data.get("override_files", []),
    )


def save_state(
    output_dir: Path,
    provider: ProviderDef,
    spec_hash: str,
    version: str,
    override_files: list[str],
) -> None:
    """Save generation state for future incremental updates."""
    state = {
        "spec_hash": spec_hash,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api2tf_version": version,
        "resources": {
            r.terraform_name: {
                "noun": r.noun,
                "id_field": r.id_field,
                "endpoints": {
                    role.value: ep.path
                    for role, ep in r.endpoints.items()
                },
            }
            for r in provider.resources
        },
        "data_sources": {
            ds.terraform_name: {
                "noun": ds.noun,
                "endpoint": ds.endpoint.path if ds.endpoint else "",
            }
            for ds in provider.data_sources
        },
        "override_files": override_files,
    }
    state_file = output_dir / STATE_FILENAME
    state_file.write_text(json.dumps(state, indent=2) + "\n")


def diff_file(existing_path: Path, new_content: str) -> str | None:
    """Compute a unified diff between existing file and new content.

    Returns the diff string, or None if files are identical.
    """
    if not existing_path.exists():
        return f"--- /dev/null\n+++ {existing_path}\n" + "\n".join(
            f"+{line}" for line in new_content.splitlines()
        )

    existing = existing_path.read_text()
    if existing == new_content:
        return None

    diff = difflib.unified_diff(
        existing.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=str(existing_path),
        tofile=str(existing_path) + " (new)",
    )
    return "".join(diff) or None


def plan_generation(
    output_dir: Path,
    provider: ProviderDef,
    file_contents: dict[str, str],
    state: GenerationState | None,
) -> list[dict[str, str]]:
    """Plan what files would be created/updated/skipped.

    Returns a list of actions: [{"action": "create|update|skip|unchanged", "path": ..., "reason": ...}]
    """
    actions: list[dict[str, str]] = []

    for rel_path, content in sorted(file_contents.items()):
        full_path = output_dir / rel_path
        is_override = "_override" in rel_path

        if not full_path.exists():
            actions.append({
                "action": "create",
                "path": rel_path,
                "reason": "new file",
            })
        elif is_override:
            actions.append({
                "action": "skip",
                "path": rel_path,
                "reason": "user override (not overwritten)",
            })
        else:
            existing = full_path.read_text()
            if existing == content:
                actions.append({
                    "action": "unchanged",
                    "path": rel_path,
                    "reason": "no changes",
                })
            else:
                actions.append({
                    "action": "update",
                    "path": rel_path,
                    "reason": "spec changed",
                })

    # Check for resources in state that no longer exist
    if state:
        current_resources = {r.terraform_name for r in provider.resources}
        for old_name in state.resources:
            if old_name not in current_resources:
                actions.append({
                    "action": "warn",
                    "path": f"resource_{old_name}",
                    "reason": f"resource '{old_name}' no longer in spec (files NOT deleted)",
                })

    return actions


def format_plan(actions: list[dict[str, str]]) -> str:
    """Format a generation plan for display."""
    lines: list[str] = []
    icons = {
        "create": "  + create:",
        "update": "  ~ update:",
        "skip": "  - skip:  ",
        "unchanged": "  = unchanged:",
        "warn": "  ! warning:",
    }
    for action in actions:
        icon = icons.get(action["action"], "  ?")
        lines.append(f"{icon} {action['path']}  ({action['reason']})")
    return "\n".join(lines)
