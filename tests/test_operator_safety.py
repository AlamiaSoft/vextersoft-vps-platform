import json
import sys
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from resolve_ansible_target import TargetError, resolve_target  # noqa: E402


class ResolveAnsibleTargetTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {
            "vps_servers": {"children": ["ubuntu_vps"]},
            "ubuntu_vps": {"hosts": ["vextersoft_vps"]},
            "_meta": {
                "hostvars": {
                    "vextersoft_vps": {
                        "ansible_host": "vps.example.net",
                        "ansible_user": "vexteradmin",
                        "ansible_port": 2222,
                        "ssh_port": 2222,
                        "cloudflare_tunnel_token": "synthetic-test-value-must-not-be-output",
                    }
                }
            },
        }

    def test_resolves_only_target_metadata_and_ignores_secret_values(self):
        result = resolve_target(self.inventory, "vextersoft_vps")
        self.assertEqual(
            result,
            {
                "alias": "vextersoft_vps",
                "host": "vps.example.net",
                "user": "vexteradmin",
                "port": 2222,
                "ssh_port": 2222,
            },
        )
        self.assertNotIn("cloudflare_tunnel_token", json.dumps(result))
        self.assertNotIn("synthetic-test-value", json.dumps(result))

    def test_rejects_alias_outside_playbook_target_group(self):
        with self.assertRaisesRegex(TargetError, "not a member"):
            resolve_target(self.inventory, "other_host")

    def test_rejects_missing_hostvars_and_ambiguous_targets(self):
        self.inventory["_meta"]["hostvars"].pop("vextersoft_vps")
        with self.assertRaisesRegex(TargetError, "does not resolve"):
            resolve_target(self.inventory, "vextersoft_vps")

    def test_rejects_placeholder_or_terminal_unsafe_host_values(self):
        for host in ("<TARGET_HOST_IP>", "host.example.net\x1b[31m"):
            with self.subTest(host=host):
                self.inventory["_meta"]["hostvars"]["vextersoft_vps"]["ansible_host"] = host
                with self.assertRaisesRegex(TargetError, "ansible_host"):
                    resolve_target(self.inventory, "vextersoft_vps")

    def test_rejects_invalid_ports_users_and_non_ssh_connections(self):
        hostvars = self.inventory["_meta"]["hostvars"]["vextersoft_vps"]
        for key, value in (("ansible_port", 0), ("ssh_port", 65536), ("ansible_user", "admin;id"), ("ansible_connection", "local")):
            with self.subTest(key=key, value=value):
                original = hostvars.get(key)
                hostvars[key] = value
                with self.assertRaises(TargetError):
                    resolve_target(self.inventory, "vextersoft_vps")
                if original is None:
                    hostvars.pop(key, None)
                else:
                    hostvars[key] = original


class IngressWorkflowSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playbook = yaml.safe_load((ROOT / "ansible/playbooks/03-cloudflared-portainer.yml").read_text(encoding="utf-8"))[0]
        cls.playbook_text = (ROOT / "ansible/playbooks/03-cloudflared-portainer.yml").read_text(encoding="utf-8")
        cls.operator = (ROOT / "scripts/vextersoft.ps1").read_text(encoding="utf-8")
        cls.runbook = (ROOT / "docs/cloudflare-portainer-runbook.md").read_text(encoding="utf-8")

    def test_host_overridable_route_settings_are_not_play_level_vars(self):
        self.assertNotIn("cloudflare_management_hostname", self.playbook["vars"])
        self.assertNotIn("cloudflare_public_routes", self.playbook["vars"])
        self.assertIn("hostvars[inventory_hostname].cloudflare_management_hostname | default", self.playbook_text)
        self.assertIn("hostvars[inventory_hostname].cloudflare_public_routes | default", self.playbook_text)

    def test_tunnel_token_must_come_from_encrypted_namespaced_vault_file(self):
        self.assertIn("'^\\$ANSIBLE_VAULT;'", self.playbook_text)
        self.assertIn("name: cloudflare_vault", self.playbook_text)
        self.assertIn("cloudflare_vault.cloudflare_tunnel_token", self.playbook_text)
        self.assertIn("content: \"{{ cloudflare_vault.cloudflare_tunnel_token | trim }}\\n\"", self.playbook_text)
        copy_task = next(t for t in self.playbook["tasks"] if "Install the tunnel token" in t["name"])
        self.assertTrue(copy_task["no_log"])
        self.assertFalse(copy_task["ansible.builtin.copy"]["diff"])

    def test_dual_ingress_approval_and_single_vault_prompt(self):
        self.assertFalse(self.playbook["vars"]["cloudflare_deployment_approved"])
        approval = next(t for t in self.playbook["pre_tasks"] if "Require explicit approval" in t["name"])
        self.assertIn("cloudflare_deployment_approved | bool", approval["ansible.builtin.assert"]["that"])
        self.assertIn("APPLY $Phase $HostAlias", self.operator)
        self.assertIn("cloudflare_deployment_approved=true", self.operator)
        self.assertEqual(self.operator.count("--ask-vault-pass"), 1)

    def test_target_resolution_is_group_limited_and_printed_before_confirmation(self):
        self.assertIn("resolve_ansible_target.py", self.operator)
        self.assertIn("Target: %s:%s (user %s; alias %s)", self.operator)
        self.assertIn("Read-Host \"Type '$confirmation' to proceed\"", self.operator)
        self.assertIn("StrictHostKeyChecking=yes", self.operator)
        self.assertIn("ANSIBLE_HOST_KEY_CHECKING=True", self.operator)
        self.assertIn("if ($LASTEXITCODE -ne 0) { throw", self.operator)
        self.assertIn("set -Eeuo pipefail", self.operator)

    def test_preflight_rejects_shared_management_and_database_networks(self):
        self.assertIn("Refuse unexpected containers on the private management network", self.playbook_text)
        self.assertIn("Refuse unexpected containers on the tunnel egress network", self.playbook_text)
        self.assertIn("Refuse non-frontend services on public application networks", self.playbook_text)
        self.assertIn("Refuse database DNAT rules", self.playbook_text)
        self.assertIn("Refuse published Docker database ports", self.playbook_text)
        long_lines = [
            (number, len(line))
            for number, line in enumerate(self.playbook_text.splitlines(), start=1)
            if len(line) > 160
        ]
        self.assertEqual(long_lines, [])

    def test_post_deployment_checks_require_healthy_services(self):
        self.assertIn('test "$state" = "running healthy"', self.operator)
        self.assertIn("health", self.runbook.lower())
        command = next(line for line in self.operator.splitlines() if "docker inspect --format" in line)
        rendered = Environment().from_string(command).render()
        self.assertIn('{{.State.Status}} {{.State.Health.Status}}', rendered)


if __name__ == "__main__":
    unittest.main()
