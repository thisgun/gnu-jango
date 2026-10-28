"""Contract tests: validate real API responses against the generated OpenAPI schema.

The schema comes from drf-spectacular, the same generator that writes ``openapi/schema.json``.
OpenAPI 3.0 is converted to JSON Schema (``nullable`` becomes a ``null`` type) and every object
with declared properties is made strict, so a response key that the contract does not declare
fails the test as well as a missing or mistyped one.
"""

import functools

import jsonschema
from drf_spectacular.generators import SchemaGenerator

_DROPPED_KEYWORDS = {"nullable", "readOnly", "writeOnly", "example", "examples", "description"}


@functools.cache
def openapi_schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def _to_json_schema(node):
    if isinstance(node, list):
        return [_to_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    converted = {}
    for key, value in node.items():
        if key in _DROPPED_KEYWORDS:
            continue
        if key == "properties":
            # property names are data, not keywords: never filter them
            converted[key] = {name: _to_json_schema(schema) for name, schema in value.items()}
        else:
            converted[key] = _to_json_schema(value)
    if "properties" in converted and "additionalProperties" not in converted:
        converted["additionalProperties"] = False
    if node.get("nullable"):
        if "type" in converted:
            converted["type"] = [converted["type"], "null"]
        else:
            converted = {"anyOf": [converted, {"type": "null"}]}
    return converted


@functools.cache
def _components():
    return _to_json_schema(openapi_schema().get("components", {}))


def typed_operations(prefix="/api/v1/"):
    """(METHOD, path) of every v1 operation whose success response has a declared schema."""
    found = set()
    for path, item in openapi_schema()["paths"].items():
        if not path.startswith(prefix):
            continue
        for method, operation in item.items():
            responses = operation.get("responses", {}) if isinstance(operation, dict) else {}
            for status in ("200", "201"):
                content = responses.get(status, {}).get("content", {})
                if content.get("application/json", {}).get("schema"):
                    found.add((method.upper(), path))
    return found


def response_validator(path, method="get", status="200"):
    operation = openapi_schema()["paths"][path][method.lower()]
    schema = operation["responses"][status]["content"]["application/json"]["schema"]
    root = {**_to_json_schema(schema), "components": _components()}
    return jsonschema.Draft7Validator(root)


class ContractAssertions:
    """Mixin for TestCase: ``self.assertMatchesContract(response, "/api/v1/settings")``."""

    def assertMatchesContract(self, response, path, method="get", status="200"):
        self.assertEqual(str(response.status_code), status, response.content[:300])
        errors = sorted(response_validator(path, method, status).iter_errors(response.json()), key=str)
        if errors:
            lines = [
                f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
                for error in errors[:8]
            ]
            self.fail(f"{method.upper()} {path} does not match its OpenAPI contract:\n" + "\n".join(lines))
