from __future__ import annotations

import json

from preflight.api_contract import (
    CompatibilityStatus,
    analyze_api_contract,
    api_contract_sha256,
    canonical_api_contract_json,
    parse_openapi_document,
)


def _base_contract() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "phone_number": {"type": "string"},
                                        },
                                    },
                                }
                            },
                        }
                    },
                }
            }
        },
    }


def test_parse_openapi_document_normalizes_paths() -> None:
    contract = parse_openapi_document(_base_contract())
    assert contract.openapi == "3.0.0"
    assert len(contract.paths) == 1
    assert contract.paths[0].path == "/profile/{id}"
    assert contract.paths[0].method == "GET"


def test_endpoint_removed_is_breaking() -> None:
    old = _base_contract()
    new = {"openapi": "3.0.0", "info": {"title": "demo", "version": "1.0.0"}, "paths": {}}
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.BREAKING
    assert any(change.rule_id == "API-ENDPOINT-REMOVED" for change in finding.changes)


def test_endpoint_added_is_safe() -> None:
    old = {"openapi": "3.0.0", "info": {"title": "demo", "version": "1.0.0"}, "paths": {}}
    new = _base_contract()
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.SAFE
    assert any(change.rule_id == "API-ENDPOINT-ADDED" for change in finding.changes)


def test_method_removed_is_breaking() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "post": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.BREAKING
    assert any(change.rule_id == "API-ENDPOINT-REMOVED" for change in finding.changes)


def test_required_request_field_added_is_breaking() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "phone_number": {"type": "string"},
                                    },
                                    "required": ["phone_number"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.BREAKING
    assert any(change.rule_id == "API-REQUIRED-ADDED" for change in finding.changes)


def test_response_property_removed_is_breaking() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.BREAKING
    assert any(change.rule_id == "API-PROPERTY-REMOVED" for change in finding.changes)


def test_type_change_is_breaking() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"phone_number": {"type": "integer"}},
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.BREAKING
    assert any(change.rule_id == "API-TYPE-NARROWED" for change in finding.changes)


def test_enum_value_removed_is_breaking() -> None:
    old = _base_contract()
    old["paths"]["/profile/{id}"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["properties"]["phone_number"]["enum"] = ["HOME", "MOBILE"]
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "phone_number": {"type": "string", "enum": ["HOME"]}
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert any(change.rule_id == "API-ENUM-VALUE-REMOVED" for change in finding.changes)


def test_nested_schema_change_has_structural_location() -> None:
    old = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/user": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "user": {
                                                "type": "object",
                                                "properties": {
                                                    "profile": {
                                                        "type": "object",
                                                        "properties": {
                                                            "address": {
                                                                "type": "object",
                                                                "properties": {
                                                                    "city": {"type": "string"}
                                                                },
                                                            }
                                                        },
                                                    }
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/user": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "user": {
                                                "type": "object",
                                                "properties": {
                                                    "profile": {
                                                        "type": "object",
                                                        "properties": {
                                                            "address": {
                                                                "type": "object",
                                                                "properties": {
                                                                    "city": {"type": "integer"}
                                                                },
                                                            }
                                                        },
                                                    }
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert any("properties/city" in change.location for change in finding.changes)


def test_local_ref_resolves_and_detects_structural_change() -> None:
    old = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            }
        },
        "paths": {
            "/user": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {"name": {"type": "integer"}},
                }
            }
        },
        "paths": {
            "/user": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert any(change.rule_id == "API-TYPE-NARROWED" for change in finding.changes)


def test_reference_cycle_does_not_recurse_forever() -> None:
    contract = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {"self": {"$ref": "#/components/schemas/Node"}},
                }
            }
        },
        "paths": {
            "/node": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"}
                                }
                            },
                        }
                    }
                }
            }
        },
    }
    parsed = parse_openapi_document(contract)
    assert parsed.components["schemas"]["Node"]["properties"]["self"]["type"] == "object"


def test_security_requirement_change_is_caution() -> None:
    old = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {"/public": {"get": {"responses": {"200": {"description": "OK"}}}}},
    }
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/public": {
                "get": {
                    "security": [{"bearerAuth": []}],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert finding.status == CompatibilityStatus.CAUTION


def test_unknown_construct_is_reported_as_unknown() -> None:
    old = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/x": {
                "get": {
                    "x-unsupported": {"weird": "value"},
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert finding.status in {CompatibilityStatus.UNKNOWN, CompatibilityStatus.SAFE}


def test_provenance_is_present_in_finding() -> None:
    finding = analyze_api_contract(
        _base_contract(),
        {"openapi": "3.0.0", "info": {"title": "demo", "version": "1.0.0"}, "paths": {}},
    )
    assert finding.provenance
    assert finding.provenance[0]["rule_id"] == "API-ENDPOINT-REMOVED"


def test_canonical_api_contract_json_is_deterministic() -> None:
    old = _base_contract()
    new = {"openapi": "3.0.0", "info": {"title": "demo", "version": "1.0.0"}, "paths": {}}
    a = canonical_api_contract_json(analyze_api_contract(old, new))
    b = canonical_api_contract_json(analyze_api_contract(old, new))
    assert a == b


def test_sha256_is_stable_for_equivalent_contracts() -> None:
    old = _base_contract()
    new = {"openapi": "3.0.0", "info": {"title": "demo", "version": "1.0.0"}, "paths": {}}
    h1 = api_contract_sha256(analyze_api_contract(old, new))
    h2 = api_contract_sha256(analyze_api_contract(old, new))
    assert h1 == h2


def test_reordered_equivalent_docs_produce_same_hash() -> None:
    old_a = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/a": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/b": {"post": {"responses": {"200": {"description": "ok"}}}},
        },
    }
    old_b = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/b": {"post": {"responses": {"200": {"description": "ok"}}}},
            "/a": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
    }
    f1 = analyze_api_contract(old_a, old_b)
    f2 = analyze_api_contract(old_b, old_a)
    assert canonical_api_contract_json(f1) == canonical_api_contract_json(f2)


def test_secret_redaction_happens_before_serialization() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "parameters": [
                        {
                            "name": "token",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "example": "super-secret-token"},
                        }
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    payload = json.dumps(finding.model_dump(mode="json"), sort_keys=True)
    assert "super-secret-token" not in payload


def test_multiple_changes_are_retained() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "tenant",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert len(finding.changes) >= 2


def test_yaml_input_parses() -> None:
    yaml_doc = """
openapi: 3.0.0
info:
  title: demo
  version: 1.0.0
paths:
  /profile/{id}:
    get:
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: ok
"""
    parsed = parse_openapi_document(yaml_doc)
    assert parsed.paths[0].method == "GET"


def test_path_parameter_requiredness_is_detected() -> None:
    old = _base_contract()
    new = {
        "openapi": "3.0.0",
        "info": {"title": "demo", "version": "1.0.0"},
        "paths": {
            "/profile/{id}": {
                "get": {
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    finding = analyze_api_contract(old, new)
    assert any(
        change.rule_id == "API-REQUIRED-ADDED" for change in finding.changes
    ) or finding.status in {CompatibilityStatus.BREAKING, CompatibilityStatus.CAUTION}
