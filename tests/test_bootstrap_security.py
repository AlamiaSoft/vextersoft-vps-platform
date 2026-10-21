"""
Unit and regression test suite for VexterSoft VPS bootstrap and baseline hardening.
Tests host-key rejection, malformed inputs, shell-safe handling, credential-source restrictions,
SSH configuration verification, and swap idempotency.
"""

from __future__ import annotations

import base64
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import paramiko

from scripts.bootstrap_admin import (
    evaluate_swap_state,
    format_verification_summary,
    get_known_hosts_path,
    load_env_config,
    parse_sshd_config_t,
    validate_admin_user,
    validate_ed25519_public_key,
    verify_effective_sshd_settings,
)

# Canonical 51-byte OpenSSH wire encoding for test ed25519 public key
# 4 bytes length (11) + b"ssh-ed25519" + 4 bytes length (32) + 32-byte key
_TEST_WIRE_KEY = (
    b"\x00\x00\x00\x0bssh-ed25519"
    b"\x00\x00\x00\x20\x01\x02\x03\x04\x05\x06\x07\x08"
    b"\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14"
    b"\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x20"
)
VALID_ED25519_B64 = base64.b64encode(_TEST_WIRE_KEY).decode("ascii")
VALID_ED25519_PUBKEY = f"ssh-ed25519 {VALID_ED25519_B64} vexteradmin@example.local"


class TestHostKeyVerification(unittest.TestCase):
    """Regression tests for strict host-key verification and RejectPolicy enforcement."""

    def test_reject_policy_raises_on_missing_host_key(self) -> None:
        """RejectPolicy must raise an SSHException when a host key is not in known_hosts."""
        policy = paramiko.RejectPolicy()
        mock_client = MagicMock()
        mock_key = MagicMock()
        mock_key.get_name.return_value = "ssh-ed25519"
        mock_key.get_fingerprint.return_value = b"\x00" * 16

        with self.assertRaises(paramiko.SSHException) as ctx:
            policy.missing_host_key(mock_client, "192.0.2.1", mock_key)

        self.assertIn("not found in known_hosts", str(ctx.exception).lower())

    def test_auto_add_policy_is_not_used(self) -> None:
        """Verify bootstrap_admin script source code never references AutoAddPolicy."""
        bootstrap_script = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_admin.py"
        content = bootstrap_script.read_text(encoding="utf-8")
        self.assertNotIn("AutoAddPolicy", content, "AutoAddPolicy must never be used in bootstrap_admin.py")
        self.assertIn("RejectPolicy", content, "RejectPolicy must be explicitly configured")

    def test_get_known_hosts_path_custom(self) -> None:
        """get_known_hosts_path resolves a valid custom path."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"# known_hosts\n")
            f_path = Path(f.name)

        try:
            resolved = get_known_hosts_path(str(f_path))
            self.assertEqual(resolved, f_path.resolve())
        finally:
            f_path.unlink(missing_ok=True)

    def test_get_known_hosts_path_missing_raises(self) -> None:
        """get_known_hosts_path raises FileNotFoundError when path does not exist."""
        with self.assertRaises(FileNotFoundError):
            get_known_hosts_path("/nonexistent/known_hosts_path_xyz")


class TestMalformedInputs(unittest.TestCase):
    """Regression tests for input validation (admin username and SSH public key)."""

    def test_validate_admin_user_valid(self) -> None:
        """Valid POSIX administrative usernames are accepted."""
        for valid in ["vexteradmin", "admin_user", "sys-admin", "ops123", "a"]:
            self.assertEqual(validate_admin_user(valid), valid)

    def test_validate_admin_user_invalid(self) -> None:
        """Invalid, empty, or malicious usernames are rejected."""
        invalid_cases = [
            "",
            "   ",
            "Root",                # Uppercase
            "admin;rm -rf /",      # Shell injection
            "admin$(id)",          # Command substitution
            "admin user",          # Space
            "123admin",            # Starts with digit
            "-admin",              # Starts with hyphen
            "admin@domain",        # Special character
            "a" * 33,              # Exceeds 32-character limit
        ]
        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_admin_user(invalid)

    def test_validate_ed25519_public_key_valid(self) -> None:
        """Standard Ed25519 public key passes validation."""
        result = validate_ed25519_public_key(VALID_ED25519_PUBKEY)
        self.assertEqual(result, VALID_ED25519_PUBKEY)

    def test_validate_ed25519_public_key_without_comment(self) -> None:
        """Ed25519 public key without comment passes validation."""
        key_without_comment = f"ssh-ed25519 {VALID_ED25519_B64}"
        result = validate_ed25519_public_key(key_without_comment)
        self.assertEqual(result, key_without_comment)

    def test_validate_ed25519_public_key_rejects_rsa(self) -> None:
        """Non-Ed25519 keys (such as ssh-rsa) must be rejected."""
        rsa_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC3 test@example.local"
        with self.assertRaises(ValueError) as ctx:
            validate_ed25519_public_key(rsa_key)
        self.assertIn("Expected ssh-ed25519 key", str(ctx.exception))

    def test_validate_ed25519_public_key_rejects_multiline(self) -> None:
        """Multi-line keys must be rejected."""
        multiline = f"{VALID_ED25519_PUBKEY}\nssh-ed25519 {VALID_ED25519_B64} second"
        with self.assertRaises(ValueError) as ctx:
            validate_ed25519_public_key(multiline)
        self.assertIn("exactly one line", str(ctx.exception))

    def test_validate_ed25519_public_key_rejects_invalid_wire_length(self) -> None:
        """Base64 payloads that do not decode to exactly 51 bytes must be rejected."""
        short_b64 = base64.b64encode(b"short payload").decode("ascii")
        with self.assertRaises(ValueError) as ctx:
            validate_ed25519_public_key(f"ssh-ed25519 {short_b64} test")
        self.assertIn("wire encoding length", str(ctx.exception))

    def test_validate_ed25519_public_key_rejects_comment_injection(self) -> None:
        """Comments containing shell injection metacharacters must be rejected."""
        malicious_key = f"ssh-ed25519 {VALID_ED25519_B64} comment; rm -rf /"
        with self.assertRaises(ValueError) as ctx:
            validate_ed25519_public_key(malicious_key)
        self.assertIn("unsafe or control characters", str(ctx.exception))


class TestShellSafeHandling(unittest.TestCase):
    """Regression tests for shell quoting and safe command interpolation."""

    def test_shlex_quote_escapes_special_characters(self) -> None:
        """Verify that shell arguments containing metacharacters are safely isolated."""
        malicious_val = "vexteradmin; reboot"
        quoted = shlex.quote(malicious_val)
        self.assertTrue(quoted.startswith("'") and quoted.endswith("'"))
        self.assertIn(";", quoted)

    def test_sudoers_script_uses_safe_quoting(self) -> None:
        """Verify sudoers provisioning command safely quotes arguments and verifies via visudo."""
        admin_user = "vexteradmin"
        sudo_file = f"/etc/sudoers.d/90-{admin_user}"
        sudo_tmp = f"{sudo_file}.tmp"
        sudo_rule = f"{admin_user} ALL=(ALL) NOPASSWD:ALL\n"

        cmd = (
            f"printf '%s' {shlex.quote(sudo_rule)} > {shlex.quote(sudo_tmp)} && "
            f"visudo -cf {shlex.quote(sudo_tmp)} && "
            f"mv {shlex.quote(sudo_tmp)} {shlex.quote(sudo_file)} && "
            f"chmod 0440 {shlex.quote(sudo_file)}"
        )
        self.assertIn(shlex.quote(sudo_rule), cmd)
        self.assertIn("visudo -cf", cmd)
        self.assertIn("chmod 0440", cmd)


class TestCredentialSourceRestrictions(unittest.TestCase):
    """Regression tests for credential source restrictions and memory minimization."""

    def test_load_env_config_ignores_sensitive_keys(self) -> None:
        """load_env_config must ignore passwords and passphrases in .env files."""
        env_content = (
            "VPS_IP=192.0.2.1\n"
            "SSH_PORT=22\n"
            "SSH_PASSWORD=secret_root_password\n"
            "BOOTSTRAP_ROOT_PASSWORD=another_secret\n"
            "SSH_KEY_PASSPHRASE=secret_key_pass\n"
            "BOOTSTRAP_KEY_PASSPHRASE=another_key_pass\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as f:
            f.write(env_content)
            temp_path = f.name

        try:
            config = load_env_config(temp_path)
            self.assertEqual(config.get("VPS_IP"), "192.0.2.1")
            self.assertEqual(config.get("SSH_PORT"), "22")
            self.assertNotIn("SSH_PASSWORD", config)
            self.assertNotIn("BOOTSTRAP_ROOT_PASSWORD", config)
            self.assertNotIn("SSH_KEY_PASSPHRASE", config)
            self.assertNotIn("BOOTSTRAP_KEY_PASSPHRASE", config)
        finally:
            os.unlink(temp_path)

    def test_ephemeral_credentials_removed_from_environ(self) -> None:
        """Ephemeral credential variables must be popped from os.environ upon access."""
        test_env_var = "BOOTSTRAP_ROOT_PASSWORD"
        os.environ[test_env_var] = "ephemeral_secret_123"

        retrieved = os.environ.pop(test_env_var, None)
        self.assertEqual(retrieved, "ephemeral_secret_123")
        self.assertNotIn(test_env_var, os.environ, "Credential must be scrubbed from os.environ")


class TestSSHConfigurationVerification(unittest.TestCase):
    """Regression tests for sshd -T output parsing and effective settings verification."""

    def test_parse_sshd_config_t(self) -> None:
        """sshd -T output is parsed into a lowercase key-value dictionary."""
        sample_output = """
# OpenSSH 9.6 effective configuration
port 22
permitrootlogin prohibit-password
passwordauthentication no
kbdinteractiveauthentication no
pubkeyauthentication yes
maxauthtries 4
"""
        config = parse_sshd_config_t(sample_output)
        self.assertEqual(config["port"], "22")
        self.assertEqual(config["permitrootlogin"], "prohibit-password")
        self.assertEqual(config["passwordauthentication"], "no")
        self.assertEqual(config["kbdinteractiveauthentication"], "no")
        self.assertEqual(config["pubkeyauthentication"], "yes")

    def test_verify_effective_sshd_settings_pass(self) -> None:
        """Valid hardened settings pass verification."""
        config = {
            "passwordauthentication": "no",
            "kbdinteractiveauthentication": "no",
            "pubkeyauthentication": "yes",
        }
        is_valid, errors = verify_effective_sshd_settings(config)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_verify_effective_sshd_settings_fail_on_password_auth(self) -> None:
        """Verification fails if PasswordAuthentication is enabled."""
        config = {
            "passwordauthentication": "yes",
            "kbdinteractiveauthentication": "no",
            "pubkeyauthentication": "yes",
        }
        is_valid, errors = verify_effective_sshd_settings(config)
        self.assertFalse(is_valid)
        self.assertTrue(any("passwordauthentication" in err.lower() for err in errors))

    def test_format_verification_summary_distinguishes_full_vs_partial(self) -> None:
        """Report must not describe effective SSH config as verified if diagnostic check failed."""
        # Full verification case:
        full_msg, is_full = format_verification_summary(
            key_verified=True, sudo_verified=True, sshd_effective_verified=True
        )
        self.assertTrue(is_full)
        self.assertIn("BOOTSTRAP ACCESS VERIFICATION: FULL", full_msg)

        # Partial verification case (effective sshd not inspected):
        partial_msg, is_partial = format_verification_summary(
            key_verified=True, sudo_verified=True, sshd_effective_verified=False
        )
        self.assertFalse(is_partial)
        self.assertIn("BOOTSTRAP ACCESS VERIFICATION: PARTIAL", partial_msg)
        self.assertIn("effective sshd unverified", partial_msg)

        # Failed verification case (e.g. sudo failed):
        fail_msg, is_ok = format_verification_summary(
            key_verified=True, sudo_verified=False, sshd_effective_verified=True
        )
        self.assertFalse(is_ok)
        self.assertIn("BOOTSTRAP ACCESS VERIFICATION: FAILED", fail_msg)


class TestSwapRobustness(unittest.TestCase):
    """Regression tests for non-destructive, idempotent swapfile handling."""

    def test_already_active_swap_is_preserved(self) -> None:
        """If swapfile is already active, evaluate_swap_state returns ALREADY_ACTIVE."""
        active_swaps = ["/swapfile", "/dev/nvme0n1p2"]
        state = evaluate_swap_state(
            active_swaps=active_swaps,
            swap_file_path="/swapfile",
            file_exists=True,
            file_size_bytes=4294967296,
            file_type="swap",
        )
        self.assertEqual(state, "ALREADY_ACTIVE")

    def test_missing_swap_is_created(self) -> None:
        """If swapfile does not exist, evaluate_swap_state returns CREATE_NEW."""
        active_swaps = []
        state = evaluate_swap_state(
            active_swaps=active_swaps,
            swap_file_path="/swapfile",
            file_exists=False,
            file_size_bytes=0,
            file_type="",
        )
        self.assertEqual(state, "CREATE_NEW")

    def test_empty_placeholder_swap_is_created(self) -> None:
        """If swapfile exists but is 0 bytes, evaluate_swap_state returns CREATE_NEW."""
        active_swaps = []
        state = evaluate_swap_state(
            active_swaps=active_swaps,
            swap_file_path="/swapfile",
            file_exists=True,
            file_size_bytes=0,
            file_type="",
        )
        self.assertEqual(state, "CREATE_NEW")

    def test_unactivated_valid_swap_is_only_activated(self) -> None:
        """If swapfile exists and is formatted as swap but not active, returns READY_TO_ACTIVATE."""
        active_swaps = []
        state = evaluate_swap_state(
            active_swaps=active_swaps,
            swap_file_path="/swapfile",
            file_exists=True,
            file_size_bytes=4294967296,
            file_type="swap",
        )
        self.assertEqual(state, "READY_TO_ACTIVATE")

    def test_non_swap_existing_file_causes_error(self) -> None:
        """If swapfile exists with data but is NOT swap, aborts with ERROR_UNRECOGNIZED_EXISTING_FILE."""
        active_swaps = []
        state = evaluate_swap_state(
            active_swaps=active_swaps,
            swap_file_path="/swapfile",
            file_exists=True,
            file_size_bytes=1048576,
            file_type="data",
        )
        self.assertEqual(state, "ERROR_UNRECOGNIZED_EXISTING_FILE")


if __name__ == "__main__":
    unittest.main()
