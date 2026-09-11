from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import SourceError

_GITHUB_SHORTHAND = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(slots=True)
class SourceIdentity:
    id: str
    original: str
    normalized: str
    source_type: str
    storage_key: str


@dataclass(slots=True)
class MaterializedSource:
    identity: SourceIdentity
    path: Path
    revision: str | None


class SourceManager:
    """Materialize Git and local sources without coupling them to a skill layout."""

    def __init__(self, home: Path):
        self.home = home
        self.sources_dir = home / "sources"
        self.staging_dir = home / "staging"

    def identify(self, source: str) -> SourceIdentity:
        source = source.strip()
        if _GITHUB_SHORTHAND.fullmatch(source):
            source = f"https://github.com/{source}"

        if _looks_like_git(source):
            normalized = _normalize_git_url(source)
            parsed = urlparse(normalized)
            if parsed.hostname and parsed.hostname.casefold() == "github.com":
                parts = parsed.path.strip("/").removesuffix(".git").split("/")
                if len(parts) >= 2:
                    source_id = f"github:{parts[0].casefold()}/{parts[1].casefold()}"
                else:
                    source_id = f"git:{_short_hash(normalized)}"
            else:
                source_id = f"git:{_short_hash(normalized)}"
            return SourceIdentity(
                id=source_id,
                original=source,
                normalized=normalized,
                source_type="git",
                storage_key=_short_hash(source_id, 20),
            )

        path = Path(source).expanduser()
        if not path.is_dir():
            raise SourceError(
                f'Local skill source does not exist or is not a directory: "{source}"'
            )
        normalized = str(path.resolve())
        basename = re.sub(r"[^a-z0-9-]+", "-", path.name.casefold()).strip("-") or "skills"
        source_id = f"local:{basename}-{_short_hash(normalized)}"
        return SourceIdentity(
            id=source_id,
            original=source,
            normalized=normalized,
            source_type="local",
            storage_key=_short_hash(source_id, 20),
        )

    def acquire(self, source: str, *, ref: str | None = None) -> MaterializedSource:
        identity = self.identify(source)
        target = self.sources_dir / identity.storage_key
        if target.exists():
            raise SourceError(f'Source "{identity.id}" is already materialized')
        staging = self.staging_dir / f"acquire-{uuid.uuid4().hex}"
        try:
            revision = self._populate(identity, staging, ref=ref)
            os.replace(staging, target)
            return MaterializedSource(identity=identity, path=target, revision=revision)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def refresh(self, identity: SourceIdentity, *, ref: str | None = None) -> MaterializedSource:
        target = self.sources_dir / identity.storage_key
        staging = self.staging_dir / f"refresh-{uuid.uuid4().hex}"
        backup = self.staging_dir / f"backup-{uuid.uuid4().hex}"
        try:
            revision = self._populate(identity, staging, ref=ref)
            if target.exists():
                os.replace(target, backup)
            os.replace(staging, target)
            shutil.rmtree(backup, ignore_errors=True)
            return MaterializedSource(identity=identity, path=target, revision=revision)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise

    def remove_materialized(self, path: Path) -> None:
        resolved = path.resolve()
        allowed = self.sources_dir.resolve()
        try:
            resolved.relative_to(allowed)
        except ValueError as exc:
            raise SourceError(
                f"Refusing to remove source outside managed storage: {resolved}"
            ) from exc
        if resolved == allowed:
            raise SourceError("Refusing to remove the managed sources root")
        if resolved.exists():
            shutil.rmtree(resolved, onerror=_remove_readonly)

    def _populate(
        self, identity: SourceIdentity, destination: Path, *, ref: str | None
    ) -> str | None:
        if identity.source_type == "git":
            command = ["git", "clone", "--depth", "1"]
            if ref:
                command.extend(["--branch", ref])
            command.extend([identity.normalized, str(destination)])
            _run_git(command)
            return _git_revision(destination)

        origin = Path(identity.normalized)
        revision = _git_revision(origin, required=False)
        shutil.copytree(origin, destination, ignore=_copy_ignore)
        return revision


def source_identity_from_record(
    source_id: str, source: str, normalized: str, source_type: str
) -> SourceIdentity:
    return SourceIdentity(
        id=source_id,
        original=source,
        normalized=normalized,
        source_type=source_type,
        storage_key=_short_hash(source_id, 20),
    )


def _looks_like_git(source: str) -> bool:
    return source.startswith(("https://", "http://", "ssh://", "git://", "git@"))


def _normalize_git_url(source: str) -> str:
    normalized = source.rstrip("/")
    if normalized.startswith("http://github.com/"):
        normalized = "https://github.com/" + normalized[len("http://github.com/") :]
    return normalized


def _short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _run_git(command: list[str]) -> None:
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"Git source acquisition failed: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git exited with an error"
        raise SourceError(f"Git source acquisition failed: {detail}")


def _git_revision(path: Path, *, required: bool = True) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        if required:
            raise SourceError(f"Could not read Git revision for {path}") from None
        return None
    if completed.returncode:
        if required:
            raise SourceError(completed.stderr.strip() or f"Could not read Git revision for {path}")
        return None
    return completed.stdout.strip()


def _copy_ignore(_directory: str, entries: list[str]) -> set[str]:
    ignored_names = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".tox"}
    return {entry for entry in entries if entry in ignored_names or entry.endswith(".pyc")}


def _remove_readonly(function: object, path: str, _error: object) -> None:
    """Clear Windows Git pack read-only bits, then retry the exact failed operation."""
    os.chmod(path, stat.S_IWRITE)
    if callable(function):
        function(path)
