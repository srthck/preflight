"""Thin HTTP adapter over the real PreFlight orchestration pipeline.

This module owns no analysis logic. Every request is turned into either an
``AnalysisInput`` (built-in fixture scenario) or a securely-extracted
project directory (uploaded archive), and handed to
``preflight.orchestration.run_analysis`` / ``run_project_analysis`` —
the same real analyzers either way (semantic parsing, blast radius,
deployment rehearsal, API contract diffing, rollback truth, decision,
explanation). This file's only job is: parse the HTTP request, call the
orchestrator, and serialize whatever it returns.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from preflight.ingestion import (  # noqa: E402
    ArchiveTooLargeError,
    MalformedArchiveError,
    TooManyFilesError,
    UnsafeArchiveError,
    extracted_project,
    parse_multipart_form,
)
from preflight.ingestion.limits import MAX_ARCHIVE_BYTES  # noqa: E402
from preflight.orchestration import (  # noqa: E402
    SCENARIOS,
    AnalysisInput,
    FixtureUnavailableError,
    UnknownScenarioError,
    run_analysis,
    run_project_analysis,
    run_snapshot_comparison,
)

ALLOWED_ORIGINS = frozenset(
    origin.strip()
    for origin in os.environ.get(
        "PREFLIGHT_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
)

# Multipart framing (boundaries, headers) adds overhead beyond the raw
# archive bytes; allow a fixed margin above the archive-content limit so a
# legitimate upload at the limit isn't rejected by the outer HTTP guard
# before `extracted_project` gets a chance to give a precise error.
_MULTIPART_OVERHEAD_MARGIN = 8192


def analyze(scenario: str, *, case_id: str | None = None) -> tuple[int, dict[str, Any]]:
    """Run the real pipeline for a built-in fixture ``scenario``."""

    request = AnalysisInput(case_id=case_id or f"PF-{scenario}", scenario=scenario)
    try:
        result = run_analysis(request, repo_root=_ROOT)
    except UnknownScenarioError:
        return 400, {
            "error": "UNSUPPORTED_SCENARIO",
            "detail": f"Unknown scenario: {scenario!r}",
            "supported_scenarios": sorted(SCENARIOS),
        }
    except FixtureUnavailableError as exc:
        return 404, {"error": "FIXTURE_UNAVAILABLE", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never leak a raw traceback to clients
        return 500, {"error": "ANALYSIS_UNAVAILABLE", "detail": f"{type(exc).__name__}: {exc}"}
    return 200, result.to_response_payload()


def analyze_project(archive_bytes: bytes, *, case_id: str) -> tuple[int, dict[str, Any]]:
    """Securely extract an uploaded archive and run the real pipeline on it.

    Maps each ingestion failure mode to a distinct, honest status — never a
    blanket 500, and never a silently-downgraded success.
    """

    try:
        with extracted_project(archive_bytes) as root:
            result = run_project_analysis(root, case_id=case_id)
            return 200, result.to_response_payload()
    except MalformedArchiveError as exc:
        return 400, {"error": "INVALID_ARCHIVE", "detail": str(exc)}
    except UnsafeArchiveError as exc:
        return 400, {"error": "UNSAFE_ARCHIVE", "detail": str(exc)}
    except TooManyFilesError as exc:
        return 400, {"error": "ARCHIVE_TOO_MANY_FILES", "detail": str(exc)}
    except ArchiveTooLargeError as exc:
        return 413, {"error": "ARCHIVE_TOO_LARGE", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never leak a raw traceback to clients
        return 500, {"error": "ANALYSIS_UNAVAILABLE", "detail": f"{type(exc).__name__}: {exc}"}


def analyze_change(
    old_archive_bytes: bytes, new_archive_bytes: bytes, *, case_id: str
) -> tuple[int, dict[str, Any]]:
    """Securely extract two uploaded archives (OLD, NEW) and run the real
    snapshot-comparison pipeline on them.

    Each archive is validated and extracted independently by the same
    ``extracted_project`` boundary a single-archive upload uses — nothing
    about the security posture is relaxed because there are two files.
    """

    try:
        with extracted_project(old_archive_bytes) as old_root, extracted_project(
            new_archive_bytes
        ) as new_root:
            result = run_snapshot_comparison(old_root, new_root, case_id=case_id)
            return 200, result.to_response_payload()
    except MalformedArchiveError as exc:
        return 400, {"error": "INVALID_ARCHIVE", "detail": str(exc)}
    except UnsafeArchiveError as exc:
        return 400, {"error": "UNSAFE_ARCHIVE", "detail": str(exc)}
    except TooManyFilesError as exc:
        return 400, {"error": "ARCHIVE_TOO_MANY_FILES", "detail": str(exc)}
    except ArchiveTooLargeError as exc:
        return 413, {"error": "ARCHIVE_TOO_LARGE", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - never leak a raw traceback to clients
        return 500, {"error": "ANALYSIS_UNAVAILABLE", "detail": f"{type(exc).__name__}: {exc}"}


class Handler(BaseHTTPRequestHandler):
    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        return origin if origin in ALLOWED_ORIGINS else None

    def _send_cors(self) -> None:
        if origin := self._cors_origin():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "online", "engine": "deterministic"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/api/analyze":
            self._handle_analyze()
        elif self.path == "/api/analyze-project":
            self._handle_analyze_project()
        elif self.path == "/api/analyze-change":
            self._handle_analyze_change()
        else:
            self._send(404, {"error": "not found"})

    def _handle_analyze(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "INVALID_JSON", "detail": "Request body must be JSON."})
            return
        scenario = payload.get("scenario")
        if not isinstance(scenario, str) or not scenario:
            self._send(400, {"error": "MISSING_SCENARIO", "detail": "'scenario' is required."})
            return
        status, body = self._safe_call(lambda: analyze(scenario))
        self._send(status, body)

    def _handle_analyze_project(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send(
                400,
                {
                    "error": "INVALID_ARCHIVE",
                    "detail": "Expected multipart/form-data with an 'archive' file field.",
                },
            )
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_ARCHIVE_BYTES + _MULTIPART_OVERHEAD_MARGIN:
            self._send(
                413,
                {
                    "error": "ARCHIVE_TOO_LARGE",
                    "detail": f"upload is {length} bytes; the limit is {MAX_ARCHIVE_BYTES} bytes",
                },
            )
            return

        body = self.rfile.read(length)
        try:
            fields = parse_multipart_form(content_type, body)
        except MalformedArchiveError as exc:
            self._send(400, {"error": "INVALID_ARCHIVE", "detail": str(exc)})
            return

        archive_field = fields.get("archive")
        if archive_field is None or not archive_field.content:
            self._send(
                400,
                {"error": "INVALID_ARCHIVE", "detail": "No 'archive' file field was provided."},
            )
            return

        case_id = f"PF-upload-{archive_field.filename or 'project'}"
        status, response_body = self._safe_call(
            lambda: analyze_project(archive_field.content, case_id=case_id)
        )
        self._send(status, response_body)

    def _handle_analyze_change(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send(
                400,
                {
                    "error": "INVALID_ARCHIVE",
                    "detail": (
                        "Expected multipart/form-data with 'old' and 'new' archive fields."
                    ),
                },
            )
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > 2 * MAX_ARCHIVE_BYTES + _MULTIPART_OVERHEAD_MARGIN:
            self._send(
                413,
                {
                    "error": "ARCHIVE_TOO_LARGE",
                    "detail": (
                        f"upload is {length} bytes; the combined limit is "
                        f"{2 * MAX_ARCHIVE_BYTES} bytes"
                    ),
                },
            )
            return

        body = self.rfile.read(length)
        try:
            fields = parse_multipart_form(content_type, body)
        except MalformedArchiveError as exc:
            self._send(400, {"error": "INVALID_ARCHIVE", "detail": str(exc)})
            return

        old_field = fields.get("old")
        new_field = fields.get("new")
        if old_field is None or not old_field.content or new_field is None or not new_field.content:
            self._send(
                400,
                {
                    "error": "INVALID_ARCHIVE",
                    "detail": "Both an 'old' and a 'new' archive file field are required.",
                },
            )
            return

        case_id = f"PF-change-{old_field.filename or 'old'}-vs-{new_field.filename or 'new'}"
        status, response_body = self._safe_call(
            lambda: analyze_change(old_field.content, new_field.content, case_id=case_id)
        )
        self._send(status, response_body)

    @staticmethod
    def _safe_call(fn: Any) -> tuple[int, dict[str, Any]]:
        try:
            return fn()  # type: ignore[no-any-return]
        except Exception as exc:  # noqa: BLE001 - final safety net, never a raw traceback
            return 500, {"error": "ANALYSIS_UNAVAILABLE", "detail": f"{type(exc).__name__}: {exc}"}

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", sys.argv[1] if len(sys.argv) > 1 else "8000"))
    print(f"PreFlight API listening on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
