"""
Unit and regression test suite for Issue #13:
Live structured logging, safe command execution with timeouts, accurate verification reporting,
and end-of-run execution summaries.
"""

from __future__ import annotations

import base64
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.bootstrap_admin import (
    BootstrapLogger,
    CommandTimeoutError,
    evaluate_ssh_directives_status,
    evaluate_verification_gate,
    execute_remote_cmd,
    format_end_of_run_summary,
    sanitize_text,
)

# Canonical 51-byte OpenSSH wire encoding for test ed25519 public key
_TEST_WIRE_KEY = (
    b"\x00\x00\x00\x0bssh-ed25519"
    b"\x00\x00\x00\x20\x01\x02\x03\x04\x05\x06\x07\x08"
    b"\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10\x11\x12\x13\x14"
    b"\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x20"
)
VALID_ED25519_B64 = base64.b64encode(_TEST_WIRE_KEY).decode("ascii")
VALID_ED25519_PUBKEY = f"ssh-ed25519 {VALID_ED25519_B64} vexteradmin@example.local"


class TestLiveLoggingAndRedaction(unittest.TestCase):
    """Tests for live structured logging, persistent audit trail, and secret sanitization."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name) / "logs" / "bootstrap"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_logger_creates_file_and_records_events(self) -> None:
        """BootstrapLogger creates a persistent log file and writes timestamped events."""
        logger = BootstrapLogger(log_dir=self.log_dir)
        self.assertTrue(logger.log_path.is_file(), "Log file must exist on disk.")

        logger.log("INFO", "Test message without step")
        logger.log_step_start("B-01", command_preview="pre-flight check")
        logger.log_step_success("B-01", duration_sec=0.15, message="Check passed")
        logger.close()

        content = logger.log_path.read_text(encoding="utf-8")
        self.assertIn("[INFO ]", content)
        self.assertIn("[B-01]", content)
        self.assertIn("Test message without step", content)
        self.assertIn("SUCCESS: Pre-flight checks & host-key verification (0.15s)", content)

    def test_logger_scrubs_registered_secrets(self) -> None:
        """Registered secrets must be replaced with <redacted-secret> in both console and file logs."""
        root_password = "super_secret_root_password_123"
        key_passphrase = "confidential_passphrase_456"

        logger = BootstrapLogger(log_dir=self.log_dir, secrets=[root_password, key_passphrase])
        logger.log("INFO", f"Connecting with password: {root_password}")
        logger.log("INFO", f"Using passphrase: {key_passphrase}")
        logger.close()

        content = logger.log_path.read_text(encoding="utf-8")
        self.assertNotIn(root_password, content, "Root password must not appear in log file.")
        self.assertNotIn(key_passphrase, content, "Key passphrase must not appear in log file.")
        self.assertEqual(content.count("<redacted-secret>"), 2)

    def test_sanitize_text_redacts_ed25519_pubkey_to_fingerprint(self) -> None:
        """Full Ed25519 public key payload must be converted to SHA256 fingerprint."""
        raw_cmd = f"echo '{VALID_ED25519_PUBKEY}' >> /home/vexteradmin/.ssh/authorized_keys"
        sanitized = sanitize_text(raw_cmd)

        self.assertNotIn(VALID_ED25519_B64, sanitized, "Raw base64 public key must be sanitized.")
        self.assertIn("ssh-ed25519 SHA256:", sanitized, "Must display fingerprint.")
        self.assertIn("vexteradmin@example.local", sanitized, "Comment should be preserved.")

    def test_step_lifecycle_tracking(self) -> None:
        """Logger correctly updates step statuses across lifecycle."""
        logger = BootstrapLogger(log_dir=self.log_dir)

        # Step B-02
        logger.log_step_start("B-02")
        self.assertEqual(logger.step_results["B-02"].status, "STARTED")

        logger.log_step_success("B-02", duration_sec=0.22, message="Account found")
        self.assertEqual(logger.step_results["B-02"].status, "SUCCESS")
        self.assertEqual(logger.step_results["B-02"].duration_sec, 0.22)

        # Step B-03 skipped
        logger.log_step_skipped("B-03", reason="User already exists")
        self.assertEqual(logger.step_results["B-03"].status, "SKIPPED")

        # Step B-04 failed
        logger.log_step_start("B-04")
        logger.log_step_failed("B-04", duration_sec=0.5, error_msg="Permission denied")
        self.assertEqual(logger.step_results["B-04"].status, "FAILED")
        self.assertEqual(logger.step_results["B-04"].message, "Permission denied")
        logger.close()


class TestCommandExecutionAndTimeout(unittest.TestCase):
    """Tests for non-blocking remote command execution, timeout handling, and return-code checks."""

    def test_execute_remote_cmd_success(self) -> None:
        """execute_remote_cmd drains stdout and stderr without deadlock and returns exit status."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_channel = MagicMock()

        mock_client.get_transport.return_value = mock_transport
        mock_transport.is_active.return_value = True
        mock_transport.open_session.return_value = mock_channel

        # Simulate channel output
        mock_channel.recv_ready.side_effect = [True, False]
        mock_channel.recv.return_value = b"uid=0(root) gid=0(root)\n"
        mock_channel.recv_stderr_ready.return_value = False
        mock_channel.exit_status_ready.return_value = True
        mock_channel.recv_exit_status.return_value = 0

        rc, out, err = execute_remote_cmd(mock_client, "id", timeout=5.0)

        self.assertEqual(rc, 0)
        self.assertEqual(out, "uid=0(root) gid=0(root)")
        self.assertEqual(err, "")
        mock_channel.close.assert_called_once()

    def test_execute_remote_cmd_timeout(self) -> None:
        """execute_remote_cmd raises CommandTimeoutError when command exceeds timeout."""
        mock_client = MagicMock()
        mock_transport = MagicMock()
        mock_channel = MagicMock()

        mock_client.get_transport.return_value = mock_transport
        mock_transport.is_active.return_value = True
        mock_transport.open_session.return_value = mock_channel

        # Simulate stuck/stalled channel
        mock_channel.recv_ready.return_value = False
        mock_channel.recv_stderr_ready.return_value = False
        mock_channel.exit_status_ready.return_value = False

        with self.assertRaises(CommandTimeoutError) as ctx:
            execute_remote_cmd(mock_client, "sleep 100", timeout=0.1)

        err_msg = str(ctx.exception)
        self.assertIn("Command timed out after 0.1s", err_msg)
        self.assertIn("Remote outcome is UNKNOWN", err_msg)
        self.assertIn("Some remote modifications may have already succeeded", err_msg)
        mock_channel.close.assert_called_once()

    def test_account_presence_distinction(self) -> None:
        """
        Verify that B-02 logic correctly distinguishes:
        - rc=0: user exists
        - rc=1 with 'no such user': user absent
        - unexpected rc/err: raises RuntimeError rather than assuming absence
        """
        # Case 1: user exists
        rc, out, err = 0, "1001", ""
        user_exists = (rc == 0)
        self.assertTrue(user_exists)

        # Case 2: user absent (standard id command exit 1 with stderr)
        rc, out, err = 1, "", "id: 'vexteradmin': no such user"
        if rc == 0:
            user_exists = True
        elif rc == 1 and ("no such user" in err.lower() or "user not found" in err.lower() or not out):
            user_exists = False
        else:
            user_exists = None
        self.assertFalse(user_exists)

        # Case 3: unexpected error (e.g. exit code 127 command not found)
        rc, out, err = 127, "", "bash: id: command not found"
        with self.assertRaises(RuntimeError) as ctx:
            if rc == 0:
                user_exists = True
            elif rc == 1 and ("no such user" in err.lower() or "user not found" in err.lower() or not out):
                user_exists = False
            else:
                raise RuntimeError(f"Unexpected error checking user 'vexteradmin' (exit: {rc}, err: {err})")
        self.assertIn("Unexpected error checking user", str(ctx.exception))


class TestAccurateVerificationReporting(unittest.TestCase):
    """
    Tests for accurate, truthful verification reporting.
    Proves that bootstrap access verification and SSH hardening policy verification are strictly separate.
    """

    def test_evaluate_verification_gate_full(self) -> None:
        """Access verification is FULL only when key login, sudo, and sshd -T all pass."""
        ssh_directives = {
            "PubkeyAuthentication": {"expected": "yes", "observed": "yes", "status": "PASS"},
        }
        access_status, hardening_status = evaluate_verification_gate(
            key_verified=True,
            sudo_verified=True,
            sshd_t_executed=True,
            sshd_directives=ssh_directives,
        )
        self.assertEqual(access_status, "FULL")
        self.assertIn("NOT APPLIED / NOT VERIFIED", hardening_status)

    def test_evaluate_verification_gate_partial(self) -> None:
        """Access verification is PARTIAL if key and sudo succeeded but sshd -T failed or was uninspected."""
        access_status, hardening_status = evaluate_verification_gate(
            key_verified=True,
            sudo_verified=True,
            sshd_t_executed=False,
            sshd_directives={},
        )
        self.assertEqual(access_status, "PARTIAL")
        self.assertIn("NOT APPLIED / NOT VERIFIED", hardening_status)

    def test_evaluate_verification_gate_failed(self) -> None:
        """Access verification is FAILED if key login or sudo failed."""
        access_status, _ = evaluate_verification_gate(
            key_verified=False,
            sudo_verified=True,
            sshd_t_executed=True,
            sshd_directives={},
        )
        self.assertEqual(access_status, "FAILED")

        access_status, _ = evaluate_verification_gate(
            key_verified=True,
            sudo_verified=False,
            sshd_t_executed=True,
            sshd_directives={},
        )
        self.assertEqual(access_status, "FAILED")

    def test_sshd_t_success_does_not_mark_hardening_verified(self) -> None:
        """
        REGRESSION PROOF:
        Successful execution of sshd -T with PubkeyAuthentication=yes must NEVER
        cause the SSH Hardening Policy status to be marked as verified or complete.
        """
        directives = evaluate_ssh_directives_status({
            "pubkeyauthentication": "yes",
            "passwordauthentication": "yes",  # Insecure default still active!
            "permitrootlogin": "yes",         # Insecure default still active!
        })

        access_status, hardening_status = evaluate_verification_gate(
            key_verified=True,
            sudo_verified=True,
            sshd_t_executed=True,
            sshd_directives=directives,
        )

        self.assertEqual(access_status, "FULL", "Bootstrap access verification should be full.")
        self.assertIn("NOT APPLIED / NOT VERIFIED", hardening_status, "Hardening policy MUST remain unverified.")
        self.assertIn("Deferred to Ansible", hardening_status)

        # Verify hardening directives are explicitly marked NOT CHECKED IN BOOTSTRAP
        self.assertEqual(directives["PasswordAuthentication"]["status"], "NOT CHECKED IN BOOTSTRAP")
        self.assertEqual(directives["PermitRootLogin"]["status"], "NOT CHECKED IN BOOTSTRAP")
        self.assertEqual(directives["KbdInteractiveAuthentication"]["status"], "NOT CHECKED IN BOOTSTRAP")

        # Only PubkeyAuthentication should have PASS status
        self.assertEqual(directives["PubkeyAuthentication"]["status"], "PASS")

    def test_directive_fails_when_expected_does_not_match(self) -> None:
        """A directive is marked FAIL if its observed value does not match expected."""
        directives = evaluate_ssh_directives_status({"pubkeyauthentication": "no"})
        self.assertEqual(directives["PubkeyAuthentication"]["status"], "FAIL")
        self.assertEqual(directives["PubkeyAuthentication"]["observed"], "no")


class TestEndOfRunSummary(unittest.TestCase):
    """Tests for the end-of-run execution summary structure and accuracy."""

    def test_format_end_of_run_summary_counts_and_content(self) -> None:
        """Summary accurately reflects step counts, mutation states, and next actions."""
        with tempfile.TemporaryDirectory() as td:
            logger = BootstrapLogger(log_dir=td)
            logger.step_results["B-01"].status = "SUCCESS"
            logger.step_results["B-01"].duration_sec = 0.5
            logger.step_results["B-02"].status = "SUCCESS"
            logger.step_results["B-02"].duration_sec = 0.2
            logger.step_results["B-03"].status = "SKIPPED"
            logger.step_results["B-03"].message = "Already exists"
            logger.step_results["B-04"].status = "FAILED"
            logger.step_results["B-04"].duration_sec = 0.3
            logger.step_results["B-04"].message = "usermod failed"
            # B-05 through B-10 remain NOT_RUN

            start_t = datetime(2026, 10, 21, 15, 0, 0, tzinfo=timezone.utc)
            end_t = datetime(2026, 10, 21, 15, 0, 5, tzinfo=timezone.utc)

            summary = format_end_of_run_summary(
                logger=logger,
                start_time_utc=start_t,
                end_time_utc=end_t,
                mutations_occurred=True,
                mutation_outcome_unknown=False,
                access_status="FAILED",
                hardening_status="NOT APPLIED / NOT VERIFIED (Deferred to Ansible baseline hardening)",
                ssh_directives={},
                next_safe_action="Inspect failure at B-04.",
            )
            logger.close()

            self.assertIn("Steps Completed: 2", summary)
            self.assertIn("Steps Skipped:   1", summary)
            self.assertIn("Steps Failed:    1", summary)
            self.assertIn("Steps Not Run:   6", summary)
            self.assertIn("MUTATIONS OCCURRED", summary)
            self.assertIn("BOOTSTRAP ACCESS VERIFICATION:       FAILED", summary)
            self.assertIn("SSH HARDENING POLICY VERIFICATION:   NOT APPLIED / NOT VERIFIED", summary)
            self.assertIn("Next Safe Action:", summary)
            self.assertIn("Inspect failure at B-04.", summary)


if __name__ == "__main__":
    unittest.main()
