"""Naming conventions, string utilities, and shared helpers."""

from __future__ import annotations

import re


def to_snake_case(name: str) -> str:
    """Convert camelCase, PascalCase, or kebab-case to snake_case.

    >>> to_snake_case("petId")
    'pet_id'
    >>> to_snake_case("HTTPSConnection")
    'https_connection'
    >>> to_snake_case("my-resource-name")
    'my_resource_name'
    """
    # Replace hyphens with underscores
    name = name.replace("-", "_")
    # Insert underscore before uppercase letters that follow lowercase
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert underscore between consecutive uppercase + lowercase (e.g. HTTPSConn -> HTTPS_Conn)
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return name.lower()


def to_pascal_case(name: str) -> str:
    """Convert snake_case or kebab-case to PascalCase.

    >>> to_pascal_case("pet_store")
    'PetStore'
    >>> to_pascal_case("my-resource")
    'MyResource'
    """
    return "".join(word.capitalize() for word in re.split(r"[_\-]+", name) if word)


def to_camel_case(name: str) -> str:
    """Convert snake_case to camelCase.

    >>> to_camel_case("pet_store")
    'petStore'
    """
    pascal = to_pascal_case(name)
    return pascal[0].lower() + pascal[1:] if pascal else ""


def terraform_resource_name(provider: str, noun: str) -> str:
    """Build a Terraform resource type name.

    >>> terraform_resource_name("petstore", "pet")
    'petstore_pet'
    """
    return f"{provider}_{to_snake_case(noun)}"


def terraform_datasource_name(provider: str, noun: str) -> str:
    """Build a Terraform data source type name.

    >>> terraform_datasource_name("petstore", "pets")
    'petstore_pets'
    """
    return f"{provider}_{to_snake_case(noun)}"


def go_exported_name(name: str) -> str:
    """Build an exported Go identifier from a snake_case name.

    >>> go_exported_name("pet_store")
    'PetStore'
    """
    return to_pascal_case(name)


def provider_name_from_title(title: str) -> str:
    """Derive a provider name from the OpenAPI info.title.

    >>> provider_name_from_title("Petstore API v3")
    'petstore'
    >>> provider_name_from_title("My Cool Service")
    'my_cool_service'
    """
    # Remove common suffixes
    cleaned = re.sub(r"\s*(api|service|platform|server)\s*v?\d*\.?\d*$", "", title, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if not cleaned:
        cleaned = title.strip()
    return to_snake_case(cleaned).replace(" ", "_").strip("_")


def env_var_name(provider: str, suffix: str) -> str:
    """Build an environment variable name.

    >>> env_var_name("petstore", "api_key")
    'PETSTORE_API_KEY'
    """
    return f"{provider.upper()}_{suffix.upper()}"


def is_sensitive_field(name: str, fmt: str = "") -> bool:
    """Heuristic: does this field name suggest sensitive data?"""
    sensitive_patterns = [
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "private_key", "access_key", "secret_key", "credentials",
        "auth_token", "bearer",
    ]
    lower = name.lower()
    if fmt == "password":
        return True
    return any(pat in lower for pat in sensitive_patterns)


def path_to_slug(path: str) -> str:
    """Convert an OpenAPI path to a slug suitable for naming.

    >>> path_to_slug("/pets/{petId}/vaccinations")
    'pets_vaccinations'
    """
    # Remove path params and leading slash
    parts = []
    for segment in path.strip("/").split("/"):
        if not segment.startswith("{"):
            parts.append(segment)
    return "_".join(parts)


def singularize(word: str) -> str:
    """Naive singularization for common English plurals.

    >>> singularize("pets")
    'pet'
    >>> singularize("categories")
    'category'
    >>> singularize("addresses")
    'address'
    >>> singularize("status")
    'status'
    """
    if not word:
        return word
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes") or word.endswith("zes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and not word.endswith("us"):
        return word[:-1]
    return word


def pluralize(word: str) -> str:
    """Naive pluralization for common English words.

    >>> pluralize("pet")
    'pets'
    >>> pluralize("category")
    'categories'
    """
    if word.endswith("y") and not word.endswith("ey"):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "sh", "ch")):
        return word + "es"
    return word + "s"


def composite_id_format(path_params: list[str]) -> str:
    """Build a composite ID format string for sub-resources.

    >>> composite_id_format(["orgId", "teamId"])
    '{orgId}/{teamId}'
    """
    return "/".join(f"{{{p}}}" for p in path_params)
