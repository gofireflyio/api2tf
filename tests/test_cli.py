"""Tests for CLI argument parsing."""

from api2tf._cli import _build_parser


class TestParser:
    def test_generate_command(self):
        parser = _build_parser()
        args = parser.parse_args(["generate", "spec.yaml"])
        assert args.command == "generate"
        assert args.spec == "spec.yaml"

    def test_generate_with_options(self):
        parser = _build_parser()
        args = parser.parse_args([
            "generate", "spec.yaml",
            "-o", "./output",
            "--provider-name", "myapi",
            "--dry-run",
            "--verbose",
        ])
        assert args.output_dir == "./output"
        assert args.provider_name == "myapi"
        assert args.dry_run is True
        assert args.verbose is True

    def test_inspect_command(self):
        parser = _build_parser()
        args = parser.parse_args(["inspect", "spec.yaml"])
        assert args.command == "inspect"
        assert args.spec == "spec.yaml"

    def test_diff_command(self):
        parser = _build_parser()
        args = parser.parse_args(["diff", "old.yaml", "new.yaml"])
        assert args.command == "diff"
        assert args.old_spec == "old.yaml"
        assert args.new_spec == "new.yaml"

    def test_no_command_returns_none(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None
