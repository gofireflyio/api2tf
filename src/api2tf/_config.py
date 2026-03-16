"""Override configuration loading and validation."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from api2tf._types import OverrideConfig

logger = logging.getLogger(__name__)


def load_config(path: str | Path | None) -> OverrideConfig:
    """Load an override config from a YAML file.

    Returns a default (empty) config if the file doesn't exist or path is None.
    """
    if path is None:
        return OverrideConfig()

    p = Path(path)
    if not p.exists():
        return OverrideConfig()

    raw = p.read_text()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        print(f"Error: override config must be a YAML mapping: {path}", file=sys.stderr)
        sys.exit(1)

    return _parse_config(data)


def _parse_config(data: dict[str, Any]) -> OverrideConfig:
    """Parse a config dict into an OverrideConfig."""
    provider = data.get("provider", {})

    return OverrideConfig(
        provider_name=provider.get("name"),
        go_module=provider.get("go_module"),
        resource_overrides=data.get("resources", {}),
        data_source_overrides=data.get("data_sources", {}),
        ignore_paths=data.get("ignore_paths", []),
        attribute_renames=data.get("attribute_renames", {}),
        auth_override=data.get("auth", {}),
    )


def apply_overrides(config: OverrideConfig, provider: Any) -> None:
    """Apply override config to an inferred ProviderDef (mutates in place)."""
    if config.provider_name:
        provider.name = config.provider_name
    if config.go_module:
        provider.go_module = config.go_module

    # Apply resource overrides
    for resource in provider.resources:
        overrides = config.resource_overrides.get(resource.terraform_name, {})
        if not overrides:
            continue

        # Override ID field
        if "id_field" in overrides:
            resource.id_field = overrides["id_field"]

        # Override CRUD paths
        from api2tf._types import EndpointDef, CRUDRole

        for role_name in ("create", "read", "update", "delete"):
            if role_name in overrides:
                role = CRUDRole(role_name)
                ep_data = overrides[role_name]
                resource.endpoints[role] = EndpointDef(
                    path=ep_data["path"],
                    method=ep_data.get("method", "GET").upper(),
                    role=role,
                )

        # Override individual attributes
        attr_overrides = overrides.get("attributes", {})
        for attr in resource.attributes:
            if attr.name in attr_overrides:
                ao = attr_overrides[attr.name]
                if ao.get("ignore"):
                    resource.attributes = [a for a in resource.attributes if a.name != attr.name]
                    continue
                if "computed" in ao:
                    from api2tf._types import AttrComputability

                    attr.computability = (
                        AttrComputability.COMPUTED if ao["computed"] else attr.computability
                    )
                if "sensitive" in ao:
                    attr.sensitive = ao["sensitive"]

    # Apply global attribute renames
    if config.attribute_renames:
        for resource in provider.resources:
            for attr in resource.attributes:
                if attr.original_name in config.attribute_renames:
                    from api2tf._helpers import to_snake_case

                    attr.name = to_snake_case(config.attribute_renames[attr.original_name])
        for ds in provider.data_sources:
            for attr in ds.attributes:
                if attr.original_name in config.attribute_renames:
                    from api2tf._helpers import to_snake_case

                    attr.name = to_snake_case(config.attribute_renames[attr.original_name])
