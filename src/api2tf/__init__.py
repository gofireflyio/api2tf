"""api2tf: Generate complete Terraform providers from OpenAPI specs."""

__version__ = "0.1.0"


def main() -> None:
    """Entry point for the api2tf CLI."""
    from api2tf._cli import main as _main

    _main()
