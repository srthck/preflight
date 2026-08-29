"""Build the three judge-facing demo ZIPs from real fixture sources.

Each ZIP is a genuine, self-contained project snapshot — not a scenario
name. The three represent one real causal story:

    destructive-release.zip   DROP COLUMN, consumers still depend on it
                               -> DO_NOT_DEPLOY
    safe-release.zip          ADD COLUMN, purely additive
                               -> SAFE
    remediated-release.zip    same DROP COLUMN, but consumers no longer
                               reference the column -> SAFE (different
                               reason: the dependency itself is gone)

Run: python scripts/build_upload_demos.py
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO_ROOT / "fixtures" / "uploads"

# Files that exist in fixtures/demo-commerce purely to support the *fixture
# scenario registry* (multiple migration variants side by side) rather than
# representing one real project snapshot. A real uploaded project has one
# migration file, not two — so these are excluded when assembling ZIPs.
_EXCLUDE_RELATIVE = {"database/migration_safe.sql"}


def _iter_source_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).as_posix() not in _EXCLUDE_RELATIVE
    )


def _write_zip(out_path: Path, entries: list[tuple[str, bytes]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in sorted(entries):
            info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
            zf.writestr(info, data)
    print(f"wrote {out_path.relative_to(_REPO_ROOT)} ({len(entries)} files)")


def build_destructive_release() -> None:
    root = _REPO_ROOT / "fixtures" / "demo-commerce"
    entries = [
        (p.relative_to(root).as_posix(), p.read_bytes()) for p in _iter_source_files(root)
    ]
    _write_zip(_OUT_DIR / "destructive-release.zip", entries)


def build_safe_release() -> None:
    root = _REPO_ROOT / "fixtures" / "demo-commerce"
    safe_migration = (root / "database" / "migration_safe.sql").read_bytes()
    entries = []
    for path in _iter_source_files(root):
        arcname = path.relative_to(root).as_posix()
        if arcname == "database/migration.sql":
            entries.append((arcname, safe_migration))
        else:
            entries.append((arcname, path.read_bytes()))
    _write_zip(_OUT_DIR / "safe-release.zip", entries)


def build_remediated_release() -> None:
    root = _REPO_ROOT / "fixtures" / "demo-commerce-remediated"
    entries = [
        (p.relative_to(root).as_posix(), p.read_bytes()) for p in _iter_source_files(root)
    ]
    _write_zip(_OUT_DIR / "remediated-release.zip", entries)


def main() -> int:
    build_destructive_release()
    build_safe_release()
    build_remediated_release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
