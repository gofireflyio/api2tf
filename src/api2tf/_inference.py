"""CRUD pattern detection and resource grouping from OpenAPI paths."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from api2tf._types import (
    ResourceDef,
    DataSourceDef,
    EndpointDef,
    CRUDRole,
    AuthSchemeDef,
    ProviderDef,
)
from api2tf._helpers import (
    to_snake_case,
    singularize,
    path_to_slug,
    terraform_resource_name,
    terraform_datasource_name,
    provider_name_from_title,
    env_var_name,
)


def _slug_to_noun(stem: str) -> str:
    """Singularize only the last segment of a snake_case slug."""
    snake = to_snake_case(stem)
    parts = snake.rsplit("_", 1)
    if len(parts) == 2:
        return parts[0] + "_" + singularize(parts[1])
    return singularize(snake)
from api2tf._openapi import (
    get_paths,
    get_spec_info,
    get_base_url,
    get_security_schemes,
    get_path_parameters,
    get_request_body_schema,
    get_success_response_schema,
    is_detail_path,
)
from api2tf._schema_mapper import (
    map_schema_to_attributes,
    merge_attributes,
)

logger = logging.getLogger(__name__)

# HTTP methods relevant to CRUD
CRUD_METHODS = {"get", "post", "put", "patch", "delete"}


def _group_paths(paths: dict[str, dict]) -> dict[str, list[tuple[str, str, dict]]]:
    """Group paths by resource stem.

    Returns: {stem: [(path, method, operation), ...]}
    """
    groups: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        stem = path_to_slug(path)
        for method, operation in methods.items():
            if method.lower() not in CRUD_METHODS:
                continue
            if not isinstance(operation, dict):
                continue
            groups[stem].append((path, method.lower(), operation))

    return dict(groups)


def _assign_crud_roles(
    entries: list[tuple[str, str, dict]],
) -> dict[CRUDRole, tuple[str, str, dict]]:
    """Assign CRUD roles to grouped path/method entries."""
    roles: dict[CRUDRole, tuple[str, str, dict]] = {}

    for path, method, operation in entries:
        detail = is_detail_path(path)

        if method == "post" and not detail:
            roles[CRUDRole.CREATE] = (path, method, operation)
        elif method == "get" and detail:
            roles[CRUDRole.READ] = (path, method, operation)
        elif method == "get" and not detail:
            roles[CRUDRole.LIST] = (path, method, operation)
        elif method in ("put", "patch") and detail:
            # Prefer PUT for full update, but PATCH is acceptable
            if CRUDRole.UPDATE not in roles or method == "put":
                roles[CRUDRole.UPDATE] = (path, method, operation)
        elif method == "delete" and detail:
            roles[CRUDRole.DELETE] = (path, method, operation)

    return roles


def _detect_id_field(
    roles: dict[CRUDRole, tuple[str, str, dict]],
) -> str:
    """Detect the ID field from path parameters and response schemas."""
    # Check path parameter on detail paths
    for role in (CRUDRole.READ, CRUDRole.UPDATE, CRUDRole.DELETE):
        if role in roles:
            path = roles[role][0]
            params = get_path_parameters(path)
            if params:
                # Use the last path param (e.g., /orgs/{orgId}/pets/{petId} -> petId)
                return params[-1]

    # Check create response for id field
    if CRUDRole.CREATE in roles:
        _, _, operation = roles[CRUDRole.CREATE]
        resp_schema = get_success_response_schema(operation)
        props = resp_schema.get("properties", {})
        if "id" in props:
            return "id"

    return "id"  # default fallback


def _build_resource(
    provider_name: str,
    stem: str,
    roles: dict[CRUDRole, tuple[str, str, dict]],
) -> ResourceDef:
    """Build a ResourceDef from CRUD roles."""
    noun = _slug_to_noun(stem)
    tf_name = terraform_resource_name(provider_name, noun)
    id_field = _detect_id_field(roles)

    endpoints: dict[CRUDRole, EndpointDef] = {}
    for role, (path, method, operation) in roles.items():
        if role == CRUDRole.LIST:
            continue  # list is for data sources
        op_id = operation.get("operationId", "")
        endpoints[role] = EndpointDef(
            path=path,
            method=method.upper(),
            role=role,
            operation_id=op_id,
        )

    # Merge attributes from create request + read response
    request_attrs = []
    response_attrs = []

    if CRUDRole.CREATE in roles:
        _, _, create_op = roles[CRUDRole.CREATE]
        req_schema = get_request_body_schema(create_op)
        if req_schema:
            request_attrs = map_schema_to_attributes(req_schema)

    if CRUDRole.READ in roles:
        _, _, read_op = roles[CRUDRole.READ]
        resp_schema = get_success_response_schema(read_op)
        if resp_schema:
            response_attrs = map_schema_to_attributes(resp_schema, read_only=True)

    attributes = merge_attributes(request_attrs, response_attrs)

    # Ensure the id_field is present as an attribute (may come from path params)
    attr_names = {a.name for a in attributes}
    id_tf = to_snake_case(id_field)
    if id_tf and id_tf not in attr_names and id_tf != "id":
        from api2tf._types import AttributeDef, TFType, AttrComputability
        attributes.insert(0, AttributeDef(
            name=id_tf,
            tf_type=TFType.STRING,
            computability=AttrComputability.COMPUTED,
            sensitive=False,
            description=f"ID parameter ({id_field})",
        ))
    elif id_tf and id_tf not in attr_names and id_tf == "id":
        from api2tf._types import AttributeDef, TFType, AttrComputability
        attributes.insert(0, AttributeDef(
            name="id",
            tf_type=TFType.STRING,
            computability=AttrComputability.COMPUTED,
            sensitive=False,
            description="Resource identifier",
        ))

    # Confidence score
    confidence = sum(
        1 for r in (CRUDRole.CREATE, CRUDRole.READ, CRUDRole.DELETE) if r in roles
    )

    description = ""
    if CRUDRole.CREATE in roles:
        _, _, op = roles[CRUDRole.CREATE]
        description = op.get("summary", "") or op.get("description", "")

    return ResourceDef(
        terraform_name=tf_name,
        noun=noun,
        endpoints=endpoints,
        attributes=attributes,
        id_field=id_field,
        confidence=confidence,
        description=description,
    )


def _build_data_source(
    provider_name: str,
    stem: str,
    roles: dict[CRUDRole, tuple[str, str, dict]],
) -> DataSourceDef | None:
    """Build a DataSourceDef from a LIST or READ-only role."""
    if CRUDRole.LIST in roles:
        path, method, operation = roles[CRUDRole.LIST]
        noun = to_snake_case(stem)
        tf_name = terraform_datasource_name(provider_name, noun)
    elif CRUDRole.READ in roles and CRUDRole.CREATE not in roles:
        # Read-only endpoint -> data source
        path, method, operation = roles[CRUDRole.READ]
        noun = _slug_to_noun(stem)
        tf_name = terraform_datasource_name(provider_name, noun)
    else:
        return None

    resp_schema = get_success_response_schema(operation)
    attributes = map_schema_to_attributes(resp_schema, read_only=True) if resp_schema else []

    endpoint = EndpointDef(
        path=path,
        method=method.upper(),
        role=CRUDRole.LIST if CRUDRole.LIST in roles else CRUDRole.READ,
        operation_id=operation.get("operationId", ""),
    )

    description = operation.get("summary", "") or operation.get("description", "")

    return DataSourceDef(
        terraform_name=tf_name,
        noun=noun,
        endpoint=endpoint,
        attributes=attributes,
        description=description,
    )


def _infer_auth_schemes(
    provider_name: str,
    security_schemes: dict[str, dict],
) -> list[AuthSchemeDef]:
    """Infer Terraform provider auth attributes from securitySchemes."""
    auth_defs: list[AuthSchemeDef] = []

    for name, scheme in security_schemes.items():
        scheme_type = scheme.get("type", "")

        if scheme_type == "apiKey":
            location = scheme.get("in", "header")
            param_name = scheme.get("name", "")
            tf_attr = to_snake_case(param_name) if param_name else "api_key"
            auth_defs.append(AuthSchemeDef(
                scheme_type="apiKey",
                param_name=param_name,
                param_location=location,
                tf_attr_name=tf_attr,
                env_var=env_var_name(provider_name, tf_attr),
                description=f"API key ({location}: {param_name})",
            ))

        elif scheme_type == "http":
            http_scheme = scheme.get("scheme", "bearer")
            if http_scheme == "bearer":
                auth_defs.append(AuthSchemeDef(
                    scheme_type="http",
                    http_scheme="bearer",
                    tf_attr_name="api_token",
                    env_var=env_var_name(provider_name, "api_token"),
                    description="Bearer token for API authentication",
                ))
            elif http_scheme == "basic":
                auth_defs.append(AuthSchemeDef(
                    scheme_type="http",
                    http_scheme="basic",
                    tf_attr_name="username",
                    env_var=env_var_name(provider_name, "username"),
                    description="Username for basic authentication",
                ))
                auth_defs.append(AuthSchemeDef(
                    scheme_type="http",
                    http_scheme="basic",
                    tf_attr_name="password",
                    env_var=env_var_name(provider_name, "password"),
                    description="Password for basic authentication",
                ))

        elif scheme_type == "oauth2":
            flows = scheme.get("flows", {})
            # Prefer client_credentials, then authorizationCode
            for flow_name in ("clientCredentials", "authorizationCode"):
                if flow_name in flows:
                    flow = flows[flow_name]
                    auth_defs.append(AuthSchemeDef(
                        scheme_type="oauth2",
                        token_url=flow.get("tokenUrl", ""),
                        scopes=list(flow.get("scopes", {}).keys()),
                        tf_attr_name="client_id",
                        env_var=env_var_name(provider_name, "client_id"),
                        description="OAuth2 client ID",
                    ))
                    auth_defs.append(AuthSchemeDef(
                        scheme_type="oauth2",
                        token_url=flow.get("tokenUrl", ""),
                        tf_attr_name="client_secret",
                        env_var=env_var_name(provider_name, "client_secret"),
                        description="OAuth2 client secret",
                    ))
                    break

    # Deduplicate by tf_attr_name (first wins)
    seen: set[str] = set()
    unique: list[AuthSchemeDef] = []
    for a in auth_defs:
        if a.tf_attr_name not in seen:
            seen.add(a.tf_attr_name)
            unique.append(a)
    return unique


def infer_provider(
    spec: dict,
    *,
    provider_name: str | None = None,
    go_module: str | None = None,
    base_url: str | None = None,
    ignore_paths: list[str] | None = None,
) -> ProviderDef:
    """Infer a complete ProviderDef from an OpenAPI spec.

    This is the main entry point for the inference engine.
    """
    info = get_spec_info(spec)
    name = provider_name or provider_name_from_title(info["title"])
    module = go_module or f"github.com/{name}/terraform-provider-{name}"
    url = base_url or get_base_url(spec)

    # Group paths and assign CRUD roles
    paths = get_paths(spec)
    groups = _group_paths(paths)

    ignore = set(ignore_paths or [])
    resources: list[ResourceDef] = []
    data_sources: list[DataSourceDef] = []
    low_confidence: list[str] = []

    for stem, entries in groups.items():
        # Check ignore patterns
        sample_path = entries[0][0]
        if _should_ignore(sample_path, ignore):
            logger.info("Ignoring path group: %s", stem)
            continue

        roles = _assign_crud_roles(entries)

        # Build resource if sufficient CRUD coverage
        has_create = CRUDRole.CREATE in roles
        has_read = CRUDRole.READ in roles
        if has_create and has_read:
            resource = _build_resource(name, stem, roles)
            resources.append(resource)
            if resource.confidence < 3:
                low_confidence.append(resource.terraform_name)

        # Build data source if list endpoint exists
        ds = _build_data_source(name, stem, roles)
        if ds:
            data_sources.append(ds)

    if low_confidence:
        logger.warning(
            "%d resource(s) have partial CRUD (missing delete or update). "
            "Use --verbose to list them.",
            len(low_confidence),
        )
        for name_lc in low_confidence:
            logger.debug("  Low confidence: %s", name_lc)

    # Infer auth
    security_schemes = get_security_schemes(spec)
    auth_schemes = _infer_auth_schemes(name, security_schemes)

    return ProviderDef(
        name=name,
        go_module=module,
        base_url=url,
        description=info.get("description", ""),
        auth_schemes=auth_schemes,
        resources=resources,
        data_sources=data_sources,
    )


def _should_ignore(path: str, ignore_patterns: set[str]) -> bool:
    """Check if a path matches any ignore pattern."""
    import fnmatch

    for pattern in ignore_patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False
