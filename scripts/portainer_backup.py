#!/usr/bin/env python3
"""
VexterSoft VPS Platform — Safe Portainer Volume Backup & Sandbox Restore Helper

Provides a single, auditable implementation for:
  1. Quiesced or live read-only Portainer Docker volume backups (`backup`)
     with a `try...finally` container-restart guarantee on failure.
  2. Multi-stage archive integrity & member verification (`verify-archive`).
  3. Isolated sandbox volume restoration (`restore-sandbox`) that refuses
     production volume targets, refuses `source == target`, and refuses
     non-empty existing volumes (never executing `rm -rf /target/*`).

This helper is used both by automated CI tests (with disposable Docker volumes
and real Portainer CE containers) and by the operator handover runbook.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Callable, Sequence

DEFAULT_HELPER_IMAGE = "alpine:3.21"
DEFAULT_EXPECTED_FILES = ("portainer.db",)

# Production volume identifiers that must NEVER be used as an implicit default
# or as a target for `restore-sandbox`.
PROTECTED_PRODUCTION_VOLUMES = frozenset({
    "vextersoft_portainer_data",
    "portainer_data",
})

DOCKER_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PLACEHOLDER_RE = re.compile(r"<[^>]+>")


class BackupError(RuntimeError):
    """Raised when a backup, verification, or sandbox restore safeguard fails."""


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Execute a subprocess command and return its CompletedProcess result."""
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def _docker_cmd(use_sudo: bool, *args: str) -> list[str]:
    prefix = ["sudo", "docker"] if use_sudo else ["docker"]
    return [*prefix, *args]


def validate_identifier(value: str, label: str) -> str:
    """Validate a Docker volume or container identifier, rejecting placeholders."""
    if not isinstance(value, str) or not value.strip():
        raise BackupError(f"{label} must not be empty.")
    cleaned = value.strip()
    if PLACEHOLDER_RE.search(cleaned) or "TODO" in cleaned.upper() or "CHANGEME" in cleaned.upper():
        raise BackupError(f"{label} contains an unresolved placeholder: {cleaned!r}")
    if not DOCKER_IDENTIFIER_RE.fullmatch(cleaned):
        raise BackupError(f"{label} contains invalid characters: {cleaned!r}")
    return cleaned


def validate_archive_path(archive_path: str | Path) -> Path:
    """Validate an archive path string/Path and reject placeholders or directories."""
    raw = str(archive_path).strip() if archive_path is not None else ""
    if not raw:
        raise BackupError("Archive path must not be empty.")
    if PLACEHOLDER_RE.search(raw) or "*" in raw or "?" in raw:
        raise BackupError(f"Archive path contains an unresolved placeholder or wildcard: {raw!r}")
    resolved = Path(raw).expanduser().resolve()
    if resolved.exists() and resolved.is_dir():
        raise BackupError(f"Archive path points to a directory, not a file: {resolved}")
    return resolved


def normalize_member_name(name: str) -> str:
    """Normalize a tar member path and reject path-traversal or absolute paths."""
    raw = name.replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    if raw in {"", "."}:
        return "."
    if raw.startswith("/"):
        raise BackupError(f"Archive contains an unsafe absolute member path: {name!r}")
    parts = [part for part in raw.split("/") if part]
    if ".." in parts:
        raise BackupError(f"Archive contains an unsafe path-traversal member: {name!r}")
    return "/".join(parts)


def verify_archive(
    archive_path: str | Path,
    expected_files: Sequence[str] = DEFAULT_EXPECTED_FILES,
) -> dict[str, Any]:
    """
    Verify that a Portainer backup `.tar.gz` archive:
      1. Exists as a regular file with size > 0 bytes.
      2. Has a valid, non-truncated gzip stream.
      3. Can be listed cleanly as a tar archive with no unsafe member paths.
      4. Contains all expected Portainer data markers (e.g. `portainer.db`) with non-zero size.
    """
    resolved = validate_archive_path(archive_path)
    if not resolved.is_file():
        raise BackupError(f"Backup archive does not exist: {resolved}")

    size_bytes = resolved.stat().st_size
    if size_bytes <= 0:
        raise BackupError(f"Backup archive is empty (0 bytes): {resolved}")

    # 1. Verify full gzip stream integrity and compute SHA-256 digest
    sha256 = hashlib.sha256()
    try:
        with resolved.open("rb") as raw_fh:
            while chunk := raw_fh.read(65536):
                sha256.update(chunk)
        with gzip.open(resolved, "rb") as gz_fh:
            while gz_fh.read(65536):
                pass
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise BackupError(f"Gzip integrity check failed for {resolved}: {exc}") from exc

    # 2. Verify tar structure, member safety, and expected files
    members_by_name: dict[str, tarfile.TarInfo] = {}
    try:
        with tarfile.open(resolved, mode="r:gz") as tar:
            members = tar.getmembers()
            if not members:
                raise BackupError(f"Tar archive contains no members: {resolved}")
            for member in members:
                if member.ischr() or member.isblk() or member.isfifo():
                    raise BackupError(f"Archive contains unsafe special device/FIFO member: {member.name!r}")
                norm = normalize_member_name(member.name)
                if norm != ".":
                    members_by_name[norm] = member
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise BackupError(f"Tar readability check failed for {resolved}: {exc}") from exc

    if not members_by_name:
        raise BackupError(f"Tar archive contains no files beyond root directory: {resolved}")

    matched_expected: list[str] = []
    for req in expected_files:
        req_norm = normalize_member_name(req)
        info = members_by_name.get(req_norm)
        if info is None:
            raise BackupError(
                f"Archive {resolved.name} is missing required Portainer file {req_norm!r}. "
                f"Found members: {sorted(members_by_name.keys())[:10]}"
            )
        if info.isfile() and info.size <= 0:
            raise BackupError(f"Required Portainer file {req_norm!r} in archive is 0 bytes.")
        matched_expected.append(req_norm)

    return {
        "archive_path": str(resolved),
        "size_bytes": size_bytes,
        "sha256": sha256.hexdigest(),
        "member_count": len(members_by_name),
        "verified_files": matched_expected,
    }


def backup_volume(
    source_volume: str,
    archive_path: str | Path,
    *,
    quiesce_container: str | None = None,
    helper_image: str = DEFAULT_HELPER_IMAGE,
    expected_files: Sequence[str] = DEFAULT_EXPECTED_FILES,
    use_sudo: bool = False,
    runner: CommandRunner = default_runner,
) -> dict[str, Any]:
    """
    Create a compressed tar archive of `source_volume` and verify its integrity.

    If `quiesce_container` is supplied, the container is stopped before archiving
    and is GUARANTEED to be started again in a `finally` block even when archive
    creation or archive verification fails.
    """
    src_vol = validate_identifier(source_volume, "Source volume")
    dest_path = validate_archive_path(archive_path)
    container_name = (
        validate_identifier(quiesce_container, "Quiesce container")
        if quiesce_container is not None
        else None
    )

    # Verify source volume exists before stopping anything
    vol_inspect = runner(_docker_cmd(use_sudo, "volume", "inspect", src_vol))
    if vol_inspect.returncode != 0:
        raise BackupError(
            f"Source volume {src_vol!r} does not exist or cannot be inspected: "
            f"{vol_inspect.stderr.strip() or vol_inspect.stdout.strip()}"
        )

    if container_name:
        ctr_inspect = runner(_docker_cmd(use_sudo, "inspect", container_name))
        if ctr_inspect.returncode != 0:
            raise BackupError(
                f"Quiesce container {container_name!r} does not exist or cannot be inspected: "
                f"{ctr_inspect.stderr.strip() or ctr_inspect.stdout.strip()}"
            )

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    container_stop_attempted = False
    primary_error: Exception | None = None
    verification_info: dict[str, Any] = {}

    try:
        if container_name:
            container_stop_attempted = True
            stop_res = runner(_docker_cmd(use_sudo, "stop", container_name))
            if stop_res.returncode != 0:
                raise BackupError(
                    f"Failed to stop Portainer container {container_name!r} before backup: "
                    f"{stop_res.stderr.strip() or stop_res.stdout.strip()}"
                )

        tar_cmd = _docker_cmd(
            use_sudo,
            "run",
            "--rm",
            "--mount",
            f"type=volume,source={src_vol},target=/source,readonly",
            "--mount",
            f"type=bind,source={dest_path.parent},target=/backup",
            helper_image,
            "tar",
            "-czf",
            f"/backup/{dest_path.name}",
            "-C",
            "/source",
            ".",
        )
        tar_res = runner(tar_cmd)
        if tar_res.returncode != 0:
            raise BackupError(
                f"Archive creation failed for volume {src_vol!r}: "
                f"{tar_res.stderr.strip() or tar_res.stdout.strip()}"
            )

        verification_info = verify_archive(dest_path, expected_files=expected_files)
    except Exception as exc:
        primary_error = exc
        # Remove partial or corrupt archive so it cannot be mistaken for a valid backup
        if dest_path.is_file():
            try:
                dest_path.unlink()
            except OSError:
                pass
        raise
    finally:
        if container_name and container_stop_attempted:
            start_res = runner(_docker_cmd(use_sudo, "start", container_name))
            if start_res.returncode != 0:
                restart_msg = (
                    f"CRITICAL: Failed to restart Portainer container {container_name!r} "
                    f"after backup: {start_res.stderr.strip() or start_res.stdout.strip()}"
                )
                if primary_error is not None:
                    raise BackupError(f"{primary_error} | {restart_msg}") from primary_error
                raise BackupError(restart_msg)

    return {
        "status": "ok",
        "source_volume": src_vol,
        "quiesced_container": container_name,
        "container_restarted": bool(container_name),
        **verification_info,
    }


def restore_sandbox_volume(
    archive_path: str | Path,
    target_volume: str,
    *,
    source_volume: str | None = None,
    create_volume: bool = True,
    helper_image: str = DEFAULT_HELPER_IMAGE,
    expected_files: Sequence[str] = DEFAULT_EXPECTED_FILES,
    use_sudo: bool = False,
    runner: CommandRunner = default_runner,
) -> dict[str, Any]:
    """
    Restore a verified Portainer backup archive into an isolated sandbox volume.

    Safety invariants:
      - Rejects protected production volume names (`vextersoft_portainer_data`, `portainer_data`).
      - Rejects `target_volume == source_volume`.
      - Verifies archive integrity before touching any Docker volume.
      - Refuses to restore into a non-empty existing volume (never runs `rm -rf /target/*`).
      - Cleans up newly created sandbox volume if extraction or post-restore verification fails.
    """
    tgt_vol = validate_identifier(target_volume, "Target sandbox volume")
    if tgt_vol in PROTECTED_PRODUCTION_VOLUMES:
        raise BackupError(
            f"Refusing to restore into protected production volume {tgt_vol!r}. "
            "restore-sandbox only permits isolated non-production volumes."
        )

    if source_volume is not None:
        src_vol = validate_identifier(source_volume, "Source volume")
        if src_vol == tgt_vol:
            raise BackupError(
                f"Target volume {tgt_vol!r} must be distinct from source volume {src_vol!r}."
            )

    # Verify archive before touching Docker volumes
    archive_info = verify_archive(archive_path, expected_files=expected_files)
    resolved_archive = Path(archive_info["archive_path"])

    inspect_res = runner(_docker_cmd(use_sudo, "volume", "inspect", tgt_vol))
    volume_existed = inspect_res.returncode == 0
    created_new_volume = False

    if not volume_existed:
        if not create_volume:
            raise BackupError(
                f"Target sandbox volume {tgt_vol!r} does not exist and --no-create-volume was specified."
            )
        create_res = runner(_docker_cmd(use_sudo, "volume", "create", tgt_vol))
        if create_res.returncode != 0:
            raise BackupError(
                f"Failed to create sandbox volume {tgt_vol!r}: "
                f"{create_res.stderr.strip() or create_res.stdout.strip()}"
            )
        created_new_volume = True
    else:
        # Check if existing volume is completely empty; refuse if non-empty
        empty_check_cmd = _docker_cmd(
            use_sudo,
            "run",
            "--rm",
            "--mount",
            f"type=volume,source={tgt_vol},target=/target,readonly",
            helper_image,
            "sh",
            "-c",
            "ls -A /target",
        )
        empty_res = runner(empty_check_cmd)
        if empty_res.returncode != 0:
            raise BackupError(
                f"Failed to inspect existing volume {tgt_vol!r}: "
                f"{empty_res.stderr.strip() or empty_res.stdout.strip()}"
            )
        if empty_res.stdout.strip():
            raise BackupError(
                f"Refusing to restore into non-empty volume {tgt_vol!r}. "
                "Use a fresh sandbox volume name instead of overwriting existing data."
            )

    try:
        extract_cmd = _docker_cmd(
            use_sudo,
            "run",
            "--rm",
            "--mount",
            f"type=volume,source={tgt_vol},target=/target",
            "--mount",
            f"type=bind,source={resolved_archive.parent},target=/backup,readonly",
            helper_image,
            "tar",
            "-xzf",
            f"/backup/{resolved_archive.name}",
            "-C",
            "/target",
        )
        extract_res = runner(extract_cmd)
        if extract_res.returncode != 0:
            raise BackupError(
                f"Failed to extract archive into sandbox volume {tgt_vol!r}: "
                f"{extract_res.stderr.strip() or extract_res.stdout.strip()}"
            )

        # Post-restore verification inside the target volume
        checks = " && ".join(
            f"test -s /target/{normalize_member_name(req)}" for req in expected_files
        )
        verify_cmd = _docker_cmd(
            use_sudo,
            "run",
            "--rm",
            "--mount",
            f"type=volume,source={tgt_vol},target=/target,readonly",
            helper_image,
            "sh",
            "-c",
            f"{checks} && ls -1A /target",
        )
        verify_res = runner(verify_cmd)
        if verify_res.returncode != 0:
            raise BackupError(
                f"Post-restore verification failed on sandbox volume {tgt_vol!r}: "
                f"{verify_res.stderr.strip() or verify_res.stdout.strip()}"
            )
        restored_entries = [
            line.strip() for line in verify_res.stdout.splitlines() if line.strip()
        ]
    except Exception:
        if created_new_volume:
            runner(_docker_cmd(use_sudo, "volume", "rm", tgt_vol))
        raise

    return {
        "status": "ok",
        "target_volume": tgt_vol,
        "created_volume": created_new_volume,
        "restored_entries": restored_entries,
        "archive": archive_info,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safe Portainer Docker volume backup, verification, and sandbox restore helper."
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_backup = sub.add_parser("backup", help="Back up a Portainer volume and verify the archive")
    p_backup.add_argument(
        "--source-volume",
        required=True,
        help="Docker volume name to back up (required; no implicit default)",
    )
    p_backup.add_argument(
        "--archive-path",
        required=True,
        help="Destination path for the .tar.gz backup archive",
    )
    p_backup.add_argument(
        "--quiesce-container",
        default=None,
        help="Optional Portainer container name to stop before backup and always restart in finally",
    )
    p_backup.add_argument(
        "--helper-image",
        default=DEFAULT_HELPER_IMAGE,
        help=f"Helper image for tar execution (default: {DEFAULT_HELPER_IMAGE})",
    )
    p_backup.add_argument(
        "--expected-files",
        default=",".join(DEFAULT_EXPECTED_FILES),
        help="Comma-separated list of required files inside the archive (default: portainer.db)",
    )
    p_backup.add_argument(
        "--sudo",
        action="store_true",
        help="Run docker commands via sudo",
    )

    p_verify = sub.add_parser("verify-archive", help="Verify a Portainer backup archive")
    p_verify.add_argument(
        "--archive-path",
        required=True,
        help="Path to the .tar.gz backup archive to verify",
    )
    p_verify.add_argument(
        "--expected-files",
        default=",".join(DEFAULT_EXPECTED_FILES),
        help="Comma-separated list of required files inside the archive (default: portainer.db)",
    )

    p_restore = sub.add_parser(
        "restore-sandbox",
        help="Restore a verified backup archive into an isolated, empty sandbox Docker volume",
    )
    p_restore.add_argument(
        "--archive-path",
        required=True,
        help="Path to the .tar.gz backup archive to restore",
    )
    p_restore.add_argument(
        "--target-volume",
        required=True,
        help="Name of the isolated sandbox volume (production volume names are rejected)",
    )
    p_restore.add_argument(
        "--source-volume",
        default=None,
        help="Optional source volume name to assert source != target",
    )
    p_restore.add_argument(
        "--no-create-volume",
        action="store_true",
        help="Require the empty sandbox volume to already exist instead of creating it",
    )
    p_restore.add_argument(
        "--helper-image",
        default=DEFAULT_HELPER_IMAGE,
        help=f"Helper image for tar extraction (default: {DEFAULT_HELPER_IMAGE})",
    )
    p_restore.add_argument(
        "--expected-files",
        default=",".join(DEFAULT_EXPECTED_FILES),
        help="Comma-separated list of required files to verify (default: portainer.db)",
    )
    p_restore.add_argument(
        "--sudo",
        action="store_true",
        help="Run docker commands via sudo",
    )

    return parser


def _parse_expected(raw: str) -> list[str]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items:
        raise BackupError("At least one expected file marker must be specified.")
    return items


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        expected = _parse_expected(args.expected_files)
        if args.subcommand == "backup":
            result = backup_volume(
                args.source_volume,
                args.archive_path,
                quiesce_container=args.quiesce_container,
                helper_image=args.helper_image,
                expected_files=expected,
                use_sudo=args.sudo,
            )
        elif args.subcommand == "verify-archive":
            result = verify_archive(args.archive_path, expected_files=expected)
        elif args.subcommand == "restore-sandbox":
            result = restore_sandbox_volume(
                args.archive_path,
                args.target_volume,
                source_volume=args.source_volume,
                create_volume=not args.no_create_volume,
                helper_image=args.helper_image,
                expected_files=expected,
                use_sudo=args.sudo,
            )
        else:
            raise BackupError(f"Unsupported subcommand: {args.subcommand}")
    except BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
