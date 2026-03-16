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
    gen.add_argument("--smart", action="store_true", help="Use LLM (Claude) to analyze spec before generating")
    gen.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # inspect
    insp = subparsers.add_parser("inspect", help="Show detected resources and auth from an OpenAPI spec")
    insp.add_argument("spec", help="Path or URL to the OpenAPI spec")
    insp.add_argument("--smart", action="store_true", help="Use LLM (Claude) to analyze spec")
    insp.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # diff
    df = subparsers.add_parser("diff", help="Show changes between two OpenAPI spec versions")
    df.add_argument("old_spec", help="Path to the old spec")
    df.add_argument("new_spec", help="Path to the new spec")
    df.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # init
    init_cmd = subparsers.add_parser("init", help="Generate override config + provider code + go mod tidy")
    init_cmd.add_argument("spec", help="Path or URL to the OpenAPI spec")
    init_cmd.add_argument("-o", "--output-dir", help="Output directory")
    init_cmd.add_argument("--provider-name", help="Terraform provider name")
    init_cmd.add_argument("--base-url", help="API base URL override")
    init_cmd.add_argument("--go-module", help="Go module path")
    init_cmd.add_argument("--config", default="api2tf.override.yaml", help="Override config file path")
    init_cmd.add_argument("--no-config", action="store_true", help="Ignore override config")
    init_cmd.add_argument("--smart", action="store_true", help="Use LLM (Claude) to analyze spec")
    init_cmd.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # update
    upd = subparsers.add_parser("update", help="Update provider from a new spec version (with changelog)")
    upd.add_argument("new_spec", help="Path or URL to the updated OpenAPI spec")
    upd.add_argument("provider_dir", help="Path to the existing terraform-provider-* directory")
    upd.add_argument("--provider-name", help="Terraform provider name")
    upd.add_argument("--base-url", help="API base URL override")
    upd.add_argument("--go-module", help="Go module path")
    upd.add_argument("--config", default="api2tf.override.yaml", help="Override config file path")
    upd.add_argument("--no-config", action="store_true", help="Ignore override config")
    upd.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    upd.add_argument("--force", action="store_true", help="Overwrite override files")
    upd.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # validate
    val = subparsers.add_parser("validate", help="Compile generated Go code to check for errors")
    val.add_argument("provider_dir", help="Path to the generated terraform-provider-* directory")
    val.add_argument("--docker", action="store_true", default=True, help="Use Docker for compilation (default)")
    val.add_argument("--no-docker", dest="docker", action="store_false", help="Use local Go installation")
    val.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    return parser


def _cmd_generate(args: argparse.Namespace) -> None:
    """Handle the 'generate' command."""
    from api2tf._openapi import load_spec
    from api2tf._inference import infer_provider
    from api2tf._config import load_config, apply_overrides
    from api2tf._codegen import generate_files, write_files

    spec = load_spec(args.spec)

    # LLM analysis (optional)
    if getattr(args, "smart", False):
        from api2tf._llm import analyze_spec, merge_analysis_into_config
        analysis = analyze_spec(spec)
        if analysis:
            config_file = args.config if not args.no_config else "api2tf.override.yaml"
            merge_analysis_into_config(analysis, config_file)
            args.no_config = False
            args.config = config_file

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

    # Determine output directory — always use terraform-provider-{name} convention
    provider_dir = f"terraform-provider-{provider.name}"
    if args.output_dir:
        base = Path(args.output_dir)
        # If user already included the correct name, use as-is
        if base.name == provider_dir:
            output_dir = base
        else:
            output_dir = base / provider_dir
    else:
        output_dir = Path(f"./{provider_dir}/")

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

    # LLM analysis (optional)
    if getattr(args, "smart", False):
        from api2tf._llm import analyze_spec
        analysis = analyze_spec(spec)
        if analysis:
            print("\nLLM Analysis:")
            if analysis.get("provider_name"):
                print(f"  Suggested provider name: {analysis['provider_name']}")
            if analysis.get("ignore_paths"):
                print(f"  Suggested ignore paths: {', '.join(analysis['ignore_paths'])}")
            resources = analysis.get("resources", [])
            actions = [r for r in resources if r.get("resource_type") == "action"]
            if actions:
                print(f"  Non-CRUD endpoints (actions): {len(actions)}")
                for a in actions[:5]:
                    print(f"    - {a.get('terraform_name', '?')}: {a.get('description', '')}")
            print()

    provider = infer_provider(spec)

    print(f"API: {info['title']} (v{info['version']})")
    print(f"Provider name: {provider.name}")
    print(f"Base URL: {provider.base_url or '(not specified — use --base-url)'}")
    print()

    if provider.auth_schemes:
        print("Auth schemes:")
        for auth in provider.auth_schemes:
            print(f"  - {auth.tf_attr_name} ({auth.scheme_type}) -> env: {auth.env_var}")
        print()

    # Split resources by confidence
    full_crud = [r for r in provider.resources if r.confidence >= 3]
    partial_crud = [r for r in provider.resources if r.confidence < 3]

    print(f"Resources ({len(provider.resources)}):")
    if full_crud:
        print(f"  Full CRUD ({len(full_crud)}):")
        for r in full_crud:
            roles = ", ".join(role.value for role in r.endpoints.keys())
            print(f"    - {r.terraform_name} [{roles}] ({len(r.attributes)} attrs)")
    if partial_crud:
        print(f"  Partial CRUD ({len(partial_crud)}):")
        if getattr(args, "verbose", False):
            for r in partial_crud:
                roles = ", ".join(role.value for role in r.endpoints.keys())
                print(f"    - {r.terraform_name} [{roles}] ({len(r.attributes)} attrs)")
        else:
            # Show first 5, then summary
            for r in partial_crud[:5]:
                roles = ", ".join(role.value for role in r.endpoints.keys())
                print(f"    - {r.terraform_name} [{roles}] ({len(r.attributes)} attrs)")
            if len(partial_crud) > 5:
                print(f"    ... and {len(partial_crud) - 5} more (use -v to list all)")

    print()
    print(f"Data Sources ({len(provider.data_sources)}):")
    if getattr(args, "verbose", False):
        for ds in provider.data_sources:
            print(f"  - {ds.terraform_name} ({len(ds.attributes)} attrs)")
    else:
        for ds in provider.data_sources[:10]:
            print(f"  - {ds.terraform_name} ({len(ds.attributes)} attrs)")
        if len(provider.data_sources) > 10:
            print(f"  ... and {len(provider.data_sources) - 10} more (use -v to list all)")

    # Summary
    print()
    print(f"To generate: api2tf generate {args.spec} --provider-name {provider.name}")


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
    """Handle the 'init' command: generate override config + provider code + go mod tidy."""
    import subprocess

    from api2tf._openapi import load_spec
    from api2tf._inference import infer_provider

    spec = load_spec(args.spec)
    provider = infer_provider(
        spec,
        provider_name=args.provider_name,
        go_module=args.go_module,
        base_url=args.base_url,
    )

    # Step 1: Generate override config if it doesn't exist
    config_path = Path(args.config)
    if not config_path.exists():
        _generate_override_config(config_path, provider)
        print(f"Created {config_path} — review and customize before regenerating.")
    else:
        print(f"Config {config_path} already exists, skipping generation.")

    # Step 2: Generate provider code
    args.dry_run = False
    args.diff = False
    args.force = False
    args.no_config = getattr(args, "no_config", False)
    args.include = None
    args.exclude = None
    _cmd_generate(args)

    # Step 3: Determine output dir for go mod tidy
    provider_dir = f"terraform-provider-{provider.name}"
    if args.output_dir:
        base = Path(args.output_dir)
        output_dir = base / provider_dir if base.name != provider_dir else base
    else:
        output_dir = Path(f"./{provider_dir}/")

    # Step 4: Run go mod tidy
    print("\nRunning go mod tidy...")
    result = subprocess.run(
        ["go", "mod", "tidy"],
        cwd=output_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"go mod tidy failed:\n{result.stderr}", file=sys.stderr)
        print("Tip: If Go is not installed locally, use: api2tf validate <provider_dir>")
    else:
        print("go mod tidy succeeded.")


def _generate_override_config(path: Path, provider) -> None:
    """Generate an api2tf.override.yaml with all detected resources for customization."""
    with open(path, "w") as f:
        f.write("# api2tf override configuration\n")
        f.write("# Edit this file to customize the generated Terraform provider.\n")
        f.write("# Re-run 'api2tf generate' to apply changes.\n\n")
        f.write(f"provider:\n  name: {provider.name}\n\n")

        # Resources
        f.write("resources:\n")
        for r in provider.resources:
            roles = ", ".join(role.value for role in r.endpoints.keys())
            f.write(f"  {r.terraform_name}:\n")
            f.write(f"    enabled: true  # [{roles}] ({len(r.attributes)} attrs)\n")
            f.write(f"    # rename: \"\"  # Rename this resource\n")
            f.write(f"    # ignore_attributes: []  # Attributes to exclude\n")
        f.write("\n")

        # Data sources
        f.write("data_sources:\n")
        for ds in provider.data_sources:
            f.write(f"  {ds.terraform_name}:\n")
            f.write(f"    enabled: true  # ({len(ds.attributes)} attrs)\n")
        f.write("\n")

        # Ignore paths
        f.write("# ignore_paths:\n")
        f.write("#   - /health\n")
        f.write("#   - /internal/*\n")


def _cmd_update(args: argparse.Namespace) -> None:
    """Handle the 'update' command: regenerate from updated spec with changelog."""
    from api2tf._openapi import load_spec
    from api2tf._inference import infer_provider
    from api2tf._config import load_config, apply_overrides
    from api2tf._codegen import generate_files, write_files
    from api2tf._diffing import load_state, compute_spec_hash, plan_generation, format_plan

    provider_dir = Path(args.provider_dir)
    if not provider_dir.exists():
        print(f"Error: Directory '{provider_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Load previous state
    state = load_state(provider_dir)

    # Load new spec
    new_spec = load_spec(args.new_spec)
    new_hash = compute_spec_hash(new_spec)

    # Check if spec actually changed
    if state and state.spec_hash == new_hash:
        print("Spec has not changed since last generation. Nothing to update.")
        return

    # Load config
    config_path = None if args.no_config else args.config
    config = load_config(config_path)

    # Infer new provider
    new_provider = infer_provider(
        new_spec,
        provider_name=args.provider_name or config.provider_name,
        go_module=args.go_module or config.go_module,
        base_url=args.base_url,
        ignore_paths=config.ignore_paths,
    )
    apply_overrides(config, new_provider)

    # Generate changelog by comparing with state
    if state:
        old_resources = set(state.resources.keys())
        new_resources = {r.terraform_name for r in new_provider.resources}
        old_ds = set(state.data_sources.keys())
        new_ds = {ds.terraform_name for ds in new_provider.data_sources}

        added_r = new_resources - old_resources
        removed_r = old_resources - new_resources
        added_ds = new_ds - old_ds
        removed_ds = old_ds - new_ds

        print("Changelog:")
        if added_r:
            print(f"  Added resources ({len(added_r)}):")
            for name in sorted(added_r):
                r = next(r for r in new_provider.resources if r.terraform_name == name)
                roles = ", ".join(role.value for role in r.endpoints.keys())
                print(f"    + {name} [{roles}]")
        if removed_r:
            print(f"  Removed resources ({len(removed_r)}):")
            for name in sorted(removed_r):
                print(f"    - {name}")
        if added_ds:
            print(f"  Added data sources ({len(added_ds)}):")
            for name in sorted(added_ds):
                print(f"    + {name}")
        if removed_ds:
            print(f"  Removed data sources ({len(removed_ds)}):")
            for name in sorted(removed_ds):
                print(f"    - {name}")

        # Check for attribute changes in existing resources
        changed = []
        for r in new_provider.resources:
            if r.terraform_name in old_resources:
                old_info = state.resources[r.terraform_name]
                new_attrs = {a.name for a in r.attributes}
                # We don't store attrs in state, but we can detect endpoint changes
                old_endpoints = set(old_info.get("endpoints", {}).values())
                new_endpoints = {ep.path for ep in r.endpoints.values()}
                if old_endpoints != new_endpoints:
                    changed.append(r.terraform_name)
        if changed:
            print(f"  Modified resources ({len(changed)}):")
            for name in changed:
                print(f"    ~ {name}")

        if not added_r and not removed_r and not added_ds and not removed_ds and not changed:
            print("  No structural changes (attributes may have changed).")
        print()
    else:
        print("No previous state found — performing full generation.\n")

    # Generate files
    file_contents = generate_files(new_provider, new_spec)

    # Show plan in dry-run
    if args.dry_run:
        actions = plan_generation(provider_dir, new_provider, file_contents, state)
        print(format_plan(actions))
        return

    # Write files
    write_files(
        provider_dir,
        file_contents,
        force=args.force,
        dry_run=False,
        show_diff=False,
        provider=new_provider,
        spec=new_spec,
        version=__version__,
    )


def _cmd_validate(args: argparse.Namespace) -> None:
    """Handle the 'validate' command: compile generated Go code."""
    import subprocess

    provider_dir = Path(args.provider_dir)

    if not provider_dir.exists():
        print(f"Error: Directory '{provider_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    go_mod = provider_dir / "go.mod"
    if not go_mod.exists():
        print(f"Error: No go.mod found in '{provider_dir}'. Is this a generated provider?", file=sys.stderr)
        sys.exit(1)

    if args.docker:
        print(f"Validating {provider_dir} (using Docker)...")
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{provider_dir.resolve()}:/app",
                "-w", "/app",
                "golang:1.22",
                "sh", "-c", "go mod tidy && go build ./...",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    else:
        print(f"Validating {provider_dir} (using local Go)...")
        result = subprocess.run(
            ["sh", "-c", "go mod tidy && go build ./..."],
            cwd=provider_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )

    if result.returncode == 0:
        print("Validation passed — Go code compiles successfully.")
    else:
        # Parse and display errors cleanly
        errors = []
        for line in result.stderr.splitlines():
            if line.startswith("#") or ": " in line:
                errors.append(line)
        if errors:
            print("Validation failed — compilation errors:", file=sys.stderr)
            for err in errors:
                print(f"  {err}", file=sys.stderr)
        else:
            print(f"Validation failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


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
        "update": _cmd_update,
        "validate": _cmd_validate,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)
