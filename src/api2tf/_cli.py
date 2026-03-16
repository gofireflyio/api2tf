"""CLI interface for api2tf."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from api2tf import __version__

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="api2tf",
        description="Generate complete Terraform providers from OpenAPI specs.",
    )
    parser.add_argument("--version", action="version", version=f"api2tf {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # generate
    gen = subparsers.add_parser("generate", help="Generate a Terraform provider from an OpenAPI spec")
    gen.add_argument("spec", help="Path or URL to the OpenAPI spec (JSON or YAML)")
    gen.add_argument("-o", "--output-dir", help="Output directory (default: ./terraform-provider-{name}/)")
    gen.add_argument("--provider-name", help="Terraform provider name (default: inferred from spec title)")
    gen.add_argument("--base-url", help="API base URL override")
    gen.add_argument("--go-module", help="Go module path")
    gen.add_argument("--config", default="api2tf.override.yaml", help="Override config file path")
    gen.add_argument("--no-config", action="store_true", help="Ignore override config")
    gen.add_argument("--include", nargs="*", help="Glob patterns: only generate matching resources")
    gen.add_argument("--exclude", nargs="*", help="Glob patterns: skip matching resources")
    gen.add_argument("--dry-run", action="store_true", help="Show what would be generated without writing")
    gen.add_argument("--diff", action="store_true", help="Show unified diff of changes")
    gen.add_argument("--force", action="store_true", help="Overwrite override files")
    gen.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # inspect
    insp = subparsers.add_parser("inspect", help="Show detected resources and auth from an OpenAPI spec")
    insp.add_argument("spec", help="Path or URL to the OpenAPI spec")
    insp.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # diff
    df = subparsers.add_parser("diff", help="Show changes between two OpenAPI spec versions")
    df.add_argument("old_spec", help="Path to the old spec")
    df.add_argument("new_spec", help="Path to the new spec")
    df.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # init
    init_cmd = subparsers.add_parser("init", help="Generate + run go mod tidy")
    init_cmd.add_argument("spec", help="Path or URL to the OpenAPI spec")
    init_cmd.add_argument("-o", "--output-dir", help="Output directory")
    init_cmd.add_argument("--provider-name", help="Terraform provider name")
    init_cmd.add_argument("--base-url", help="API base URL override")
    init_cmd.add_argument("--go-module", help="Go module path")
    init_cmd.add_argument("--config", default="api2tf.override.yaml", help="Override config file path")
    init_cmd.add_argument("--no-config", action="store_true", help="Ignore override config")
    init_cmd.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    return parser


def _cmd_generate(args: argparse.Namespace) -> None:
    """Handle the 'generate' command."""
    from api2tf._openapi import load_spec
    from api2tf._inference import infer_provider
    from api2tf._config import load_config, apply_overrides
    from api2tf._codegen import generate_files, write_files

    spec = load_spec(args.spec)

    # Load override config
    config_path = None if args.no_config else args.config
    config = load_config(config_path)

    # Infer provider
    provider = infer_provider(
        spec,
        provider_name=args.provider_name or config.provider_name,
        go_module=args.go_module or config.go_module,
        base_url=args.base_url,
        ignore_paths=config.ignore_paths,
    )

    # Apply overrides
    apply_overrides(config, provider)

    # Determine output directory
    output_dir = Path(args.output_dir or f"./terraform-provider-{provider.name}/")

    # Generate files
    file_contents = generate_files(provider, spec)

    # Write files
    write_files(
        output_dir,
        file_contents,
        force=args.force,
        dry_run=args.dry_run,
        show_diff=args.diff,
        provider=provider,
        spec=spec,
        version=__version__,
    )


def _cmd_inspect(args: argparse.Namespace) -> None:
    """Handle the 'inspect' command."""
    from api2tf._openapi import load_spec, get_spec_info
    from api2tf._inference import infer_provider

    spec = load_spec(args.spec)
    info = get_spec_info(spec)
    provider = infer_provider(spec)

    print(f"API: {info['title']} (v{info['version']})")
    print(f"Provider name: {provider.name}")
    print(f"Base URL: {provider.base_url}")
    print()

    if provider.auth_schemes:
        print("Auth schemes:")
        for auth in provider.auth_schemes:
            print(f"  - {auth.tf_attr_name} ({auth.scheme_type}) -> env: {auth.env_var}")
        print()

    print(f"Resources ({len(provider.resources)}):")
    for r in provider.resources:
        roles = ", ".join(role.value for role in r.endpoints.keys())
        confidence = "*" * r.confidence
        print(f"  - {r.terraform_name} [{roles}] ({len(r.attributes)} attrs) {confidence}")

    print()
    print(f"Data Sources ({len(provider.data_sources)}):")
    for ds in provider.data_sources:
        print(f"  - {ds.terraform_name} ({len(ds.attributes)} attrs)")


def _cmd_diff(args: argparse.Namespace) -> None:
    """Handle the 'diff' command."""
    from api2tf._openapi import load_spec
    from api2tf._inference import infer_provider

    old_spec = load_spec(args.old_spec)
    new_spec = load_spec(args.new_spec)

    old_provider = infer_provider(old_spec)
    new_provider = infer_provider(new_spec)

    old_resources = {r.terraform_name for r in old_provider.resources}
    new_resources = {r.terraform_name for r in new_provider.resources}

    added = new_resources - old_resources
    removed = old_resources - new_resources
    common = old_resources & new_resources

    if added:
        print("Added resources:")
        for name in sorted(added):
            r = next(r for r in new_provider.resources if r.terraform_name == name)
            roles = ", ".join(role.value for role in r.endpoints.keys())
            print(f"  + {name} [{roles}] ({len(r.attributes)} attrs)")

    if removed:
        print("Removed resources:")
        for name in sorted(removed):
            print(f"  - {name}")

    if common:
        print("Modified resources:")
        for name in sorted(common):
            old_r = next(r for r in old_provider.resources if r.terraform_name == name)
            new_r = next(r for r in new_provider.resources if r.terraform_name == name)
            old_attrs = {a.name for a in old_r.attributes}
            new_attrs = {a.name for a in new_r.attributes}
            added_attrs = new_attrs - old_attrs
            removed_attrs = old_attrs - new_attrs
            if added_attrs or removed_attrs:
                print(f"  ~ {name}")
                for a in sorted(added_attrs):
                    print(f"      + {a}")
                for a in sorted(removed_attrs):
                    print(f"      - {a}")

    if not added and not removed:
        # Check data sources too
        old_ds = {ds.terraform_name for ds in old_provider.data_sources}
        new_ds = {ds.terraform_name for ds in new_provider.data_sources}
        if old_ds == new_ds:
            print("No changes detected.")


def _cmd_init(args: argparse.Namespace) -> None:
    """Handle the 'init' command: generate + go mod tidy."""
    import subprocess

    # Reuse generate logic
    args.dry_run = False
    args.diff = False
    args.force = False
    args.no_config = getattr(args, "no_config", False)
    args.include = None
    args.exclude = None
    _cmd_generate(args)

    from api2tf._openapi import load_spec
    from api2tf._inference import infer_provider

    spec = load_spec(args.spec)
    provider = infer_provider(spec, provider_name=args.provider_name)
    output_dir = Path(args.output_dir or f"./terraform-provider-{provider.name}/")

    print("\nRunning go mod tidy...")
    result = subprocess.run(
        ["go", "mod", "tidy"],
        cwd=output_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"go mod tidy failed:\n{result.stderr}", file=sys.stderr)
    else:
        print("go mod tidy succeeded.")


def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "generate": _cmd_generate,
        "inspect": _cmd_inspect,
        "diff": _cmd_diff,
        "init": _cmd_init,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)
