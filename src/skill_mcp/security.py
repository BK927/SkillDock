from __future__ import annotations

import base64
import mimetypes
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import SecurityError
from .models import SkillRecord

_ALLOWED_ROOTS = {"references", "assets", "scripts"}
_TEXT_SCRIPT_SUFFIXES = {
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".sh",
    ".bash",
    ".ps1",
    ".rb",
    ".pl",
    ".php",
    ".lua",
    ".r",
    ".sql",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}
_TEXT_SUFFIXES = _TEXT_SCRIPT_SUFFIXES | {
    ".csv",
    ".tsv",
    ".xml",
    ".html",
    ".css",
    ".svg",
    ".ini",
    ".cfg",
    ".conf",
    ".rst",
}
_INTERPRETERS = {
    ".py": ["python"],
    ".js": ["node"],
    ".mjs": ["node"],
    ".cjs": ["node"],
    ".sh": ["bash"],
    ".bash": ["bash"],
    ".ps1": ["pwsh", "-NoProfile", "-File"],
}


def resolve_asset(skill: SkillRecord, requested_path: str, *, for_execution: bool = False) -> Path:
    normalized_text = requested_path.replace("\\", "/")
    pure = PurePosixPath(normalized_text)
    if (
        not normalized_text
        or pure.is_absolute()
        or ".." in pure.parts
        or "." in pure.parts
        or len(pure.parts) < 2
        or pure.parts[0] not in _ALLOWED_ROOTS
        or ":" in pure.parts[0]
    ):
        raise SecurityError(
            'Asset path must be a relative file below "references/", "assets/", or "scripts/"'
        )
    if pure.parts[0] == "scripts" and pure.suffix.casefold() not in _TEXT_SCRIPT_SUFFIXES:
        raise SecurityError("Only recognized text-based files are allowed below scripts/")
    if for_execution and pure.parts[0] != "scripts":
        raise SecurityError("Only files below scripts/ can be executed")

    root = Path(skill.install_path).resolve(strict=True)
    candidate = root.joinpath(*pure.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise SecurityError(
            f'Asset "{requested_path}" does not exist or escapes the skill root'
        ) from exc
    if not resolved.is_file():
        raise SecurityError(f'Asset "{requested_path}" is not a file')
    return resolved


def read_asset(
    skill: SkillRecord, requested_path: str, *, max_bytes: int = 5 * 1024 * 1024
) -> dict[str, Any]:
    path = resolve_asset(skill, requested_path)
    size = path.stat().st_size
    if size > max_bytes:
        raise SecurityError(f"Asset is {size} bytes; maximum readable size is {max_bytes} bytes")
    data = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.casefold() in _TEXT_SUFFIXES or mime_type.startswith("text/"):
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SecurityError("Text asset is not valid UTF-8") from exc
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        return {
            "skill": skill.id,
            "path": requested_path.replace("\\", "/"),
            "mimeType": mime_type,
            "encoding": "utf-8",
            "content": content,
        }
    return {
        "skill": skill.id,
        "path": requested_path.replace("\\", "/"),
        "mimeType": mime_type,
        "encoding": "base64",
        "content": base64.b64encode(data).decode("ascii"),
    }


def execute_script(
    skill: SkillRecord,
    script: str,
    args: list[str],
    *,
    timeout: float = 60,
) -> dict[str, Any]:
    if not skill.trusted:
        raise SecurityError(
            f'Skill "{skill.id}" is not trusted for scripts; reinstall with --allow-scripts'
        )
    path = resolve_asset(skill, script, for_execution=True)
    interpreter = _INTERPRETERS.get(path.suffix.casefold())
    if not interpreter:
        raise SecurityError(f'Script type "{path.suffix}" is not executable by this runtime')
    environment = os.environ.copy()
    environment["SKILL_DIR"] = skill.install_path
    try:
        completed = subprocess.run(
            [*interpreter, str(path), *args],
            cwd=skill.install_path,
            env=environment,
            capture_output=True,
            text=True,
            shell=False,
            timeout=max(1, min(timeout, 600)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SecurityError(f"Script execution failed: {exc}") from exc
    return {
        "skill": skill.id,
        "script": script,
        "exitCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
