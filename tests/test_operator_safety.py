import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

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

    def test_vault_file_is_outside_auto_discovered_host_vars(self):
        expected_path = '{{ playbook_dir }}/../vault/{{ inventory_hostname }}.vault.yml'
        header_task = next(task for task in self.playbook["pre_tasks"] if "Check the per-host tunnel credential" in task["name"])
        include_task = next(task for task in self.playbook["pre_tasks"] if "Load tunnel credential" in task["name"])
        self.assertEqual(header_task["ansible.builtin.command"]["argv"][-1], expected_path)
        self.assertEqual(include_task["ansible.builtin.include_vars"]["file"], expected_path)
        self.assertIn("ansible/vault/*.vault.yml", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        self.assertIn('ansible-inventory -i "$INVENTORY" --list', self.operator)
        self.assertNotRegex(self.operator, r"ansible-inventory[^\n]*ask-vault")

    def test_inventory_list_ignores_real_encrypted_vault_file_without_prompt(self):
        try:
            from ansible.parsing.vault import VaultLib, VaultSecret
            from ansible.constants import DEFAULT_VAULT_IDENTITY
        except ImportError:
            self.skipTest("ansible-core is not installed")
        inventory_cli = shutil.which("ansible-inventory")
        if not inventory_cli:
            self.skipTest("ansible-inventory is not installed")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "ansible"
            inventory_dir = root / "inventory"
            host_vars = inventory_dir / "host_vars" / "vextersoft_vps"
            vault_dir = root / "vault"
            host_vars.mkdir(parents=True)
            vault_dir.mkdir(parents=True)
            (inventory_dir / "hosts.yml").write_text(
                "all:\n  children:\n    vps_servers:\n      hosts:\n        vextersoft_vps:\n          ansible_host: 192.0.2.5\n          ansible_user: deploy\n",
                encoding="utf-8",
            )
            (host_vars / "cloudflare.yml").write_text(
                "cloudflare_management_hostname: devops.example.test\n",
                encoding="utf-8",
            )
            synthetic_vault_yaml = b'cloudflare_tunnel_token: "synthetic-secret-never-output"\n'
            vault = VaultLib([(DEFAULT_VAULT_IDENTITY, VaultSecret(b"test-only-password"))])
            encrypted = vault.encrypt(synthetic_vault_yaml)
            self.assertTrue(encrypted.startswith(b"$ANSIBLE_VAULT;"))
            (vault_dir / "vextersoft_vps.vault.yml").write_bytes(encrypted)

            env = os.environ.copy()
            env["ANSIBLE_CONFIG"] = str(ROOT / "ansible" / "ansible.cfg")
            try:
                result = subprocess.run(
                    [inventory_cli, "-i", str(inventory_dir / "hosts.yml"), "--list"],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except OSError as exc:
                if os.name == "nt":
                    self.skipTest(f"Windows Ansible CLI is unavailable in this non-console session: {exc}")
                raise
            if result.returncode and "get_blocking" in result.stderr and os.name == "nt":
                self.skipTest("Windows Ansible CLI requires a console; Linux CI runs this regression")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("synthetic-secret-never-output", result.stdout + result.stderr)
            parsed = json.loads(result.stdout)
            self.assertNotIn("cloudflare_tunnel_token", json.dumps(parsed))

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
        verifications = re.findall(r"\$verify = @'\n(?P<body>.*?)\n'@", self.operator, re.DOTALL)
        body = next((item for item in verifications if "format=$(printf" in item), None)
        self.assertIsNotNone(body)
        self.assertIn('format=$(printf "\\\\173\\\\173.State.Status\\\\175\\\\175 \\\\173\\\\173.State.Health.Status\\\\175\\\\175")', body)
        self.assertNotIn("{{", body)

        bash = shutil.which("bash")
        if os.name == "nt":
            git = shutil.which("git")
            candidates = [Path(git).parent.parent / "bin" / "bash.exe"] if git else []
            bash = next((str(path) for path in candidates if path.is_file()), bash)
        if not bash:
            self.skipTest("Bash is unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            bin_dir = temp / "bin"
            bin_dir.mkdir()
            log_path = temp / "docker-args.jsonl"
            docker_stub = bin_dir / ("docker.cmd" if os.name == "nt" else "docker")
            if os.name == "nt":
                self.skipTest("A POSIX Bash runtime is required to exercise shell argument handling")
            docker_stub.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ $1 == inspect ]]; then\n"
                "  printf '%s\\n' \"$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\")\" >> \"$DOCKER_ARGS_LOG\"\n"
                "  printf 'running healthy\\n'\n"
                "elif [[ $1 == compose ]]; then printf 'NAME STATUS\\n'; fi\n",
                encoding="utf-8",
            )
            docker_stub.chmod(0o755)
            for command in ("ss", "ufw"):
                stub = bin_dir / command
                stub.write_text("#!/usr/bin/env bash\nprintf 'stubbed\\n'\n", encoding="utf-8")
                stub.chmod(0o755)
            shell_script = "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -Eeuo pipefail",
                    "ansible() {",
                    "  local arg= next=",
                    "  while (($#)); do",
                    "    if [[ $1 == -a ]]; then shift; arg=$1; break; fi",
                    "    shift",
                    "  done",
                    "  [[ -n $arg ]] || { echo 'missing Ansible shell argument' >&2; return 2; }",
                    "  bash -c \"$arg\"",
                    "}",
                    body,
                ]
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir.as_posix()}:{env['PATH']}" if os.name == "nt" else f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["DOCKER_ARGS_LOG"] = str(log_path)
            result = subprocess.run([bash, "-c", shell_script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            captured = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[0][:2], ["inspect", "--format"])
            self.assertEqual(captured[0][2], "{{.State.Status}} {{.State.Health.Status}}")


if __name__ == "__main__":
    unittest.main()
