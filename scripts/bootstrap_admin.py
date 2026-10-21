#!/usr/bin/env python3
"""
VexterSoft VPS Bootstrap Administrator Provisioner
Connects to initial root account, provisions 'vexteradmin', installs Ed25519 public key,
and executes the mandatory Dual-Session Verification Gate before any daemon changes.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("Error: paramiko is required. Run: python -m pip install paramiko", file=sys.stderr)
    sys.exit(1)


def get_public_key(env_creds: dict[str, str] | None = None) -> str:
    """Retrieve and validate Ed25519 public key from environment, .env, or default file."""
    key_str = os.environ.get("SSH_PUBLIC_KEY", "").strip()

    if not key_str and env_creds:
        key_str = env_creds.get("SSH_PUBLIC_KEY", "").strip()

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

    # Validate single-line Ed25519 format
    lines = key_str.splitlines()
    if len(lines) != 1:
        raise ValueError(f"SSH public key must be exactly one line, got {len(lines)} lines.")

    parts = lines[0].split()
    if len(parts) < 2:
        raise ValueError("Invalid SSH public key format.")

    key_type, key_data = parts[0], parts[1]
    if key_type != "ssh-ed25519":
        raise ValueError(f"Expected ssh-ed25519 key, got '{key_type}'. Only Ed25519 is accepted.")

    try:
        raw_bytes = base64.b64decode(key_data, validate=True)
        if len(raw_bytes) < 32:
            raise ValueError("Key data is too short for a valid Ed25519 key.")
    except Exception as e:
        raise ValueError(f"Invalid base64 key payload: {e}")

    return lines[0]


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
            "Provide the passphrase interactively or via SSH_KEY_PASSPHRASE."
        )


def load_env_credentials() -> dict[str, str]:
    """Safely read .env if present without printing contents."""
    env = {}
    env_file = Path(".env")
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return env


def execute_remote_cmd(client: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    """Execute command on remote host and return exit status, stdout, stderr."""
    stdin, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return exit_code, out, err


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap vexteradmin and verify dual-session access.")
    parser.add_argument("--host", help="Target VPS host/IP (defaults to VPS_IP from .env)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--admin-user", default="vexteradmin", help="Administrative user to provision")
    args = parser.parse_args()

    env_creds = load_env_credentials()
    host = args.host or env_creds.get("VPS_IP")
    if not host:
        print("Error: Target host IP must be specified via --host or VPS_IP in .env", file=sys.stderr)
        return 1

    # Validate Ed25519 public key
    try:
        pub_key = get_public_key(env_creds)
        priv_key_path = get_private_key_path()
    except Exception as e:
        print(f"Key validation error: {e}", file=sys.stderr)
        return 1

    # Determine root password
    root_password = os.environ.get("SSH_PASSWORD") or env_creds.get("SSH_PASSWORD")
    if not root_password:
        if sys.stdin.isatty():
            root_password = getpass.getpass(f"Enter initial root password for {host}: ")
        else:
            print(
                "Error: Non-interactive session detected and no root password supplied. "
                "Provide SSH_PASSWORD via environment or run in an interactive terminal.",
                file=sys.stderr
            )
            return 1

    # Check key passphrase
    key_passphrase = os.environ.get("SSH_KEY_PASSPHRASE") or env_creds.get("SSH_KEY_PASSPHRASE")
    try:
        pkey = load_private_key(priv_key_path, key_passphrase)
    except Exception as e:
        print(f"Private key loading error: {e}", file=sys.stderr)
        return 1

    print(f"[*] Step 1: Connecting as root to {host}:{args.port}...", flush=True)
    root_client = paramiko.SSHClient()
    root_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

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
        print("[+] Primary root session established.", flush=True)
    except Exception as e:
        print(f"[-] Failed to establish root connection: {e}", file=sys.stderr)
        return 1

    admin_user = args.admin_user

    try:
        print(f"[*] Step 2: Provisioning administrative user '{admin_user}'...", flush=True)
        # Check if user exists
        rc, _, _ = execute_remote_cmd(root_client, f"id -u {admin_user}")
        if rc != 0:
            rc, out, err = execute_remote_cmd(root_client, f"useradd -m -s /bin/bash {admin_user}")
            if rc != 0:
                raise RuntimeError(f"Failed to create user {admin_user}: {err}")
            print(f"[+] User '{admin_user}' created.", flush=True)
        else:
            print(f"[+] User '{admin_user}' already exists.", flush=True)

        # Ensure sudo group membership
        execute_remote_cmd(root_client, f"usermod -aG sudo {admin_user}")

        # Configure passwordless sudo for admin user with visudo check
        sudo_file = f"/etc/sudoers.d/90-{admin_user}"
        sudo_rule = f"{admin_user} ALL=(ALL) NOPASSWD:ALL"
        rc, _, err = execute_remote_cmd(
            root_client,
            f"echo '{sudo_rule}' > {sudo_file}.tmp && visudo -cf {sudo_file}.tmp && mv {sudo_file}.tmp {sudo_file} && chmod 0440 {sudo_file}"
        )
        if rc != 0:
            raise RuntimeError(f"Failed to configure safe sudoers for {admin_user}: {err}")
        print(f"[+] Sudoers rule installed and validated at {sudo_file}.", flush=True)

        # Install SSH public key
        ssh_dir = f"/home/{admin_user}/.ssh"
        auth_keys = f"{ssh_dir}/authorized_keys"
        setup_cmds = [
            f"mkdir -p {ssh_dir}",
            f"chmod 0700 {ssh_dir}",
            f"grep -qxF '{pub_key}' {auth_keys} 2>/dev/null || echo '{pub_key}' >> {auth_keys}",
            f"chmod 0600 {auth_keys}",
            f"chown -R {admin_user}:{admin_user} {ssh_dir}",
        ]
        rc, _, err = execute_remote_cmd(root_client, " && ".join(setup_cmds))
        if rc != 0:
            raise RuntimeError(f"Failed to configure authorized_keys: {err}")
        print(f"[+] Authorized Ed25519 key installed at {auth_keys}.", flush=True)

        # Step 3: Mandatory Dual-Session Verification Gate
        print("[*] Step 3: Executing Dual-Session Verification Gate...", flush=True)
        print("    (Preserving primary root session while testing independent key connection...)", flush=True)

        test_client = paramiko.SSHClient()
        test_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

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
        test_client.close()

        if rc != 0 or out != "0":
            raise RuntimeError(f"Dual-session sudo verification failed (exit: {rc}, out: '{out}', err: '{err}')")

        print("[+] Dual-session sudo verification PASSED: 'sudo -n id -u' executed as UID 0.", flush=True)
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
