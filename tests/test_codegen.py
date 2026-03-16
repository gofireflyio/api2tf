"""Tests for code generation."""

from pathlib import Path

from api2tf._openapi import resolve_refs
from api2tf._inference import infer_provider
from api2tf._codegen import generate_files, write_files


class TestGenerateFiles:
    def test_generates_main_go(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "main.go" in files
        assert "providerserver" in files["main.go"]

    def test_generates_go_mod(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "go.mod" in files
        assert "terraform-plugin-framework" in files["go.mod"]

    def test_generates_provider_go(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/provider/provider.go" in files
        content = files["internal/provider/provider.go"]
        assert "PetstoreProvider" in content
        assert "NewPetResource" in content

    def test_generates_client(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/client/client.go" in files
        assert "NewClient" in files["internal/client/client.go"]

    def test_generates_resource_schema(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/provider/resource_pet_schema_gen.go" in files
        content = files["internal/provider/resource_pet_schema_gen.go"]
        assert "PetModel" in content
        assert "PetResourceSchema" in content

    def test_generates_resource_crud(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/provider/resource_pet_crud_gen.go" in files
        content = files["internal/provider/resource_pet_crud_gen.go"]
        assert "func (r *PetResource) Create" in content
        assert "func (r *PetResource) Read" in content
        assert "func (r *PetResource) Delete" in content
        assert "ImportState" in content

    def test_generates_resource_override(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/provider/resource_pet_override.go" in files
        assert "api2tf will not overwrite" in files["internal/provider/resource_pet_override.go"]

    def test_generates_client_service(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/client/pet.go" in files
        content = files["internal/client/pet.go"]
        assert "CreatePet" in content
        assert "GetPet" in content
        assert "DeletePet" in content

    def test_generates_data_source(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "internal/provider/data_source_pets_schema_gen.go" in files
        assert "internal/provider/data_source_pets_read_gen.go" in files

    def test_generates_example_tf(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        assert "examples/provider/provider.tf" in files

    def test_gen_files_have_do_not_edit_header(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        for path, content in files.items():
            if "_gen.go" in path:
                assert "DO NOT EDIT" in content, f"{path} missing DO NOT EDIT header"


class TestWriteFiles:
    def test_writes_files_to_disk(self, petstore_spec_resolved, tmp_output):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)
        write_files(tmp_output, files, provider=provider, spec=petstore_spec_resolved)

        assert (tmp_output / "main.go").exists()
        assert (tmp_output / "internal/provider/provider.go").exists()
        assert (tmp_output / "internal/client/client.go").exists()
        assert (tmp_output / ".api2tf.state.json").exists()

    def test_does_not_overwrite_override_files(self, petstore_spec_resolved, tmp_output):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)

        # First write
        write_files(tmp_output, files, provider=provider, spec=petstore_spec_resolved)

        # Modify an override file
        override_path = tmp_output / "internal/provider/resource_pet_override.go"
        override_path.write_text("// my custom code\npackage provider\n")

        # Second write
        write_files(tmp_output, files, provider=provider, spec=petstore_spec_resolved)

        # Override should be preserved
        assert override_path.read_text().startswith("// my custom code")

    def test_force_overwrites_override_files(self, petstore_spec_resolved, tmp_output):
        provider = infer_provider(petstore_spec_resolved)
        files = generate_files(provider, petstore_spec_resolved)

        # First write
        write_files(tmp_output, files, provider=provider, spec=petstore_spec_resolved)

        # Modify override
        override_path = tmp_output / "internal/provider/resource_pet_override.go"
        override_path.write_text("// my custom code\npackage provider\n")

        # Force write
        write_files(tmp_output, files, force=True, provider=provider, spec=petstore_spec_resolved)

        # Override should be replaced
        assert "api2tf will not overwrite" in override_path.read_text()
