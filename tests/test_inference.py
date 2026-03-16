"""Tests for CRUD inference engine."""

from api2tf._openapi import resolve_refs
from api2tf._inference import infer_provider
from api2tf._types import CRUDRole


class TestCRUDInference:
    def test_detects_pet_resource(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        names = [r.terraform_name for r in provider.resources]
        assert "petstore_pet" in names

    def test_detects_owner_resource(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        names = [r.terraform_name for r in provider.resources]
        assert "petstore_owner" in names

    def test_pet_has_full_crud(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        assert CRUDRole.CREATE in pet.endpoints
        assert CRUDRole.READ in pet.endpoints
        assert CRUDRole.UPDATE in pet.endpoints
        assert CRUDRole.DELETE in pet.endpoints

    def test_owner_missing_update(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        owner = next(r for r in provider.resources if r.terraform_name == "petstore_owner")
        assert CRUDRole.CREATE in owner.endpoints
        assert CRUDRole.READ in owner.endpoints
        assert CRUDRole.UPDATE not in owner.endpoints
        assert CRUDRole.DELETE in owner.endpoints

    def test_pet_confidence_score(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        assert pet.confidence == 3  # create + read + delete

    def test_pet_id_field(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        assert pet.id_field == "petId"

    def test_detects_data_sources(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        ds_names = [ds.terraform_name for ds in provider.data_sources]
        assert "petstore_pets" in ds_names
        assert "petstore_owners" in ds_names

    def test_health_not_a_resource(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        names = [r.terraform_name for r in provider.resources]
        assert not any("health" in n for n in names)


class TestProviderInference:
    def test_provider_name(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        assert provider.name == "petstore"

    def test_provider_name_override(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved, provider_name="custom")
        assert provider.name == "custom"

    def test_base_url(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        assert provider.base_url == "https://api.petstore.example.com/v1"

    def test_auth_schemes(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        assert len(provider.auth_schemes) == 1
        assert provider.auth_schemes[0].scheme_type == "http"
        assert provider.auth_schemes[0].http_scheme == "bearer"
        assert provider.auth_schemes[0].env_var == "PETSTORE_API_TOKEN"


class TestAttributeInference:
    def test_pet_has_attributes(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        attr_names = [a.name for a in pet.attributes]
        assert "name" in attr_names
        assert "species" in attr_names

    def test_pet_name_is_required(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        name_attr = next(a for a in pet.attributes if a.name == "name")
        from api2tf._types import AttrComputability
        assert name_attr.computability == AttrComputability.REQUIRED

    def test_species_has_enum(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        species_attr = next(a for a in pet.attributes if a.name == "species")
        assert species_attr.enum_values == ["dog", "cat", "bird", "fish"]

    def test_id_is_computed(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        id_attr = next((a for a in pet.attributes if a.name == "id"), None)
        if id_attr:
            from api2tf._types import AttrComputability
            assert id_attr.computability == AttrComputability.COMPUTED


class TestSlugToNoun:
    """Test that _slug_to_noun singularizes only the last segment."""

    def test_simple_plural(self):
        from api2tf._inference import _slug_to_noun
        assert _slug_to_noun("pets") == "pet"

    def test_compound_last_segment_plural(self):
        from api2tf._inference import _slug_to_noun
        assert _slug_to_noun("access_credentials_postgres") == "access_credentials_postgres"

    def test_compound_last_segment_redis(self):
        from api2tf._inference import _slug_to_noun
        assert _slug_to_noun("access_credentials_redis") == "access_credentials_redis"

    def test_compound_last_segment_regular_plural(self):
        from api2tf._inference import _slug_to_noun
        assert _slug_to_noun("access_policies") == "access_policy"

    def test_compound_last_segment_users(self):
        from api2tf._inference import _slug_to_noun
        assert _slug_to_noun("api_users") == "api_user"


class TestIdFieldInjection:
    """Test that path-param ID fields are added to attributes when missing."""

    def test_id_field_added_when_missing(self, petstore_spec_resolved):
        """If the id_field comes from a path param not in response body, it should be injected."""
        provider = infer_provider(petstore_spec_resolved)
        pet = next(r for r in provider.resources if r.terraform_name == "petstore_pet")
        attr_names = [a.name for a in pet.attributes]
        # pet_id comes from path param {petId} and should exist as an attribute
        assert "pet_id" in attr_names or "id" in attr_names


class TestIgnorePaths:
    def test_ignore_health(self, petstore_spec_resolved):
        provider = infer_provider(petstore_spec_resolved, ignore_paths=["/health"])
        names = [r.terraform_name for r in provider.resources]
        ds_names = [ds.terraform_name for ds in provider.data_sources]
        all_names = names + ds_names
        assert not any("health" in n for n in all_names)
