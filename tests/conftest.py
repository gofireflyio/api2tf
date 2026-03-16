"""Shared test fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def petstore_spec() -> dict:
    """Load the petstore OpenAPI spec as a dict."""
    raw = (FIXTURES_DIR / "petstore.yaml").read_text()
    return yaml.safe_load(raw)


@pytest.fixture
def petstore_spec_resolved(petstore_spec: dict) -> dict:
    """Load the petstore spec with $refs resolved."""
    from api2tf._openapi import resolve_refs

    return resolve_refs(petstore_spec)


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Provide a temporary output directory."""
    out = tmp_path / "terraform-provider-petstore"
    out.mkdir()
    return out
