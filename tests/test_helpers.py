"""Tests for naming conventions and string utilities."""

from api2tf._helpers import (
    to_snake_case,
    to_pascal_case,
    to_camel_case,
    singularize,
    pluralize,
    provider_name_from_title,
    is_sensitive_field,
    path_to_slug,
    terraform_resource_name,
    env_var_name,
)


class TestToSnakeCase:
    def test_camel_case(self):
        assert to_snake_case("petId") == "pet_id"

    def test_pascal_case(self):
        assert to_snake_case("PetStore") == "pet_store"

    def test_kebab_case(self):
        assert to_snake_case("my-resource") == "my_resource"

    def test_acronym(self):
        assert to_snake_case("HTTPSConnection") == "https_connection"

    def test_already_snake(self):
        assert to_snake_case("already_snake") == "already_snake"


class TestToPascalCase:
    def test_snake_case(self):
        assert to_pascal_case("pet_store") == "PetStore"

    def test_kebab_case(self):
        assert to_pascal_case("my-resource") == "MyResource"

    def test_single_word(self):
        assert to_pascal_case("pet") == "Pet"


class TestToCamelCase:
    def test_snake_case(self):
        assert to_camel_case("pet_store") == "petStore"


class TestSingularize:
    def test_regular_plural(self):
        assert singularize("pets") == "pet"

    def test_ies_plural(self):
        assert singularize("categories") == "category"

    def test_ses_plural(self):
        assert singularize("addresses") == "address"

    def test_already_singular(self):
        assert singularize("status") == "status"

    def test_empty(self):
        assert singularize("") == ""

    # Singular exceptions — words ending in 's' that should NOT be stripped
    def test_postgres_not_stripped(self):
        assert singularize("postgres") == "postgres"

    def test_redis_not_stripped(self):
        assert singularize("redis") == "redis"

    def test_kubernetes_not_stripped(self):
        assert singularize("kubernetes") == "kubernetes"

    def test_elasticsearch_not_stripped(self):
        assert singularize("elasticsearch") == "elasticsearch"

    def test_credentials_not_stripped(self):
        assert singularize("credentials") == "credentials"

    def test_prometheus_not_stripped(self):
        assert singularize("prometheus") == "prometheus"

    def test_access_not_stripped(self):
        assert singularize("access") == "access"


class TestPluralize:
    def test_regular(self):
        assert pluralize("pet") == "pets"

    def test_y_ending(self):
        assert pluralize("category") == "categories"

    def test_s_ending(self):
        assert pluralize("address") == "addresses"


class TestProviderNameFromTitle:
    def test_simple(self):
        assert provider_name_from_title("Petstore API") == "petstore"

    def test_with_version(self):
        assert provider_name_from_title("Petstore API v3") == "petstore"

    def test_multi_word(self):
        assert provider_name_from_title("My Cool Service") == "my_cool"


class TestIsSensitiveField:
    def test_password(self):
        assert is_sensitive_field("password") is True

    def test_api_key(self):
        assert is_sensitive_field("api_key") is True

    def test_token(self):
        assert is_sensitive_field("auth_token") is True

    def test_normal_field(self):
        assert is_sensitive_field("name") is False

    def test_password_format(self):
        assert is_sensitive_field("user_pass", fmt="password") is True


class TestPathToSlug:
    def test_simple(self):
        assert path_to_slug("/pets") == "pets"

    def test_with_param(self):
        assert path_to_slug("/pets/{petId}") == "pets"

    def test_nested(self):
        assert path_to_slug("/pets/{petId}/vaccinations") == "pets_vaccinations"

    # Version prefix stripping
    def test_strips_v1_prefix(self):
        assert path_to_slug("/v1/users") == "users"

    def test_strips_v2_prefix(self):
        assert path_to_slug("/v2/access_policies") == "access_policies"

    def test_strips_api_prefix(self):
        assert path_to_slug("/api/users") == "users"

    def test_strips_both_api_and_version(self):
        assert path_to_slug("/api/v1/resources") == "resources"

    def test_preserves_non_version_segments(self):
        assert path_to_slug("/v1/access_credentials/{id}/postgres") == "access_credentials_postgres"

    def test_no_prefix_unchanged(self):
        assert path_to_slug("/users/{userId}") == "users"


class TestTerraformResourceName:
    def test_simple(self):
        assert terraform_resource_name("petstore", "pet") == "petstore_pet"


class TestEnvVarName:
    def test_simple(self):
        assert env_var_name("petstore", "api_key") == "PETSTORE_API_KEY"
