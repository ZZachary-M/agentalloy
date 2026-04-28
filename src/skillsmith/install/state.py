"""Install state file management.

Owns read/write of the user-scoped install state. As of schema v2, state
lives at ``${XDG_CONFIG_HOME:-~/.config}/skillsmith/install-state.json``
rather than per-repo so a single Skillsmith install can serve multiple
repos. The corpus and any output artifacts live under
``${XDG_DATA_HOME:-~/.local/share}/skillsmith/``.

The legacy per-repo path (``<repo>/.skillsmith/install-state.json``)
is detected on load and surfaces a warning telling the user to move it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CURRENT_SCHEMA_VERSION = 2

STATE_DIR_NAME = "skillsmith"  # under XDG_CONFIG_HOME
STATE_FILE_NAME = "install-state.json"
OUTPUTS_DIR_NAME = "outputs"
CORPUS_DIR_NAME = "corpus"
LEGACY_STATE_DIR_NAME = ".skillsmith"  # used pre-v2; per-repo


def user_config_dir() -> Path:
    """Return ``${XDG_CONFIG_HOME:-~/.config}/skillsmith``."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / STATE_DIR_NAME


def user_data_dir() -> Path:
    """Return ``${XDG_DATA_HOME:-~/.local/share}/skillsmith``."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / STATE_DIR_NAME


def corpus_dir() -> Path:
    """User-writable corpus location. Populated on first run from the wheel."""
    return user_data_dir() / CORPUS_DIR_NAME


def env_path() -> Path:
    """User-scoped ``.env`` location. Holds runtime config for the service."""
    return user_config_dir() / ".env"


def _is_real_corpus(p: Path) -> bool:
    """Sentinel check — returns True only if ``p`` looks like a complete corpus.

    A directory that exists but lacks ``skills.duck`` is either a partial
    install (interrupted copy) or a same-named dir from a different
    package. Either way we should refuse to use it.
    """
    return p.exists() and (p / "skills.duck").exists()


def bundled_corpus_dir() -> Path | None:
    """Return the read-only corpus shipped inside the wheel, if locatable.

    Uses ``importlib.resources`` to find ``skillsmith/_corpus/``. Falls
    back to the repo's source tree for development checkouts. Returns
    ``None`` if no usable corpus is bundled (operator must seed manually).

    The sentinel check (``skills.duck`` must exist inside the dir) blocks
    silently returning a same-named-but-empty directory from a different
    package on the Python path.
    """
    try:
        from importlib import resources

        # The corpus is package data under skillsmith/_corpus/. resources.files
        # returns a Traversable; for filesystem-backed package layouts (the
        # only kind we ship) this exposes __fspath__ and we can convert to
        # a Path for shutil. Zipped wheels don't currently apply (the
        # corpus is binary data not safe to read from a zip).
        corpus = resources.files("skillsmith") / "_corpus"
        fspath = getattr(corpus, "__fspath__", None)
        if fspath is not None:
            p = Path(fspath())
            if _is_real_corpus(p):
                return p
    except (ModuleNotFoundError, FileNotFoundError, AttributeError, OSError):
        pass
    # Dev fallback: walk up from this file looking for src/skillsmith/_corpus.
    # Apply the same sentinel check so a stub _corpus dir on PYTHONPATH
    # can't shadow the real one.
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "src" / "skillsmith" / "_corpus"
        if _is_real_corpus(candidate):
            return candidate
    return None


def ensure_corpus_seeded() -> tuple[Path, bool]:
    """Copy the bundled corpus into the user data dir if not already present.

    Returns ``(corpus_path, was_seeded)`` — ``was_seeded`` is True if this
    call created the user copy, False if it was already there. Idempotent.
    """
    user_corpus = corpus_dir()
    if (user_corpus / "skills.duck").exists() and (user_corpus / "ladybug").exists():
        return user_corpus, False
    bundled = bundled_corpus_dir()
    if bundled is None:
        # No bundled corpus — caller must surface a clear error.
        return user_corpus, False
    user_corpus.mkdir(parents=True, exist_ok=True)
    src_duck = bundled / "skills.duck"
    src_ladybug = bundled / "ladybug"

    def _atomic_copy(src: Path, dst: Path) -> None:
        """Copy src → dst via a temp sibling so a partial / interrupted
        copy never leaves a half-written file at the final path. Without
        this, an aborted copytree leaves a directory at `ladybug/` whose
        `.exists()` is True forever, and the next run skips it.
        """
        if dst.exists():
            return
        tmp = dst.with_name(dst.name + ".part")
        # Wipe any leftover from a previous failed attempt.
        if tmp.exists():
            if tmp.is_dir():
                shutil.rmtree(tmp)
            else:
                tmp.unlink()
        try:
            if src.is_dir():
                shutil.copytree(src, tmp)
            else:
                shutil.copyfile(src, tmp)
            os.replace(tmp, dst)  # atomic on the same filesystem
        except BaseException:
            with contextlib.suppress(FileNotFoundError, OSError):
                if tmp.is_dir():
                    shutil.rmtree(tmp)
                else:
                    tmp.unlink()
            raise

    if src_duck.exists():
        _atomic_copy(src_duck, user_corpus / "skills.duck")
    if src_ladybug.exists():
        _atomic_copy(src_ladybug, user_corpus / "ladybug")
    return user_corpus, True


def is_inside_root(path: Path, root: Path) -> bool:
    """Return True if ``path`` resolves to a location inside ``root``.

    Used as a containment guard around any code path that takes a
    filesystem path from install-state.json (which lives inside the
    user's repo and could be tampered with by a hostile dependency or
    attacker) before writing or unlinking. Resolution failures count as
    "not inside" so callers fall through their skip / warn branch.
    """
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return False
    return True


def validate_port(value: Any) -> int:
    """Coerce a state-file `port` value to a sane integer.

    Hostile state may set port to a string (`"1@evil.com:80"` for URL
    confusion), a float, a negative int, or > 65535. Reject all of those
    rather than letting them flow into URL construction or socket calls.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        print(
            f"ERROR: install-state.json `port` must be an integer; got {type(value).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if value < 1 or value > 65535:
        print(
            f"ERROR: install-state.json `port` {value} is out of range (1–65535).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return value


def _repo_root() -> Path:
    """Locate the current repo root.

    Used by ``wire-harness`` to find the user's repo (the only subcommand
    that still operates on cwd). Walks up from cwd looking for a marker
    that indicates the user is inside a project (pyproject.toml,
    package.json, .git, etc.). Falls back to cwd.

    Note: this is *not* used to locate skillsmith state — state is
    user-scoped. It's only for wire-harness's "where to inject sentinels".
    """
    cwd = Path.cwd().resolve()
    markers = ("pyproject.toml", "package.json", ".git", "Cargo.toml", "go.mod")
    for ancestor in (cwd, *cwd.parents):
        if any((ancestor / m).exists() for m in markers):
            return ancestor
    return cwd


# `root` parameters are accepted on the public state functions for
# backwards-compatibility with subcommand call sites. They are ignored
# for state/outputs paths (those are user-scoped now); they still apply
# to wire-harness's per-repo file targets.


def state_dir(root: Path | None = None) -> Path:  # noqa: ARG001 — kept for back-compat
    """Return the user-scoped state directory."""
    return user_config_dir()


def state_path(root: Path | None = None) -> Path:  # noqa: ARG001
    """Return the user-scoped install-state.json path."""
    return user_config_dir() / STATE_FILE_NAME


def outputs_dir(root: Path | None = None) -> Path:  # noqa: ARG001
    """Return the user-scoped outputs directory."""
    return user_data_dir() / OUTPUTS_DIR_NAME


def _legacy_state_path_from_repo(repo_root: Path) -> Path:
    """Pre-v2 (per-repo) install-state.json path. For migration detection."""
    return repo_root / LEGACY_STATE_DIR_NAME / STATE_FILE_NAME


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "install_started_at": datetime.now(UTC).isoformat(),
        "completed_steps": [],
        "harness_files_written": [],
        "models_pulled": [],
        "env_path": None,
        "port": 47950,
        "last_verify_passed_at": None,
    }


def load_state(root: Path | None = None) -> dict[str, Any]:
    """Load install state, or return a fresh empty state if no file exists.

    Exits with code 3 if the file's schema_version is newer than the code supports.
    """
    fp = state_path()
    if not fp.exists():
        # Detect legacy per-repo state and warn (not an error — first run is
        # the common case). Migration is a manual one-liner.
        legacy = _legacy_state_path_from_repo(root or _repo_root())
        if legacy.exists():
            print(
                f"WARNING: Found legacy per-repo state at {legacy}.\n"
                f"         Skillsmith now uses user-scoped state at {fp}.\n"
                f"         To migrate: mv {legacy} {fp}\n"
                f"         (Or delete the legacy file and re-run setup.)",
                file=sys.stderr,
            )
        return _empty_state()
    data = json.loads(fp.read_text())
    raw_version = data.get("schema_version", 0)
    # A hostile state file can set schema_version to a string or other
    # type; coercing through int() with a fallback gives a clean exit
    # instead of an unhandled TypeError downstream.
    try:
        file_version = int(raw_version)
    except (TypeError, ValueError):
        print(
            f"ERROR: install-state.json schema_version {raw_version!r} is not an integer.",
            file=sys.stderr,
        )
        raise SystemExit(3) from None
    if file_version > CURRENT_SCHEMA_VERSION:
        print(
            f"ERROR: install-state.json schema_version {file_version} "
            f"is newer than this code supports ({CURRENT_SCHEMA_VERSION}). "
            f"Update skillsmith before re-running install.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    if file_version < CURRENT_SCHEMA_VERSION:
        data = _migrate(data, file_version)
    return data


def _atomic_write(target: Path, content: str, *, mode: int = 0o644) -> None:
    """Write to a sibling tempfile then os.replace into target.

    Atomic on POSIX and Windows (when on the same filesystem). Survives
    crashes and concurrent writers — readers see either the old file or
    the new one, never a torn write.

    Symlink-safe: opens the temp file with O_NOFOLLOW so a symlink
    pre-planted at the .tmp path can't redirect the write. Stale .tmp
    files (e.g. from a previous crashed run) are removed first; if the
    .tmp path is a symlink, removing it deletes only the link, never the
    target.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    # Remove a stale tempfile (or hostile symlink) before opening exclusively.
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    # O_NOFOLLOW only exists on POSIX; on Windows the O_EXCL above is
    # sufficient because Windows does not follow reparse points the same way.
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(tmp, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except BaseException:
        # If writing fails, remove the half-written tempfile so the next
        # invocation's O_EXCL doesn't trip on it.
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    os.replace(tmp, target)


def save_state(data: dict[str, Any], root: Path | None = None) -> Path:  # noqa: ARG001
    """Write install state to disk atomically. Creates the directory if needed."""
    fp = state_path()
    _atomic_write(fp, json.dumps(data, indent=2) + "\n")
    return fp


def record_step(
    data: dict[str, Any],
    step: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a completed-step entry. Returns the mutated state dict."""
    entry: dict[str, Any] = {
        "step": step,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    if extra:
        entry.update(extra)
    data["completed_steps"].append(entry)
    return data


def is_step_completed(data: dict[str, Any], step: str) -> bool:
    return any(s["step"] == step for s in data.get("completed_steps", []))


def get_step_output(data: dict[str, Any], step: str) -> dict[str, Any] | None:
    for s in data.get("completed_steps", []):
        if s["step"] == step:
            return s
    return None


def save_output_file(
    content: dict[str, Any],
    filename: str,
    root: Path | None = None,  # noqa: ARG001 — kept for back-compat
) -> tuple[Path, str]:
    """Write a JSON output file to the user outputs dir. Returns (path, sha256)."""
    fp = outputs_dir() / filename
    raw = json.dumps(content, indent=2) + "\n"
    _atomic_write(fp, raw)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return fp, f"sha256:{digest}"


def _migrate(data: dict[str, Any], from_version: int) -> dict[str, Any]:
    """Migrate state file forward to CURRENT_SCHEMA_VERSION."""
    if from_version < 1:
        data.setdefault("harness_files_written", [])
        data.setdefault("models_pulled", [])
        data.setdefault("env_path", None)
        data.setdefault("port", 47950)
        data.setdefault("last_verify_passed_at", None)
    if from_version < 2:
        # v1 → v2: state moved from per-repo to user-scope. v1 had a
        # single top-level `harness` field; in v2 each harness_files_written
        # entry carries its own `harness` so multi-repo wiring is first
        # class. Read the old top-level value BEFORE popping so existing
        # entries inherit the correct harness rather than a fixed guess.
        legacy_harness = data.get("harness") or "claude-code"
        legacy_repo_root = data.get("repo_root")
        data.pop("harness", None)
        data.pop("repo_root", None)
        for entry in data.get("harness_files_written", []):
            entry.setdefault("harness", legacy_harness)
            if legacy_repo_root:
                entry.setdefault("repo_root", legacy_repo_root)
    data["schema_version"] = CURRENT_SCHEMA_VERSION
    return data
