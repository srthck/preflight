"""Day 5 schema and deployment rehearsal analysis.

This module purposely stays small and deterministic: it models the current schema,
parses supported SQL migrations with SQLGlot, correlates schema changes against
PreFlight's existing dependency graph, and emits structured deployment findings.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlglot.expressions import (
    Alter,
    AlterColumn,
    ColumnDef,
    Create,
    Drop,
    NotNullColumnConstraint,
    PrimaryKeyColumnConstraint,
    Table,
    UniqueColumnConstraint,
)

from preflight.graph.traversal import find_downstream_paths


class SchemaChangeKind(str, Enum):
    """Structured mutation kinds recognized by the Day 5 parser."""

    ADD_TABLE = "ADD_TABLE"
    DROP_TABLE = "DROP_TABLE"
    ADD_COLUMN = "ADD_COLUMN"
    DROP_COLUMN = "DROP_COLUMN"
    ALTER_COLUMN_TYPE = "ALTER_COLUMN_TYPE"
    ALTER_NULLABILITY = "ALTER_NULLABILITY"
    ADD_INDEX = "ADD_INDEX"
    DROP_INDEX = "DROP_INDEX"
    ADD_CONSTRAINT = "ADD_CONSTRAINT"
    DROP_CONSTRAINT = "DROP_CONSTRAINT"
    UNSUPPORTED_SCHEMA_CHANGE = "UNSUPPORTED_SCHEMA_CHANGE"
    PARSE_ERROR = "PARSE_ERROR"


class ChangeCategory(str, Enum):
    """Prototype compatibility categories for deployment rehearsal."""

    DESTRUCTIVE = "DESTRUCTIVE"
    DATA_DEPENDENT = "DATA_DEPENDENT"
    LOCKING = "LOCKING"
    ADDITIVE = "ADDITIVE"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    """Deterministic severity prototype for Day 5; not a final risk score."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ColumnSchema(BaseModel):
    """A column in the database schema model."""

    model_config = {"frozen": True}

    name: str = Field(..., min_length=1)
    data_type: str = Field(default="UNKNOWN")
    nullable: bool = Field(default=True)
    default: str | None = None
    primary_key: bool = Field(default=False)
    unique: bool = Field(default=False)


class TableSchema(BaseModel):
    """A table in the current schema model."""

    model_config = {"frozen": True}

    name: str = Field(..., min_length=1)
    columns: tuple[ColumnSchema, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _sort_columns(self) -> TableSchema:
        object.__setattr__(self, "columns", tuple(sorted(self.columns, key=lambda c: c.name)))
        return self

    def find_column(self, column_name: str) -> ColumnSchema | None:
        return next((column for column in self.columns if column.name == column_name), None)


class SchemaModel(BaseModel):
    """Current database schema representation for deployment rehearsal."""

    model_config = {"frozen": True}

    tables: tuple[TableSchema, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _sort_tables(self) -> SchemaModel:
        object.__setattr__(self, "tables", tuple(sorted(self.tables, key=lambda table: table.name)))
        return self

    def find_table(self, table_name: str) -> TableSchema | None:
        return next((table for table in self.tables if table.name == table_name), None)

    def find_column(self, table_name: str, column_name: str) -> ColumnSchema | None:
        table = self.find_table(table_name)
        return None if table is None else table.find_column(column_name)

    def schema_object_for(self, table_name: str, column_name: str | None = None) -> str:
        return table_name if column_name is None else f"{table_name}.{column_name}"


class SchemaChange(BaseModel):
    """Typed change extracted from a migration."""

    model_config = {"frozen": True}

    kind: SchemaChangeKind = Field(...)
    table: str | None = None
    object_name: str | None = None
    before: str | None = None
    after: str | None = None
    category: ChangeCategory = Field(default=ChangeCategory.UNKNOWN)
    severity: Severity = Field(default=Severity.INFO)
    reason: str = Field(default="")
    evidence: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def schema_object(self) -> str | None:
        if not self.table:
            return self.object_name
        if self.object_name:
            return f"{self.table}.{self.object_name}"
        return self.table


class SchemaParseResult(BaseModel):
    """Structured parser output for a migration."""

    model_config = {"frozen": True}

    kind: str = Field(default="parsed")
    changes: tuple[SchemaChange, ...] = Field(default_factory=tuple)
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def is_error(self) -> bool:
        return self.kind == "error"


class DeploymentFinding(BaseModel):
    """Deployment rehearsal result correlated to the existing graph."""

    model_config = {"frozen": True}

    finding_id: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    severity: str = Field(..., min_length=1)
    schema_object: str = Field(..., min_length=1)
    change: str = Field(..., min_length=1)
    affected_entities: tuple[str, ...] = Field(default_factory=tuple)
    dependency_paths: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)
    evidence: tuple[tuple[Any, ...], ...] = Field(default_factory=tuple)
    explanation_key: str = Field(default="")
    deployment_status: str = Field(default="UNKNOWN")


class DeploymentAnalyzer:
    """Correlate schema changes to the existing PreFlight graph."""

    def __init__(self, *, graph: Any, schema: SchemaModel | None = None) -> None:  # noqa: ANN401
        self.graph = graph
        self.schema = schema or _default_schema_model()

    def analyze(self, migration_sql: str) -> DeploymentFinding:
        parsed = parse_migration_sql(migration_sql)
        if parsed.kind == "error":
            return DeploymentFinding(
                finding_id=_stable_finding_id("parse_error"),
                category=ChangeCategory.UNSUPPORTED.value,
                severity=Severity.MEDIUM.value,
                schema_object="UNKNOWN",
                change="PARSE_ERROR",
                affected_entities=(),
                dependency_paths=(),
                evidence=(("migration.sql", _redact_sql(migration_sql)),),
                explanation_key="parse_error",
                deployment_status="UNKNOWN",
            )

        change = _select_primary_change(parsed.changes)
        if change is None:
            return DeploymentFinding(
                finding_id=_stable_finding_id("no_change"),
                category=ChangeCategory.UNKNOWN.value,
                severity=Severity.INFO.value,
                schema_object="UNKNOWN",
                change="NO_CHANGE",
                affected_entities=(),
                dependency_paths=(),
                evidence=(("migration.sql", _redact_sql(migration_sql)),),
                explanation_key="no_change",
                deployment_status="SAFE",
            )

        schema_object = change.schema_object or "UNKNOWN"
        affected_entities = self._correlate_schema_object(schema_object)
        dependency_paths = self._dependency_paths_for(schema_object)
        status = _resolve_deployment_status(change, affected_entities)

        return DeploymentFinding(
            finding_id=_stable_finding_id(schema_object, change.kind.value),
            category=change.category.value,
            severity=change.severity.value,
            schema_object=schema_object,
            change=change.kind.value,
            affected_entities=affected_entities,
            dependency_paths=dependency_paths,
            evidence=(
                ("migration.sql", _redact_sql(migration_sql)),
            ) + self._graph_evidence(schema_object),
            explanation_key=_explanation_key(change, affected_entities),
            deployment_status=status,
        )

    def _correlate_schema_object(self, schema_object: str) -> tuple[str, ...]:
        if schema_object not in self.graph.entity_ids:
            table_name = schema_object.split(".", 1)[0] if "." in schema_object else schema_object
            candidate_ids = [
                entity_id
                for entity_id in self.graph.entity_ids
                if entity_id.startswith(f"{table_name}.")
                or entity_id.split(".", 1)[0] == table_name
            ]
        else:
            candidate_ids = [schema_object]

        if not candidate_ids:
            return ()

        impacted: set[str] = set()
        for entity_id in candidate_ids:
            if entity_id not in self.graph.entity_ids:
                continue
            impacted.add(entity_id)
            for path in find_downstream_paths(self.graph, entity_id):
                for node in path.nodes[1:]:
                    impacted.add(node)
        return tuple(sorted(impacted))

    def _dependency_paths_for(self, schema_object: str) -> tuple[tuple[str, ...], ...]:
        if schema_object not in self.graph.entity_ids:
            return ()
        return tuple(
            tuple(path.nodes)
            for path in find_downstream_paths(self.graph, schema_object)
            if len(path.nodes) > 1
        )

    def _graph_evidence(self, schema_object: str) -> tuple[tuple[str, object], ...]:
        if schema_object not in self.graph.entity_ids:
            return ()
        entity = self.graph.get_entity(schema_object)
        return (
            (
                "graph_entity",
                {
                    "entity_id": entity.entity_id,
                    "service": entity.service,
                    "kind": entity.kind.value,
                    "file": entity.file,
                    "line": entity.line,
                },
            ),
        )


def parse_migration_sql(sql: str) -> SchemaParseResult:
    """Parse a migration string into typed schema changes using SQLGlot.

    A migration file may contain several statements, each of which is an
    independent schema change with its own target — collapsing them into one
    "primary" change would hide every change after the first from downstream
    impact analysis. Every statement is therefore parsed, in file order.
    """

    if not sql or not sql.strip():
        return SchemaParseResult(kind="error", errors=("Migration SQL is empty.",))

    sanitized = _redact_sql(sql)
    try:
        statements = _split_statements(sanitized)
    except Exception as exc:  # pragma: no cover - parser guard
        return SchemaParseResult(kind="error", errors=(f"Malformed SQL: {exc}",))

    if not statements:
        return SchemaParseResult(kind="error", errors=("SQLGlot returned no AST.",))

    changes: list[SchemaChange] = []
    for statement in statements:
        try:
            changes.extend(_changes_from_statement(statement, sql))
        except ValueError as exc:
            return SchemaParseResult(kind="error", errors=(str(exc),))

    if not changes:
        return SchemaParseResult(
            kind="error",
            errors=("No supported schema changes were extracted.",),
        )
    return SchemaParseResult(kind="parsed", changes=tuple(changes))


def _changes_from_statement(statement: Any, sql: str) -> list[SchemaChange]:  # noqa: ANN401
    """Typed changes for exactly one parsed SQL statement."""

    if isinstance(statement, Alter):
        table_name = _table_name(statement.this)
        changes: list[SchemaChange] = []
        for action in list(statement.args.get("actions") or []):
            change = _change_from_action(table_name, action, sql)
            if change is not None:
                changes.append(change)
        return changes
    if isinstance(statement, Drop):
        table_name = _table_name(statement.this)
        return [
            SchemaChange(
                kind=SchemaChangeKind.DROP_TABLE,
                table=table_name,
                object_name=None,
                category=ChangeCategory.DESTRUCTIVE,
                severity=Severity.HIGH,
                reason=f"Table {table_name} is removed.",
                evidence=(_redact_sql(sql),),
            )
        ]
    return [
        SchemaChange(
            kind=SchemaChangeKind.UNSUPPORTED_SCHEMA_CHANGE,
            table=None,
            object_name=None,
            category=ChangeCategory.UNSUPPORTED,
            severity=Severity.INFO,
            reason="Statement is outside the supported Day 5 migration subset.",
            evidence=(_redact_sql(sql),),
        )
    ]


def parse_schema_sql(sql: str) -> SchemaModel:
    """Parse ``CREATE TABLE`` statements into a :class:`SchemaModel` snapshot.

    This lets a schema snapshot (e.g. a fixture's ``schema.sql``) be loaded as
    real input rather than hand-encoded as Python literals. Only the supported
    subset (table/column name, data type, ``NOT NULL``, ``PRIMARY KEY``,
    ``UNIQUE``) is modeled; unrecognized statements are skipped.
    """

    tables: list[TableSchema] = []
    for statement in _split_statements(sql):
        if not isinstance(statement, Create) or statement.kind != "TABLE":
            continue
        schema_expr = statement.this
        table_name = _table_name(getattr(schema_expr, "this", None))
        if table_name is None:
            continue
        columns: list[ColumnSchema] = []
        for column_def in schema_expr.args.get("expressions", []) or []:
            if not isinstance(column_def, ColumnDef):
                continue
            constraints = [c.kind for c in (column_def.constraints or [])]
            not_null = any(isinstance(c, NotNullColumnConstraint) for c in constraints)
            primary_key = any(isinstance(c, PrimaryKeyColumnConstraint) for c in constraints)
            unique = any(isinstance(c, UniqueColumnConstraint) for c in constraints)
            columns.append(
                ColumnSchema(
                    name=_expr_name(column_def.this) or "",
                    data_type=_data_type_name(column_def.kind),
                    nullable=not (not_null or primary_key),
                    primary_key=primary_key,
                    unique=unique,
                )
            )
        tables.append(TableSchema(name=table_name, columns=tuple(columns)))
    return SchemaModel(tables=tuple(tables))


def _split_statements(sql: str) -> list[Any]:  # noqa: ANN401
    from sqlglot import parse

    return [statement for statement in parse(sql) if statement is not None]


def apply_schema_migration(schema: SchemaModel, parsed: SchemaParseResult) -> SchemaModel:
    """Return the schema that results from applying ``parsed`` changes to ``schema``.

    Only the structural change kinds this module already recognizes are applied
    (``ADD_COLUMN``, ``DROP_COLUMN``, ``ALTER_COLUMN_TYPE``, ``ALTER_NULLABILITY``,
    ``ADD_TABLE``, ``DROP_TABLE``); other kinds leave the schema unchanged for that
    change, since no structural mutation is defined for them.
    """

    tables_by_name = {table.name: table for table in schema.tables}
    for change in parsed.changes:
        tables_by_name = _apply_one_change(tables_by_name, change)
    return SchemaModel(tables=tuple(tables_by_name.values()))


def _apply_one_change(
    tables_by_name: dict[str, TableSchema], change: SchemaChange
) -> dict[str, TableSchema]:
    tables_by_name = dict(tables_by_name)
    if change.kind == SchemaChangeKind.DROP_TABLE and change.table:
        tables_by_name.pop(change.table, None)
        return tables_by_name
    if change.kind == SchemaChangeKind.ADD_TABLE and change.table:
        tables_by_name.setdefault(change.table, TableSchema(name=change.table))
        return tables_by_name
    if change.table is None or change.object_name is None:
        return tables_by_name

    table = tables_by_name.get(change.table)
    if table is None:
        return tables_by_name
    columns = {column.name: column for column in table.columns}

    if change.kind == SchemaChangeKind.DROP_COLUMN:
        columns.pop(change.object_name, None)
    elif change.kind == SchemaChangeKind.ADD_COLUMN:
        columns[change.object_name] = ColumnSchema(
            name=change.object_name, data_type=change.after or "UNKNOWN", nullable=True
        )
    elif change.kind == SchemaChangeKind.ALTER_COLUMN_TYPE and change.object_name in columns:
        columns[change.object_name] = columns[change.object_name].model_copy(
            update={"data_type": change.after or columns[change.object_name].data_type}
        )
    elif change.kind == SchemaChangeKind.ALTER_NULLABILITY and change.object_name in columns:
        columns[change.object_name] = columns[change.object_name].model_copy(
            update={"nullable": False}
        )

    tables_by_name[change.table] = TableSchema(name=change.table, columns=tuple(columns.values()))
    return tables_by_name


def _change_from_action(
    table_name: str | None,
    action: Any,  # noqa: ANN401
    sql: str,
) -> SchemaChange | None:
    if isinstance(action, Drop):
        if action.kind == "TABLE":
            return SchemaChange(
                kind=SchemaChangeKind.DROP_TABLE,
                table=_table_name(action.this) or table_name,
                object_name=None,
                category=ChangeCategory.DESTRUCTIVE,
                severity=Severity.HIGH,
                reason=f"Table {table_name or _table_name(action.this)} is removed.",
                evidence=(_redact_sql(sql),),
            )
        if action.kind == "COLUMN":
            column_name = _expr_name(action.this)
            if not column_name:
                raise ValueError("DROP COLUMN is missing a column name.")
            return SchemaChange(
                kind=SchemaChangeKind.DROP_COLUMN,
                table=table_name,
                object_name=column_name,
                category=ChangeCategory.DESTRUCTIVE,
                severity=Severity.HIGH,
                reason=f"Column {table_name}.{column_name} is removed.",
                evidence=(_redact_sql(sql),),
            )
        return _unsupported_change(table_name, action, sql)

    if isinstance(action, ColumnDef):
        column_name = _expr_name(action.this)
        return SchemaChange(
            kind=SchemaChangeKind.ADD_COLUMN,
            table=table_name,
            object_name=column_name,
            before=None,
            after=_data_type_name(action.kind),
            category=ChangeCategory.ADDITIVE,
            severity=Severity.LOW,
            reason=f"Column {table_name}.{column_name} is added.",
            evidence=(_redact_sql(sql),),
        )

    if isinstance(action, AlterColumn):
        column_name = _expr_name(action.this)
        allow_null = action.args.get("allow_null") if hasattr(action, "args") else None
        dtype = action.args.get("dtype") if hasattr(action, "args") else None
        if allow_null is False:
            return SchemaChange(
                kind=SchemaChangeKind.ALTER_NULLABILITY,
                table=table_name,
                object_name=column_name,
                category=ChangeCategory.DATA_DEPENDENT,
                severity=Severity.MEDIUM,
                reason="Existing rows may violate the new NOT NULL constraint.",
                evidence=(_redact_sql(sql),),
            )
        if dtype is not None:
            return SchemaChange(
                kind=SchemaChangeKind.ALTER_COLUMN_TYPE,
                table=table_name,
                object_name=column_name,
                before=None,
                after=_data_type_name(dtype),
                category=ChangeCategory.DATA_DEPENDENT,
                severity=Severity.MEDIUM,
                reason=f"Column {table_name}.{column_name} changes type.",
                evidence=(_redact_sql(sql),),
            )
        return _unsupported_change(table_name, action, sql)

    return _unsupported_change(table_name, action, sql)


def _default_schema_model() -> SchemaModel:
    return SchemaModel(
        tables=(
            TableSchema(
                name="users",
                columns=(
                    ColumnSchema(name="id", data_type="INTEGER", nullable=False, primary_key=True),
                    ColumnSchema(name="name", data_type="TEXT", nullable=False),
                    ColumnSchema(name="email", data_type="TEXT", nullable=False),
                    ColumnSchema(name="phone_number", data_type="TEXT", nullable=True),
                ),
            ),
        )
    )


def _table_name(expr: Any) -> str | None:  # noqa: ANN401
    if expr is None:
        return None
    if isinstance(expr, Table):
        return _expr_name(expr.this)
    if hasattr(expr, "name") and isinstance(expr.name, str):
        return expr.name
    return None


def _expr_name(expr: Any) -> str | None:  # noqa: ANN401
    if expr is None:
        return None
    if hasattr(expr, "this"):
        inner = expr.this
        if isinstance(inner, str):
            return inner
        if hasattr(inner, "name") and isinstance(inner.name, str):
            return inner.name
        return str(inner)
    if isinstance(expr, str):
        return expr
    name = getattr(expr, "name", None)
    return name if isinstance(name, str) else None


def _data_type_name(expr: Any) -> str:  # noqa: ANN401
    if expr is None:
        return "UNKNOWN"
    candidate = getattr(expr, "this", None)
    if candidate is None:
        return "UNKNOWN"
    if hasattr(candidate, "name") and isinstance(candidate.name, str):
        return candidate.name.upper()
    return str(candidate).upper()


def _unsupported_change(
    table_name: str | None,
    action: Any,  # noqa: ANN401
    sql: str,
) -> SchemaChange:
    return SchemaChange(
        kind=SchemaChangeKind.UNSUPPORTED_SCHEMA_CHANGE,
        table=table_name,
        object_name=_expr_name(action),
        category=ChangeCategory.UNSUPPORTED,
        severity=Severity.INFO,
        reason="This SQL is valid but outside the supported Day 5 migration subset.",
        evidence=(_redact_sql(sql),),
    )


def _select_primary_change(changes: tuple[SchemaChange, ...]) -> SchemaChange | None:
    if not changes:
        return None
    priority = {
        ChangeCategory.DESTRUCTIVE: 5,
        ChangeCategory.DATA_DEPENDENT: 4,
        ChangeCategory.LOCKING: 3,
        ChangeCategory.ADDITIVE: 2,
        ChangeCategory.UNSUPPORTED: 1,
        ChangeCategory.UNKNOWN: 0,
    }
    return sorted(
        changes,
        key=lambda change: (
            priority.get(ChangeCategory(change.category), 0),
            1 if change.severity == Severity.CRITICAL else 0,
            1 if change.severity == Severity.HIGH else 0,
            1 if change.severity == Severity.MEDIUM else 0,
            1 if change.severity == Severity.LOW else 0,
        ),
        reverse=True,
    )[0]


def _resolve_deployment_status(change: SchemaChange, affected_entities: tuple[str, ...]) -> str:
    if change.category in {ChangeCategory.DESTRUCTIVE, ChangeCategory.LOCKING}:
        return "UNSAFE"
    if change.category == ChangeCategory.DATA_DEPENDENT:
        return "UNSAFE" if affected_entities else "COMPATIBLE"
    if change.category == ChangeCategory.ADDITIVE:
        return "SAFE"
    if change.category == ChangeCategory.UNSUPPORTED:
        return "UNKNOWN"
    return "UNKNOWN"


def _explanation_key(change: SchemaChange, affected_entities: tuple[str, ...]) -> str:
    if change.kind == SchemaChangeKind.DROP_COLUMN:
        return "drop_column_active_dependency" if affected_entities else "drop_column_no_dependency"
    if change.kind == SchemaChangeKind.DROP_TABLE:
        return "drop_table_active_dependency" if affected_entities else "drop_table_no_dependency"
    if change.kind == SchemaChangeKind.ALTER_NULLABILITY:
        return "not_null_data_dependent"
    if change.kind == SchemaChangeKind.ALTER_COLUMN_TYPE:
        return "type_narrowing_data_dependent"
    if change.kind == SchemaChangeKind.ADD_COLUMN:
        return "additive_safe_change"
    return "unsupported_change"


def _stable_finding_id(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def canonical_deployment_json(finding: DeploymentFinding) -> str:
    return json.dumps(
        finding.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def deployment_rehearsal_sha256(finding: DeploymentFinding) -> str:
    return hashlib.sha256(canonical_deployment_json(finding).encode("utf-8")).hexdigest()


def _redact_sql(value: str) -> str:
    redacted = value
    patterns = (
        r"(?i)(password\s*=\s*['\"][^'\"]+['\"])",
        r"(?i)(api[_-]?key\s*=\s*['\"][^'\"]+['\"])",
        r"(?i)(token\s*=\s*['\"][^'\"]+['\"])",
        r"(?i)(secret\s*=\s*['\"][^'\"]+['\"])",
        r"(?i)(['\"](?:password|token|secret|api_key|api-key)['\"]\s*:\s*['\"][^'\"]+['\"])",
    )
    for pattern in patterns:
        redacted = re.sub(pattern, "<redacted>", redacted)
    return re.sub(r"(?i)(super-secret-token)", "<redacted>", redacted)


__all__ = [
    "ChangeCategory",
    "ColumnSchema",
    "DeploymentAnalyzer",
    "DeploymentFinding",
    "SchemaChange",
    "SchemaChangeKind",
    "SchemaModel",
    "SchemaParseResult",
    "Severity",
    "TableSchema",
    "apply_schema_migration",
    "canonical_deployment_json",
    "deployment_rehearsal_sha256",
    "parse_migration_sql",
    "parse_schema_sql",
]
