"""Integration tests — generate a provider and verify Go compilation.

These tests require Docker to be available and are marked with @pytest.mark.integration.
Run with: pytest tests/test_integration.py -m integration
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from api2tf._openapi import load_spec
from api2tf._inference import infer_provider
from api2tf._codegen import generate_files, write_files

# Skip all tests in this file if Docker is not available
pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _go_compile(output_dir: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run go mod tidy && go build in a Docker container."""
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{output_dir}:/app",
            "-w", "/app",
            "golang:1.22",
            "sh", "-c", "go mod tidy && go build ./...",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def petstore_provider(petstore_spec_resolved):
    """Generate a petstore provider in a temp directory."""
    provider = infer_provider(petstore_spec_resolved, provider_name="petstore")
    files = generate_files(provider, petstore_spec_resolved)
    tmpdir = tempfile.mkdtemp(prefix="api2tf_test_")
    outdir = Path(tmpdir) / "terraform-provider-petstore"
    write_files(outdir, files, provider=provider, spec=petstore_spec_resolved)
    yield str(outdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
class TestGoCompilation:
    def test_petstore_compiles(self, petstore_provider):
        """Generated petstore provider compiles with Go."""
        result = _go_compile(petstore_provider)
        assert result.returncode == 0, f"Go build failed:\n{result.stderr}"

    def test_petstore_has_expected_files(self, petstore_provider):
        """Generated provider contains required files."""
        assert os.path.exists(os.path.join(petstore_provider, "main.go"))
        assert os.path.exists(os.path.join(petstore_provider, "go.mod"))
        assert os.path.exists(os.path.join(petstore_provider, "internal", "provider", "provider.go"))
        assert os.path.exists(os.path.join(petstore_provider, "internal", "client", "client.go"))

    def test_petstore_resource_files_exist(self, petstore_provider):
        """Resource schema, CRUD, and override files are generated."""
        base = os.path.join(petstore_provider, "internal", "provider")
        assert os.path.exists(os.path.join(base, "resource_pet_schema_gen.go"))
        assert os.path.exists(os.path.join(base, "resource_pet_crud_gen.go"))
        assert os.path.exists(os.path.join(base, "resource_pet_override.go"))

    def test_petstore_examples_exist(self, petstore_provider):
        """Example .tf files are generated."""
        assert os.path.exists(os.path.join(petstore_provider, "examples", "provider", "provider.tf"))
        assert os.path.exists(
            os.path.join(petstore_provider, "examples", "resources", "petstore_pet", "resource.tf")
        )

    def test_go_mod_module_path(self, petstore_provider):
        """go.mod has the correct module path."""
        with open(os.path.join(petstore_provider, "go.mod")) as f:
            content = f.read()
        assert "terraform-provider-petstore" in content


class TestGenerateFileCount:
    """Non-Docker tests that verify generation without compilation."""

    def test_petstore_file_count(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved, provider_name="petstore")
        files = generate_files(provider, petstore_spec_resolved)
        gen_files = [f for f in files if "_gen." in f]
        override_files = [f for f in files if "_override" in f]
        assert len(gen_files) > 0
        assert len(override_files) > 0
        # At least: main.go, go.mod, provider.go, client.go + per-resource files
        assert len(files) >= 10

    def test_all_gen_files_have_header(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved, provider_name="petstore")
        files = generate_files(provider, petstore_spec_resolved)
        for path, content in files.items():
            if "_gen." in path:
                assert "DO NOT EDIT" in content, f"Missing header in {path}"
