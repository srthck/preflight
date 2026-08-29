"""Locate real analysis inputs inside an arbitrary extracted project.

This module contains no analysis logic of its own — it only decides which
real files on disk should be handed to the existing analyzers
(``SemanticAnalyzer``, ``DeploymentAnalyzer``, ``analyze_api_contract``).
Every decision here is a deterministic, explainable file-selection rule,
never a scenario-name lookup.
"""

from __future__ import annotations

from pathlib import Path

IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "dist",
        "build",
        ".next",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "vendor",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        ".idea",
        ".vscode",
        ".gradle",
        ".tox",
        "egg-info",
    }
)

SEMANTIC_SUFFIXES = frozenset({".py", ".kt"})

# Recognized-but-unsupported source languages: these are reported as
# explicitly unsupported rather than silently omitted.
UNSUPPORTED_SOURCE_SUFFIXES = frozenset(
    {
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".java",
        ".rb",
        ".rs",
        ".c",
        ".cpp",
        ".cc",
        ".h",
        ".hpp",
        ".cs",
        ".php",
        ".swift",
        ".scala",
    }
)

BINARY_OR_MEDIA_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".svg",
        ".pdf",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".jar",
        ".class",
        ".so",
        ".dll",
        ".dylib",
        ".exe",
        ".pyc",
        ".mp3",
        ".mp4",
        ".mov",
        ".db",
        ".sqlite",
    }
)

API_CONTRACT_NAMES = frozenset(
    {"openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.yml"}
)

# Recognized project/build-manifest filenames. These are informational
# *signals* for reporting where project boundaries likely are — they are
# never required, never used to restrict discovery (which always walks the
# whole extracted tree), and never imply which technology is "the" root.
PROJECT_MARKER_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "requirements.txt",
        "package.json",
        "go.mod",
        "cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "composer.json",
        "gemfile",
    }
)
PROJECT_MARKER_SUFFIXES = frozenset({".csproj"})


def is_ignored(path: Path, root: Path) -> bool:
    """True if any path component (excluding the file itself) is a known ignore-directory."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return any(part in IGNORED_DIR_NAMES for part in relative.parts[:-1])


def classify(path: Path, root: Path) -> tuple[str, str | None]:
    """Return ``(classification, ignored_reason)`` for one file.

    Classification is one of: semantic, migration_candidate, api_contract,
    unsupported, ignored, other. ``migration_candidate`` covers any ``.sql``
    file; :func:`find_schema_and_migration` later narrows that set to the
    specific schema/migration roles.
    """
    if is_ignored(path, root):
        return "ignored", "matches an ignored directory (build output, dependency cache, or VCS)"
    suffix = path.suffix.lower()
    name = path.name.lower()
    if name in API_CONTRACT_NAMES:
        return "api_contract", None
    if suffix in SEMANTIC_SUFFIXES:
        return "semantic", None
    if suffix == ".sql":
        return "migration_candidate", None
    if suffix in UNSUPPORTED_SOURCE_SUFFIXES:
        return "unsupported", f"{suffix} is a recognized source language PreFlight does not parse"
    if suffix in BINARY_OR_MEDIA_SUFFIXES:
        return "ignored", "binary or media file — not a static-analysis input"
    return "other", None


def find_semantic_files(root: Path) -> list[Path | str]:
    """All Python/Kotlin files under ``root``, excluding ignored directories.

    Passed to ``SemanticAnalyzer.analyze(root, files=...)`` so an uploaded
    project's vendored/build directories never pollute the dependency graph
    — reuses the analyzer's existing explicit-file-list support rather than
    adding new filtering logic to the analyzer itself.
    """
    files: list[Path] = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SEMANTIC_SUFFIXES
            and not is_ignored(path, root)
        ),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    return list(files)


def find_api_contract(root: Path) -> Path | None:
    """The first OpenAPI/Swagger contract file, by sorted path, or ``None``."""
    candidates = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name.lower() in API_CONTRACT_NAMES
            and not is_ignored(path, root)
        ),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    return candidates[0] if candidates else None


def find_schema_and_migration(root: Path) -> tuple[Path | None, Path | None, tuple[str, ...]]:
    """Deterministically select the schema snapshot and the migration under review.

    Rules, in order:
    1. A file literally named ``schema.sql`` is the schema snapshot.
    2. Every other ``.sql`` file is a migration candidate.
    3. If any candidates live in a directory whose name contains
       "migration", the lexicographically last one of those (matching the
       common timestamp/sequence-prefixed naming convention) is the
       migration under review.
    4. Otherwise, the lexicographically last remaining ``.sql`` file is
       used, and an explanatory note is recorded if more than one existed
       (so the choice is visible, not silently guessed).
    """
    notes: list[str] = []
    sql_files = sorted(
        (
            path
            for path in root.rglob("*.sql")
            if path.is_file() and not is_ignored(path, root)
        ),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    schema_candidates = [p for p in sql_files if p.name.lower() == "schema.sql"]
    schema_path = schema_candidates[0] if schema_candidates else None
    if len(schema_candidates) > 1 and schema_path is not None:
        notes.append(
            f"Multiple schema.sql files found; using "
            f"{schema_path.relative_to(root).as_posix()} deterministically."
        )

    remaining = [p for p in sql_files if p != schema_path]
    migrations_dir_files = sorted(p for p in remaining if "migration" in p.parent.name.lower())

    if migrations_dir_files:
        migration_path = migrations_dir_files[-1]
    elif remaining:
        migration_path = remaining[-1]
        if len(remaining) > 1:
            notes.append(
                f"Multiple candidate migration files found with no dedicated migrations "
                f"directory; selected {migration_path.relative_to(root).as_posix()} "
                "deterministically (lexicographically last)."
            )
    else:
        migration_path = None

    if schema_path is None:
        notes.append("No schema.sql was found; schema-snapshot evidence is unavailable.")
    if migration_path is None:
        notes.append(
            "No migration SQL file was found; deployment-rehearsal evidence is unavailable."
        )

    return schema_path, migration_path, tuple(notes)


def find_framework_signals(root: Path) -> tuple[str, ...]:
    """Repository-relative paths of recognized project/build-manifest files.

    Purely informational: reports where project boundaries likely are (a
    monorepo typically has several) without restricting or directing
    discovery in any way — semantic/SQL/API discovery already walk the
    whole tree regardless of what this finds.
    """
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or is_ignored(path, root):
            continue
        is_marker = (
            path.name.lower() in PROJECT_MARKER_NAMES
            or path.suffix.lower() in PROJECT_MARKER_SUFFIXES
        )
        if is_marker:
            found.append(path.relative_to(root).as_posix())
    return tuple(sorted(found))


__all__ = [
    "API_CONTRACT_NAMES",
    "IGNORED_DIR_NAMES",
    "PROJECT_MARKER_NAMES",
    "SEMANTIC_SUFFIXES",
    "UNSUPPORTED_SOURCE_SUFFIXES",
    "classify",
    "find_api_contract",
    "find_framework_signals",
    "find_schema_and_migration",
    "find_semantic_files",
    "is_ignored",
]
