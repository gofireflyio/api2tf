"""Tests for OpenAPI to Terraform type mapping."""

from api2tf._schema_mapper import map_openapi_type, map_schema_to_attributes, merge_attributes
from api2tf._types import TFType, AttrComputability


class TestPrimitiveTypeMapping:
    def test_string(self):
        attr = map_openapi_type("name", {"type": "string"}, set())
        assert attr.tf_type == TFType.STRING

    def test_integer(self):
        attr = map_openapi_type("age", {"type": "integer"}, set())
        assert attr.tf_type == TFType.INT64

    def test_number(self):
        attr = map_openapi_type("price", {"type": "number"}, set())
        assert attr.tf_type == TFType.FLOAT64

    def test_boolean(self):
        attr = map_openapi_type("active", {"type": "boolean"}, set())
        assert attr.tf_type == TFType.BOOL

    def test_string_with_format(self):
        attr = map_openapi_type("created_at", {"type": "string", "format": "date-time"}, set())
        assert attr.tf_type == TFType.STRING
        assert attr.format_hint == "date-time"


class TestCollectionTypeMapping:
    def test_array_of_strings(self):
        attr = map_openapi_type("tags", {"type": "array", "items": {"type": "string"}}, set())
        assert attr.tf_type == TFType.LIST
        assert attr.element_type == TFType.STRING

    def test_array_of_objects(self):
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
            },
        }
        attr = map_openapi_type("items", schema, set())
        assert attr.tf_type == TFType.LIST_NESTED
        assert len(attr.nested_attributes) == 2

    def test_object_with_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "street": {"type": "string"},
                "city": {"type": "string"},
            },
        }
        attr = map_openapi_type("address", schema, set())
        assert attr.tf_type == TFType.SINGLE_NESTED
        assert len(attr.nested_attributes) == 2

    def test_object_with_additional_properties(self):
        schema = {
            "type": "object",
            "additionalProperties": {"type": "string"},
        }
        attr = map_openapi_type("metadata", schema, set())
        assert attr.tf_type == TFType.MAP
        assert attr.element_type == TFType.STRING


class TestComputability:
    def test_required_field(self):
        attr = map_openapi_type("name", {"type": "string"}, {"name"})
        assert attr.computability == AttrComputability.REQUIRED

    def test_optional_field(self):
        attr = map_openapi_type("nickname", {"type": "string"}, {"name"})
        assert attr.computability == AttrComputability.OPTIONAL

    def test_readonly_field(self):
        attr = map_openapi_type("id", {"type": "string", "readOnly": True}, set())
        assert attr.computability == AttrComputability.COMPUTED

    def test_writeonly_field(self):
        attr = map_openapi_type("password", {"type": "string", "writeOnly": True}, set())
        assert attr.write_only is True


class TestSensitivity:
    def test_password_field(self):
        attr = map_openapi_type("password", {"type": "string"}, set())
        assert attr.sensitive is True

    def test_api_key_field(self):
        attr = map_openapi_type("api_key", {"type": "string"}, set())
        assert attr.sensitive is True

    def test_password_format(self):
        attr = map_openapi_type("user_pass", {"type": "string", "format": "password"}, set())
        assert attr.sensitive is True

    def test_normal_field_not_sensitive(self):
        attr = map_openapi_type("name", {"type": "string"}, set())
        assert attr.sensitive is False


class TestEnumMapping:
    def test_string_enum(self):
        attr = map_openapi_type("status", {"type": "string", "enum": ["active", "inactive"]}, set())
        assert attr.enum_values == ["active", "inactive"]


class TestNullable:
    def test_openapi_30_nullable(self):
        attr = map_openapi_type("name", {"type": "string", "nullable": True}, {"name"})
        # Nullable required field stays required (Terraform handles null via its type system)
        assert attr.tf_type == TFType.STRING

    def test_openapi_31_nullable(self):
        attr = map_openapi_type("name", {"type": ["string", "null"]}, set())
        assert attr.tf_type == TFType.STRING


class TestMergeAttributes:
    def test_merge_request_and_response(self):
        request_attrs = [
            map_openapi_type("name", {"type": "string"}, {"name"}),
            map_openapi_type("age", {"type": "integer"}, set()),
        ]
        response_attrs = [
            map_openapi_type("name", {"type": "string"}, set(), read_only=True),
            map_openapi_type("id", {"type": "string", "readOnly": True}, set()),
            map_openapi_type("created_at", {"type": "string", "readOnly": True}, set()),
        ]
        merged = merge_attributes(request_attrs, response_attrs)
        by_name = {a.name: a for a in merged}

        # name: from request, stays Required
        assert by_name["name"].computability == AttrComputability.REQUIRED
        # age: request only, stays Optional
        assert by_name["age"].computability == AttrComputability.OPTIONAL
        # id: response only, Computed
        assert by_name["id"].computability == AttrComputability.COMPUTED
        # created_at: response only, Computed
        assert by_name["created_at"].computability == AttrComputability.COMPUTED


class TestOneOfFallback:
    def test_oneof_becomes_string(self):
        schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        attr = map_openapi_type("value", schema, set())
        assert attr.tf_type == TFType.STRING
