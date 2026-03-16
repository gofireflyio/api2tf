# Contributing to api2tf

Thank you for your interest in contributing to api2tf! This guide will help you get started.

## Development Setup

```bash
git clone https://github.com/gofireflyio/api2tf.git
cd api2tf
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test,smart]"
```

## Running Tests

```bash
# Unit tests (fast, no external dependencies)
pytest tests/ -m "not integration" -v

# Integration tests (requires Docker)
pytest tests/test_integration.py -m integration -v

# All tests
pytest tests/ -v
```

## Project Structure

```
src/api2tf/
  _cli.py          CLI entry point and subcommands
  _openapi.py      OpenAPI spec parsing and $ref resolution
  _inference.py    CRUD pattern detection engine
  _schema_mapper.py  OpenAPI → Terraform type mapping
  _codegen.py      Jinja2 template rendering and file writing
  _diffing.py      Spec diffing and incremental updates
  _config.py       Override config parsing
  _types.py        Core data classes
  _helpers.py      String utilities and naming conventions
  _llm.py          LLM-assisted analysis (optional)
  templates/       Jinja2 templates for Go code generation
```

## How to Contribute

1. **Fork** the repository
2. **Create a branch** for your feature or fix (`git checkout -b feature/my-feature`)
3. **Write tests** for any new functionality
4. **Run the test suite** to make sure nothing is broken
5. **Submit a pull request** with a clear description of the change

## Guidelines

- Keep changes focused — one feature or fix per PR
- Add tests for new functionality
- Follow the existing code style
- Update documentation if your change affects user-facing behavior

## Reporting Issues

Please open an issue on [GitHub](https://github.com/gofireflyio/api2tf/issues) with:
- A description of the problem
- The OpenAPI spec (or a minimal reproduction) that triggers the issue
- The expected vs actual behavior
- Your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
