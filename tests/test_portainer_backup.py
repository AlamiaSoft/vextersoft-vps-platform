from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.portainer_backup import (
    BackupError,
    backup_volume,
    main,
    restore_sandbox_volume,
    validate_archive_path,
    validate_identifier,
    verify_archive,
)


def _create_tar_gz(
    path: Path,
    files: dict[str, bytes],
) -> Path:
    """Create a valid .tar.gz archive at `path` with the given filename -> bytes map."""
    with tarfile.open(path, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


class PortainerBackupHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_validate_identifier_rejects_empty_placeholder_and_bad_chars(self) -> None:
        for invalid in ["", "   ", "<VOLUME_NAME>", "todo_CHANGE_ME", "../bad", "vol name", "-leadingdash"]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(BackupError):
                    validate_identifier(invalid, "Volume")

        self.assertEqual(
            validate_identifier("portainer_sandbox_20261022", "Volume"),
            "portainer_sandbox_20261022",
        )

    def test_validate_archive_path_rejects_placeholders_wildcards_and_directories(self) -> None:
        for invalid in ["", "  ", "/var/backups/<BACKUP_FILE>.tar.gz", "/var/backups/portainer-*.tar.gz"]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(BackupError):
                    validate_archive_path(invalid)

        with self.assertRaises(BackupError):
            validate_archive_path(self.root)

    def test_verify_archive_accepts_valid_portainer_archive(self) -> None:
        archive = _create_tar_gz(
            self.root / "valid-backup.tar.gz",
            {
                "./portainer.db": b"boltdb-mock-header-and-state",
                "./tls/cert.pem": b"cert-bytes",
            },
        )
        result = verify_archive(archive)
        self.assertEqual(result["verified_files"], ["portainer.db"])
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(result["member_count"], 2)
        self.assertEqual(len(result["sha256"]), 64)

    def test_verify_archive_rejects_missing_empty_or_corrupt_archives(self) -> None:
        # Missing file
        with self.assertRaisesRegex(BackupError, "does not exist"):
            verify_archive(self.root / "nonexistent.tar.gz")

        # Zero-byte file
        empty_file = self.root / "empty.tar.gz"
        empty_file.write_bytes(b"")
        with self.assertRaisesRegex(BackupError, "empty"):
            verify_archive(empty_file)

        # Corrupt gzip bytes
        corrupt_file = self.root / "corrupt.tar.gz"
        corrupt_file.write_bytes(b"not-a-valid-gzip-stream")
        with self.assertRaisesRegex(BackupError, "Gzip integrity check failed"):
            verify_archive(corrupt_file)

        # Missing portainer.db
        missing_db = _create_tar_gz(
            self.root / "no-db.tar.gz",
            {"./config.json": b'{"version": 1}'},
        )
        with self.assertRaisesRegex(BackupError, "missing required Portainer file 'portainer.db'"):
            verify_archive(missing_db)

        # 0-byte portainer.db
        zero_db = _create_tar_gz(
            self.root / "zero-db.tar.gz",
            {"./portainer.db": b""},
        )
        with self.assertRaisesRegex(BackupError, "0 bytes"):
            verify_archive(zero_db)

        # Path traversal member
        traversal_archive = _create_tar_gz(
            self.root / "traversal.tar.gz",
            {"../escaped/portainer.db": b"data"},
        )
        with self.assertRaisesRegex(BackupError, "path-traversal"):
            verify_archive(traversal_archive)

    def test_quiesced_backup_restarts_container_even_when_tar_fails(self) -> None:
        calls: list[list[str]] = []
        archive_path = self.root / "failed-backup.tar.gz"
        archive_path.write_bytes(b"partial-corrupt-data")

        def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(list(cmd))
            if cmd[:3] == ["docker", "volume", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            if cmd[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            if cmd[:2] == ["docker", "stop"]:
                return subprocess.CompletedProcess(cmd, 0, "portainer-test\n", "")
            if cmd[:2] == ["docker", "run"]:
                return subprocess.CompletedProcess(cmd, 1, "", "tar: write error: disk full")
            if cmd[:2] == ["docker", "start"]:
                return subprocess.CompletedProcess(cmd, 0, "portainer-test\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with self.assertRaisesRegex(BackupError, "Archive creation failed"):
            backup_volume(
                "portainer_test_source",
                archive_path,
                quiesce_container="portainer-test",
                runner=fake_runner,
            )

        # Verify docker stop was followed by docker run AND docker start in finally
        cmd_prefixes = [c[:2] for c in calls]
        self.assertIn(["docker", "stop"], cmd_prefixes)
        self.assertIn(["docker", "start"], cmd_prefixes)
        self.assertEqual(calls[-1], ["docker", "start", "portainer-test"])
        # Partial archive must be cleaned up on failure
        self.assertFalse(archive_path.exists())

    def test_quiesced_backup_reports_both_errors_if_tar_and_restart_fail(self) -> None:
        def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["docker", "volume", "inspect"] or cmd[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            if cmd[:2] == ["docker", "stop"]:
                return subprocess.CompletedProcess(cmd, 0, "ok", "")
            if cmd[:2] == ["docker", "run"]:
                return subprocess.CompletedProcess(cmd, 1, "", "tar failed")
            if cmd[:2] == ["docker", "start"]:
                return subprocess.CompletedProcess(cmd, 1, "", "daemon unreachable")
            raise AssertionError(f"Unexpected command: {cmd}")

        with self.assertRaises(BackupError) as ctx:
            backup_volume(
                "portainer_test_source",
                self.root / "out.tar.gz",
                quiesce_container="portainer-test",
                runner=fake_runner,
            )
        msg = str(ctx.exception)
        self.assertIn("Archive creation failed", msg)
        self.assertIn("CRITICAL: Failed to restart Portainer container", msg)

    def test_quiesced_backup_happy_path(self) -> None:
        archive_path = self.root / "good-backup.tar.gz"
        calls: list[list[str]] = []

        def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(list(cmd))
            if cmd[:2] == ["sudo", "docker"] and cmd[2] == "run":
                _create_tar_gz(archive_path, {"./portainer.db": b"valid-boltdb-content"})
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        res = backup_volume(
            "vextersoft_portainer_data",
            archive_path,
            quiesce_container="vextersoft-management-portainer-1",
            use_sudo=True,
            runner=fake_runner,
        )
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["container_restarted"])
        self.assertEqual(calls[-1], ["sudo", "docker", "start", "vextersoft-management-portainer-1"])

    def test_restore_sandbox_rejects_production_and_identical_volumes(self) -> None:
        archive = _create_tar_gz(
            self.root / "backup.tar.gz",
            {"./portainer.db": b"valid-boltdb-content"},
        )
        # Rejects production volume names
        for prod_vol in ("vextersoft_portainer_data", "portainer_data"):
            with self.assertRaisesRegex(BackupError, "protected production volume"):
                restore_sandbox_volume(archive, prod_vol)

        # Rejects source == target
        with self.assertRaisesRegex(BackupError, "distinct from source volume"):
            restore_sandbox_volume(
                archive,
                "portainer_sandbox_1",
                source_volume="portainer_sandbox_1",
            )

    def test_restore_sandbox_refuses_non_empty_existing_volume(self) -> None:
        archive = _create_tar_gz(
            self.root / "backup.tar.gz",
            {"./portainer.db": b"valid-boltdb-content"},
        )

        def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["docker", "volume", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0, "[]", "")
            if cmd[:2] == ["docker", "run"] and "ls -A /target" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "portainer.db\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with self.assertRaisesRegex(BackupError, "Refusing to restore into non-empty volume"):
            restore_sandbox_volume(archive, "portainer_existing_nonempty", runner=fake_runner)

    def test_restore_sandbox_cleans_up_created_volume_on_extract_failure(self) -> None:
        archive = _create_tar_gz(
            self.root / "backup.tar.gz",
            {"./portainer.db": b"valid-boltdb-content"},
        )
        calls: list[list[str]] = []

        def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(list(cmd))
            if cmd[:3] == ["docker", "volume", "inspect"]:
                return subprocess.CompletedProcess(cmd, 1, "", "no such volume")
            if cmd[:3] == ["docker", "volume", "create"]:
                return subprocess.CompletedProcess(cmd, 0, "portainer_sandbox_fail\n", "")
            if cmd[:2] == ["docker", "run"] and "tar" in cmd:
                return subprocess.CompletedProcess(cmd, 1, "", "tar extract error")
            if cmd[:3] == ["docker", "volume", "rm"]:
                return subprocess.CompletedProcess(cmd, 0, "portainer_sandbox_fail\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        with self.assertRaisesRegex(BackupError, "Failed to extract archive"):
            restore_sandbox_volume(archive, "portainer_sandbox_fail", runner=fake_runner)

        self.assertEqual(calls[-1], ["docker", "volume", "rm", "portainer_sandbox_fail"])

    def test_restore_sandbox_happy_path_and_cli_exit_codes(self) -> None:
        archive = _create_tar_gz(
            self.root / "backup.tar.gz",
            {"./portainer.db": b"valid-boltdb-content", "./tls/key.pem": b"k"},
        )

        def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["docker", "volume", "inspect"]:
                return subprocess.CompletedProcess(cmd, 1, "", "no such volume")
            if cmd[:3] == ["docker", "volume", "create"]:
                return subprocess.CompletedProcess(cmd, 0, "portainer_sandbox_ok\n", "")
            if cmd[:2] == ["docker", "run"] and "tar" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd[:2] == ["docker", "run"] and "test -s /target/portainer.db && ls -1A /target" in cmd:
                return subprocess.CompletedProcess(cmd, 0, "portainer.db\ntls\n", "")
            raise AssertionError(f"Unexpected command: {cmd}")

        res = restore_sandbox_volume(
            archive,
            "portainer_sandbox_ok",
            source_volume="vextersoft_portainer_data",
            runner=fake_runner,
        )
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["created_volume"])
        self.assertIn("portainer.db", res["restored_entries"])

        # CLI verify-archive returns 0 on valid archive, 1 on missing archive
        self.assertEqual(main(["verify-archive", "--archive-path", str(archive)]), 0)
        self.assertEqual(
            main(["verify-archive", "--archive-path", str(self.root / "missing.tar.gz")]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
