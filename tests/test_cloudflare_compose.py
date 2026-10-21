import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "ansible" / "templates"
TEMPLATE_NAME = "cloudflared-portainer.compose.yml.j2"


def render_compose(public_routes, secret_path="/opt/vextersoft/management/secrets/tunnel-token"):
    environment = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False)
    template = environment.get_template(TEMPLATE_NAME)
    rendered = template.render(
        cloudflare_portainer_image="portainer/portainer-ce:2.45.1",
        cloudflare_tunnel_image="cloudflare/cloudflared:2026.10.2",
        cloudflare_tunnel_secret_path=secret_path,
        cloudflare_portainer_volume="vextersoft_portainer_data",
        cloudflare_management_network="vextersoft-management",
        cloudflare_tunnel_egress_network="vextersoft-tunnel-egress",
        cloudflare_public_routes=public_routes,
    )
    return yaml.safe_load(rendered)


class CloudflareComposeTests(unittest.TestCase):
    def test_management_services_have_no_host_published_ports(self):
        compose = render_compose([])
        self.assertEqual(set(compose["services"]), {"portainer", "cloudflared"})
        for service in compose["services"].values():
            self.assertNotIn("ports", service)
        self.assertEqual(compose["services"]["portainer"]["networks"], ["management"])
        self.assertEqual(
            compose["services"]["cloudflared"]["networks"],
            ["management", "tunnel_egress"],
        )

    def test_portainer_data_and_docker_socket_are_explicit(self):
        compose = render_compose([])
        portainer = compose["services"]["portainer"]
        self.assertIn("portainer_data:/data", portainer["volumes"])
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", portainer["volumes"])
        self.assertEqual(compose["volumes"]["portainer_data"]["name"], "vextersoft_portainer_data")
        self.assertTrue(compose["volumes"]["portainer_data"]["external"])

    def test_tunnel_uses_file_secret_and_pinned_image(self):
        compose = render_compose([])
        tunnel = compose["services"]["cloudflared"]
        self.assertEqual(tunnel["image"], "cloudflare/cloudflared:2026.10.2")
        self.assertEqual(tunnel["user"], "65532:65532")
        self.assertIn("cloudflare_tunnel_token", tunnel["secrets"])
        self.assertIn("--token-file", tunnel["command"])
        self.assertNotIn("environment", tunnel)
        self.assertEqual(
            compose["secrets"]["cloudflare_tunnel_token"]["file"],
            "/opt/vextersoft/management/secrets/tunnel-token",
        )

    def test_public_application_networks_are_opt_in_and_isolated(self):
        compose = render_compose(
            [
                {
                    "hostname": "app.example.com",
                    "network": "app_frontend",
                    "service": "web",
                    "port": 8080,
                }
            ]
        )
        self.assertEqual(
            compose["services"]["cloudflared"]["networks"],
            ["management", "tunnel_egress", "app_1"],
        )
        self.assertEqual(compose["networks"]["app_1"]["name"], "app_frontend")
        self.assertNotIn("app_1", compose["services"]["portainer"]["networks"])
        self.assertNotIn("ports", compose["services"]["cloudflared"])
        self.assertNotIn("ports", compose["services"]["portainer"])

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI is unavailable")
    def test_rendered_compose_passes_docker_compose_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            secret_path = temporary_path / "tunnel-token"
            secret_path.write_text("placeholder-test-token\\n")
            compose_path = temporary_path / "compose.yml"
            compose_path.write_text(
                yaml.safe_dump(
                    render_compose([], secret_path=str(secret_path)),
                    sort_keys=False,
                )
            )
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose_path), "config", "--quiet"],
                capture_output=True,
                text=True,
                check=False,
            )
            if "could not be found in this WSL 2 distro" in result.stdout:
                self.skipTest("Docker Desktop WSL integration is disabled in this distro")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
