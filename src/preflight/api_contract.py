"""Deterministic API contract comparison for OpenAPI 3.x documents.

This module intentionally focuses on the supported subset required by Day 6:
normalized OpenAPI parsing, local schema-reference resolution, structural
compatibility checks, and stable hash generation. It does not attempt to
implement the full JSON Schema or OpenAPI compatibility spec.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field


class CompatibilityStatus(str, Enum):
    """Deterministic compatibility verdict for an API contract change."""

    SAFE = "SAFE"
    CAUTION = "CAUTION"
    BREAKING = "BREAKING"
    UNKNOWN = "UNKNOWN"


class APIChange(BaseModel):
    """One structurally detected API contract change."""

    model_config = {"frozen": True}

    rule_id: str = Field(..., min_length=1)
    severity: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    method: str = Field(..., min_length=1)
    location: str = Field(..., min_length=1)
    before: Any = None
    after: Any = None
    reason: str = Field(default="")
    compatibility: CompatibilityStatus = CompatibilityStatus.UNKNOWN
    evidence: tuple[str, ...] = Field(default_factory=tuple)


class APIContractFinding(BaseModel):
    """Result of comparing one API contract against another."""

    model_config = {"frozen": True}

    status: CompatibilityStatus = CompatibilityStatus.UNKNOWN
    changes: tuple[APIChange, ...] = Field(default_factory=tuple)
    breaking_changes: tuple[APIChange, ...] = Field(default_factory=tuple)
    warnings: tuple[APIChange, ...] = Field(default_factory=tuple)
    compatible_changes: tuple[APIChange, ...] = Field(default_factory=tuple)
    unknown_changes: tuple[APIChange, ...] = Field(default_factory=tuple)
    provenance: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    schema_version: str = Field(default="1.0")


class APIEndpoint(BaseModel):
    """Normalized API endpoint description."""

    model_config = {"frozen": True}

    path: str
    method: str
    operation_id: str | None = None
    summary: str | None = None
    parameters: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    request_body: dict[str, Any] | None = None
    responses: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    security: tuple[str, ...] = Field(default_factory=tuple)


class APIOperation(BaseModel):
    """Normalized API operation."""

    model_config = {"frozen": True}

    path: str
    method: str
    operation_id: str | None = None
    summary: str | None = None
    parameters: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    request_schema: dict[str, Any] | None = None
    response_schemas: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    security: tuple[str, ...] = Field(default_factory=tuple)


class OpenAPIContract(BaseModel):
    """Normalized OpenAPI contract representation."""

    model_config = {"frozen": True}

    openapi: str = Field(default="3.0.0")
    info: dict[str, Any] = Field(default_factory=dict)
    paths: tuple[APIEndpoint, ...] = Field(default_factory=tuple)
    components: dict[str, Any] = Field(default_factory=dict)


def parse_openapi_document(source: str | Path | dict[str, Any]) -> OpenAPIContract:
    """Parse a JSON/YAML OpenAPI document into the normalized internal model."""

    if isinstance(source, (str, Path)):
        raw_text = (
            Path(source).read_text(encoding="utf-8") if Path(source).exists() else str(source)
        )
        if Path(source).suffix.lower() in {".yaml", ".yml"} or raw_text.lstrip().startswith(
            ("---", "openapi:")
        ):
            payload = yaml.safe_load(raw_text) or {}
        else:
            payload = json.loads(raw_text)
    else:
        payload = source

    if not isinstance(payload, dict):
        raise ValueError("OpenAPI document must resolve to a dictionary.")

    paths = payload.get("paths", {})
    endpoints: list[APIEndpoint] = []
    for path_name, path_spec in sorted(paths.items(), key=lambda item: item[0]):
        if not isinstance(path_spec, dict):
            continue
        for method_name in sorted(path_spec):
            if method_name.lower() not in {
                "get",
                "put",
                "post",
                "delete",
                "patch",
                "head",
                "options",
            }:
                continue
            operation = path_spec[method_name]
            if not isinstance(operation, dict):
                continue
            parameters = _normalize_parameters(
                operation.get("parameters", []), path_spec.get("parameters", [])
            )
            request_schema = _request_body_schema(operation, payload.get("components", {}))
            responses = _normalize_responses(
                operation.get("responses", {}), payload.get("components", {})
            )
            security = _security_requirements(operation)
            endpoints.append(
                APIEndpoint(
                    path=path_name,
                    method=method_name.upper(),
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary"),
                    parameters=tuple(parameters),
                    request_body=request_schema,
                    responses=tuple(responses),
                    security=tuple(sorted(security)),
                )
            )

    raw_components = payload.get("components", {})
    components = (
        dict(sorted((str(k), v) for k, v in raw_components.items()))
        if isinstance(raw_components, dict)
        else {}
    )
    if isinstance(components.get("schemas"), dict):
        components["schemas"] = {
            str(name): _resolve_local_refs(schema, components, set())
            for name, schema in sorted(components["schemas"].items())
        }

    return OpenAPIContract(
        openapi=str(payload.get("openapi", "3.0.0")),
        info=dict(sorted((str(k), v) for k, v in payload.get("info", {}).items())),
        paths=tuple(sorted(endpoints, key=lambda endpoint: (endpoint.path, endpoint.method))),
        components=components,
    )


def _normalize_parameters(*parameter_groups: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    normalized: list[dict[str, Any]] = []
    for group in parameter_groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            resolved = _resolve_local_refs(item, {}, set())
            normalized.append(
                {
                    "name": str(resolved.get("name", "")),
                    "in": str(resolved.get("in", "query")),
                    "required": bool(resolved.get("required", False)),
                    "schema": _sanitize_schema(resolved.get("schema", {})),
                }
            )
    normalized.sort(key=lambda item: (item["in"], item["name"]))
    return normalized


def _request_body_schema(
    operation: dict[str, Any], components: dict[str, Any]
) -> dict[str, Any] | None:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    resolved = _resolve_local_refs(request_body, components, set())
    content = resolved.get("content", {})
    if not content:
        return None
    for _media_type, config in sorted(content.items()):
        if not isinstance(config, dict):
            continue
        schema = config.get("schema")
        if schema is not None:
            sanitized = _sanitize_schema(_resolve_local_refs(schema, components, set()))
            return cast(dict[str, Any], sanitized)
    return None


def _normalize_responses(
    responses: dict[str, Any], components: dict[str, Any]
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(responses, dict):
        return normalized
    for status_code in sorted(responses):
        response = responses[status_code]
        if not isinstance(response, dict):
            continue
        resolved = _resolve_local_refs(response, components, set())
        content = resolved.get("content", {})
        schema: dict[str, Any] | None = None
        for media_type in sorted(content):
            media_value = content[media_type]
            if isinstance(media_value, dict):
                media_schema = media_value.get("schema")
                if media_schema is not None:
                    schema = _sanitize_schema(_resolve_local_refs(media_schema, components, set()))
                    break
        normalized.append(
            {
                "status": str(status_code),
                "schema": schema or {},
                "headers": _sanitize_schema(resolved.get("headers", {})),
            }
        )
    return normalized


def _security_requirements(operation: dict[str, Any]) -> list[str]:
    security = operation.get("security")
    if not isinstance(security, list):
        return []
    names: list[str] = []
    for requirement in security:
        if isinstance(requirement, dict):
            for name in requirement:
                names.append(str(name))
    return sorted(set(names))


def _sanitize_schema(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        return {
            str(key): _sanitize_schema(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [_sanitize_schema(item) for item in value]
    return value


def _resolve_local_refs(value: Any, components: dict[str, Any], seen: set[str]) -> Any:  # noqa: ANN401
    if isinstance(value, dict):
        if "$ref" in value and isinstance(value["$ref"], str):
            ref = value["$ref"]
            if ref.startswith("#/components/") and ref not in seen:
                seen.add(ref)
                target: Any = components
                for segment in ref.split("/")[2:]:
                    target = target.get(segment) if isinstance(target, dict) else None
                if isinstance(target, dict):
                    resolved = _resolve_local_refs(target, components, seen)
                    if isinstance(resolved, dict):
                        merged = {k: v for k, v in resolved.items() if k != "$ref"}
                        for key, item in value.items():
                            if key != "$ref":
                                merged[key] = _resolve_local_refs(item, components, seen)
                        return merged
        return {str(k): _resolve_local_refs(v, components, seen) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_local_refs(item, components, seen) for item in value]
    return value


def analyze_api_contract(
    old_contract: str | Path | dict[str, Any], new_contract: str | Path | dict[str, Any]
) -> APIContractFinding:
    """Compare two OpenAPI documents and return a deterministic compatibility finding."""

    old = parse_openapi_document(old_contract)
    new = parse_openapi_document(new_contract)

    changes: list[APIChange] = []
    provenance: list[dict[str, Any]] = []

    old_ops = {(endpoint.path, endpoint.method): endpoint for endpoint in old.paths}
    new_ops = {(endpoint.path, endpoint.method): endpoint for endpoint in new.paths}

    for (path, method), _old_endpoint in sorted(old_ops.items()):
        if (path, method) not in new_ops:
            changes.append(
                APIChange(
                    rule_id="API-ENDPOINT-REMOVED",
                    severity="HIGH",
                    path=path,
                    method=method,
                    location=f"/paths/{path}/{method.lower()}",
                    before={"path": path, "method": method},
                    after=None,
                    reason="An endpoint that existed in the prior contract is no longer present.",
                    compatibility=CompatibilityStatus.BREAKING,
                    evidence=("contract.old",),
                )
            )
            provenance.append(
                {
                    "source": "old_contract",
                    "path": path,
                    "method": method,
                    "rule_id": "API-ENDPOINT-REMOVED",
                }
            )

    for (path, method), _new_endpoint in sorted(new_ops.items()):
        if (path, method) not in old_ops:
            changes.append(
                APIChange(
                    rule_id="API-ENDPOINT-ADDED",
                    severity="LOW",
                    path=path,
                    method=method,
                    location=f"/paths/{path}/{method.lower()}",
                    before=None,
                    after={"path": path, "method": method},
                    reason="A new API endpoint was introduced.",
                    compatibility=CompatibilityStatus.SAFE,
                    evidence=("contract.new",),
                )
            )
            provenance.append(
                {
                    "source": "new_contract",
                    "path": path,
                    "method": method,
                    "rule_id": "API-ENDPOINT-ADDED",
                }
            )

    for (path, method), old_endpoint in sorted(old_ops.items()):
        new_endpoint: APIEndpoint | None = new_ops.get((path, method))
        if new_endpoint is None:
            continue
        changes.extend(_compare_parameters(old_endpoint, new_endpoint))
        changes.extend(_compare_request_schema(old_endpoint, new_endpoint))
        changes.extend(_compare_response_schema(old_endpoint, new_endpoint))
        changes.extend(_compare_security(old_endpoint, new_endpoint))

    breaking = tuple(
        change for change in changes if change.compatibility == CompatibilityStatus.BREAKING
    )
    warnings = tuple(
        change for change in changes if change.compatibility == CompatibilityStatus.CAUTION
    )
    compatible = tuple(
        change for change in changes if change.compatibility == CompatibilityStatus.SAFE
    )
    unknown = tuple(
        change for change in changes if change.compatibility == CompatibilityStatus.UNKNOWN
    )

    if breaking:
        status = CompatibilityStatus.BREAKING
    elif unknown:
        status = CompatibilityStatus.UNKNOWN
    elif warnings:
        status = CompatibilityStatus.CAUTION
    elif compatible:
        status = CompatibilityStatus.SAFE
    else:
        status = CompatibilityStatus.SAFE

    return APIContractFinding(
        status=status,
        changes=tuple(changes),
        breaking_changes=breaking,
        warnings=warnings,
        compatible_changes=compatible,
        unknown_changes=unknown,
        provenance=tuple(provenance),
    )


def _compare_parameters(old_endpoint: APIEndpoint, new_endpoint: APIEndpoint) -> list[APIChange]:
    old_params = {param["name"]: param for param in old_endpoint.parameters}
    new_params = {param["name"]: param for param in new_endpoint.parameters}
    changes: list[APIChange] = []

    for name, removed_param in sorted(old_params.items()):
        if name not in new_params:
            changes.append(
                APIChange(
                    rule_id="API-PARAM-REMOVED",
                    severity="HIGH",
                    path=old_endpoint.path,
                    method=old_endpoint.method,
                    location=f"/paths/{old_endpoint.path}/{old_endpoint.method.lower()}/parameters/{name}",
                    before=removed_param,
                    after=None,
                    reason="A parameter present in the old contract no longer exists.",
                    compatibility=CompatibilityStatus.BREAKING,
                    evidence=("parameter.removed",),
                )
            )

    for name, new_param in sorted(new_params.items()):
        old_param = old_params.get(name)
        if old_param is None:
            if new_param.get("required"):
                changes.append(
                    APIChange(
                        rule_id="API-REQUIRED-ADDED",
                        severity="HIGH",
                        path=new_endpoint.path,
                        method=new_endpoint.method,
                        location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/parameters/{name}",
                        before=None,
                        after={"name": name, "required": True},
                        reason="A new required parameter was added to the contract.",
                        compatibility=CompatibilityStatus.BREAKING,
                        evidence=("parameter.required_added",),
                    )
                )
            continue
        if old_param.get("in") != new_param.get("in"):
            changes.append(
                APIChange(
                    rule_id="API-PARAM-LOCATION-CHANGED",
                    severity="MEDIUM",
                    path=new_endpoint.path,
                    method=new_endpoint.method,
                    location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/parameters/{name}",
                    before=old_param,
                    after=new_param,
                    reason="Parameter location changed.",
                    compatibility=CompatibilityStatus.CAUTION,
                    evidence=("parameter.location_changed",),
                )
            )
        if old_param.get("required") != new_param.get("required") and new_param.get("required"):
            changes.append(
                APIChange(
                    rule_id="API-REQUIRED-ADDED",
                    severity="HIGH",
                    path=new_endpoint.path,
                    method=new_endpoint.method,
                    location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/parameters/{name}",
                    before=old_param,
                    after=new_param,
                    reason="A previously optional parameter became required.",
                    compatibility=CompatibilityStatus.BREAKING,
                    evidence=("parameter.required_added",),
                )
            )
        _compare_schema_values(
            old_param.get("schema", {}),
            new_param.get("schema", {}),
            location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/parameters/{name}",
            path=new_endpoint.path,
            method=new_endpoint.method,
            direction="REQUEST",
            changes=changes,
        )
    return changes


def _compare_request_schema(
    old_endpoint: APIEndpoint, new_endpoint: APIEndpoint
) -> list[APIChange]:
    old_schema = old_endpoint.request_body or {}
    new_schema = new_endpoint.request_body or {}
    changes: list[APIChange] = []
    _compare_schema_values(
        old_schema,
        new_schema,
        location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/requestBody",
        path=new_endpoint.path,
        method=new_endpoint.method,
        direction="REQUEST",
        changes=changes,
    )
    return changes


def _compare_response_schema(
    old_endpoint: APIEndpoint, new_endpoint: APIEndpoint
) -> list[APIChange]:
    old_map = {
        str(status.get("status", "")): status.get("schema", {}) for status in old_endpoint.responses
    }
    new_map = {
        str(status.get("status", "")): status.get("schema", {}) for status in new_endpoint.responses
    }
    changes: list[APIChange] = []

    for status_code in sorted(set(old_map) - set(new_map)):
        changes.append(
            APIChange(
                rule_id="API-RESPONSE-REMOVED",
                severity="HIGH",
                path=old_endpoint.path,
                method=old_endpoint.method,
                location=f"/paths/{old_endpoint.path}/{old_endpoint.method.lower()}/responses/{status_code}",
                before={"status": status_code},
                after=None,
                reason="A response status code was removed from the contract.",
                compatibility=CompatibilityStatus.BREAKING,
                evidence=("response.removed",),
            )
        )

    for status_code in sorted(set(new_map) - set(old_map)):
        changes.append(
            APIChange(
                rule_id="API-RESPONSE-ADDED",
                severity="LOW",
                path=new_endpoint.path,
                method=new_endpoint.method,
                location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/responses/{status_code}",
                before=None,
                after={"status": status_code},
                reason="A new response status code was introduced.",
                compatibility=CompatibilityStatus.SAFE,
                evidence=("response.added",),
            )
        )

    for status_code in sorted(set(old_map) & set(new_map)):
        _compare_schema_values(
            old_map.get(status_code, {}),
            new_map.get(status_code, {}),
            location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/responses/{status_code}",
            path=new_endpoint.path,
            method=new_endpoint.method,
            direction="RESPONSE",
            changes=changes,
        )
    return changes


def _compare_security(old_endpoint: APIEndpoint, new_endpoint: APIEndpoint) -> list[APIChange]:
    old_security = set(old_endpoint.security)
    new_security = set(new_endpoint.security)
    if old_security == new_security:
        return []
    if new_security and not old_security:
        return [
            APIChange(
                rule_id="API-SECURITY-REQUIRED",
                severity="MEDIUM",
                path=new_endpoint.path,
                method=new_endpoint.method,
                location=f"/paths/{new_endpoint.path}/{new_endpoint.method.lower()}/security",
                before=sorted(old_security),
                after=sorted(new_security),
                reason="The endpoint now requires authentication or a security scheme.",
                compatibility=CompatibilityStatus.CAUTION,
                evidence=("security.required",),
            )
        ]
    return []


def _compare_schema_values(
    old_schema: Any,  # noqa: ANN401
    new_schema: Any,  # noqa: ANN401
    *,
    location: str,
    path: str,
    method: str,
    direction: str,
    changes: list[APIChange],
) -> None:
    if old_schema is None:
        return
    if new_schema is None:
        if direction == "RESPONSE":
            changes.append(
                APIChange(
                    rule_id="API-PROPERTY-REMOVED",
                    severity="HIGH",
                    path=path,
                    method=method,
                    location=location,
                    before=old_schema,
                    after=None,
                    reason="The response schema no longer contains the old value.",
                    compatibility=CompatibilityStatus.BREAKING,
                    evidence=("schema.removed",),
                )
            )
        return

    if not isinstance(old_schema, dict) or not isinstance(new_schema, dict):
        if old_schema != new_schema:
            changes.append(
                APIChange(
                    rule_id="API-TYPE-NARROWED",
                    severity="HIGH",
                    path=path,
                    method=method,
                    location=location,
                    before=old_schema,
                    after=new_schema,
                    reason="The schema type or value changed structurally.",
                    compatibility=CompatibilityStatus.BREAKING,
                    evidence=("schema.type_changed",),
                )
            )
        return

    old_required = set(old_schema.get("required", []))
    new_required = set(new_schema.get("required", []))
    old_type = old_schema.get("type")
    new_type = new_schema.get("type")
    old_enum = set(old_schema.get("enum", []))
    new_enum = set(new_schema.get("enum", []))

    if old_type and new_type and old_type != new_type:
        changes.append(
            APIChange(
                rule_id="API-TYPE-NARROWED",
                severity="HIGH",
                path=path,
                method=method,
                location=location,
                before=old_type,
                after=new_type,
                reason="The schema type changed in a way that can break clients.",
                compatibility=CompatibilityStatus.BREAKING,
                evidence=("schema.type_changed",),
            )
        )

    if new_enum and old_enum - new_enum:
        changes.append(
            APIChange(
                rule_id="API-ENUM-VALUE-REMOVED",
                severity="HIGH",
                path=path,
                method=method,
                location=location,
                before=sorted(old_enum),
                after=sorted(new_enum),
                reason="One or more enum values were removed.",
                compatibility=CompatibilityStatus.BREAKING,
                evidence=("schema.enum_removed",),
            )
        )
    elif new_enum and not old_enum:
        changes.append(
            APIChange(
                rule_id="API-ENUM-CONSTRAINT-ADDED",
                severity="HIGH",
                path=path,
                method=method,
                location=location,
                before=None,
                after=sorted(new_enum),
                reason="An enum constraint was added to an existing schema.",
                compatibility=CompatibilityStatus.BREAKING,
                evidence=("schema.enum_constraint_added",),
            )
        )

    old_props = old_schema.get("properties", {})
    new_props = new_schema.get("properties", {})
    if isinstance(old_props, dict) and isinstance(new_props, dict):
        for prop_name in sorted(set(old_props) - set(new_props)):
            if direction == "RESPONSE":
                compatibility = CompatibilityStatus.BREAKING
                reason = "A response property was removed from the API contract."
            else:
                compatibility = CompatibilityStatus.CAUTION
                reason = "A request property was removed from the API contract."
            changes.append(
                APIChange(
                    rule_id="API-PROPERTY-REMOVED",
                    severity="HIGH",
                    path=path,
                    method=method,
                    location=f"{location}/properties/{prop_name}",
                    before=old_props[prop_name],
                    after=None,
                    reason=reason,
                    compatibility=compatibility,
                    evidence=("schema.property_removed",),
                )
            )

        for prop_name in sorted(set(new_props) - set(old_props)):
            if prop_name in new_required:
                changes.append(
                    APIChange(
                        rule_id="API-REQUIRED-ADDED",
                        severity="HIGH",
                        path=path,
                        method=method,
                        location=f"{location}/properties/{prop_name}",
                        before=None,
                        after={"property": prop_name, "required": True},
                        reason="A required request property was added.",
                        compatibility=CompatibilityStatus.BREAKING,
                        evidence=("schema.required_added",),
                    )
                )

        for prop_name in sorted(set(old_props) & set(new_props)):
            _compare_schema_values(
                old_props[prop_name],
                new_props[prop_name],
                location=f"{location}/properties/{prop_name}",
                path=path,
                method=method,
                direction=direction,
                changes=changes,
            )

    if isinstance(old_schema.get("items"), dict) and isinstance(new_schema.get("items"), dict):
        _compare_schema_values(
            old_schema["items"],
            new_schema["items"],
            location=f"{location}/items",
            path=path,
            method=method,
            direction=direction,
            changes=changes,
        )

    if old_required and new_required:
        added_required = sorted(new_required - old_required)
        for field_name in added_required:
            changes.append(
                APIChange(
                    rule_id="API-REQUIRED-ADDED",
                    severity="HIGH",
                    path=path,
                    method=method,
                    location=f"{location}/required/{field_name}",
                    before=None,
                    after={"field": field_name, "required": True},
                    reason="A field became required in the schema.",
                    compatibility=CompatibilityStatus.BREAKING,
                    evidence=("schema.required_added",),
                )
            )


def canonical_api_contract_json(finding: APIContractFinding) -> str:
    """Serialize a finding deterministically without timestamps or random IDs."""

    return json.dumps(
        finding.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def api_contract_sha256(finding: APIContractFinding) -> str:
    """Return a stable SHA-256 for the normalized structured API finding."""

    return hashlib.sha256(canonical_api_contract_json(finding).encode("utf-8")).hexdigest()


def _pretty_print_json(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "APIChange",
    "APIContractFinding",
    "APIEndpoint",
    "APIOperation",
    "CompatibilityStatus",
    "OpenAPIContract",
    "analyze_api_contract",
    "api_contract_sha256",
    "canonical_api_contract_json",
    "parse_openapi_document",
]
