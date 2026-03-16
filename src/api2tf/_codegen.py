"""Code generation orchestrator: renders Jinja2 templates to Go source files."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from api2tf._types import (
    ProviderDef,
    ResourceDef,
    DataSourceDef,
    AttributeDef,
    AttrComputability,
    CRUDRole,
    TFType,
)
from api2tf._helpers import to_pascal_case, to_snake_case
from api2tf._diffing import (
    compute_spec_hash,
    load_state,
    save_state,
    plan_generation,
    format_plan,
    diff_file,
)

logger = logging.getLogger(__name__)


def _create_jinja_env() -> Environment:
    """Create a Jinja2 environment with custom filters."""
    env = Environment(
        loader=PackageLoader("api2tf", "templates"),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["escape_go_string"] = _escape_go_string
    env.filters["go_api_type"] = _go_api_type
    env.filters["go_path_format"] = _go_path_format
    env.filters["render_schema_attribute"] = _render_schema_attribute
    env.filters["render_datasource_attribute"] = _render_datasource_attribute
    env.filters["render_plan_to_api"] = _render_plan_to_api
    env.filters["render_api_to_plan"] = _render_api_to_plan
    return env


# -- Jinja2 Filters --


def _escape_go_string(value: str) -> str:
    """Escape a string for use in a Go string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _go_api_type(attr: AttributeDef) -> str:
    """Map an attribute to its Go API struct type (not Terraform types.*)."""
    type_map = {
        TFType.STRING: "string",
        TFType.INT64: "int64",
        TFType.FLOAT64: "float64",
        TFType.BOOL: "bool",
    }
    if attr.tf_type in type_map:
        return type_map[attr.tf_type]
    if attr.tf_type == TFType.LIST:
        elem = type_map.get(attr.element_type, "interface{}") if attr.element_type else "interface{}"
        return f"[]{elem}"
    if attr.tf_type in (TFType.MAP, TFType.MAP_NESTED):
        return "map[string]interface{}"
    if attr.tf_type in (TFType.SINGLE_NESTED, TFType.LIST_NESTED):
        return "interface{}"
    return "interface{}"


def _go_path_format(path: str) -> str:
    """Convert OpenAPI path params to Go fmt.Sprintf format.

    /pets/{petId} -> /pets/%s
    """
    return re.sub(r"\{[^}]+\}", "%s", path)


def _indent(text: str, level: int) -> str:
    """Indent each line of text by level tabs."""
    prefix = "\t" * level
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def _render_schema_attribute(attr: AttributeDef, indent: int = 3) -> str:
    """Render a Terraform resource schema attribute definition."""
    lines = []
    prefix = "\t" * indent

    attr_type = _tf_schema_type(attr, "resource/schema")
    lines.append(f'{prefix}"{attr.name}": {attr_type}{{')

    if attr.description:
        lines.append(f'{prefix}\tDescription: "{_escape_go_string(attr.description)}",')

    comp = attr.computability
    if comp == AttrComputability.REQUIRED:
        lines.append(f"{prefix}\tRequired: true,")
    elif comp == AttrComputability.OPTIONAL:
        lines.append(f"{prefix}\tOptional: true,")
    elif comp == AttrComputability.COMPUTED:
        lines.append(f"{prefix}\tComputed: true,")
    elif comp == AttrComputability.COMPUTED_OPTIONAL:
        lines.append(f"{prefix}\tComputed: true,")
        lines.append(f"{prefix}\tOptional: true,")

    if attr.sensitive:
        lines.append(f"{prefix}\tSensitive: true,")

    # Element type for lists/sets/maps
    if attr.tf_type in (TFType.LIST, TFType.SET, TFType.MAP) and attr.element_type:
        elem_go = f"types.{attr.element_type.value}Type"
        lines.append(f"{prefix}\tElementType: {elem_go},")

    # Enum validator
    if attr.enum_values and attr.tf_type == TFType.STRING:
        vals = ", ".join(f'"{v}"' for v in attr.enum_values)
        lines.append(f"{prefix}\tValidators: []validator.String{{")
        lines.append(f"{prefix}\t\tstringvalidator.OneOf({vals}),")
        lines.append(f"{prefix}\t}},")

    lines.append(f"{prefix}}},")
    return "\n".join(lines)


def _render_datasource_attribute(attr: AttributeDef, indent: int = 3) -> str:
    """Render a Terraform data source schema attribute definition."""
    lines = []
    prefix = "\t" * indent
    attr_type = _tf_schema_type(attr, "datasource/schema")

    lines.append(f'{prefix}"{attr.name}": {attr_type}{{')
    if attr.description:
        lines.append(f'{prefix}\tDescription: "{_escape_go_string(attr.description)}",')
    lines.append(f"{prefix}\tComputed: true,")
    if attr.sensitive:
        lines.append(f"{prefix}\tSensitive: true,")
    if attr.tf_type in (TFType.LIST, TFType.SET, TFType.MAP) and attr.element_type:
        elem_go = f"types.{attr.element_type.value}Type"
        lines.append(f"{prefix}\tElementType: {elem_go},")
    lines.append(f"{prefix}}},")
    return "\n".join(lines)


def _tf_schema_type(attr: AttributeDef, schema_pkg: str = "resource/schema") -> str:
    """Get the Terraform schema attribute type constructor name."""
    mapping = {
        TFType.STRING: "schema.StringAttribute",
        TFType.INT64: "schema.Int64Attribute",
        TFType.FLOAT64: "schema.Float64Attribute",
        TFType.BOOL: "schema.BoolAttribute",
        TFType.LIST: "schema.ListAttribute",
        TFType.SET: "schema.SetAttribute",
        TFType.MAP: "schema.MapAttribute",
        TFType.SINGLE_NESTED: "schema.SingleNestedAttribute",
        TFType.LIST_NESTED: "schema.ListNestedAttribute",
        TFType.MAP_NESTED: "schema.MapNestedAttribute",
    }
    return mapping.get(attr.tf_type, "schema.StringAttribute")


def _render_plan_to_api(attr: AttributeDef, indent: int = 1) -> str:
    """Render a plan -> API conversion line."""
    prefix = "\t" * indent
    field = attr.go_field_name
    tf_type = attr.tf_type

    if tf_type == TFType.STRING:
        return f"{prefix}if !plan.{field}.IsNull() && !plan.{field}.IsUnknown() {{\n{prefix}\tinput.{field} = plan.{field}.ValueString()\n{prefix}}}"
    elif tf_type == TFType.INT64:
        return f"{prefix}if !plan.{field}.IsNull() && !plan.{field}.IsUnknown() {{\n{prefix}\tinput.{field} = plan.{field}.ValueInt64()\n{prefix}}}"
    elif tf_type == TFType.FLOAT64:
        return f"{prefix}if !plan.{field}.IsNull() && !plan.{field}.IsUnknown() {{\n{prefix}\tinput.{field} = plan.{field}.ValueFloat64()\n{prefix}}}"
    elif tf_type == TFType.BOOL:
        return f"{prefix}if !plan.{field}.IsNull() && !plan.{field}.IsUnknown() {{\n{prefix}\tinput.{field} = plan.{field}.ValueBool()\n{prefix}}}"
    else:
        return f"{prefix}// TODO: Handle complex type conversion for {field}"


def _render_api_to_plan(attr: AttributeDef, indent: int = 1) -> str:
    """Render an API -> plan conversion line."""
    prefix = "\t" * indent
    field = attr.go_field_name
    tf_type = attr.tf_type

    if tf_type == TFType.STRING:
        return f"{prefix}plan.{field} = types.StringValue(api.{field})"
    elif tf_type == TFType.INT64:
        return f"{prefix}plan.{field} = types.Int64Value(api.{field})"
    elif tf_type == TFType.FLOAT64:
        return f"{prefix}plan.{field} = types.Float64Value(api.{field})"
    elif tf_type == TFType.BOOL:
        return f"{prefix}plan.{field} = types.BoolValue(api.{field})"
    else:
        return f"{prefix}// TODO: Handle complex type conversion for {field}"


# -- File Generation --


def _get_id_args(resource: ResourceDef, role: CRUDRole) -> str:
    """Get the Go arguments for passing ID to client methods."""
    if role in resource.endpoints:
        from api2tf._openapi import get_path_parameters

        params = get_path_parameters(resource.endpoints[role].path)
        if params:
            # Map path params to Terraform state fields
            args = []
            for p in params:
                tf_name = to_snake_case(p)
                go_field = to_pascal_case(tf_name)
                args.append(f"state.{go_field}.ValueString()")
            return ", ".join(args)
    return f"state.{to_pascal_case(resource.id_field)}.ValueString()"


def _get_id_params(resource: ResourceDef) -> str:
    """Get Go function parameter declarations for ID params."""
    if CRUDRole.READ in resource.endpoints:
        from api2tf._openapi import get_path_parameters

        params = get_path_parameters(resource.endpoints[CRUDRole.READ].path)
        if params:
            return ", ".join(f"{to_snake_case(p)} string" for p in params)
    return "id string"


def _get_id_call_args(resource: ResourceDef) -> str:
    """Get Go call arguments (just variable names, no types)."""
    if CRUDRole.READ in resource.endpoints:
        from api2tf._openapi import get_path_parameters

        params = get_path_parameters(resource.endpoints[CRUDRole.READ].path)
        if params:
            return ", ".join(to_snake_case(p) for p in params)
    return "id"


def generate_files(
    provider: ProviderDef,
    spec: dict,
) -> dict[str, str]:
    """Generate all file contents for a provider.

    Returns: {relative_path: file_content}
    """
    env = _create_jinja_env()
    files: dict[str, str] = {}

    provider_type = to_pascal_case(provider.name)
    provider_org = provider.name  # default org = provider name

    # Common template context (no 'description' — it varies per resource/provider)
    base_ctx = {
        "provider_name": provider.name,
        "provider_type": provider_type,
        "provider_org": provider_org,
        "go_module": provider.go_module,
        "base_url": provider.base_url,
    }

    # main.go
    tmpl = env.get_template("main.go.j2")
    files["main.go"] = tmpl.render(**base_ctx)

    # go.mod
    tmpl = env.get_template("go.mod.j2")
    files["go.mod"] = tmpl.render(**base_ctx)

    # internal/client/client.go
    tmpl = env.get_template("client.go.j2")
    files["internal/client/client.go"] = tmpl.render(**base_ctx)

    # provider.go
    tmpl = env.get_template("provider.go.j2")
    files["internal/provider/provider.go"] = tmpl.render(
        **base_ctx,
        description=provider.description,
        auth_attributes=provider.auth_schemes,
        resources=provider.resources,
        data_sources=provider.data_sources,
    )

    # Per-resource files
    for resource in provider.resources:
        _generate_resource_files(env, files, resource, provider, base_ctx)

    # Per-data-source files
    for ds in provider.data_sources:
        _generate_datasource_files(env, files, ds, provider, base_ctx)

    # Client service files (one per resource)
    for resource in provider.resources:
        _generate_client_service(env, files, resource, provider, base_ctx)

    # Example provider.tf
    tmpl = env.get_template("example_provider.tf.j2")
    files["examples/provider/provider.tf"] = tmpl.render(
        **base_ctx,
        auth_attributes=provider.auth_schemes,
    )

    return files


def _generate_resource_files(
    env: Environment,
    files: dict[str, str],
    resource: ResourceDef,
    provider: ProviderDef,
    base_ctx: dict,
) -> None:
    """Generate the three-layer files for a resource."""
    type_name = resource.go_type_name
    noun = resource.noun
    has_validators = any(attr.enum_values for attr in resource.attributes)

    writable_attrs = [
        a for a in resource.attributes
        if a.computability != AttrComputability.COMPUTED
    ]

    # Schema gen
    tmpl = env.get_template("resource_schema_gen.go.j2")
    files[f"internal/provider/resource_{noun}_schema_gen.go"] = tmpl.render(
        **base_ctx,
        type_name=type_name,
        noun=noun,
        attributes=resource.attributes,
        description=resource.description,
        has_validators=has_validators,
    )

    # CRUD gen
    tmpl = env.get_template("resource_crud_gen.go.j2")
    files[f"internal/provider/resource_{noun}_crud_gen.go"] = tmpl.render(
        **base_ctx,
        type_name=type_name,
        noun=noun,
        id_field=to_snake_case(resource.id_field),
        has_create=resource.has_create,
        has_update=resource.has_update,
        has_delete=resource.has_delete,
        read_id_args=_get_id_args(resource, CRUDRole.READ),
        update_id_args=_get_id_args(resource, CRUDRole.UPDATE) if resource.has_update else "",
        delete_id_args=_get_id_args(resource, CRUDRole.DELETE) if resource.has_delete else "",
        writable_attributes=writable_attrs,
        all_attributes=resource.attributes,
    )

    # Override (scaffold)
    tmpl = env.get_template("resource_override.go.j2")
    files[f"internal/provider/resource_{noun}_override.go"] = tmpl.render(
        type_name=type_name,
    )


def _generate_datasource_files(
    env: Environment,
    files: dict[str, str],
    ds: DataSourceDef,
    provider: ProviderDef,
    base_ctx: dict,
) -> None:
    """Generate the three-layer files for a data source."""
    type_name = ds.go_type_name

    # Schema gen
    tmpl = env.get_template("datasource_schema_gen.go.j2")
    files[f"internal/provider/data_source_{ds.noun}_schema_gen.go"] = tmpl.render(
        **base_ctx,
        type_name=type_name,
        noun=ds.noun,
        attributes=ds.attributes,
        description=ds.description,
    )

    # Read gen
    tmpl = env.get_template("datasource_read_gen.go.j2")
    files[f"internal/provider/data_source_{ds.noun}_read_gen.go"] = tmpl.render(
        **base_ctx,
        type_name=type_name,
        noun=ds.noun,
    )

    # Override (scaffold)
    tmpl = env.get_template("datasource_override.go.j2")
    files[f"internal/provider/data_source_{ds.noun}_override.go"] = tmpl.render(
        type_name=type_name,
    )


def _generate_client_service(
    env: Environment,
    files: dict[str, str],
    resource: ResourceDef,
    provider: ProviderDef,
    base_ctx: dict,
) -> None:
    """Generate a client service file for a resource."""
    type_name = resource.go_type_name
    tmpl = env.get_template("client_service.go.j2")

    # Filter to only non-nested primitive attributes for the API struct
    api_attrs = [a for a in resource.attributes if a.tf_type not in (TFType.SINGLE_NESTED, TFType.LIST_NESTED)]

    id_params = _get_id_params(resource)
    id_args = _get_id_call_args(resource)
    id_params_with_input = f"{id_params}, input *{type_name}"

    files[f"internal/client/{resource.noun}.go"] = tmpl.render(
        **base_ctx,
        type_name=type_name,
        noun=resource.noun,
        api_attributes=api_attrs,
        id_params=id_params,
        id_args=id_args,
        id_params_with_input=id_params_with_input,
        create_endpoint=resource.endpoints.get(CRUDRole.CREATE),
        read_endpoint=resource.endpoints.get(CRUDRole.READ),
        update_endpoint=resource.endpoints.get(CRUDRole.UPDATE),
        delete_endpoint=resource.endpoints.get(CRUDRole.DELETE),
    )


def write_files(
    output_dir: Path,
    file_contents: dict[str, str],
    *,
    force: bool = False,
    dry_run: bool = False,
    show_diff: bool = False,
    provider: ProviderDef | None = None,
    spec: dict | None = None,
    version: str = "0.1.0",
) -> None:
    """Write generated files to disk with safe update handling."""
    state = load_state(output_dir)

    if provider:
        actions = plan_generation(output_dir, provider, file_contents, state)
    else:
        actions = []

    if dry_run:
        print(format_plan(actions))
        return

    if show_diff:
        for rel_path, content in sorted(file_contents.items()):
            full_path = output_dir / rel_path
            d = diff_file(full_path, content)
            if d:
                print(d)
        return

    override_files: list[str] = []
    created = 0
    updated = 0
    skipped = 0

    for rel_path, content in sorted(file_contents.items()):
        full_path = output_dir / rel_path
        is_override = "_override" in rel_path

        if is_override:
            override_files.append(rel_path)

        if full_path.exists() and is_override and not force:
            skipped += 1
            logger.info("Skipping override file: %s", rel_path)
            continue

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if full_path.exists():
            existing = full_path.read_text()
            if existing == content:
                continue
            updated += 1
        else:
            created += 1

        full_path.write_text(content)

    # Save state
    if provider and spec:
        save_state(output_dir, provider, compute_spec_hash(spec), version, override_files)

    print(f"Generated: {created} created, {updated} updated, {skipped} skipped (override files)")
