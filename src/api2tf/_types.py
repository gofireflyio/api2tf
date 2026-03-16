"""Core data structures for api2tf."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AttrComputability(Enum):
    """How Terraform should treat an attribute."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    COMPUTED = "computed"
    COMPUTED_OPTIONAL = "computed_optional"


class TFType(Enum):
    """Terraform Plugin Framework attribute types."""

    STRING = "String"
    INT64 = "Int64"
    FLOAT64 = "Float64"
    BOOL = "Bool"
    LIST = "List"
    SET = "Set"
    MAP = "Map"
    SINGLE_NESTED = "SingleNested"
    LIST_NESTED = "ListNested"
    MAP_NESTED = "MapNested"
    SET_NESTED = "SetNested"


class CRUDRole(Enum):
    """Role of an HTTP operation in a CRUD lifecycle."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LIST = "list"


@dataclass
class AttributeDef:
    """A single Terraform schema attribute."""

    name: str  # snake_case Terraform attribute name
    tf_type: TFType
    computability: AttrComputability
    description: str = ""
    sensitive: bool = False
    deprecated: str = ""
    # For enum validators
    enum_values: list[str] = field(default_factory=list)
    # For list/set element type
    element_type: TFType | None = None
    # For nested attributes
    nested_attributes: list[AttributeDef] = field(default_factory=list)
    # Original OpenAPI property name (before snake_case conversion)
    original_name: str = ""
    # Whether this field is write-only (excluded from state)
    write_only: bool = False
    # OpenAPI format hint (date-time, uuid, etc.)
    format_hint: str = ""

    @property
    def go_field_name(self) -> str:
        """PascalCase Go struct field name."""
        from api2tf._helpers import to_pascal_case

        return to_pascal_case(self.name)

    @property
    def go_type(self) -> str:
        """Terraform Plugin Framework Go type (e.g. types.String)."""
        return f"types.{self.tf_type.value}"


@dataclass
class EndpointDef:
    """An HTTP endpoint mapped to a CRUD role."""

    path: str
    method: str  # GET, POST, PUT, PATCH, DELETE
    role: CRUDRole
    operation_id: str = ""
    request_content_type: str = "application/json"
    response_content_type: str = "application/json"


@dataclass
class ResourceDef:
    """A Terraform resource derived from OpenAPI endpoints."""

    terraform_name: str  # e.g. "petstore_pet"
    noun: str  # e.g. "pet"
    endpoints: dict[CRUDRole, EndpointDef] = field(default_factory=dict)
    attributes: list[AttributeDef] = field(default_factory=list)
    id_field: str = "id"
    # For sub-resources
    parent_resource: str | None = None
    parent_id_field: str | None = None
    # Confidence score from inference (higher = more certain)
    confidence: int = 0
    description: str = ""

    @property
    def go_type_name(self) -> str:
        """PascalCase Go type name (e.g. Pet)."""
        from api2tf._helpers import to_pascal_case

        return to_pascal_case(self.noun)

    @property
    def has_create(self) -> bool:
        return CRUDRole.CREATE in self.endpoints

    @property
    def has_update(self) -> bool:
        return CRUDRole.UPDATE in self.endpoints

    @property
    def has_delete(self) -> bool:
        return CRUDRole.DELETE in self.endpoints


@dataclass
class DataSourceDef:
    """A Terraform data source derived from OpenAPI endpoints."""

    terraform_name: str  # e.g. "petstore_pets"
    noun: str  # e.g. "pets"
    endpoint: EndpointDef | None = None
    attributes: list[AttributeDef] = field(default_factory=list)
    description: str = ""

    @property
    def go_type_name(self) -> str:
        from api2tf._helpers import to_pascal_case

        return to_pascal_case(self.noun)


@dataclass
class AuthSchemeDef:
    """Authentication scheme derived from securitySchemes."""

    scheme_type: str  # "apiKey", "http", "oauth2"
    # For apiKey
    param_name: str = ""  # header/query param name
    param_location: str = ""  # "header" or "query"
    # For http
    http_scheme: str = ""  # "bearer" or "basic"
    # For oauth2
    token_url: str = ""
    scopes: list[str] = field(default_factory=list)
    # Terraform provider attribute name
    tf_attr_name: str = ""
    # Environment variable name for fallback
    env_var: str = ""
    # Description for the provider schema attribute
    description: str = ""

    @property
    def name(self) -> str:
        """Alias for tf_attr_name (used in templates)."""
        return self.tf_attr_name

    @property
    def go_field_name(self) -> str:
        """PascalCase Go struct field name."""
        from api2tf._helpers import to_pascal_case

        return to_pascal_case(self.tf_attr_name)


@dataclass
class ProviderDef:
    """The full Terraform provider definition."""

    name: str  # e.g. "petstore"
    go_module: str  # e.g. "github.com/example/terraform-provider-petstore"
    base_url: str = ""
    description: str = ""
    auth_schemes: list[AuthSchemeDef] = field(default_factory=list)
    resources: list[ResourceDef] = field(default_factory=list)
    data_sources: list[DataSourceDef] = field(default_factory=list)
    version: str = "0.1.0"


@dataclass
class OverrideConfig:
    """User-provided override configuration."""

    provider_name: str | None = None
    go_module: str | None = None
    resource_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    data_source_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    ignore_paths: list[str] = field(default_factory=list)
    attribute_renames: dict[str, str] = field(default_factory=dict)
    auth_override: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationState:
    """State persisted between generations for safe incremental updates."""

    spec_hash: str = ""
    generated_at: str = ""
    api2tf_version: str = ""
    resources: dict[str, dict[str, str]] = field(default_factory=dict)
    data_sources: dict[str, dict[str, str]] = field(default_factory=dict)
    override_files: list[str] = field(default_factory=list)
