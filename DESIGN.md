# api2tf — Design Document

## 1. Overview

`api2tf` is a Python CLI tool that takes an OpenAPI 3.0.x/3.1.x specification and generates a **complete, working** Terraform provider in Go targeting the Terraform Plugin Framework. Unlike HashiCorp's `terraform-plugin-codegen-openapi` (which only generates schema stubs and requires a hand-written YAML config), api2tf auto-detects CRUD patterns from REST conventions and generates actual HTTP client code, provider auth configuration, and full Create/Read/Update/Delete implementations.

### 1.1 Competitive Landscape

| Tool | Auto CRUD detection | Generates HTTP client | Generates CRUD logic | Incremental updates | Open source |
|------|--------------------|-----------------------|---------------------|--------------------|----|
| HashiCorp `tfplugingen-openapi` | No (manual YAML) | No | No | No | Yes |
| Speakeasy | No (proprietary `x-speakeasy-*` extensions) | Yes | Yes | Partial | No |
| **api2tf** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

---

## 2. Project Structure

```
api2tf/
  LICENSE
  README.md
  pyproject.toml
  uv.lock
  src/
    api2tf/
      __init__.py                   # version, re-exports
      __main__.py                   # python -m api2tf entry
      _cli.py                       # argparse CLI, subcommands
      _openapi.py                   # OpenAPI loading, $ref resolution, validation
      _inference.py                 # CRUD pattern detection, resource grouping
      _schema_mapper.py             # OpenAPI types -> Terraform attribute types
      _codegen.py                   # orchestrates template rendering, file writing
      _diffing.py                   # spec diffing, safe regeneration
      _config.py                    # override config loading/validation
      _types.py                     # dataclasses: ResourceDef, DataSourceDef, AttributeDef
      _helpers.py                   # naming conventions, string utils
      templates/                    # Jinja2 templates producing Go source
        main.go.j2
        provider.go.j2
        provider_test.go.j2
        resource_schema_gen.go.j2
        resource_crud_gen.go.j2
        resource_override.go.j2     # scaffold only (never regenerated)
        datasource_schema_gen.go.j2
        datasource_read_gen.go.j2
        datasource_override.go.j2   # scaffold only
        client.go.j2
        client_service.go.j2
        models.go.j2
        go.mod.j2
        doc.go.j2
        example.tf.j2
  tests/
    conftest.py
    test_inference.py
    test_schema_mapper.py
    test_codegen.py
    test_diffing.py
    test_config.py
    test_cli.py
    test_helpers.py
    fixtures/
      petstore.yaml
      petstore_extended.yaml
      complex_nested.yaml
      non_restful.yaml
      api2tf.override.yaml
```

### 2.1 Dependencies

```toml
[project]
name = "api2tf"
version = "0.1.0"
description = "Generate complete Terraform providers from OpenAPI specs"
requires-python = ">=3.10"
dependencies = [
    "pyyaml",
    "jinja2",
    "jsonschema",       # override config validation
    "deepdiff",         # spec diffing
]

[project.scripts]
api2tf = "api2tf:main"
```

---

## 3. CLI Interface

### 3.1 Primary Command: `generate`

```
api2tf generate <spec-path-or-url> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir`, `-o` | `./terraform-provider-{name}/` | Output directory |
| `--provider-name` | Inferred from `info.title` | Terraform provider name |
| `--base-url` | From `servers[0].url` | API base URL override |
| `--go-module` | `github.com/{org}/terraform-provider-{name}` | Go module path |
| `--config` | `api2tf.override.yaml` | Override config path |
| `--no-config` | — | Ignore override config |
| `--include` / `--exclude` | — | Glob patterns to filter resources |
| `--dry-run` | — | Show what would be generated |
| `--diff` | — | Show unified diff vs existing files |
| `--force` | — | Overwrite override files |
| `--verbose`, `-v` | — | Debug logging |

### 3.2 Other Commands

```
api2tf inspect <spec>           # show detected resources, data sources, auth schemes
api2tf diff <old-spec> <new-spec>  # show what changed between two spec versions
api2tf init <spec>              # generate + go mod tidy + verify compilation
api2tf version                  # print version
```

---

## 4. CRUD Inference Algorithm

This is the core differentiator. The algorithm works in four phases.

### Phase 1: Path Grouping

Group OpenAPI paths by their base noun (the "resource stem"):

```
/pets              -> stem "pets"
/pets/{petId}      -> stem "pets"
/pets/{petId}/vaccinations          -> stem "pets_vaccinations"
/pets/{petId}/vaccinations/{vacId}  -> stem "pets_vaccinations"
```

### Phase 2: CRUD Role Assignment

For each group, assign roles based on HTTP method + path shape:

| Method | Trailing `{id}`? | Role |
|--------|-------------------|------|
| POST   | No                | Create |
| GET    | Yes               | Read |
| GET    | No                | List (data source candidate) |
| PUT    | Yes               | Update (full replace) |
| PATCH  | Yes               | Update (partial) |
| DELETE | Yes               | Delete |

Confidence scoring:
- Create + Read + Delete = **high confidence resource** (score 3)
- Create + Read = **medium confidence** (score 2)
- List-only or Read-only = **data source only**
- Score < 2 = warn, generate with TODO comments

### Phase 3: ID Field Detection

1. Check path parameter name on the detail path (`{petId}` -> `pet_id`)
2. Check Create response (201/200) body for an `id` field
3. Check Read response for an `id` field
4. If response has a field matching the path parameter name, use it
5. Fallback: `id`

### Phase 4: Attribute Merging

Merge attributes from Create request body + Read response:

| Appears in... | Terraform mapping |
|---|---|
| Request body only | `Required` or `Optional` (per OpenAPI `required` array) |
| Response body only | `Computed: true` |
| Both | User-settable, also returned by API |
| `readOnly: true` | `Computed: true` |
| `writeOnly: true` | Plan-only, excluded from state |
| Name matches `password`, `secret`, `token`, `api_key` | `Sensitive: true` |

---

## 5. Schema Type Mapping

### 5.1 OpenAPI → Terraform Types

| OpenAPI Type | Format | Terraform Attribute | Go Type |
|---|---|---|---|
| `string` | — | `StringAttribute` | `types.String` |
| `string` | `date-time` | `StringAttribute` + RFC 3339 validator | `types.String` |
| `string` | `password` | `StringAttribute` + `Sensitive: true` | `types.String` |
| `string` + `enum` | — | `StringAttribute` + enum validator | `types.String` |
| `integer` | — | `Int64Attribute` | `types.Int64` |
| `number` | — | `Float64Attribute` | `types.Float64` |
| `boolean` | — | `BoolAttribute` | `types.Bool` |
| `array` of primitives | — | `ListAttribute` + `ElementType` | `types.List` |
| `array` of objects | — | `ListNestedAttribute` | `types.List` of nested |
| `object` (properties) | — | `SingleNestedAttribute` | nested struct |
| `object` (additionalProperties) | — | `MapAttribute` | `types.Map` |
| `oneOf` / `anyOf` | — | `StringAttribute` (JSON-encoded) | `types.String` |

### 5.2 Naming Conventions (per HashiCorp best practices)

- Resource names: `{provider}_{noun}` singular (`petstore_pet`)
- Data source names: `{provider}_{noun}` plural OK for lists (`petstore_pets`)
- Attributes: `lowercase_underscore` (`first_name`)
- Lists/sets/maps: plural nouns (`security_group_ids`)
- Booleans: positive logic, `true` = enabled (`monitoring`)
- Write-only args: `_wo` suffix (`password_wo`)
- Go struct fields: `PascalCase` (`FirstName`)

### 5.3 Nullable Handling

- OpenAPI 3.0.x: `nullable: true` → `Optional: true`
- OpenAPI 3.1.x: `type: ["string", "null"]` → `Optional: true`

---

## 6. Code Generation

### 6.1 Three-Layer File Separation

For each resource `foo`:

| Layer | File | Regenerated? | Contents |
|-------|------|-------------|----------|
| Schema | `resource_foo_schema_gen.go` | Always | `Schema()` method, model structs |
| CRUD | `resource_foo_crud_gen.go` | Always | `Create()`, `Read()`, `Update()`, `Delete()`, `ImportState()` |
| Override | `resource_foo_override.go` | First time only | Hook functions, custom validators, plan modifiers |

Generated files carry:
```go
// Code generated by api2tf from OpenAPI spec; DO NOT EDIT.
```

Override files carry:
```go
// This file is for manual customizations. api2tf will not overwrite it.
```

### 6.2 Generated Provider Directory

```
terraform-provider-{name}/
  main.go
  go.mod
  internal/
    provider/
      provider.go
      provider_test.go
      doc.go
      resource_{noun}_schema_gen.go
      resource_{noun}_crud_gen.go
      resource_{noun}_override.go
      data_source_{noun}_schema_gen.go
      data_source_{noun}_read_gen.go
      data_source_{noun}_override.go
    client/
      client.go                     # HTTP client, auth, base URL
      models.go                     # API request/response structs
      {noun}.go                     # per-resource service methods
  examples/
    provider/provider.tf
    resources/{noun}/resource.tf
    data-sources/{noun}/data-source.tf
  .goreleaser.yml
  GNUmakefile
```

### 6.3 Auth Generation from securitySchemes

| securityScheme | Provider Schema | Configure() behavior |
|---|---|---|
| `apiKey` (header) | `StringAttribute{Sensitive: true}` | Sets header on HTTP client |
| `apiKey` (query) | `StringAttribute{Sensitive: true}` | Sets query param |
| `http` (bearer) | `StringAttribute{Sensitive: true}` | Sets `Authorization: Bearer` header |
| `http` (basic) | username + password attrs | Sets basic auth |
| `oauth2` | client_id + client_secret | Token exchange in `Configure()` |

Each auth attribute also checks for an environment variable fallback (`{PROVIDER}_API_KEY`).

### 6.4 Generated CRUD Pattern

- **Create**: Plan → API struct → POST → set ID from response → GET to refresh → set state
- **Read**: State → GET by ID → handle 404 (remove from state) → map response to state
- **Update**: Plan → API struct → PUT/PATCH by ID → GET to refresh → set state
- **Delete**: State → DELETE by ID → handle errors
- **ImportState**: `resource.ImportStatePassthroughID(ctx, path.Root("id"), req, resp)`

### 6.5 Override Hooks

Users can implement optional hooks in `_override.go` files:

```go
func (r *PetResource) BeforeCreate(ctx context.Context, plan PetModel) (PetModel, diag.Diagnostics) {
    // custom logic before API call
}

func (r *PetResource) AfterRead(ctx context.Context, state *PetModel) diag.Diagnostics {
    // custom post-processing
}
```

Generated CRUD code calls these hooks if they exist.

### 6.6 Template Engine

Jinja2 with custom filters: `to_pascal_case`, `to_snake_case`, `go_type_for_tf_attr`, `quote`. Jinja2's template inheritance and macros reduce duplication across templates.

---

## 7. Incremental Update Flow

### 7.1 State File

On each generation, api2tf writes `.api2tf.state.json`:

```json
{
  "spec_hash": "sha256:abc123...",
  "generated_at": "2026-03-16T10:00:00Z",
  "api2tf_version": "0.1.0",
  "resources": {
    "petstore_pet": {
      "create_path": "/pets",
      "read_path": "/pets/{petId}",
      "attributes_hash": "sha256:def456..."
    }
  },
  "override_files": ["resource_pet_override.go"]
}
```

### 7.2 Update Algorithm

1. Load `.api2tf.state.json` from existing output
2. Parse the new spec, run CRUD inference
3. Compute diff:
   - **New resource** → generate all three layers
   - **Removed resource** → warn, do not delete
   - **Modified resource** → regenerate `_schema_gen.go` and `_crud_gen.go` only
4. Never overwrite `_override.go` (unless `--force`)
5. Update `.api2tf.state.json`
6. Update `provider.go` to register new resources/data sources

### 7.3 `--dry-run` Output

```
Would create: internal/provider/resource_widget_schema_gen.go
Would create: internal/provider/resource_widget_crud_gen.go
Would create: internal/provider/resource_widget_override.go
Would update: internal/provider/resource_pet_schema_gen.go  (added: color field)
Would update: internal/provider/resource_pet_crud_gen.go
Would skip:   internal/provider/resource_pet_override.go    (user override)
Unchanged:    internal/client/client.go
```

### 7.4 `api2tf diff` Command

Compares two spec versions and produces a human-readable changelog:

```
Added:    widget resource (4 endpoints: CRUD)
Modified: pet resource — added 'color' (string), removed 'legacy_id'
Modified: order data source — 'total' changed from integer to number
Removed:  tag resource (3 endpoints) — will NOT be deleted from generated code
```

---

## 8. Override Config Format

File: `api2tf.override.yaml`

```yaml
version: "1"

provider:
  name: petstore
  go_module: "github.com/example/terraform-provider-petstore"

# Manual CRUD mappings (when inference fails)
resources:
  petstore_pet:
    create:
      path: /v2/pets
      method: POST
    read:
      path: /v2/pets/{petId}
      method: GET
    update:
      path: /v2/pets/{petId}
      method: PUT
    delete:
      path: /v2/pets/{petId}
      method: DELETE
    id_field: pet_id
    attributes:
      status:
        computed: true
      internal_code:
        ignore: true
      owner_email:
        sensitive: true

  # Sub-resource with parent
  petstore_vaccination:
    create:
      path: /pets/{petId}/vaccinations
      method: POST
    read:
      path: /pets/{petId}/vaccinations/{vaccinationId}
      method: GET
    parent_id_field: petId
    parent_resource: petstore_pet

data_sources:
  petstore_pets:
    read:
      path: /pets
      method: GET

# Paths to skip entirely
ignore_paths:
  - /health
  - /metrics
  - /internal/*

# Global attribute renames
attribute_renames:
  firstName: first_name
  lastName: last_name

# Auth overrides
auth:
  scheme: bearer
  env_var: PETSTORE_API_TOKEN
```

---

## 9. Edge Cases and Limitations

### Will Handle

- **Composite IDs** (`/orgs/{orgId}/teams/{teamId}`) → composite ID format `orgId/teamId`, Import splits on `/`
- **`allOf` merging** → merge all branches, last wins on conflicts (with warning)
- **Missing `operationId`** → generate from `{method}_{path_slug}`
- **No `servers` block** → require `--base-url` flag
- **Server-side defaults** → `UseStateForUnknown` plan modifier after first create

### Won't Handle (v1)

- **Paginated list endpoints** — data sources call list once; pagination needs manual override
- **Async operations** (202 + polling) — generated code expects synchronous responses
- **Deeply nested objects (4+ levels)** — generates them but warns about schema complexity
- **`oneOf`/`anyOf`/`discriminator`** — falls back to JSON string attribute with TODO comment
- **File uploads (`multipart/form-data`)** — skipped with warning
- **WebSocket/streaming** — ignored
- **API versioning** (v1/v2 in same spec) — not handled

---

## 10. Implementation Phases

### Phase 1: MVP

| Module | What |
|--------|------|
| `_types.py` | Core data structures |
| `_openapi.py` | Spec loading, $ref resolution (port from mcp2cli) |
| `_inference.py` | CRUD detection + resource grouping |
| `_schema_mapper.py` | Type mapping |
| `_codegen.py` | Template rendering + file writing |
| Templates | main.go, provider.go, resource files, client files |
| `_cli.py` | `generate` command |
| Tests | Inference + schema mapping |

### Phase 2: Polish

| Feature | What |
|---------|------|
| `_config.py` | Override config support |
| `_diffing.py` | Spec diffing + safe updates |
| Modes | `--dry-run`, `--diff` |
| `inspect` | Subcommand |
| Data sources | Full generation |
| Auth | securitySchemes detection |

### Phase 3: Production

| Feature | What |
|---------|------|
| `init` | Subcommand (go mod tidy integration) |
| Import | Support for all resources |
| Tests | Acceptance test scaffolding in generated provider |
| Examples | .tf file generation |
| Release | `.goreleaser.yml` scaffolding |
| Edge cases | allOf, oneOf, nested objects, composite IDs |
