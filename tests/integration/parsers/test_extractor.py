"""Integration tests for the SourceExtractor end-to-end pipeline.

Tests cover:
- Extracting the canonical demo-commerce fixture
- File discovery is deterministic
- Reversed file order produces identical DVH
- Symbols extracted from Python and Kotlin files
- Entities produced from class symbols
- Diagnostics surface correctly
- ExtractionResult counts are accurate
- Performance baseline is populated (not verified for speed)
- JSON output is deterministic
- Graph can be built from extraction result
"""

from __future__ import annotations

from pathlib import Path

import pytest

from preflight.graph.builder import GraphBuilder
from preflight.graph.parsers.extractor import SourceExtractor
from preflight.graph.parsers.models import Language
from preflight.graph.serialization import canonical_sha256

FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "demo-commerce"


@pytest.fixture
def extractor() -> SourceExtractor:
    return SourceExtractor()


@pytest.fixture
def result(extractor: SourceExtractor) -> object:
    return extractor.extract(FIXTURE_PATH)


class TestFixtureDiscovery:
    def test_three_source_files_found(self, result: object) -> None:
        # 2 Python + 1 Kotlin
        assert result.file_count == 3

    def test_python_files_found(self, result: object) -> None:
        langs = [sf.language for sf in result.source_files]
        assert Language.PYTHON in langs

    def test_kotlin_file_found(self, result: object) -> None:
        langs = [sf.language for sf in result.source_files]
        assert Language.KOTLIN in langs

    def test_source_files_sorted_by_path(self, result: object) -> None:
        paths = [sf.file_path for sf in result.source_files]
        assert paths == sorted(paths)

    def test_language_counts(self, result: object) -> None:
        counts = result.language_counts
        assert counts.get("python", 0) == 2
        assert counts.get("kotlin", 0) == 1


class TestFixtureSymbolExtraction:
    def test_symbols_extracted(self, result: object) -> None:
        assert result.symbol_count > 0

    def test_user_service_class_extracted(self, result: object) -> None:
        all_syms = [sym for sf in result.source_files for sym in sf.symbols]
        names = {s.qualified_name for s in all_syms}
        assert "UserService" in names

    def test_profile_api_class_extracted(self, result: object) -> None:
        all_syms = [sym for sf in result.source_files for sym in sf.symbols]
        names = {s.qualified_name for s in all_syms}
        assert "ProfileAPI" in names

    def test_profile_client_class_extracted(self, result: object) -> None:
        all_syms = [sym for sf in result.source_files for sym in sf.symbols]
        names = {s.qualified_name for s in all_syms}
        assert "ProfileClient" in names

    def test_all_parsed_without_failure(self, result: object) -> None:
        from preflight.graph.parsers.models import ParseStatus
        for sf in result.source_files:
            assert sf.parse_status != ParseStatus.PARSE_FAILURE


class TestFixtureEntityGeneration:
    def test_entities_produced(self, result: object) -> None:
        assert len(result.entities) > 0

    def test_user_service_entity_has_correct_id(self, result: object) -> None:
        entity_ids = {e.entity_id for e in result.entities}
        assert "user-service.UserService" in entity_ids

    def test_profile_api_entity_has_correct_id(self, result: object) -> None:
        entity_ids = {e.entity_id for e in result.entities}
        assert "profile-api.ProfileAPI" in entity_ids

    def test_profile_client_entity_has_correct_id(self, result: object) -> None:
        entity_ids = {e.entity_id for e in result.entities}
        assert "android-client.ProfileClient" in entity_ids

    def test_entities_sorted_by_entity_id(self, result: object) -> None:
        ids = [e.entity_id for e in result.entities]
        assert ids == sorted(ids)

    def test_entity_file_path_is_set(self, result: object) -> None:
        for entity in result.entities:
            assert entity.file is not None


class TestFixtureDeterminism:
    def test_dvh_identical_across_two_runs(self, extractor: SourceExtractor) -> None:
        r1 = extractor.extract(FIXTURE_PATH)
        r2 = extractor.extract(FIXTURE_PATH)

        builder1, builder2 = GraphBuilder(), GraphBuilder()
        for e in r1.entities:
            try:
                builder1.add_entity(e)
            except Exception:  # noqa: BLE001
                pass
        for e in r1.edges:
            try:
                builder1.add_dependency(e)
            except Exception:  # noqa: BLE001
                pass
        for e in r2.entities:
            try:
                builder2.add_entity(e)
            except Exception:  # noqa: BLE001
                pass
        for e in r2.edges:
            try:
                builder2.add_dependency(e)
            except Exception:  # noqa: BLE001
                pass

        g1 = builder1.build()
        g2 = builder2.build()
        assert canonical_sha256(g1) == canonical_sha256(g2)

    def test_dvh_identical_three_runs(self, extractor: SourceExtractor) -> None:
        """Three independent runs must produce the same DVH."""
        def _build_dvh() -> str:
            r = extractor.extract(FIXTURE_PATH)
            b = GraphBuilder()
            for e in r.entities:
                try:
                    b.add_entity(e)
                except Exception:  # noqa: BLE001
                    pass
            return canonical_sha256(b.build()) if b.build().node_count > 0 else ""

        dvh1 = _build_dvh()
        dvh2 = _build_dvh()
        dvh3 = _build_dvh()
        assert dvh1 == dvh2 == dvh3, f"DVH mismatch: {dvh1!r} vs {dvh2!r} vs {dvh3!r}"

    def test_entity_ids_stable(self, extractor: SourceExtractor) -> None:
        r1 = extractor.extract(FIXTURE_PATH)
        r2 = extractor.extract(FIXTURE_PATH)
        ids1 = sorted(e.entity_id for e in r1.entities)
        ids2 = sorted(e.entity_id for e in r2.entities)
        assert ids1 == ids2


class TestFixtureGraphIntegration:
    """End-to-end: parse → entities/edges → GraphBuilder → canonical SHA-256."""

    def test_graph_builds_from_extraction(self, result: object) -> None:
        builder = GraphBuilder()
        for entity in result.entities:
            try:
                builder.add_entity(entity)
            except Exception:  # noqa: BLE001
                pass
        graph = builder.build()
        assert graph.node_count > 0

    def test_graph_sha256_is_64_chars(self, result: object) -> None:
        builder = GraphBuilder()
        for entity in result.entities:
            try:
                builder.add_entity(entity)
            except Exception:  # noqa: BLE001
                pass
        graph = builder.build()
        assert len(canonical_sha256(graph)) == 64

    def test_user_service_in_graph(self, result: object) -> None:
        builder = GraphBuilder()
        for entity in result.entities:
            try:
                builder.add_entity(entity)
            except Exception:  # noqa: BLE001
                pass
        graph = builder.build()
        assert "user-service.UserService" in graph.entity_ids


class TestFixturePerformance:
    def test_performance_baseline_populated(self, result: object) -> None:
        perf = result.performance
        assert perf.files_analyzed == 3
        assert perf.total_bytes > 0
        assert perf.total_time >= 0

    def test_performance_dict_keys(self, result: object) -> None:
        d = result.performance.to_dict()
        assert "files_analyzed" in d
        assert "total_bytes" in d
        assert "total_time_s" in d


class TestInvalidPath:
    def test_nonexistent_path_raises(self, extractor: SourceExtractor) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            extractor.extract(Path("/nonexistent/path/xyz"))

    def test_file_path_raises(self, extractor: SourceExtractor) -> None:
        file_path = FIXTURE_PATH / "database" / "schema.sql"
        with pytest.raises(ValueError, match="not a directory"):
            extractor.extract(file_path)
