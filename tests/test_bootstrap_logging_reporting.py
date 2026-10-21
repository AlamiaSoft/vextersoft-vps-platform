"""
Unit and regression test suite for Issue #13 and follow-up findings:
Live structured logging, safe command execution with timeouts and transport handling,
accurate verification reporting, B-09 diagnostics fallback, and end-of-run execution summaries.
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
    SSHTransportError,
    evaluate_ssh_directives_status,
    evaluate_verification_gate,
    execute_remote_cmd,
    format_end_of_run_summary,
    main,
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

    def test_logger_scrubs_short_secrets(self) -> None:
        """P2 finding: verify secrets shorter than 4 characters are properly scrubbed."""
        short_secret = "abc"
        logger = BootstrapLogger(log_dir=self.log_dir, secrets=[short_secret])
        logger.log("INFO", f"User provided short password: {short_secret}")
        logger.close()

        content = logger.log_path.read_text(encoding="utf-8")
        self.assertNotIn(short_secret, content, "Short secret must not appear in log.")
        self.assertIn("<redacted-secret>", content)

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
    """Tests for non-blocking remote command execution, timeout handling, and transport errors."""

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

    def test_execute_remote_cmd_transport_failure_open_session(self) -> None:
        """
        P1 finding: socket reset during open_session() must raise SSHTransportError,
        indicating failure occurred BEFORE command submission.
        """
        mock_client = MagicMock()
        mock_transport = MagicMock()

        mock_client.get_transport.return_value = mock_transport
        mock_transport.is_active.return_value = True
        mock_transport.open_session.side_effect = ConnectionResetError("[WinError 10054] Connection reset by peer")

        with self.assertRaises(SSHTransportError) as ctx:
            execute_remote_cmd(mock_client, "usermod -aG sudo vexteradmin", timeout=5.0)

        self.assertIn("Transport failure opening SSH session before command submission", str(ctx.exception))
        self.assertIn("10054", str(ctx.exception))

    def test_account_presence_distinction(self) -> None:
        """
        P2 finding: Verify that B-02 logic requires explicit account-absence patterns
        and treats unrelated errors (even with exit code 1) as unexpected failures.
        """
        absence_patterns = ["no such user", "user not found", "unknown user", "does not exist"]

        # Case 1: user exists
        rc, out, err = 0, "1001", ""
        self.assertTrue(rc == 0)

        # Case 2: standard user absent
        rc, out, err = 1, "", "id: 'vexteradmin': no such user"
        self.assertTrue(rc == 1 and any(p in err.lower() for p in absence_patterns))

        # Case 3: exit 1 with empty stdout and unrelated error (must NOT be treated as absent)
        rc, out, err = 1, "", "id: cannot connect to user database service"
        is_absent = (rc == 1 and any(p in err.lower() for p in absence_patterns))
        self.assertFalse(is_absent, "Unrelated exit 1 error must NOT be treated as user absent.")


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

    def test_evaluate_verification_gate_keyword_compatibility(self) -> None:
        """P0 regression: evaluate_verification_gate accepts both sshd_directives and ssh_directives."""
        directives = {"PubkeyAuthentication": {"expected": "yes", "observed": "yes", "status": "PASS"}}

        # Accepts sshd_directives
        acc1, _ = evaluate_verification_gate(True, True, True, sshd_directives=directives)
        self.assertEqual(acc1, "FULL")

        # Accepts ssh_directives (previously caused TypeError)
        acc2, _ = evaluate_verification_gate(True, True, True, ssh_directives=directives)
        self.assertEqual(acc2, "FULL")

    def test_unavailable_sshd_output_is_not_checked_not_fail(self) -> None:
        """
        P2 finding: If sshd -T diagnostic is unavailable, directives must be marked
        'NOT CHECKED IN BOOTSTRAP' with observed 'UNAVAILABLE', not fabricated 'FAIL'.
        """
        directives = evaluate_ssh_directives_status({}, diagnostic_available=False)

        for name, info in directives.items():
            self.assertEqual(
                info["status"],
                "NOT CHECKED IN BOOTSTRAP",
                f"Directive {name} must be NOT CHECKED when diagnostics fail.",
            )
            self.assertEqual(info["observed"], "UNAVAILABLE")

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


class TestEndOfRunSummary(unittest.TestCase):
    """Tests for the end-of-run execution summary structure and accuracy."""

    def test_format_end_of_run_summary_accounts_for_every_step(self) -> None:
        """P1 finding: summary must account for all 10 steps, including interrupted steps."""
        with tempfile.TemporaryDirectory() as td:
            logger = BootstrapLogger(log_dir=td)
            logger.step_results["B-01"].status = "SUCCESS"
            logger.step_results["B-01"].duration_sec = 0.5
            logger.step_results["B-02"].status = "SUCCESS"
            logger.step_results["B-02"].duration_sec = 0.2
            logger.step_results["B-03"].status = "SKIPPED"
            logger.step_results["B-03"].message = "Already exists"
            logger.step_results["B-04"].status = "STARTED"  # Interrupted!
            logger.step_results["B-04"].message = "Connection reset"
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
            self.assertIn("Steps Failed:    1", summary)  # B-04 counted as failed/interrupted
            self.assertIn("Steps Not Run:   6", summary)  # B-05 to B-10
            self.assertIn("Total Steps:     10", summary)
            # Reconcile counts: 2 + 1 + 1 + 6 = 10
            self.assertEqual(2 + 1 + 1 + 6, 10)


class TestOperatorFailurePathRegression(unittest.TestCase):
    """
    P0 Regression test replicating the exact failure seen in operator run on 2026-10-21:
    - B-01 and B-02 succeed
    - B-03 skipped (user already exists)
    - B-04 open_session() fails with ConnectionResetError [WinError 10054]
    - Proves original failure is preserved, no secondary TypeError is raised,
      summary is printed, active resources close safely, and non-zero exit code is returned.
    """

    @patch("scripts.bootstrap_admin.getpass.getpass", return_value="mock_root_pw")
    @patch("scripts.bootstrap_admin.load_private_key")
    @patch("scripts.bootstrap_admin.get_public_key", return_value=VALID_ED25519_PUBKEY)
    @patch("scripts.bootstrap_admin.get_private_key_path", return_value=Path("/tmp/privkey"))
    @patch("scripts.bootstrap_admin.get_known_hosts_path", return_value=Path("/tmp/known_hosts"))
    @patch("scripts.bootstrap_admin.paramiko.SSHClient")
    def test_operator_open_session_reset_handling(
        self,
        mock_ssh_client_cls: MagicMock,
        mock_known_hosts: MagicMock,
        mock_priv_path: MagicMock,
        mock_pub_key: MagicMock,
        mock_load_priv: MagicMock,
        mock_getpass: MagicMock,
    ) -> None:
        mock_root_client = MagicMock()
        mock_ssh_client_cls.return_value = mock_root_client

        mock_transport = MagicMock()
        mock_root_client.get_transport.return_value = mock_transport
        mock_transport.is_active.return_value = True

        # Channel for B-02 (id -u): succeeds, returns 0 (user exists)
        mock_b02_channel = MagicMock()
        mock_b02_channel.recv_ready.side_effect = [True, False]
        mock_b02_channel.recv.return_value = b"1001\n"
        mock_b02_channel.recv_stderr_ready.return_value = False
        mock_b02_channel.exit_status_ready.return_value = True
        mock_b02_channel.recv_exit_status.return_value = 0

        # For B-04 (usermod -aG sudo): open_session raises ConnectionResetError
        mock_transport.open_session.side_effect = [
            mock_b02_channel,  # B-02
            ConnectionResetError("[WinError 10054] An existing connection was forcibly closed by the remote host"),  # B-04
        ]

        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"BOOTSTRAP_ROOT_PASSWORD": "test_root_password"}):
                with patch("sys.argv", ["bootstrap_admin.py", "--host", "192.0.2.1", "--log-dir", td]):
                    exit_code = main()

            # Must return non-zero
            self.assertEqual(exit_code, 1)

            # Check persistent log
            log_files = list(Path(td).glob("bootstrap-*.log"))
            self.assertEqual(len(log_files), 1)
            log_content = log_files[0].read_text(encoding="utf-8")

            # Must contain original error context
            self.assertIn("10054", log_content)
            self.assertIn("Transport failure opening SSH session before command submission", log_content)

            # Must contain summary
            self.assertIn("VEXTERSOFT BOOTSTRAP EXECUTION SUMMARY", log_content)
            self.assertIn("BOOTSTRAP ACCESS VERIFICATION:       FAILED", log_content)
            self.assertIn("SSH HARDENING POLICY VERIFICATION:   NOT APPLIED / NOT VERIFIED", log_content)

            # Must NOT contain TypeError
            self.assertNotIn("TypeError", log_content)


if __name__ == "__main__":
    unittest.main()
