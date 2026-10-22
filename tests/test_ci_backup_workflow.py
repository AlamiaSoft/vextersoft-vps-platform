from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "pr-safety.yml"


class CiBackupWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.workflow = yaml.safe_load(self.raw)

    def test_backup_restore_smoke_job_exists_and_uses_shared_helper(self) -> None:
        jobs = self.workflow.get("jobs", {})
        self.assertIn("backup-restore-smoke", jobs)
        job = jobs["backup-restore-smoke"]
        self.assertEqual(job.get("runs-on"), "ubuntu-latest")

        steps = job.get("steps", [])
        run_scripts = "\n".join(step.get("run", "") for step in steps if "run" in step)

        self.assertIn("python scripts/portainer_backup.py backup", run_scripts)
        self.assertIn("python scripts/portainer_backup.py verify-archive", run_scripts)
        self.assertIn("python scripts/portainer_backup.py restore-sandbox", run_scripts)
        self.assertIn("InstanceID", run_scripts)

    def test_workflow_never_publishes_host_ports_and_has_always_cleanup(self) -> None:
        jobs = self.workflow.get("jobs", {})
        job = jobs["backup-restore-smoke"]
        steps = job.get("steps", [])

        for step in steps:
            script = step.get("run", "")
            self.assertNotIn("-p 9000", script)
            self.assertNotIn("-p 9443", script)
            self.assertNotIn("0.0.0.0:", script)

        always_steps = [s for s in steps if s.get("if") == "always()"]
        self.assertGreaterEqual(len(always_steps), 2)
        always_scripts = "\n".join(s.get("run", "") for s in always_steps)
        self.assertIn("docker rm -f", always_scripts)
        self.assertIn("docker volume rm -f", always_scripts)
        self.assertIn("GITHUB_STEP_SUMMARY", always_scripts)
        self.assertIn("ephemeral GitHub-hosted runner only", always_scripts)


if __name__ == "__main__":
    unittest.main()
