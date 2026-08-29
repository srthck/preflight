from __future__ import annotations

from preflight.fixtures.loader import build_demo_commerce_graph
from preflight.schema import (
    DeploymentAnalyzer,
    DeploymentFinding,
    SchemaChangeKind,
    SchemaModel,
    parse_migration_sql,
)


def test_schema_model_round_trips_tables_and_columns() -> None:
    schema = SchemaModel(
        tables=(
            {
                "name": "users",
                "columns": (
                    {
                        "name": "id",
                        "data_type": "INTEGER",
                        "nullable": False,
                        "default": None,
                        "primary_key": True,
                        "unique": False,
                    },
                    {
                        "name": "phone_number",
                        "data_type": "TEXT",
                        "nullable": True,
                        "default": None,
                        "primary_key": False,
                        "unique": False,
                    },
                ),
            },
        )
    )

    assert schema.tables[0].name == "users"
    assert schema.find_column("users", "phone_number").data_type == "TEXT"


def test_drop_column_change_is_destructive() -> None:
    result = parse_migration_sql("ALTER TABLE users DROP COLUMN phone_number;")

    assert result.kind == "parsed"
    changes = result.changes
    assert len(changes) == 1
    change = changes[0]
    assert change.kind == SchemaChangeKind.DROP_COLUMN
    assert change.table == "users"
    assert change.object_name == "phone_number"
    assert change.category == "DESTRUCTIVE"


def test_not_null_change_is_data_dependent() -> None:
    result = parse_migration_sql("ALTER TABLE users ALTER COLUMN phone_number SET NOT NULL;")

    assert result.kind == "parsed"
    assert result.changes[0].kind == SchemaChangeKind.ALTER_NULLABILITY
    assert result.changes[0].category == "DATA_DEPENDENT"


def test_additive_column_change_is_safe() -> None:
    result = parse_migration_sql(
        "ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;"
    )

    assert result.kind == "parsed"
    assert result.changes[0].kind == SchemaChangeKind.ADD_COLUMN
    assert result.changes[0].category == "ADDITIVE"


def test_malformed_sql_returns_structured_parse_error() -> None:
    result = parse_migration_sql("ALTER TABLE users DROP COLUMN;")

    assert result.kind == "error"
    assert result.errors


def test_deployment_analyzer_correlates_drop_column_with_graph() -> None:
    schema = SchemaModel(
        tables=(
            {
                "name": "users",
                "columns": (
                    {"name": "id", "data_type": "INTEGER", "nullable": False, "default": None, "primary_key": True, "unique": False},
                    {"name": "phone_number", "data_type": "TEXT", "nullable": True, "default": None, "primary_key": False, "unique": False},
                ),
            },
        )
    )
    graph = build_demo_commerce_graph()
    analyzer = DeploymentAnalyzer(graph=graph, schema=schema)

    finding = analyzer.analyze("ALTER TABLE users DROP COLUMN phone_number;")
    assert finding.deployment_status == "UNSAFE"
    assert finding.schema_object == "users.phone_number"
    assert finding.affected_entities
    assert any(entity == "user-service.UserService" for entity in finding.affected_entities)


def test_safe_additive_change_is_compatible() -> None:
    schema = SchemaModel(
        tables=(
            {
                "name": "users",
                "columns": (
                    {"name": "id", "data_type": "INTEGER", "nullable": False, "default": None, "primary_key": True, "unique": False},
                    {"name": "phone_number", "data_type": "TEXT", "nullable": True, "default": None, "primary_key": False, "unique": False},
                ),
            },
        )
    )
    graph = build_demo_commerce_graph()
    analyzer = DeploymentAnalyzer(graph=graph, schema=schema)

    finding = analyzer.analyze("ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;")
    assert finding.deployment_status in {"SAFE", "COMPATIBLE"}
    assert finding.schema_object == "users.phone_verified"


def test_parse_migration_sql_redacts_sensitive_values() -> None:
    result = parse_migration_sql(
        "ALTER TABLE users ADD COLUMN api_token TEXT DEFAULT 'super-secret-token';"
    )

    serialized = str(result)
    assert "super-secret-token" not in serialized
    assert "secret" not in serialized.lower()


def test_deployment_finding_is_json_serializable() -> None:
    finding = DeploymentFinding(
        finding_id="f-1",
        category="DESTRUCTIVE",
        severity="HIGH",
        schema_object="users.phone_number",
        change="DROP_COLUMN",
        affected_entities=("user-service.UserService",),
        dependency_paths=(("users.phone_number", "user-service.UserService"),),
        evidence=(("user_service.py", 48, "SELECT phone_number FROM users"),),
        explanation_key="drop_column_active_dependency",
        deployment_status="UNSAFE",
    )

    payload = finding.model_dump(mode="json")
    assert payload["deployment_status"] == "UNSAFE"
    assert payload["schema_object"] == "users.phone_number"
