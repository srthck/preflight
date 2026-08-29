"""Semantic dependency intelligence for PreFlight Day 3.

This module adds a deterministic semantic layer on top of the Day 1 and Day 2
structural facts. It intentionally stays narrow and evidence-based: all semantic
edges are backed by source location and a deterministic resolution rule.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter_kotlin as tskotlin
import tree_sitter_python as tspython
from pydantic import BaseModel, Field
from tree_sitter import Language, Node, Parser

from preflight.domain.entities import Entity
from preflight.domain.enums import EdgeKind, EntityKind
from preflight.domain.graph_models import DependencyEdge
from preflight.graph.builder import GraphBuilder, PreFlightGraph

_PY_LANGUAGE = Language(tspython.language())
_KT_LANGUAGE = Language(tskotlin.language())

# Service label for database entities. A SQL string proves a table and column
# exist; it never proves what the database itself is called, so this stays a
# neutral, repository-agnostic constant rather than any fixture's db name.
_DATABASE_SERVICE_LABEL = "database"


def _parse_source(text: str, language: str) -> Node:
    parser = Parser(_PY_LANGUAGE if language == "python" else _KT_LANGUAGE)
    return parser.parse(text.encode("utf-8")).root_node


def _walk(node: Node) -> list[Node]:
    nodes: list[Node] = []
    stack = [node]
    while stack:
        current = stack.pop()
        nodes.append(current)
        stack.extend(reversed(current.named_children))
    return nodes


def _node_text(node: Node, source: str) -> str:
    return source.encode("utf-8")[node.start_byte : node.end_byte].decode("utf-8")


class EdgeEvidence(BaseModel):
    """Immutable, source-located provenance for a semantic dependency edge."""

    model_config = {"frozen": True}

    source_file: str = Field(..., description="Project-relative file path.")
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=0)
    source_symbol: str | None = Field(default=None, description="Declaring symbol.")
    syntax_kind: str | None = Field(default=None, description="AST or syntax category.")
    matched_pattern: str | None = Field(
        default=None, description="Pattern that triggered detection."
    )
    extracted_value: str | None = Field(
        default=None, description="Normalized semantic target value."
    )
    resolution_rule: str | None = Field(default=None, description="How it was resolved.")
    evidence_text_summary: str = Field(
        default="",
        description="Short, structured summary for auditable explanations.",
    )

    @property
    def file(self) -> str:
        return self.source_file

    @property
    def symbol(self) -> str | None:
        return self.source_symbol


@dataclass(frozen=True)
class ServiceDescriptor:
    """Deterministic descriptor for a service/module boundary."""

    service_id: str
    name: str
    root_path: str
    language: str
    package: str | None = None
    metadata_source: str = "filesystem"


class RouteRegistry:
    """In-memory registry mapping normalized HTTP routes to provider entity IDs."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    def register(
        self,
        *,
        service: str,
        host: str,
        method: str,
        route: str,
        entity_id: str,
    ) -> None:
        key = (
            _normalize_host(host),
            _normalize_method(method),
            _normalize_route(route),
        )
        normalized_entity = (
            f"{service}.{entity_id.split('.')[-1]}" if "." in entity_id else entity_id
        )
        self._routes[key].add(normalized_entity)

    def match(self, method: str, host: str, route: str) -> str | None:
        candidates = self.candidates(method, host, route)
        providers = [
            candidate
            for candidate in candidates
            if not candidate.rsplit(".", 1)[-1].endswith("Client")
        ]
        candidates = providers or candidates
        return candidates[0] if len(candidates) == 1 else None

    def candidates(self, method: str, host: str, route: str) -> list[str]:
        host_key = _normalize_host(host)
        method_key = _normalize_method(method)
        route_key = _normalize_route(route)
        candidates: list[str] = []

        for (registered_host, registered_method, registered_route), entity_ids in sorted(
            self._routes.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
        ):
            if registered_method != method_key:
                continue
            if host_key and registered_host != host_key:
                continue
            if _route_matches(registered_route, route_key):
                candidates.extend(sorted(entity_ids))

        return sorted(set(candidates))

    @property
    def entries(self) -> list[tuple[str, str, str, str]]:
        return [
            (host, method, route, entity_id)
            for (host, method, route), entity_ids in sorted(
                self._routes.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
            )
            for entity_id in sorted(entity_ids)
        ]


class DatabaseEntityRegistry:
    """Registry of database tables and fields accessed by the analyzed sources."""

    def __init__(self) -> None:
        self._table_fields: dict[str, dict[str, str]] = defaultdict(dict)

    def register_table_field(self, table: str, field: str, operation: str) -> None:
        normalized_operation = _normalize_db_operation(operation)
        self._table_fields[table][field] = normalized_operation

    def lookup_table_field(self, table: str, field: str) -> str | None:
        return self._table_fields.get(table, {}).get(field)

    @property
    def table_fields(self) -> dict[str, dict[str, str]]:
        return {table: dict(fields) for table, fields in sorted(self._table_fields.items())}


@dataclass
class SemanticCandidate:
    """Intermediate semantic signal before final resolution."""

    kind: EdgeKind
    source_entity: str
    target_descriptor: str
    attributes: dict[str, Any] = field(default_factory=dict)
    evidence: list[EdgeEvidence] | None = None
    resolution_status: str = "UNRESOLVED"


@dataclass(frozen=True)
class SemanticAnalysisResult:
    """Result of a semantic pass over a fixture or repository."""

    entities: tuple[Entity, ...]
    edges: tuple[DependencyEdge, ...]
    services: tuple[ServiceDescriptor, ...]
    route_registry: RouteRegistry
    database_registry: DatabaseEntityRegistry
    graph: Any
    diagnostics: tuple[str, ...] = ()

    def semantic_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for edge in self.edges:
            counts[edge.kind.value] = counts.get(edge.kind.value, 0) + 1
        return dict(sorted(counts.items()))


class SemanticAnalyzer:
    """Deterministic semantic analyzer for Python/Kotlin source trees."""

    def analyze(
        self,
        root_path: str | Path,
        *,
        files: list[Path | str] | None = None,
    ) -> SemanticAnalysisResult:
        root = Path(root_path)
        services: list[ServiceDescriptor] = []
        entities_by_id: dict[str, Entity] = {}
        route_registry = RouteRegistry()
        database_registry = DatabaseEntityRegistry()
        edge_map: dict[tuple[str, str, str], DependencyEdge] = {}
        diagnostics: list[str] = []

        def _service_title(service_name: str) -> str:
            return service_name.replace("-", " ").title()

        if not root.exists():
            raise ValueError(f"root_path does not exist: {root}")

        discovered_files: list[Path] = []
        if files is None:
            discovered_files = sorted(
                [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".py", ".kt"}],
                key=lambda p: p.relative_to(root).as_posix(),
            )
        else:
            for file in files:
                path = Path(file)
                if not path.is_absolute():
                    path = root / path
                if path.is_file() and path.suffix.lower() in {".py", ".kt"}:
                    discovered_files.append(path)

        for file_path in discovered_files:
            rel = file_path.relative_to(root).as_posix()
            service_name = rel.split("/")[0] if "/" in rel else root.name
            language = "python" if file_path.suffix.lower() == ".py" else "kotlin"
            services.append(
                ServiceDescriptor(
                    service_id=service_name,
                    name=_service_title(service_name),
                    root_path=service_name,
                    language=language,
                    package=_package_hint(
                        file_path.read_text(encoding="utf-8", errors="ignore"), language
                    ),
                    metadata_source="filesystem",
                )
            )

            text = file_path.read_text(encoding="utf-8", errors="ignore")
            class_name = _detect_primary_class_name(text, language)
            source_symbol = class_name or f"{service_name}.module"
            source_kind = (
                EntityKind.CLIENT
                if language == "kotlin" and "client" in service_name
                else EntityKind.SERVICE
            )
            _upsert_entity(
                entities_by_id,
                Entity(
                    entity_id=f"{service_name}.{source_symbol}",
                    name=source_symbol,
                    kind=source_kind,
                    service=service_name,
                    file=rel,
                    line=1,
                    metadata={"language": language, "source": "semantic"},
                ),
            )

            # Route extraction (provider detection)
            for method, route, line_no in _extract_route_declarations(text, language):
                entity_id = f"{service_name}.{source_symbol}"
                route_registry.register(
                    service=service_name,
                    host=service_name,
                    method=method,
                    route=route,
                    entity_id=entity_id,
                )
                _upsert_entity(
                    entities_by_id,
                    Entity(
                        entity_id=entity_id,
                        name=source_symbol,
                        kind=EntityKind.API if "/" in route else EntityKind.SERVICE,
                        service=service_name,
                        file=rel,
                        line=line_no,
                        metadata={"route": route, "language": language, "source": "semantic"},
                    ),
                )

        # Match local consumer routes against the full route registry after all providers
        # have been registered. This preserves deterministic output regardless of file order.
        for file_path in discovered_files:
            rel = file_path.relative_to(root).as_posix()
            service_name = rel.split("/")[0] if "/" in rel else root.name
            language = "python" if file_path.suffix.lower() == ".py" else "kotlin"
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            class_name = _detect_primary_class_name(text, language)
            source_symbol = class_name or f"{service_name}.module"
            for method, route, line_no in _extract_route_declarations(text, language):
                if language != "kotlin":
                    continue
                consumer_entity = f"{service_name}.{source_symbol}"
                provider_match = route_registry.match(method, "", route)
                if not provider_match or provider_match == consumer_entity:
                    candidates = [
                        candidate
                        for candidate in route_registry.candidates(method, "", route)
                        if not candidate.rsplit(".", 1)[-1].endswith("Client")
                    ]
                    if len(candidates) > 1:
                        diagnostics.append(
                            f"AMBIGUOUS API route {method} {route}: {', '.join(candidates)}"
                        )
                    continue
                _upsert_edge(
                    edge_map,
                    source=provider_match,
                    target=consumer_entity,
                    kind=EdgeKind.API_CONSUMES,
                    evidence=[
                        EdgeEvidence(
                            source_file=rel,
                            line=line_no,
                            column=0,
                            source_symbol=source_symbol,
                            syntax_kind="route_consumer",
                            matched_pattern="getProfile",
                            extracted_value=route,
                            resolution_rule="route_registry_match",
                            evidence_text_summary=f"{method} {route} consumed by {source_symbol}",
                        )
                    ],
                )

            # SQL / DB detection
            for table, column, operation, line_no in _extract_db_accesses(text):
                if operation == "DYNAMIC_SQL":
                    diagnostics.append(f"DYNAMIC_SQL at {rel}:{line_no}")
                    continue
                target_entity_id = f"{table}.{column}"
                database_registry.register_table_field(table, column, operation)
                _upsert_entity(
                    entities_by_id,
                    Entity(
                        entity_id=target_entity_id,
                        name=column,
                        kind=EntityKind.DATABASE,
                        # No SQL string carries the database's own name, so
                        # there is nothing to derive one from. A neutral label
                        # is honest; naming it after any particular fixture's
                        # database would stamp that repository's vocabulary
                        # onto every other repository's graph.
                        service=_DATABASE_SERVICE_LABEL,
                        file=rel,
                        line=line_no,
                        metadata={"table": table, "column": column, "operation": operation},
                    ),
                )
                edge_kind = EdgeKind.DB_READ if operation == "SELECT" else EdgeKind.DB_WRITE
                _upsert_edge(
                    edge_map,
                    source=target_entity_id,
                    target=f"{service_name}.{source_symbol}",
                    kind=edge_kind,
                    evidence=[
                        EdgeEvidence(
                            source_file=rel,
                            line=line_no,
                            column=0,
                            source_symbol=source_symbol,
                            syntax_kind="sql",
                            matched_pattern=operation,
                            extracted_value=f"{table}.{column}",
                            resolution_rule="static_sql_pattern",
                            evidence_text_summary=f"{operation} {table}.{column}",
                        )
                    ],
                )

            # Environment / config extraction
            for variable, line_no in _extract_config_variables(text, language):
                if variable == "<dynamic>":
                    diagnostics.append(f"DYNAMIC_CONFIG at {rel}:{line_no}")
                    continue
                target_entity_id = variable
                _upsert_entity(
                    entities_by_id,
                    Entity(
                        entity_id=target_entity_id,
                        name=variable,
                        kind=EntityKind.CONFIG,
                        service=service_name,
                        file=rel,
                        line=line_no,
                        metadata={"source": "environment", "language": language},
                    ),
                )
                _upsert_edge(
                    edge_map,
                    source=f"{service_name}.{source_symbol}",
                    target=target_entity_id,
                    kind=EdgeKind.CONFIG_DEPENDENCY,
                    evidence=[
                        EdgeEvidence(
                            source_file=rel,
                            line=line_no,
                            column=0,
                            source_symbol=source_symbol,
                            syntax_kind="config_access",
                            matched_pattern=variable,
                            extracted_value=variable,
                            resolution_rule="config_lookup",
                            evidence_text_summary=f"reads environment variable {variable}",
                        )
                    ],
                )

            # HTTP call extraction
            for method, url, line_no in _extract_http_calls(text, language):
                if url == "<dynamic>":
                    diagnostics.append(f"DYNAMIC_HTTP_TARGET at {rel}:{line_no}")
                    continue
                if not url:
                    continue
                safe_url = _redact_secret_values(url)
                target_service = _infer_service_from_url(url)
                api_name = _infer_api_class_name(target_service, url) if target_service else None
                if target_service and target_service != service_name and api_name:
                    target_entity = f"{target_service}.{api_name}"
                    _upsert_entity(
                        entities_by_id,
                        Entity(
                            entity_id=target_entity,
                            name=api_name,
                            kind=EntityKind.API,
                            service=target_service,
                            file=rel,
                            line=line_no,
                            metadata={"route": _normalize_route(safe_url), "method": method},
                        ),
                    )
                elif target_service == service_name:
                    target_entity = f"{service_name}.{source_symbol}"
                else:
                    target_entity = "unresolved"

                if target_entity == "unresolved":
                    continue

                _upsert_edge(
                    edge_map,
                    source=f"{service_name}.{source_symbol}",
                    target=target_entity,
                    kind=EdgeKind.HTTP_CALL,
                    evidence=[
                        EdgeEvidence(
                            source_file=rel,
                            line=line_no,
                            column=0,
                            source_symbol=source_symbol,
                            syntax_kind="call_expression",
                            matched_pattern=method,
                            extracted_value=safe_url,
                            resolution_rule="http_static_url",
                            evidence_text_summary=f"{method} {safe_url}",
                        )
                    ],
                )

                resolved_match = route_registry.match(method, target_service or service_name, url)
                if resolved_match and resolved_match != target_entity:
                    _upsert_edge(
                        edge_map,
                        source=resolved_match,
                        target=f"{service_name}.{source_symbol}",
                        kind=EdgeKind.API_CONSUMES,
                        evidence=[
                            EdgeEvidence(
                                source_file=rel,
                                line=line_no,
                                column=0,
                                source_symbol=source_symbol,
                                syntax_kind="call_expression",
                                matched_pattern=method,
                                extracted_value=safe_url,
                                resolution_rule="route_registry_match",
                                evidence_text_summary=f"consumer calls {method} {safe_url}",
                            )
                        ],
                    )

        edges = tuple(
            sorted(edge_map.values(), key=lambda edge: (edge.source, edge.target, edge.kind.value))
        )
        ordered_entities = tuple(sorted(entities_by_id.values(), key=lambda e: e.entity_id))
        ordered_services = tuple(sorted(services, key=lambda s: s.service_id))
        graph = _build_graph(list(ordered_entities), list(edges))
        return SemanticAnalysisResult(
            entities=ordered_entities,
            edges=edges,
            services=ordered_services,
            route_registry=route_registry,
            database_registry=database_registry,
            graph=graph,
            diagnostics=tuple(sorted(set(diagnostics))),
        )


def _build_graph(entities: list[Entity], edges: list[DependencyEdge]) -> PreFlightGraph:
    builder = GraphBuilder()
    for entity in entities:
        builder.add_entity(entity)
    for edge in edges:
        try:
            builder.add_dependency(edge)
        except ValueError:
            continue
    return builder.build()


def _upsert_entity(entities_by_id: dict[str, Entity], entity: Entity) -> None:
    entities_by_id[entity.entity_id] = entity


def _upsert_edge(
    edge_map: dict[tuple[str, str, str], DependencyEdge],
    *,
    source: str,
    target: str,
    kind: EdgeKind,
    evidence: list[EdgeEvidence],
) -> None:
    key = (source, target, kind.value)
    if key in edge_map:
        existing = edge_map[key]
        current = list(existing.metadata.get("evidence", []))
        current.extend([e.model_dump(mode="python") for e in evidence])
        deduped = sorted(
            {
                (
                    item.get("source_file"),
                    item.get("line"),
                    item.get("matched_pattern"),
                    item.get("extracted_value"),
                ): item
                for item in current
            }.values(),
            key=lambda item: (
                str(item.get("source_file", "")),
                int(item.get("line") or 0),
                str(item.get("matched_pattern") or ""),
                str(item.get("extracted_value") or ""),
            ),
        )
        edge_map[key] = existing.model_copy(
            update={
                "metadata": {
                    **existing.metadata,
                    "evidence": deduped,
                    "source_file": existing.metadata.get("source_file"),
                }
            }
        )
        return

    edge_map[key] = DependencyEdge(
        source=source,
        target=target,
        kind=kind,
        metadata={"evidence": [e.model_dump(mode="python") for e in evidence]},
    )


def _detect_primary_class_name(text: str, language: str) -> str:
    candidates: list[tuple[int, int, str]] = []
    root = _parse_source(text, language)
    declaration_types = (
        {"class_definition"}
        if language == "python"
        else {"class_declaration", "interface_declaration", "object_declaration"}
    )
    for node in _walk(root):
        if node.type not in declaration_types:
            continue
        name_node = next(
            (child for child in node.named_children if child.type == "identifier"), None
        )
        if name_node is None:
            continue
        name = _node_text(name_node, text)
        score = 0
        lowered = name.lower()
        if any(token in lowered for token in ("client", "service", "api", "controller", "handler")):
            score += 3
        if name.endswith("Service") or name.endswith("Client") or name.endswith("API"):
            score += 2
        if lowered in {"response", "row", "payload", "dto"}:
            score -= 5
        candidates.append((score, name_node.start_byte, name))

    if not candidates:
        return "Service"

    # Prefer the main runtime/service symbol over incidental model types such as
    # Response or Row; and prefer a later declaration when names are otherwise tied,
    # preserving deterministic ordering for the synthetic semantic graph.
    best = max(candidates, key=lambda item: (item[0], item[1]))
    return best[2]


def _package_hint(text: str, language: str) -> str | None:
    if language == "kotlin":
        match = re.search(r"package\s+([A-Za-z0-9_.]+)", text)
        if match:
            return match.group(1)
    return None


def _extract_route_declarations(text: str, language: str) -> list[tuple[str, str, int]]:
    results: list[tuple[str, str, int]] = []
    root = _parse_source(text, language)
    for node in _walk(root):
        if language == "python" and node.type == "decorator":
            decorator = _node_text(node, text)
            match = re.match(
                r"@(?:app|router)\.(get|post|put|patch|delete)\(\s*(['\"])([^'\"]+)\2",
                decorator,
                flags=re.IGNORECASE,
            )
            if match:
                results.append((match.group(1).upper(), match.group(3), node.start_point[0] + 1))
        elif language == "kotlin" and node.type in {"annotation", "annotation_use"}:
            annotation = _node_text(node, text)
            match = re.match(
                r"@(?:GET|POST|PUT|PATCH|DELETE)\(\s*(['\"])([^'\"]+)\1",
                annotation,
                flags=re.IGNORECASE,
            )
            if match:
                name = annotation[1:].split("(", 1)[0].upper()
                results.append((name, match.group(2), node.start_point[0] + 1))

    deduped: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in results:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _extract_db_accesses(text: str) -> list[tuple[str, str, str, int]]:
    results: list[tuple[str, str, str, int]] = []
    root = _parse_source(text, "python")
    for node in _walk(root):
        if node.type != "call":
            continue
        call_text = _node_text(node, text)
        if not re.match(r"(?:[A-Za-z_][\w.]*\.)?(?:execute|executemany|query|raw)\s*\(", call_text):
            continue
        string_nodes = [child for child in _walk(node) if child.type == "string"]
        if not string_nodes:
            results.append(("", "", "DYNAMIC_SQL", node.start_point[0] + 1))
            continue
        sql = _strip_quotes(_node_text(string_nodes[0], text))
        results.extend(_parse_sql_literal(sql, node.start_point[0] + 1))
    return results


def _parse_sql_literal(sql: str, line_no: int) -> list[tuple[str, str, str, int]]:
    select_match = re.match(
        r"\s*SELECT\s+(.+?)\s+FROM\s+([A-Za-z_][\w]*)", sql, flags=re.IGNORECASE
    )
    if select_match:
        return [
            (select_match.group(2), column.strip(), "SELECT", line_no)
            for column in select_match.group(1).split(",")
            if column.strip()
        ]
    update_match = re.match(r"\s*UPDATE\s+([A-Za-z_][\w]*)\s+SET\s+(.+?)", sql, flags=re.IGNORECASE)
    if update_match:
        field_match = re.match(r"([A-Za-z_][\w]*)\s*=", update_match.group(2).strip())
        return [
            (
                update_match.group(1),
                field_match.group(1) if field_match else "unknown",
                "UPDATE",
                line_no,
            )
        ]
    insert_match = re.match(r"\s*INSERT\s+INTO\s+([A-Za-z_][\w]*)", sql, flags=re.IGNORECASE)
    if insert_match:
        return [(insert_match.group(1), "unknown", "INSERT", line_no)]
    delete_match = re.match(r"\s*DELETE\s+FROM\s+([A-Za-z_][\w]*)", sql, flags=re.IGNORECASE)
    if delete_match:
        return [(delete_match.group(1), "unknown", "DELETE", line_no)]
    return []


def _extract_config_variables(text: str, language: str) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    root = _parse_source(text, language)
    for node in _walk(root):
        if language == "python" and node.type == "call":
            call_text = _node_text(node, text)
            match = re.match(r"os\.getenv\(\s*(['\"])([A-Z0-9_]+)\1", call_text)
            if match:
                results.append((match.group(2), node.start_point[0] + 1))
            elif call_text.startswith("os.getenv("):
                results.append(("<dynamic>", node.start_point[0] + 1))
        elif language == "kotlin" and node.type == "navigation_expression":
            value = _node_text(node, text)
            match = re.fullmatch(r"BuildConfig\.([A-Z0-9_]+)", value)
            if match:
                results.append((match.group(1), node.start_point[0] + 1))
    return results


def _extract_http_calls(text: str, language: str) -> list[tuple[str, str, int]]:
    results: list[tuple[str, str, int]] = []
    root = _parse_source(text, language)
    for node in _walk(root):
        if node.type not in {"call", "call_expression"}:
            continue
        call_text = _node_text(node, text)
        match = re.match(
            r"(?:(?:requests|httpx)\.)?(get|post|put|patch|delete)\(\s*(['\"])([^'\"]+)\2",
            call_text,
            flags=re.IGNORECASE,
        )
        if match:
            results.append((match.group(1).upper(), match.group(3), node.start_point[0] + 1))
            continue
        match = re.match(
            r'_http_(get|post|put|patch|delete)\(\s*(["\'])([^"\']+)\2',
            call_text,
            flags=re.IGNORECASE,
        )
        if match:
            results.append((match.group(1).upper(), match.group(3), node.start_point[0] + 1))
            continue
        dynamic_match = re.match(
            r"(?:(?:requests|httpx)\.)?(?:get|post|put|patch|delete)\(",
            call_text,
            flags=re.IGNORECASE,
        ) or re.match(
            r"_http_(?:get|post|put|patch|delete)\(", call_text, flags=re.IGNORECASE
        )
        if dynamic_match:
            results.append(("", "<dynamic>", node.start_point[0] + 1))
    return results


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _redact_secret_values(value: str) -> str:
    """Keep secret names while removing literal values from evidence."""

    return re.sub(
        r"(?i)((?:api[_-]?key|secret|password|token|authorization|credential)=)[^&\s]+",
        r"\1<redacted>",
        value,
    )


def _infer_service_from_url(url: str) -> str | None:
    normalized = url.strip()
    if "http://" in normalized:
        normalized = normalized.split("http://", 1)[1]
    elif "https://" in normalized:
        normalized = normalized.split("https://", 1)[1]
    if not normalized:
        return None
    host = normalized.split("/", 1)[0]
    return host.split(":", 1)[0].strip() if host else None


# Tokens that read as acronyms in a service hostname. Used only for casing
# an already-extracted name — never to invent one.
_ACRONYM_TOKENS = frozenset({"api", "db", "id", "url", "http", "https", "sql", "ui", "io", "rpc"})


def _infer_api_class_name(service: str, url: str) -> str | None:
    """Derive the remote API entity's name from the real service host in the URL.

    The name is a deterministic transformation of evidence actually present in
    the source (the URL's host component), never a fixed guess: a host of
    ``profile-api`` yields ``ProfileAPI`` and ``pricing-engine`` yields
    ``PricingEngine``. Returning a hardcoded default here would stamp one
    repository's vocabulary onto every other repository's graph.
    """
    if not service:
        return None
    tokens = [token for token in re.split(r"[-_.\s]+", service.strip()) if token]
    if not tokens:
        return None
    return "".join(
        token.upper() if token.lower() in _ACRONYM_TOKENS else token[:1].upper() + token[1:].lower()
        for token in tokens
    )


def _normalize_db_operation(value: str) -> str:
    normalized = (value or "").upper().strip()
    if normalized in {"SELECT", "DB_READ"}:
        return "DB_READ"
    if normalized in {"INSERT", "UPDATE", "DELETE", "DB_WRITE"}:
        return "DB_WRITE"
    return normalized


def _normalize_host(value: str) -> str:
    return value.strip().replace("http://", "").replace("https://", "").split(":", 1)[0].lower()


def _normalize_method(value: str) -> str:
    return (value or "GET").upper().strip()


def _normalize_route(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "/"
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        _, _, remainder = cleaned.partition("//")
        cleaned = "/" + remainder.split("/", 1)[1] if "/" in remainder else "/"
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    cleaned = re.sub(r"\{[^}]+\}", "{id}", cleaned)
    return cleaned.rstrip("/") or "/"


def _route_matches(candidate: str, target: str) -> bool:
    candidate_norm = _normalize_route(candidate)
    target_norm = _normalize_route(target)
    if candidate_norm == target_norm:
        return True
    candidate_parts = candidate_norm.split("/")
    target_parts = target_norm.split("/")
    if len(candidate_parts) != len(target_parts):
        return False
    for source_part, target_part in zip(candidate_parts, target_parts, strict=True):
        if source_part == target_part:
            continue
        if source_part.startswith("{") and source_part.endswith("}"):
            continue
        if target_part.startswith("{") and target_part.endswith("}"):
            continue
        return False
    return True


__all__ = [
    "DatabaseEntityRegistry",
    "EdgeEvidence",
    "RouteRegistry",
    "SemanticAnalyzer",
    "SemanticCandidate",
    "SemanticAnalysisResult",
    "ServiceDescriptor",
]
