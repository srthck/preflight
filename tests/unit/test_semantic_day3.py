from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from preflight.domain.enums import EdgeKind
from preflight.graph.serialization import canonical_json
from preflight.semantic import (
    DatabaseEntityRegistry,
    EdgeEvidence,
    RouteRegistry,
    SemanticAnalyzer,
    ServiceDescriptor,
)


def test_edge_kind_call_exists() -> None:
    assert EdgeKind.CALL.value == "CALL"


def test_route_registry_matches_http_routes() -> None:
    registry = RouteRegistry()
    registry.register(
        service="profile-api",
        host="profile-api",
        method="GET",
        route="/profile/{id}",
        entity_id="profile-api.ProfileAPI",
    )

    result = registry.match("GET", "profile-api", "/profile/42")
    assert result == "profile-api.ProfileAPI"


def test_route_registry_reports_ambiguous_duplicate_providers() -> None:
    registry = RouteRegistry()
    for service in ("profile-a", "profile-b"):
        registry.register(
            service=service,
            host="profile-api",
            method="GET",
            route="/profile/{id}",
            entity_id=f"{service}.ProfileAPI",
        )

    assert registry.match("GET", "profile-api", "/profile/42") is None
    assert len(registry.entries) == 2


def test_http_method_matrix_is_method_sensitive() -> None:
    registry = RouteRegistry()
    for method, entity in {
        "GET": "user-service.GetProvider",
        "POST": "user-service.PostProvider",
        "PUT": "user-service.PutProvider",
        "PATCH": "user-service.PatchProvider",
        "DELETE": "user-service.DeleteProvider",
    }.items():
        registry.register(
            service="user-service",
            host="user-service",
            method=method,
            route="/users",
            entity_id=f"user-service.{entity.split('.')[-1]}",
        )

    assert registry.match("GET", "user-service", "/users") == "user-service.GetProvider"
    assert registry.match("POST", "user-service", "/users") == "user-service.PostProvider"
    assert registry.match("PUT", "user-service", "/users") == "user-service.PutProvider"
    assert registry.match("PATCH", "user-service", "/users") == "user-service.PatchProvider"
    assert registry.match("DELETE", "user-service", "/users") == "user-service.DeleteProvider"

    for wrong_method in ("POST", "PUT", "PATCH", "DELETE"):
        assert registry.match(wrong_method, "user-service", "/users") != "user-service.GetProvider"


def test_database_registry_tracks_field_access() -> None:
    registry = DatabaseEntityRegistry()
    registry.register_table_field("users", "phone_number", "DB_READ")

    assert registry.lookup_table_field("users", "phone_number") == "DB_READ"
    assert registry.lookup_table_field("users", "missing") is None


def test_database_operation_matrix_normalizes_sql_to_db_semantics() -> None:
    registry = DatabaseEntityRegistry()
    for operation, expected in {
        "SELECT": "DB_READ",
        "INSERT": "DB_WRITE",
        "UPDATE": "DB_WRITE",
        "DELETE": "DB_WRITE",
    }.items():
        registry.register_table_field("users", "phone_number", operation)
        assert registry.lookup_table_field("users", "phone_number") == expected


def test_semantic_analyzer_reports_ambiguous_provider_candidates() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        provider_a = root / "profile-a"
        provider_b = root / "profile-b"
        consumer = root / "consumer"
        for path in (provider_a, provider_b, consumer):
            path.mkdir()
            (path / "src").mkdir()

        (provider_a / "src" / "profile_api.py").write_text(
            "from __future__ import annotations\n\nclass ProfileAPI:\n    @app.get(\"/profile/{id}\")\n    def get_profile(self, user_id):\n        return None\n",
            encoding="utf-8",
        )
        (provider_b / "src" / "profile_api.py").write_text(
            "from __future__ import annotations\n\nclass ProfileAPI:\n    @app.get(\"/profile/{id}\")\n    def get_profile(self, user_id):\n        return None\n",
            encoding="utf-8",
        )
        (consumer / "src" / "profile_client.kt").write_text(
            "package demo\n\ninterface ProfileApiService {\n    @GET(\"/profile/{id}\")\n    fun getProfile(userId: Int): String\n}\n",
            encoding="utf-8",
        )

        result = SemanticAnalyzer().analyze(root)

        assert any("AMBIGUOUS API route GET /profile/{id}" in diagnostic for diagnostic in result.diagnostics)
        assert any("profile-a.ProfileAPI" in diagnostic for diagnostic in result.diagnostics)
        assert any("profile-b.ProfileAPI" in diagnostic for diagnostic in result.diagnostics)


def test_semantic_analyzer_is_independent_of_source_file_order() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        service_root = root / "user-service"
        api_root = root / "profile-api"
        client_root = root / "android-client"
        for path in (service_root, api_root, client_root):
            (path / "src").mkdir(parents=True)

        (service_root / "src" / "user_service.py").write_text(
            "import requests\n\nclass UserService:\n    def fetch(self, user_id):\n        self._db.execute(\"SELECT phone_number FROM users WHERE id = ?\")\n        requests.post(\"http://profile-api/internal/profile/sync\", {\"id\": user_id})\n",
            encoding="utf-8",
        )
        (api_root / "src" / "profile_api.py").write_text(
            "class ProfileAPI:\n    @app.get(\"/profile/{id}\")\n    def get_profile(self, user_id):\n        return None\n",
            encoding="utf-8",
        )
        (client_root / "src" / "profile_client.kt").write_text(
            "package demo\n\ninterface ProfileApiService {\n    @GET(\"/profile/{userId}\")\n    fun getProfile(userId: Int): String\n}\n",
            encoding="utf-8",
        )

        files = sorted(root.rglob("*.py")) + sorted(root.rglob("*.kt"))
        result_a = SemanticAnalyzer().analyze(root, files=files)
        result_b = SemanticAnalyzer().analyze(root, files=reversed(files))
        result_c = SemanticAnalyzer().analyze(root, files=[files[1], files[0], *files[2:]])

        assert canonical_json(result_a.graph) == canonical_json(result_b.graph)
        assert canonical_json(result_a.graph) == canonical_json(result_c.graph)
        assert result_a.diagnostics == result_b.diagnostics == result_c.diagnostics


def test_service_descriptor_is_deterministic() -> None:
    desc = ServiceDescriptor(
        service_id="user-service",
        name="UserService",
        root_path="user-service",
        language="python",
    )

    assert desc.service_id == "user-service"
    assert desc.root_path == "user-service"


def test_semantic_analyzer_detects_demo_fixture_chain() -> None:
    analyzer = SemanticAnalyzer()
    result = analyzer.analyze(Path("fixtures/demo-commerce"))

    assert result.edges
    assert any(edge.kind == EdgeKind.HTTP_CALL for edge in result.edges)
    assert any(edge.kind == EdgeKind.DB_READ for edge in result.edges)
    assert any(edge.kind == EdgeKind.API_CONSUMES for edge in result.edges)

    evidence = [e for edge in result.edges for e in edge.evidence]
    assert evidence
    assert all(isinstance(e, EdgeEvidence) for e in evidence)


def test_comments_docstrings_and_dynamic_values_do_not_create_edges() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "service.py"
        source.write_text(
            """\n# requests.get(\"https://profile-api/profile/1\")\n\"\"\"SELECT phone_number FROM users\"\"\"\n\ndef run(url, db):\n    requests.get(url)\n    db.execute(sql)\n""",
            encoding="utf-8",
        )

        result = SemanticAnalyzer().analyze(root)

    assert not result.edges


def test_dynamic_references_are_explicit_and_secret_values_are_redacted() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "service.py").write_text(
            """
import os
import requests

def run(url, query, key):
    requests.get(url)
    requests.get('http://profile-api/users?token=super-secret-value')
    db.execute(query)
    os.getenv(key)
""",
            encoding="utf-8",
        )

        result = SemanticAnalyzer().analyze(root)
        serialized = str(result.model_dump() if hasattr(result, "model_dump") else result)

    assert any("DYNAMIC_HTTP_TARGET" in diagnostic for diagnostic in result.diagnostics)
    assert any("DYNAMIC_SQL" in diagnostic for diagnostic in result.diagnostics)
    assert any("DYNAMIC_CONFIG" in diagnostic for diagnostic in result.diagnostics)
    assert "super-secret-value" not in serialized
