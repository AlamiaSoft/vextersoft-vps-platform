#!/usr/bin/env python3
"""
VexterSoft VPS Bootstrap Administrator Provisioner
Connects to initial root account, provisions 'vexteradmin', installs Ed25519 public key,
and executes the mandatory Dual-Session Verification Gate before any daemon changes.

Provides:
- Live structured logs and safe command execution with bounded timeouts and deadlock prevention.
- Persistent local log audit trail (git-ignored logs/bootstrap/).
- Accurate, independently scoped verification statuses:
    1. Bootstrap Access Verification (FULL / PARTIAL / FAILED)
    2. SSH Hardening Policy Verification (NOT APPLIED / NOT VERIFIED in bootstrap)
- Truthful end-of-run execution summary and safe operator guidance.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("Error: paramiko is required. Run: python -m pip install paramiko", file=sys.stderr)
    sys.exit(1)

# POSIX username regex (up to 32 chars, lowercase, digits, underscore, hyphen)
ADMIN_USER_REGEX = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# Disallowed secret keys in .env files to enforce credential source restrictions
PROHIBITED_ENV_FILE_KEYS = {
    "SSH_PASSWORD",
    "BOOTSTRAP_ROOT_PASSWORD",
    "ROOT_PASSWORD",
    "PASSWORD",
    "SSH_KEY_PASSPHRASE",
    "BOOTSTRAP_KEY_PASSPHRASE",
    "PASSPHRASE",
}

# Stable step IDs and human-readable names for bootstrap operations
STEPS = {
    "B-01": "Pre-flight checks & host-key verification",
    "B-02": "Check admin account",
    "B-03": "Create admin account",
    "B-04": "Add sudo group",
    "B-05": "Validate and install sudoers rule",
    "B-06": "Install authorized key",
    "B-07": "Test independent key login",
    "B-08": "Verify passwordless sudo",
    "B-09": "Inspect effective sshd configuration",
    "B-10": "Write local Ansible inventory",
}

ABSENCE_PATTERNS = ["no such user", "user not found", "unknown user", "does not exist"]


class CommandTimeoutError(RuntimeError):
    """Raised when a remote command exceeds its allocated timeout."""
    pass


class SSHTransportError(RuntimeError):
    """Raised when an SSH transport or session failure occurs before or during command execution."""
    pass


@dataclass
class StepResult:
    step_id: str
    name: str
    status: str  # STARTED, SUCCESS, SKIPPED, FAILED, NOT_RUN
    duration_sec: float = 0.0
    message: str = ""
    command_preview: str | None = None
    stdout_summary: str | None = None
    stderr_summary: str | None = None


def sanitize_text(text: str, secrets: list[str] | None = None) -> str:
    """
    Scrub credentials, passphrases, and full public keys from logs and summaries.
    Converts full Ed25519 public keys to safe SHA256 fingerprints.
    """
    if not text:
        return ""

    out = text
    if secrets:
        # Sort secrets longest-first to prevent partial substring leaks
        for s in sorted(secrets, key=len, reverse=True):
            if s:
                out = out.replace(s, "<redacted-secret>")

    # Redact full Ed25519 public keys in command strings or outputs
    def _redact_ed25519(match: re.Match) -> str:
        ktype = match.group(1)
        b64_str = match.group(2)
        comment = match.group(3) or ""
        try:
            padded = b64_str + "=" * ((4 - len(b64_str) % 4) % 4)
            raw = base64.b64decode(padded)
            fp = hashlib.sha256(raw).digest()
            fp_b64 = base64.b64encode(fp).decode("ascii").rstrip("=")
            comment_str = f" ({comment.strip()})" if comment.strip() else ""
            return f"{ktype} SHA256:{fp_b64}{comment_str}"
        except Exception:
            return f"{ktype} <redacted-key-payload>"

    out = re.sub(
        r"(ssh-ed25519)\s+([A-Za-z0-9+/=]{40,})(?:\s+([^\r\n;`$'\"]+))?",
        _redact_ed25519,
        out,
    )
    return out


class BootstrapLogger:
    """Live streaming structured logger with persistent local file auditing and secret redaction."""

    def __init__(self, log_dir: Path | str = "logs/bootstrap", secrets: list[str] | None = None):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.log_path = self.log_dir / f"bootstrap-{timestamp_str}.log"
        self.log_file = self.log_path.open("a", encoding="utf-8")
        self.secrets = secrets or []
        self.step_results: dict[str, StepResult] = {}
        for sid, sname in STEPS.items():
            self.step_results[sid] = StepResult(step_id=sid, name=sname, status="NOT_RUN")

    def add_secret(self, secret: str | None) -> None:
        """Register a secret to be scrubbed from all subsequent logs."""
        if secret and secret not in self.secrets:
            self.secrets.append(secret)

    def _format_event(self, level: str, step_id: str | None, message: str) -> str:
        utc_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        prefix = f"[{utc_ts} UTC] [{level.upper():5}]"
        if step_id:
            prefix += f" [{step_id}]"
        sanitized = sanitize_text(message, self.secrets)
        return f"{prefix} {sanitized}"

    def log(self, level: str, message: str, step_id: str | None = None, stream_console: bool = True) -> None:
        line = self._format_event(level, step_id, message)
        self.log_file.write(line + "\n")
        self.log_file.flush()
        if stream_console:
            print(line, flush=True)

    def log_step_start(self, step_id: str, command_preview: str | None = None) -> None:
        name = STEPS.get(step_id, step_id)
        msg = f"START: {name}"
        if command_preview:
            msg += f" | Command: {command_preview}"
        self.step_results[step_id].status = "STARTED"
        self.step_results[step_id].command_preview = command_preview
        self.log("INFO", msg, step_id=step_id)

    def log_step_success(
        self,
        step_id: str,
        duration_sec: float,
        message: str = "",
        stdout_summary: str | None = None,
    ) -> None:
        name = STEPS.get(step_id, step_id)
        msg = f"SUCCESS: {name} ({duration_sec:.2f}s)"
        if message:
            msg += f" - {message}"
        res = self.step_results[step_id]
        res.status = "SUCCESS"
        res.duration_sec = duration_sec
        res.message = message
        res.stdout_summary = stdout_summary
        self.log("INFO", msg, step_id=step_id)

    def log_step_skipped(self, step_id: str, reason: str) -> None:
        name = STEPS.get(step_id, step_id)
        msg = f"SKIPPED: {name} - {reason}"
        res = self.step_results[step_id]
        res.status = "SKIPPED"
        res.message = reason
        self.log("INFO", msg, step_id=step_id)

    def log_step_failed(
        self,
        step_id: str,
        duration_sec: float,
        error_msg: str,
        stdout_summary: str | None = None,
        stderr_summary: str | None = None,
    ) -> None:
        name = STEPS.get(step_id, step_id)
        msg = f"FAILED: {name} ({duration_sec:.2f}s) - {error_msg}"
        res = self.step_results[step_id]
        res.status = "FAILED"
        res.duration_sec = duration_sec
        res.message = error_msg
        res.stdout_summary = stdout_summary
        res.stderr_summary = stderr_summary
        self.log("ERROR", msg, step_id=step_id)

    def close(self) -> None:
        try:
            self.log_file.close()
        except Exception:
            pass


def validate_admin_user(username: str) -> str:
    """Validate administrative username against strict POSIX pattern."""
    username = username.strip()
    if not username:
        raise ValueError("Admin username cannot be empty.")
    if not ADMIN_USER_REGEX.match(username):
        raise ValueError(
            f"Invalid admin username '{username}'. Username must match pattern '^[a-z_][a-z0-9_-]{{0,31}}$'."
        )
    return username


def validate_ed25519_public_key(key_str: str) -> str:
    """Strictly validate that key_str is a valid single-line OpenSSH Ed25519 public key."""
    key_str = key_str.strip()
    lines = key_str.splitlines()
    if len(lines) != 1:
        raise ValueError(f"SSH public key must be exactly one line, got {len(lines)} lines.")

    parts = lines[0].split(maxsplit=2)
    if len(parts) < 2:
        raise ValueError("Invalid SSH public key format: expected at least key-type and base64 payload.")

    key_type, key_b64 = parts[0], parts[1]
    if key_type != "ssh-ed25519":
        raise ValueError(f"Expected ssh-ed25519 key, got '{key_type}'. Only Ed25519 keys are accepted.")

    try:
        raw_bytes = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid base64 payload in SSH public key: {exc}") from exc

    if len(raw_bytes) != 51:
        raise ValueError(
            f"Invalid Ed25519 wire encoding length: got {len(raw_bytes)} bytes, expected exactly 51 bytes."
        )

    if len(parts) == 3:
        comment = parts[2]
        if any(c in comment for c in "\r\n\x00;`$|&<>\"'"):
            raise ValueError("SSH public key comment contains unsafe or control characters.")

    return lines[0]


def get_public_key() -> str:
    """Retrieve and validate Ed25519 public key from environment or default file."""
    key_str = os.environ.get("SSH_PUBLIC_KEY", "").strip()

    if not key_str:
        user_profile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
        if user_profile:
            default_path = Path(user_profile) / ".ssh" / "vextersoft_vps.pub"
            if default_path.is_file():
                key_str = default_path.read_text(encoding="utf-8").strip()

    if not key_str:
        raise ValueError(
            "No SSH public key found. Set SSH_PUBLIC_KEY environment variable or "
            "place vextersoft_vps.pub in ~/.ssh/"
        )

    return validate_ed25519_public_key(key_str)


def get_private_key_path() -> Path:
    """Resolve local private key path."""
    user_profile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not user_profile:
        raise ValueError("Cannot determine user home directory.")

    key_path = Path(user_profile) / ".ssh" / "vextersoft_vps"
    if not key_path.is_file():
        raise FileNotFoundError(f"Private key not found at {key_path}")
    return key_path


def load_private_key(priv_key_path: Path, passphrase: str | None = None) -> paramiko.PKey:
    """Load private key, prompting for passphrase if encrypted and none supplied."""
    try:
        return paramiko.Ed25519Key.from_private_key_file(str(priv_key_path), password=passphrase)
    except paramiko.PasswordRequiredException:
        if not passphrase and sys.stdin.isatty():
            passphrase = getpass.getpass(f"Enter passphrase for private key '{priv_key_path.name}': ")
            return paramiko.Ed25519Key.from_private_key_file(str(priv_key_path), password=passphrase)
        raise ValueError(
            f"Private key '{priv_key_path}' is encrypted with a passphrase. "
            "Provide the passphrase interactively or via BOOTSTRAP_KEY_PASSPHRASE."
        )


def get_known_hosts_path(custom_path: str | None = None) -> Path:
    """Resolve and validate the OpenSSH known_hosts file path."""
    if custom_path:
        p = Path(custom_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Specified known_hosts file not found: {p}")
        return p

    user_profile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not user_profile:
        raise ValueError("Cannot determine user home directory for OpenSSH known_hosts.")

    p = Path(user_profile) / ".ssh" / "known_hosts"
    if not p.is_file():
        raise FileNotFoundError(
            f"OpenSSH known_hosts file not found at {p}. "
            "Strict host-key verification requires a pre-existing trusted entry."
        )
    return p


def load_env_config(env_path: Path | str = ".env") -> dict[str, str]:
    """Safely read non-credential configuration from .env if present."""
    config: dict[str, str] = {}
    path = Path(env_path)
    if not path.is_file():
        return config

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key in PROHIBITED_ENV_FILE_KEYS:
            continue
        config[key] = value

    return config


def parse_sshd_config_t(sshd_t_output: str) -> dict[str, str]:
    """Parse key-value pairs from `sshd -T` output into a lowercase dictionary."""
    config: dict[str, str] = {}
    for line in sshd_t_output.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            config[parts[0].lower()] = parts[1].lower()
    return config


def verify_effective_sshd_settings(
    effective_config: dict[str, str],
    expected_settings: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Verify that effective sshd configuration satisfies required baseline security settings."""
    if expected_settings is None:
        expected_settings = {
            "passwordauthentication": "no",
            "kbdinteractiveauthentication": "no",
            "pubkeyauthentication": "yes",
        }

    errors: list[str] = []
    for key, expected_val in expected_settings.items():
        actual_val = effective_config.get(key)
        if actual_val != expected_val:
            errors.append(
                f"Effective sshd parameter '{key}' is '{actual_val}', expected '{expected_val}'"
            )

    return (len(errors) == 0, errors)


def evaluate_ssh_directives_status(
    effective_config: dict[str, str],
    diagnostic_available: bool = True,
) -> dict[str, dict[str, str]]:
    """
    Evaluate SSH directives accurately and truthfully.
    If diagnostic output is unavailable, all directives are marked NOT CHECKED IN BOOTSTRAP.
    Never claims a directive failed or passed without an observed effective value.
    """
    directives: dict[str, dict[str, str]] = {}

    if not diagnostic_available or not effective_config:
        directives["PubkeyAuthentication"] = {
            "expected": "yes",
            "observed": "UNAVAILABLE",
            "status": "NOT CHECKED IN BOOTSTRAP",
        }
        directives["PasswordAuthentication"] = {
            "expected": "no (enforced in Ansible phase)",
            "observed": "UNAVAILABLE",
            "status": "NOT CHECKED IN BOOTSTRAP",
        }
        directives["PermitRootLogin"] = {
            "expected": "prohibit-password (enforced in Ansible phase)",
            "observed": "UNAVAILABLE",
            "status": "NOT CHECKED IN BOOTSTRAP",
        }
        directives["KbdInteractiveAuthentication"] = {
            "expected": "no (enforced in Ansible phase)",
            "observed": "UNAVAILABLE",
            "status": "NOT CHECKED IN BOOTSTRAP",
        }
        return directives

    obs_pubkey = effective_config.get("pubkeyauthentication", "").lower()
    directives["PubkeyAuthentication"] = {
        "expected": "yes",
        "observed": obs_pubkey or "absent",
        "status": "PASS" if obs_pubkey == "yes" else "FAIL",
    }

    obs_pass = effective_config.get("passwordauthentication", "").lower()
    directives["PasswordAuthentication"] = {
        "expected": "no (enforced in Ansible phase)",
        "observed": obs_pass or "absent",
        "status": "NOT CHECKED IN BOOTSTRAP",
    }

    obs_root = effective_config.get("permitrootlogin", "").lower()
    directives["PermitRootLogin"] = {
        "expected": "prohibit-password (enforced in Ansible phase)",
        "observed": obs_root or "absent",
        "status": "NOT CHECKED IN BOOTSTRAP",
    }

    obs_kbd = effective_config.get("kbdinteractiveauthentication", "").lower()
    directives["KbdInteractiveAuthentication"] = {
        "expected": "no (enforced in Ansible phase)",
        "observed": obs_kbd or "absent",
        "status": "NOT CHECKED IN BOOTSTRAP",
    }

    return directives


def evaluate_verification_gate(
    key_verified: bool,
    sudo_verified: bool,
    sshd_t_executed: bool,
    sshd_directives: dict[str, dict[str, str]] | None = None,
    ssh_directives: dict[str, dict[str, str]] | None = None,
) -> tuple[str, str]:
    """
    Evaluate verification statuses with strict separation between:
      1. BOOTSTRAP ACCESS VERIFICATION: FULL / PARTIAL / FAILED
      2. SSH HARDENING POLICY VERIFICATION: NOT APPLIED / NOT VERIFIED
    Accepts sshd_directives or ssh_directives to prevent keyword mismatch.
    """
    directives = sshd_directives if sshd_directives is not None else (ssh_directives or {})

    if not (key_verified and sudo_verified):
        access_status = "FAILED"
    elif sshd_t_executed and directives.get("PubkeyAuthentication", {}).get("status") == "PASS":
        access_status = "FULL"
    else:
        access_status = "PARTIAL"

    hardening_status = "NOT APPLIED / NOT VERIFIED (Deferred to Ansible baseline hardening)"
    return access_status, hardening_status


def format_verification_summary(
    key_verified: bool,
    sudo_verified: bool,
    sshd_effective_verified: bool,
) -> tuple[str, bool]:
    """
    Helper for scoped verification gate status without ambiguous standalone wording.
    Returns (summary_text, is_fully_verified).
    """
    if not (key_verified and sudo_verified):
        return ("BOOTSTRAP ACCESS VERIFICATION: FAILED - Core access gates (SSH key or sudo) were not validated.", False)

    if sshd_effective_verified:
        return (
            "BOOTSTRAP ACCESS VERIFICATION: FULL (Non-root SSH key access, sudo execution, and effective sshd verified).",
            True,
        )

    return (
        "BOOTSTRAP ACCESS VERIFICATION: PARTIAL (Non-root SSH key access and sudo execution validated; effective sshd unverified).",
        False,
    )


def evaluate_swap_state(
    active_swaps: list[str],
    swap_file_path: str,
    file_exists: bool,
    file_size_bytes: int,
    file_type: str,
) -> str:
    """Evaluate swap state to ensure robust, non-destructive, and idempotent handling."""
    if swap_file_path in active_swaps:
        return "ALREADY_ACTIVE"
    if not file_exists:
        return "CREATE_NEW"
    if file_size_bytes == 0:
        return "CREATE_NEW"
    if file_type.strip().lower() == "swap":
        return "READY_TO_ACTIVATE"
    return "ERROR_UNRECOGNIZED_EXISTING_FILE"


def execute_remote_cmd(
    client: paramiko.SSHClient,
    cmd: str,
    timeout: float = 30.0,
    step_id: str | None = None,
    logger: BootstrapLogger | None = None,
    command_preview: str | None = None,
) -> tuple[int, str, str]:
    """
    Execute command remotely with non-blocking channel polling to prevent deadlocks,
    enforcing an explicit timeout and recording live execution duration.
    Distinguishes pre-submission transport failures from execution timeouts.
    """
    preview = command_preview or cmd
    if logger and step_id:
        logger.log_step_start(step_id, command_preview=preview)

    start_time = time.monotonic()
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        err_msg = f"SSH transport is not active for step {step_id or 'unknown'}."
        if logger and step_id:
            logger.log_step_failed(step_id, 0.0, err_msg)
        raise SSHTransportError(err_msg)

    # Phase 1: Open session channel before submitting command
    try:
        channel = transport.open_session()
        channel.settimeout(timeout)
        channel.setblocking(0)
    except Exception as e:
        dur = time.monotonic() - start_time
        err_msg = f"Transport failure opening SSH session before command submission: {e}"
        if logger and step_id:
            logger.log_step_failed(step_id, dur, err_msg)
        raise SSHTransportError(err_msg) from e

    # Phase 2: Submit command over channel
    try:
        channel.exec_command(cmd)
    except Exception as e:
        dur = time.monotonic() - start_time
        err_msg = f"Failed to submit command over channel: {e}"
        if logger and step_id:
            logger.log_step_failed(step_id, dur, err_msg)
        channel.close()
        raise SSHTransportError(err_msg) from e

    # Phase 3: Drain stdout/stderr without deadlocks
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    last_wait_log = start_time

    while True:
        if channel.recv_ready():
            chunk = channel.recv(4096)
            if chunk:
                stdout_chunks.append(chunk)

        if channel.recv_stderr_ready():
            chunk = channel.recv_stderr(4096)
            if chunk:
                stderr_chunks.append(chunk)

        if channel.exit_status_ready():
            while channel.recv_ready():
                stdout_chunks.append(channel.recv(4096))
            while channel.recv_stderr_ready():
                stderr_chunks.append(channel.recv_stderr(4096))
            break

        elapsed = time.monotonic() - start_time
        if elapsed > timeout:
            channel.close()
            timeout_msg = (
                f"Command timed out after {timeout:.1f}s. "
                "Remote outcome is UNKNOWN. Some remote modifications may have already succeeded."
            )
            if logger and step_id:
                logger.log_step_failed(step_id, elapsed, timeout_msg)
            raise CommandTimeoutError(timeout_msg)

        if logger and step_id and (time.monotonic() - last_wait_log > 5.0):
            last_wait_log = time.monotonic()
            logger.log("DEBUG", f"Still executing command ({elapsed:.1f}s elapsed)...", step_id=step_id)

        time.sleep(0.05)

    duration = time.monotonic() - start_time
    exit_code = channel.recv_exit_status()
    channel.close()

    out = b"".join(stdout_chunks).decode("utf-8", errors="replace").strip()
    err = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()

    out_summary = (out[:300] + "...") if len(out) > 300 else out
    err_summary = (err[:300] + "...") if len(err) > 300 else err

    if logger and step_id:
        if exit_code == 0:
            msg = "Exit code 0"
            if out_summary:
                msg += f" | Stdout: {out_summary}"
            logger.log_step_success(step_id, duration, message=msg, stdout_summary=out_summary or None)
        else:
            msg = f"Exit code {exit_code}"
            if err_summary:
                msg += f" | Stderr: {err_summary}"
            elif out_summary:
                msg += f" | Stdout: {out_summary}"
            logger.log_step_failed(
                step_id,
                duration,
                error_msg=msg,
                stdout_summary=out_summary or None,
                stderr_summary=err_summary or None,
            )

    return exit_code, out, err


def format_end_of_run_summary(
    logger: BootstrapLogger,
    start_time_utc: datetime,
    end_time_utc: datetime,
    mutations_occurred: bool,
    mutation_outcome_unknown: bool,
    access_status: str,
    hardening_status: str,
    ssh_directives: dict[str, dict[str, str]],
    next_safe_action: str,
) -> str:
    """Format comprehensive, structured, and truthful end-of-run execution summary accounting for all steps."""
    total_sec = (end_time_utc - start_time_utc).total_seconds()
    lines: list[str] = [
        "",
        "=" * 80,
        "                    VEXTERSOFT BOOTSTRAP EXECUTION SUMMARY",
        "=" * 80,
        f"Execution Timestamp:      {start_time_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Log File Path:            {logger.log_path}",
        f"Total Duration:           {total_sec:.2f}s",
        "",
        "Step Outcomes:",
    ]

    completed_cnt = 0
    skipped_cnt = 0
    failed_cnt = 0
    not_run_cnt = 0

    for sid in sorted(STEPS.keys()):
        res = logger.step_results.get(sid)
        if not res or res.status == "NOT_RUN":
            lines.append(f"  [NOT RUN] {sid} {STEPS[sid]}")
            not_run_cnt += 1
        elif res.status == "SUCCESS":
            msg_str = f" - {res.message}" if res.message else ""
            lines.append(f"  [SUCCESS] {sid} {STEPS[sid]} ({res.duration_sec:.2f}s){msg_str}")
            completed_cnt += 1
        elif res.status == "SKIPPED":
            lines.append(f"  [SKIPPED] {sid} {STEPS[sid]} - {res.message}")
            skipped_cnt += 1
        elif res.status == "FAILED":
            lines.append(f"  [FAILED]  {sid} {STEPS[sid]} ({res.duration_sec:.2f}s) - {res.message}")
            failed_cnt += 1
        elif res.status in ("STARTED", "INTERRUPTED"):
            lines.append(f"  [FAILED]  {sid} {STEPS[sid]} (interrupted during execution) - {res.message or 'interrupted'}")
            failed_cnt += 1
        else:
            lines.append(f"  [{res.status}] {sid} {STEPS[sid]}")
            failed_cnt += 1

    lines.extend([
        "",
        "Summary Counts:",
        f"  Steps Completed: {completed_cnt}",
        f"  Steps Skipped:   {skipped_cnt}",
        f"  Steps Failed:    {failed_cnt}",
        f"  Steps Not Run:   {not_run_cnt}",
        f"  Total Steps:     {len(STEPS)}",
        "",
        "Remote Mutation State:",
    ])

    if mutation_outcome_unknown:
        lines.append("  MUTATION OUTCOME UNKNOWN: A command timed out. Some changes may exist on VPS.")
    elif mutations_occurred:
        lines.append("  MUTATIONS OCCURRED: Administrative user and credentials provisioned on target.")
    else:
        lines.append("  NO MUTATIONS: Execution stopped before making any changes to the remote host.")

    lines.extend([
        "",
        "Verification Status:",
        f"  BOOTSTRAP ACCESS VERIFICATION:       {access_status}",
        f"  SSH HARDENING POLICY VERIFICATION:   {hardening_status}",
        "  (Note: System firewall, fail2ban, swap, and SSH hardening policies are deferred to Ansible)",
        "",
        "Effective SSH Directives Status:",
    ])

    for directive, info in ssh_directives.items():
        status = info.get("status", "NOT CHECKED")
        exp = info.get("expected", "N/A")
        obs = info.get("observed", "N/A")
        lines.append(f"  {directive:<30} {status:<10} (Observed: {obs}, Expected: {exp})")

    lines.extend([
        "",
        "Next Safe Action:",
        f"  {next_safe_action}",
        "=" * 80,
    ])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap vexteradmin and verify dual-session access.")
    parser.add_argument("--host", help="Target VPS host/IP (defaults to VPS_IP from .env or environment)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--admin-user", default="vexteradmin", help="Administrative user to provision")
    parser.add_argument("--known-hosts", help="Path to OpenSSH known_hosts file")
    parser.add_argument("--command-timeout", type=float, default=30.0, help="Remote command timeout in seconds")
    parser.add_argument("--log-dir", default="logs/bootstrap", help="Directory for persistent execution logs")
    args = parser.parse_args()

    start_time_utc = datetime.now(timezone.utc)
    logger = BootstrapLogger(log_dir=args.log_dir)

    print(f"[*] VexterSoft VPS Bootstrap Provisioner started at {start_time_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}", flush=True)
    print(f"[*] Audit log file: {logger.log_path}\n", flush=True)

    mutations_occurred = False
    mutation_outcome_unknown = False
    key_verified = False
    sudo_verified = False
    sshd_t_executed = False
    ssh_directives: dict[str, dict[str, str]] = {}
    exit_code = 0

    root_client: paramiko.SSHClient | None = None
    test_client: paramiko.SSHClient | None = None

    env_config = load_env_config()
    host = args.host or os.environ.get("VPS_IP") or env_config.get("VPS_IP")

    try:
        # Step B-01: Pre-flight checks and strict host-key verification
        logger.log_step_start("B-01", command_preview="Local input and host-key validation")
        b01_start = time.monotonic()

        if not host:
            raise ValueError("Target host IP must be specified via --host or VPS_IP.")

        admin_user = validate_admin_user(args.admin_user)
        pub_key = get_public_key()
        priv_key_path = get_private_key_path()
        known_hosts_path = get_known_hosts_path(args.known_hosts)

        root_password = os.environ.pop("BOOTSTRAP_ROOT_PASSWORD", None) or os.environ.pop("SSH_PASSWORD", None)
        if not root_password:
            if sys.stdin.isatty():
                root_password = getpass.getpass(f"Enter initial root password for {host}: ")
            else:
                raise ValueError("Non-interactive session detected and no root password supplied.")

        logger.add_secret(root_password)

        key_passphrase = os.environ.pop("BOOTSTRAP_KEY_PASSPHRASE", None) or os.environ.pop("SSH_KEY_PASSPHRASE", None)
        if key_passphrase:
            logger.add_secret(key_passphrase)

        pkey = load_private_key(priv_key_path, key_passphrase)

        root_client = paramiko.SSHClient()
        root_client.load_host_keys(str(known_hosts_path))
        root_client.set_missing_host_key_policy(paramiko.RejectPolicy())

        root_client.connect(
            hostname=host,
            port=args.port,
            username="root",
            password=root_password,
            timeout=15,
            banner_timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )
        root_password = None

        logger.log_step_success(
            "B-01",
            time.monotonic() - b01_start,
            message=f"Root session established with strict host-key checking against {known_hosts_path.name}",
        )

        # Step B-02: Check admin account
        user_exists = False
        rc, out, err = execute_remote_cmd(
            root_client,
            f"id -u {shlex.quote(admin_user)}",
            timeout=args.command_timeout,
            step_id="B-02",
            logger=logger,
            command_preview=f"id -u {admin_user}",
        )
        if rc == 0:
            user_exists = True
        elif rc == 1 and any(pat in err.lower() for pat in ABSENCE_PATTERNS):
            user_exists = False
        else:
            raise RuntimeError(
                f"Unexpected error checking user '{admin_user}' (exit: {rc}, stdout: '{out}', stderr: '{err}')"
            )

        # Step B-03: Create admin account
        if not user_exists:
            mutations_occurred = True
            rc, out, err = execute_remote_cmd(
                root_client,
                f"useradd -m -s /bin/bash {shlex.quote(admin_user)}",
                timeout=args.command_timeout,
                step_id="B-03",
                logger=logger,
                command_preview=f"useradd -m -s /bin/bash {admin_user}",
            )
            if rc != 0:
                raise RuntimeError(f"Failed to create user {admin_user}: {err}")
        else:
            logger.log_step_skipped("B-03", f"User '{admin_user}' already exists")

        # Step B-04: Add sudo group
        mutations_occurred = True
        rc, out, err = execute_remote_cmd(
            root_client,
            f"usermod -aG sudo {shlex.quote(admin_user)}",
            timeout=args.command_timeout,
            step_id="B-04",
            logger=logger,
            command_preview=f"usermod -aG sudo {admin_user}",
        )
        if rc != 0:
            raise RuntimeError(f"Failed to add {admin_user} to sudo group (exit: {rc}, err: {err})")

        # Step B-05: Validate and install sudoers rule
        mutations_occurred = True
        sudo_file = f"/etc/sudoers.d/90-{admin_user}"
        sudo_tmp = f"{sudo_file}.tmp"
        sudo_rule = f"{admin_user} ALL=(ALL) NOPASSWD:ALL\n"

        sudo_script = (
            f"printf '%s' {shlex.quote(sudo_rule)} > {shlex.quote(sudo_tmp)} && "
            f"visudo -cf {shlex.quote(sudo_tmp)} && "
            f"mv {shlex.quote(sudo_tmp)} {shlex.quote(sudo_file)} && "
            f"chmod 0440 {shlex.quote(sudo_file)}"
        )
        rc, out, err = execute_remote_cmd(
            root_client,
            sudo_script,
            timeout=args.command_timeout,
            step_id="B-05",
            logger=logger,
            command_preview=f"visudo -cf {sudo_tmp} && mv {sudo_tmp} {sudo_file}",
        )
        if rc != 0:
            raise RuntimeError(f"Failed to configure safe sudoers rule: {err}")

        # Step B-06: Install authorized key
        mutations_occurred = True
        ssh_dir = f"/home/{admin_user}/.ssh"
        auth_keys = f"{ssh_dir}/authorized_keys"
        setup_cmds = [
            f"mkdir -p {shlex.quote(ssh_dir)}",
            f"chmod 0700 {shlex.quote(ssh_dir)}",
            f"touch {shlex.quote(auth_keys)}",
            f"chmod 0600 {shlex.quote(auth_keys)}",
            f"(grep -qxF {shlex.quote(pub_key)} {shlex.quote(auth_keys)} 2>/dev/null || printf '%s\\n' {shlex.quote(pub_key)} >> {shlex.quote(auth_keys)})",
            f"chown -R {shlex.quote(admin_user)}:{shlex.quote(admin_user)} {shlex.quote(ssh_dir)}",
        ]
        rc, out, err = execute_remote_cmd(
            root_client,
            " && ".join(setup_cmds),
            timeout=args.command_timeout,
            step_id="B-06",
            logger=logger,
            command_preview=f"install authorized_keys in {ssh_dir}",
        )
        if rc != 0:
            raise RuntimeError(f"Failed to configure authorized_keys: {err}")

        # Step B-07: Test independent key login (Dual-Session Secondary Session)
        logger.log_step_start("B-07", command_preview=f"Secondary SSH connect as {admin_user} via Ed25519 key")
        b07_start = time.monotonic()

        test_client = paramiko.SSHClient()
        test_client.load_host_keys(str(known_hosts_path))
        test_client.set_missing_host_key_policy(paramiko.RejectPolicy())

        try:
            test_client.connect(
                hostname=host,
                port=args.port,
                username=admin_user,
                pkey=pkey,
                timeout=15,
                banner_timeout=30,
                look_for_keys=False,
                allow_agent=False,
            )
            key_verified = True
            logger.log_step_success(
                "B-07",
                time.monotonic() - b07_start,
                message=f"Independent session authenticated as '{admin_user}'",
            )
        except Exception as e:
            logger.log_step_failed("B-07", time.monotonic() - b07_start, str(e))
            raise RuntimeError(f"Dual-session authentication failed: {e}")

        # Step B-08: Verify passwordless sudo
        rc, out, err = execute_remote_cmd(
            test_client,
            "sudo -n id -u",
            timeout=args.command_timeout,
            step_id="B-08",
            logger=logger,
            command_preview="sudo -n id -u",
        )
        if rc != 0 or out != "0":
            test_client.close()
            raise RuntimeError(f"Dual-session sudo verification failed (exit: {rc}, out: '{out}', err: '{err}')")

        sudo_verified = True

        # Step B-09: Inspect effective sshd configuration (single cohesive step with fallback)
        logger.log_step_start("B-09", command_preview=f"sudo sshd -T -C user={admin_user}")
        b09_start = time.monotonic()

        rc, out, err = execute_remote_cmd(
            test_client,
            f"sudo sshd -T -C user={shlex.quote(admin_user)},host=127.0.0.1,addr=127.0.0.1",
            timeout=args.command_timeout,
        )
        if rc != 0:
            logger.log("WARN", f"Context sshd -T failed (exit: {rc}); attempting general fallback 'sudo sshd -T'...", step_id="B-09")
            rc, out, err = execute_remote_cmd(
                test_client,
                "sudo sshd -T",
                timeout=args.command_timeout,
            )

        b09_dur = time.monotonic() - b09_start
        if rc == 0:
            sshd_t_executed = True
            effective_cfg = parse_sshd_config_t(out)
            ssh_directives = evaluate_ssh_directives_status(effective_cfg, diagnostic_available=True)
            logger.log_step_success("B-09", b09_dur, message="Effective sshd configuration inspected via sshd -T")
        else:
            sshd_t_executed = False
            ssh_directives = evaluate_ssh_directives_status({}, diagnostic_available=False)
            logger.log_step_failed("B-09", b09_dur, error_msg=f"All sshd -T diagnostic attempts failed (exit: {rc}, err: {err})")

        test_client.close()

        # Step B-10: Write local uncommitted inventory
        logger.log_step_start("B-10", command_preview="Write ansible/inventory/hosts.yml")
        b10_start = time.monotonic()

        inventory_dir = Path("ansible") / "inventory"
        inventory_dir.mkdir(parents=True, exist_ok=True)
        inventory_file = inventory_dir / "hosts.yml"

        inventory_content = f"""---
all:
  hosts:
    vextersoft_vps:
      ansible_host: "{host}"
      ansible_user: "{admin_user}"
      ansible_port: {args.port}
      ansible_ssh_private_key_file: "~/.ssh/vextersoft_vps"
      ansible_python_interpreter: "/usr/bin/python3"
  children:
    vps_servers:
      hosts:
        vextersoft_vps:
"""
        inventory_file.write_text(inventory_content, encoding="utf-8")
        logger.log_step_success(
            "B-10",
            time.monotonic() - b10_start,
            message=f"Local Ansible inventory generated at {inventory_file}",
        )

        root_client.close()

        access_status, hardening_status = evaluate_verification_gate(
            key_verified, sudo_verified, sshd_t_executed, ssh_directives
        )

        if access_status == "FULL":
            exit_code = 0
            next_action = (
                "Proceed to Phase B: Execute Ansible baseline hardening playbook:\n"
                "    ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/01-baseline-hardening.yml"
            )
        else:
            exit_code = 2
            next_action = (
                "Access verification is PARTIAL (effective sshd could not be inspected). "
                "Ansible baseline hardening must strictly enforce and verify sshd before reloading."
            )

        summary_text = format_end_of_run_summary(
            logger=logger,
            start_time_utc=start_time_utc,
            end_time_utc=datetime.now(timezone.utc),
            mutations_occurred=mutations_occurred,
            mutation_outcome_unknown=False,
            access_status=access_status,
            hardening_status=hardening_status,
            ssh_directives=ssh_directives,
            next_safe_action=next_action,
        )
        print(summary_text, flush=True)
        logger.log("INFO", summary_text, stream_console=False)
        logger.close()
        return exit_code

    except CommandTimeoutError as e:
        mutation_outcome_unknown = True
        logger.log("ERROR", f"TIMEOUT: {e}")
        exit_code = 1
        next_action = (
            "Inspect target host manually or via Contabo recovery console. "
            "A command timed out and remote state is indeterminate."
        )
    except SSHTransportError as e:
        logger.log("ERROR", f"CONNECTION/TRANSPORT FAILURE: {e}")
        exit_code = 1
        next_action = (
            "Check VPS network connectivity, firewall, or SSH service status. "
            "Do not rerun mutations blindly without verifying remote host state."
        )
    except Exception as e:
        logger.log("ERROR", f"FATAL ERROR: {e}")
        exit_code = 1
        next_action = (
            "Resolve the reported error before re-running bootstrap. "
            "If mutations occurred, initial root login remains available because sshd hardening was deferred."
        )
    finally:
        if test_client:
            try:
                test_client.close()
            except Exception:
                pass
        if root_client:
            try:
                root_client.close()
            except Exception:
                pass

    # Ensure any interrupted step left in STARTED state is recorded as FAILED
    for sid, res in logger.step_results.items():
        if res.status == "STARTED":
            res.status = "FAILED"
            res.message = "interrupted by error or connection reset"

    try:
        if not ssh_directives:
            ssh_directives = evaluate_ssh_directives_status({}, diagnostic_available=False)

        access_status, hardening_status = evaluate_verification_gate(
            key_verified, sudo_verified, sshd_t_executed, ssh_directives
        )

        summary_text = format_end_of_run_summary(
            logger=logger,
            start_time_utc=start_time_utc,
            end_time_utc=datetime.now(timezone.utc),
            mutations_occurred=mutations_occurred,
            mutation_outcome_unknown=mutation_outcome_unknown,
            access_status=access_status,
            hardening_status=hardening_status,
            ssh_directives=ssh_directives,
            next_safe_action=next_action,
        )
        print(summary_text, file=sys.stderr, flush=True)
        logger.log("ERROR", summary_text, stream_console=False)
    except Exception as sum_err:
        print(f"[-] Error generating final summary: {sum_err}", file=sys.stderr)

    logger.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
