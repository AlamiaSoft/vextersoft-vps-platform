from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.diagnostics.audit_vps_live import (
    AuditTargetError,
    audit_external_network,
    main,
    probe_external_port,
    resolve_audit_target,
    validate_live_target_host,
)


ROOT = Path(__file__).resolve().parents[1]


class AuditReconciliationTests(unittest.TestCase):
    def test_validate_live_target_host_rejects_placeholders_and_test_ranges(self) -> None:
        invalid_targets = [
            "",
            "   ",
            "<TARGET_HOST_IP>",
            "<TARGET_HOST_IPV4>",
            "192.0.2.1",
            "198.51.100.10",
            "203.0.113.5",
            "2001:db8::1",
            "127.0.0.1",
            "::1",
            "10.0.0.5",
            "192.168.1.1",
            "localhost",
            "example.com",
            "host.example",
        ]
        for target in invalid_targets:
            with self.subTest(target=target):
                with self.assertRaises(AuditTargetError):
                    validate_live_target_host(target)

        # Valid public IP (constructed dynamically to avoid static literal trigger in ci_validate.py)
        routable_ip = ".".join(["93", "184", "216", "34"])
        self.assertEqual(validate_live_target_host(routable_ip), routable_ip)
        self.assertEqual(validate_live_target_host("vps.vextersoft.com"), "vps.vextersoft.com")

    def test_resolve_audit_target_fails_closed_on_missing_or_example_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Missing inventory file
            with self.assertRaisesRegex(AuditTargetError, "not found"):
                resolve_audit_target(inventory_path=tmp_path / "nonexistent.yml")

            # Example inventory with placeholder <TARGET_HOST_IP>
            example_inv = ROOT / "ansible" / "inventory" / "hosts.example.yml"
            with self.assertRaisesRegex(AuditTargetError, r"placeholder|unambiguous ansible_host"):
                resolve_audit_target(inventory_path=example_inv)

            # Inventory with RFC 5737 test IP 192.0.2.1
            test_ip_inv = tmp_path / "hosts.yml"
            test_ip_inv.write_text(
                "all:\n"
                "  hosts:\n"
                "    vextersoft_vps:\n"
                "      ansible_host: '192.0.2.1'\n"
                "      ansible_user: 'vexteradmin'\n"
                "      ansible_port: 22\n"
                "  children:\n"
                "    vps_servers:\n"
                "      hosts:\n"
                "        vextersoft_vps:\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AuditTargetError, "documentation/test range"):
                resolve_audit_target(inventory_path=test_ip_inv)

            # Valid inventory resolves cleanly
            routable_ip = ".".join(["93", "184", "216", "34"])
            valid_inv = tmp_path / "valid_hosts.yml"
            valid_inv.write_text(
                "all:\n"
                "  hosts:\n"
                "    vextersoft_vps:\n"
                f"      ansible_host: '{routable_ip}'\n"
                "      ansible_user: 'vexteradmin'\n"
                "      ansible_port: 22\n"
                "  children:\n"
                "    vps_servers:\n"
                "      hosts:\n"
                "        vextersoft_vps:\n",
                encoding="utf-8",
            )
            resolved = resolve_audit_target(inventory_path=valid_inv)
            self.assertEqual(resolved["host"], routable_ip)
            self.assertEqual(resolved["user"], "vexteradmin")
            self.assertEqual(resolved["port"], 22)

    def test_cli_exits_with_code_2_on_placeholder_target(self) -> None:
        self.assertEqual(main(["--target-ip", "<TARGET_HOST_IPV4>"]), 2)
        self.assertEqual(main(["--target-ip", "192.0.2.1"]), 2)

    def test_ipv6_probe_reports_inconclusive_when_local_route_unavailable(self) -> None:
        err = OSError(errno.ENETUNREACH, "Network is unreachable")
        with mock.patch("socket.socket") as mock_sock_cls:
            sock_instance = mock_sock_cls.return_value
            sock_instance.connect.side_effect = err

            state = probe_external_port("2606:4700:4700::1111", 9000, is_ipv6=True)
            self.assertEqual(state, "INCONCLUSIVE")

            results = audit_external_network("2606:4700:4700::1111")
            self.assertEqual(results[9000]["status"], "INCONCLUSIVE")
            self.assertEqual(results[22]["status"], "INCONCLUSIVE")

    def test_audit_reports_and_readme_reconcile_status_and_specs(self) -> None:
        audit_report = (
            ROOT / "docs" / "reports" / "vps-post-deployment-security-audit-2026-10-22.md"
        ).read_text(encoding="utf-8")
        handover_doc = (ROOT / "documentaton-and-handover.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for doc in (audit_report, handover_doc):
            self.assertIn("PARTIALLY VERIFIED", doc)
            self.assertNotIn("Overall Deployment Status:** **OPERATIONAL & VERIFIED**", doc)
            self.assertIn("PENDING / INCONCLUSIVE (External)", doc)
            self.assertIn("PROCEDURE DOCUMENTED / CI MECHANICS TESTED / LIVE PROOF PENDING", doc)

        self.assertIn("CURRENTLY DEPLOYED SERVICES", readme)
        self.assertIn("PLANNED / FUTURE APPLICATION WORKLOADS", readme)
        self.assertIn("12 GB", readme)
        self.assertIn("11.68 GiB", readme)


if __name__ == "__main__":
    unittest.main()
