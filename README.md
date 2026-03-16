# api2tf

Generate complete Terraform providers from OpenAPI specs.

Unlike HashiCorp's `terraform-plugin-codegen-openapi` which only generates schema stubs and requires a hand-written YAML config, api2tf **auto-detects CRUD patterns** from REST conventions and generates actual HTTP client code, provider auth configuration, and full Create/Read/Update/Delete implementations.

## Install

```bash
pip install api2tf
```

## Quick Start

```bash
# Generate a Terraform provider from a Petstore API spec
api2tf generate petstore.yaml

# See what would be generated without writing files
api2tf generate petstore.yaml --dry-run

# Inspect detected resources and auth schemes
api2tf inspect petstore.yaml

# Generate with custom provider name and output directory
api2tf generate petstore.yaml --provider-name myapi -o ./terraform-provider-myapi/
```

## What Gets Generated

```
terraform-provider-{name}/
  main.go
  go.mod
  internal/
    provider/
      provider.go                          # Provider with auth from securitySchemes
      resource_{noun}_schema_gen.go        # Schema + model structs (always regenerated)
      resource_{noun}_crud_gen.go          # CRUD logic + HTTP calls (always regenerated)
      resource_{noun}_override.go          # Your customizations (never overwritten)
      data_source_{noun}_schema_gen.go
      data_source_{noun}_read_gen.go
      data_source_{noun}_override.go
    client/
      client.go                            # HTTP client with auth
      {noun}.go                            # Per-resource API methods
  examples/
    provider/provider.tf
```

## Incremental Updates

When your API spec changes, re-run `api2tf generate` — it safely updates `_gen.go` files while preserving your `_override.go` customizations.

```bash
# Show what would change
api2tf generate updated-spec.yaml --diff

# Compare two spec versions
api2tf diff old-spec.yaml new-spec.yaml
```

## Override Config

For when auto-detection isn't enough, create an `api2tf.override.yaml`:

```yaml
version: "1"
provider:
  name: myapi
resources:
  myapi_widget:
    create:
      path: /v2/widgets
      method: POST
    id_field: widget_id
    attributes:
      internal_code:
        ignore: true
      secret_key:
        sensitive: true
ignore_paths:
  - /health
  - /metrics
```

## Commands

| Command | Description |
|---------|-------------|
| `api2tf generate <spec>` | Generate a Terraform provider |
| `api2tf inspect <spec>` | Show detected resources and auth |
| `api2tf diff <old> <new>` | Compare two spec versions |
| `api2tf init <spec>` | Generate + run `go mod tidy` |

## How It Works

1. **Parses** OpenAPI 3.0.x/3.1.x specs (JSON or YAML)
2. **Infers** CRUD patterns from REST conventions (POST=Create, GET/{id}=Read, PUT=Update, DELETE=Delete)
3. **Maps** OpenAPI types to Terraform Plugin Framework types
4. **Generates** Go source code via Jinja2 templates
5. **Preserves** manual customizations across regeneration

See [DESIGN.md](DESIGN.md) for the full architecture.

## License

MIT
