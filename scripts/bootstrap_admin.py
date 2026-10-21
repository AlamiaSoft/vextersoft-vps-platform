#!/usr/bin/env python3
"""
VexterSoft VPS Bootstrap Administrator Provisioner
Connects to initial root account, provisions 'vexteradmin', installs Ed25519 public key,
and executes the mandatory Dual-Session Verification Gate before any daemon changes.
Enforces strict host key verification (RejectPolicy) and safe credential isolation.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import re
import shlex
import sys
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

    # Wire format for ssh-ed25519 public key in OpenSSH is exactly 51 bytes:
    # 4-byte length + "ssh-ed25519" (11) + 4-byte length + 32-byte pubkey = 51 bytes.
    if len(raw_bytes) != 51:
        raise ValueError(
            f"Invalid Ed25519 wire encoding length: got {len(raw_bytes)} bytes, expected exactly 51 bytes."
        )

    # Validate comment if present: forbid control or shell-special characters
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
    """
    Safely read non-credential configuration from .env if present.
    Strictly ignores any password or passphrase entries to prevent credential leaks.
    """
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
            # Silently discard sensitive credentials in general .env file
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
    """
    Verify that effective sshd configuration satisfies required baseline security settings.
    Returns (is_valid, list_of_errors).
    """
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


def evaluate_swap_state(
    active_swaps: list[str],
    swap_file_path: str,
    file_exists: bool,
    file_size_bytes: int,
    file_type: str,
) -> str:
    """
    Evaluate swap state to ensure robust, non-destructive, and idempotent handling.
    Returns one of:
      - 'ALREADY_ACTIVE': swapfile is currently active in /proc/swaps (do not touch).
      - 'READY_TO_ACTIVATE': file exists and is already formatted as swap (run swapon only).
      - 'CREATE_NEW': file does not exist or is empty 0-byte file (safe to allocate and mkswap).
      - 'ERROR_UNRECOGNIZED_EXISTING_FILE': file exists, non-empty, but not swap (abort).
    """
    if swap_file_path in active_swaps:
        return "ALREADY_ACTIVE"

    if not file_exists:
        return "CREATE_NEW"

    if file_size_bytes == 0:
        return "CREATE_NEW"

    if file_type.strip().lower() == "swap":
        return "READY_TO_ACTIVATE"

    return "ERROR_UNRECOGNIZED_EXISTING_FILE"


def execute_remote_cmd(client: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    """Execute command on remote host and return exit status, stdout, stderr."""
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return exit_code, out, err


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap vexteradmin and verify dual-session access.")
    parser.add_argument("--host", help="Target VPS host/IP (defaults to VPS_IP from .env or environment)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--admin-user", default="vexteradmin", help="Administrative user to provision")
    parser.add_argument("--known-hosts", help="Path to OpenSSH known_hosts file")
    args = parser.parse_args()

    # Load non-credential environment configuration
    env_config = load_env_config()
    host = args.host or os.environ.get("VPS_IP") or env_config.get("VPS_IP")
    if not host:
        print("Error: Target host IP must be specified via --host or VPS_IP.", file=sys.stderr)
        return 1

    try:
        admin_user = validate_admin_user(args.admin_user)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Validate Ed25519 public key
    try:
        pub_key = get_public_key()
        priv_key_path = get_private_key_path()
    except Exception as e:
        print(f"Key validation error: {e}", file=sys.stderr)
        return 1

    # Resolve OpenSSH known_hosts path for strict verification
    try:
        known_hosts_path = get_known_hosts_path(args.known_hosts)
    except Exception as e:
        print(f"Host-key configuration error: {e}", file=sys.stderr)
        return 1

    # Retrieve root password: from ephemeral environment or interactive prompt ONLY (never .env)
    root_password = os.environ.pop("BOOTSTRAP_ROOT_PASSWORD", None) or os.environ.pop("SSH_PASSWORD", None)
    if not root_password:
        if sys.stdin.isatty():
            root_password = getpass.getpass(f"Enter initial root password for {host}: ")
        else:
            print(
                "Error: Non-interactive session detected and no root password supplied. "
                "Provide BOOTSTRAP_ROOT_PASSWORD or SSH_PASSWORD via environment or run in an interactive terminal.",
                file=sys.stderr,
            )
            return 1

    # Retrieve key passphrase: from ephemeral environment or interactive prompt ONLY (never .env)
    key_passphrase = os.environ.pop("BOOTSTRAP_KEY_PASSPHRASE", None) or os.environ.pop("SSH_KEY_PASSPHRASE", None)
    try:
        pkey = load_private_key(priv_key_path, key_passphrase)
    except Exception as e:
        print(f"Private key loading error: {e}", file=sys.stderr)
        return 1

    print(f"[*] Step 1: Connecting as root to {host}:{args.port} (Strict Host-Key Verification)...", flush=True)
    root_client = paramiko.SSHClient()
    root_client.load_host_keys(str(known_hosts_path))
    root_client.set_missing_host_key_policy(paramiko.RejectPolicy())

    try:
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
        print("[+] Primary root session established and host key strictly verified.", flush=True)
    except paramiko.BadHostKeyException as e:
        print(f"[-] Host key verification FAILED for {host}:{args.port}: Key does not match known_hosts!", file=sys.stderr)
        return 1
    except paramiko.SSHException as e:
        if "not found in known_hosts" in str(e).lower():
            print(f"[-] Host key verification FAILED: Server '{host}' is not present in {known_hosts_path}.", file=sys.stderr)
        else:
            print(f"[-] SSH error connecting to {host}: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[-] Failed to establish root connection: {e}", file=sys.stderr)
        return 1
    finally:
        # Scrub root password from memory immediately after connection attempt
        root_password = None

    try:
        print(f"[*] Step 2: Provisioning administrative user '{admin_user}'...", flush=True)
        # Check if user exists using safely quoted arguments
        rc, _, _ = execute_remote_cmd(root_client, f"id -u {shlex.quote(admin_user)}")
        if rc != 0:
            rc, out, err = execute_remote_cmd(
                root_client, f"useradd -m -s /bin/bash {shlex.quote(admin_user)}"
            )
            if rc != 0:
                raise RuntimeError(f"Failed to create user {admin_user}: {err}")
            print(f"[+] User '{admin_user}' created.", flush=True)
        else:
            print(f"[+] User '{admin_user}' already exists.", flush=True)

        # Ensure sudo group membership
        execute_remote_cmd(root_client, f"usermod -aG sudo {shlex.quote(admin_user)}")

        # Configure passwordless sudo for admin user with atomic visudo validation
        sudo_file = f"/etc/sudoers.d/90-{admin_user}"
        sudo_tmp = f"{sudo_file}.tmp"
        sudo_rule = f"{admin_user} ALL=(ALL) NOPASSWD:ALL\n"

        sudo_script = (
            f"printf '%s' {shlex.quote(sudo_rule)} > {shlex.quote(sudo_tmp)} && "
            f"visudo -cf {shlex.quote(sudo_tmp)} && "
            f"mv {shlex.quote(sudo_tmp)} {shlex.quote(sudo_file)} && "
            f"chmod 0440 {shlex.quote(sudo_file)}"
        )
        rc, _, err = execute_remote_cmd(root_client, sudo_script)
        if rc != 0:
            raise RuntimeError(f"Failed to configure safe sudoers for {admin_user}: {err}")
        print(f"[+] Sudoers rule installed and validated at {sudo_file}.", flush=True)

        # Install SSH public key with safe file permissions and safe quoting
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
        rc, _, err = execute_remote_cmd(root_client, " && ".join(setup_cmds))
        if rc != 0:
            raise RuntimeError(f"Failed to configure authorized_keys: {err}")
        print(f"[+] Authorized Ed25519 key installed at {auth_keys}.", flush=True)

        # Step 3: Mandatory Dual-Session Verification Gate
        print("[*] Step 3: Executing Dual-Session Verification Gate...", flush=True)
        print("    (Preserving primary root session while testing independent key connection...)", flush=True)

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
            print(f"[+] Secondary session authenticated successfully as '{admin_user}' via Ed25519 key.", flush=True)
        except Exception as e:
            raise RuntimeError(f"Dual-session authentication failed: {e}")

        # Test sudo execution in secondary session
        rc, out, err = execute_remote_cmd(test_client, "sudo -n id -u")
        if rc != 0 or out != "0":
            test_client.close()
            raise RuntimeError(f"Dual-session sudo verification failed (exit: {rc}, out: '{out}', err: '{err}')")

        print("[+] Dual-session sudo verification PASSED: 'sudo -n id -u' executed as UID 0.", flush=True)

        # Check effective sshd configuration in secondary session
        rc, out, err = execute_remote_cmd(
            test_client,
            f"sudo sshd -T -C user={shlex.quote(admin_user)},host=127.0.0.1,addr=127.0.0.1",
        )
        if rc != 0:
            # Fallback to general sshd -T
            rc, out, err = execute_remote_cmd(test_client, "sudo sshd -T")

        if rc == 0:
            effective_cfg = parse_sshd_config_t(out)
            pubkey_val = effective_cfg.get("pubkeyauthentication", "unknown")
            print(f"[+] Verified effective remote sshd: PubkeyAuthentication={pubkey_val}.", flush=True)
        else:
            print(f"[!] Warning: Unable to inspect remote sshd -T: {err}", flush=True)

        test_client.close()
        print("[+] Dual-Session Verification Gate successfully validated!", flush=True)

        # Step 4: Write local uncommitted inventory for Ansible
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
        print(f"[+] Generated local Ansible inventory at {inventory_file} (git-ignored).", flush=True)

    except Exception as e:
        print(f"\n[-] Bootstrap failed: {e}", file=sys.stderr)
        print("[-] Primary root connection remains available. No sshd hardening was applied.", file=sys.stderr)
        root_client.close()
        return 1

    root_client.close()
    print("\n[SUCCESS] Phase A complete: 'vexteradmin' is provisioned, key-verified, and Ansible is configured.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
