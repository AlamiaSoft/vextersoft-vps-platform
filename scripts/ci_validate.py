#!/usr/bin/env python3
"""Validate changed repository files for basic syntax and accidental host/secret exposure."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML is required: python -m pip install PyYAML", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parents[1]
IP_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
LOCAL_FILE_URL_RE = re.compile(r"file:///(?:[A-Za-z]:/|Users/|home/|mnt/)", re.IGNORECASE)
PRIVATE_FILE_NAMES = {
    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
}
PRIVATE_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}


def changed_paths() -> list[Path]:
    base = os.environ.get("BASE_SHA", "").strip()
    if base:
        command = ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD"]
    else:
        command = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    paths = []
    for item in result.stdout.splitlines():
        path = (ROOT / item).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError:
            continue
        if path.is_file():
            paths.append(path)
    return paths


def is_sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in PRIVATE_FILE_NAMES
        or name.startswith("id_rsa")
        or name.startswith("id_ed25519")
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or (name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"})
    )


def validate_yaml(path: Path, content: str, errors: list[str]) -> None:
    try:
        if path.name.endswith(".md") and path.parent.name == "ISSUE_TEMPLATE":
            if not content.startswith("---\n"):
                errors.append(f"{path.relative_to(ROOT)}: issue template is missing YAML front matter")
                return
            parts = content.split("---", 2)
            if len(parts) < 3:
                errors.append(f"{path.relative_to(ROOT)}: malformed YAML front matter")
                return
            yaml.safe_load(parts[1])
        else:
            yaml.safe_load(content)
    except yaml.YAMLError as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")


def main() -> int:
    paths = changed_paths()
    errors: list[str] = []
    if not paths:
        print("No changed files found for syntax/safety checks.")
        return 0

    for path in paths:
        rel = path.relative_to(ROOT)
        if is_sensitive_filename(path):
            errors.append(f"{rel}: sensitive credential/config filename must not be committed")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if LOCAL_FILE_URL_RE.search(content):
            errors.append(f"{rel}: machine-local file:// URL found; use repository-relative links")

        for match in IP_RE.finditer(content):
            candidate = match.group(0)
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if address.is_global:
                errors.append(f"{rel}: public IP literal {candidate} found; use local/ignored inventory or a placeholder")

        if path.suffix.lower() in {".yaml", ".yml"}:
            validate_yaml(path, content, errors)
        elif path.suffix.lower() == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                errors.append(f"{rel}: invalid JSON: {exc}")

        if rel.parts[:3] == (".github", "ISSUE_TEMPLATE", rel.name) and path.suffix.lower() == ".md":
            validate_yaml(path, content, errors)

    if errors:
        print("Repository safety validation FAILED:")
        for error in errors:
            print(f"::error::{error}")
        return 1

    print(f"Repository safety validation passed for {len(paths)} changed file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
