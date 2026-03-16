"""Map OpenAPI schema types to Terraform Plugin Framework attribute types."""

from __future__ import annotations

import logging

from api2tf._types import (
    AttributeDef,
    AttrComputability,
    TFType,
)
from api2tf._helpers import to_snake_case, is_sensitive_field
from api2tf._openapi import get_schema_properties, get_required_fields

logger = logging.getLogger(__name__)


def _is_nullable(schema: dict) -> bool:
    """Check if a schema is nullable (3.0.x or 3.1.x)."""
    # 3.0.x
    if schema.get("nullable"):
        return True
    # 3.1.x
    schema_type = schema.get("type")
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    return False


def _get_base_type(schema: dict) -> str:
    """Get the base type string, handling 3.1.x type arrays."""
    schema_type = schema.get("type", "string")
    if isinstance(schema_type, list):
        # Filter out "null" and take the first real type
        real_types = [t for t in schema_type if t != "null"]
        return real_types[0] if real_types else "string"
    return schema_type


def map_openapi_type(
    prop_name: str,
    schema: dict,
    required_fields: set[str],
    *,
    read_only: bool = False,
    write_only: bool = False,
) -> AttributeDef:
    """Map a single OpenAPI property to a Terraform AttributeDef."""
    base_type = _get_base_type(schema)
    fmt = schema.get("format", "")
    description = schema.get("description", "")
    enum_values = schema.get("enum", [])
    is_read_only = schema.get("readOnly", False) or read_only
    is_write_only = schema.get("writeOnly", False) or write_only
    tf_name = to_snake_case(prop_name)

    # Determine computability
    if is_read_only:
        computability = AttrComputability.COMPUTED
    elif prop_name in required_fields and not is_write_only:
        computability = AttrComputability.REQUIRED
    else:
        computability = AttrComputability.OPTIONAL

    # Determine sensitivity
    sensitive = is_sensitive_field(tf_name, fmt)

    # Map type
    tf_type, element_type, nested_attrs = _map_type_recursive(
        prop_name, schema, base_type, fmt, required_fields
    )

    return AttributeDef(
        name=tf_name,
        tf_type=tf_type,
        computability=computability,
        description=description,
        sensitive=sensitive,
        enum_values=[str(v) for v in enum_values] if enum_values else [],
        element_type=element_type,
        nested_attributes=nested_attrs,
        original_name=prop_name,
        write_only=is_write_only,
        format_hint=fmt,
    )


def _map_type_recursive(
    prop_name: str,
    schema: dict,
    base_type: str,
    fmt: str,
    required_fields: set[str],
) -> tuple[TFType, TFType | None, list[AttributeDef]]:
    """Map an OpenAPI type to TFType, element type, and nested attributes."""
    if base_type == "string":
        return TFType.STRING, None, []

    if base_type == "integer":
        return TFType.INT64, None, []

    if base_type == "number":
        return TFType.FLOAT64, None, []

    if base_type == "boolean":
        return TFType.BOOL, None, []

    if base_type == "array":
        items = schema.get("items", {})
        items_type = _get_base_type(items)

        if items_type == "object" and items.get("properties"):
            # Array of objects -> ListNestedAttribute
            nested = map_schema_to_attributes(items)
            return TFType.LIST_NESTED, None, nested
        else:
            # Array of primitives -> ListAttribute with element type
            elem_type = _primitive_to_tf_type(items_type)
            return TFType.LIST, elem_type, []

    if base_type == "object":
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties")

        if properties:
            # Object with known properties -> SingleNestedAttribute
            nested = map_schema_to_attributes(schema)
            return TFType.SINGLE_NESTED, None, nested
        elif additional and isinstance(additional, dict):
            # Map type
            elem_type = _primitive_to_tf_type(_get_base_type(additional))
            return TFType.MAP, elem_type, []
        else:
            # Generic object -> MapAttribute of strings
            return TFType.MAP, TFType.STRING, []

    # oneOf / anyOf fallback -> JSON string
    if "oneOf" in schema or "anyOf" in schema:
        logger.warning(
            "Property '%s' uses oneOf/anyOf; falling back to JSON string attribute",
            prop_name,
        )
        return TFType.STRING, None, []

    # Default fallback
    logger.warning("Unknown OpenAPI type '%s' for '%s'; defaulting to string", base_type, prop_name)
    return TFType.STRING, None, []


def _primitive_to_tf_type(type_str: str) -> TFType:
    """Map a primitive OpenAPI type string to a TFType."""
    mapping = {
        "string": TFType.STRING,
        "integer": TFType.INT64,
        "number": TFType.FLOAT64,
        "boolean": TFType.BOOL,
    }
    return mapping.get(type_str, TFType.STRING)


def map_schema_to_attributes(
    schema: dict,
    *,
    read_only: bool = False,
    write_only: bool = False,
) -> list[AttributeDef]:
    """Map all properties in an OpenAPI schema to Terraform attributes."""
    properties = get_schema_properties(schema)
    required_fields = get_required_fields(schema)
    attrs: list[AttributeDef] = []

    for prop_name, prop_schema in properties.items():
        attr = map_openapi_type(
            prop_name,
            prop_schema,
            required_fields,
            read_only=read_only,
            write_only=write_only,
        )
        attrs.append(attr)

    return attrs


def merge_attributes(
    request_attrs: list[AttributeDef],
    response_attrs: list[AttributeDef],
) -> list[AttributeDef]:
    """Merge request body attributes with response attributes.

    - Request-only: Required or Optional (as detected)
    - Response-only: Computed
    - Both: keep the request computability (user-settable, also returned)
    """
    by_name: dict[str, AttributeDef] = {}

    # Start with request attributes
    for attr in request_attrs:
        by_name[attr.name] = attr

    # Merge response attributes
    for attr in response_attrs:
        if attr.name not in by_name:
            # Response-only field -> Computed
            attr.computability = AttrComputability.COMPUTED
            by_name[attr.name] = attr
        else:
            # Both request and response -- keep request computability
            existing = by_name[attr.name]
            # If the response has a better description, use it
            if not existing.description and attr.description:
                existing.description = attr.description

    return list(by_name.values())
