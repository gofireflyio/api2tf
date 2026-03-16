"""Tests for spec diffing and state management."""

import json
from pathlib import Path

from api2tf._diffing import compute_spec_hash, load_state, save_state, diff_file, plan_generation
from api2tf._inference import infer_provider


class TestSpecHash:
    def test_deterministic(self):
        spec = {"paths": {"/a": {}}, "info": {"title": "Test"}}
        h1 = compute_spec_hash(spec)
        h2 = compute_spec_hash(spec)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_different_specs_different_hashes(self):
        s1 = {"paths": {"/a": {}}}
        s2 = {"paths": {"/b": {}}}
        assert compute_spec_hash(s1) != compute_spec_hash(s2)


class TestStatePersistence:
    def test_save_and_load(self, petstore_spec_resolved, tmp_output):
        provider = infer_provider(petstore_spec_resolved)
        save_state(tmp_output, provider, "sha256:abc", "0.1.0", ["override.go"])

        state = load_state(tmp_output)
        assert state is not None
        assert state.spec_hash == "sha256:abc"
        assert state.api2tf_version == "0.1.0"
        assert "override.go" in state.override_files

    def test_load_missing_state(self, tmp_output):
        state = load_state(tmp_output)
        assert state is None


class TestDiffFile:
    def test_new_file(self, tmp_path):
        result = diff_file(tmp_path / "new.go", "package main\n")
        assert result is not None
        assert "+package main" in result

    def test_identical_file(self, tmp_path):
        f = tmp_path / "same.go"
        f.write_text("package main\n")
        result = diff_file(f, "package main\n")
        assert result is None

    def test_changed_file(self, tmp_path):
        f = tmp_path / "changed.go"
        f.write_text("package main\n")
        result = diff_file(f, "package provider\n")
        assert result is not None
