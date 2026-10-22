from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOVER_RUNBOOK = ROOT / "docs" / "devops-handover-runbook.md"
CLOUDFLARE_RUNBOOK = ROOT / "docs" / "cloudflare-portainer-runbook.md"


class BackupRunbookSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handover = HANDOVER_RUNBOOK.read_text(encoding="utf-8")
        self.cf_runbook = CLOUDFLARE_RUNBOOK.read_text(encoding="utf-8")

    def test_handover_runbook_uses_shared_helper_and_removes_unsafe_patterns(self) -> None:
        self.assertIn("scripts/portainer_backup.py backup", self.handover)
        self.assertIn("scripts/portainer_backup.py verify-archive", self.handover)
        self.assertIn("scripts/portainer_backup.py restore-sandbox", self.handover)

        # Must never recommend unguarded rm -rf inside a volume or rely on undefined $TARGET_HOST
        self.assertNotIn("rm -rf /target/*", self.handover)
        self.assertNotIn("$TARGET_HOST", self.handover)

    def test_handover_runbook_explains_ro_consistency_and_scope_limits(self) -> None:
        self.assertIn("Why `:ro` Alone Does Not Guarantee Database Consistency", self.handover)
        self.assertIn("try...finally", self.handover)
        self.assertIn("What is NOT backed up by this archive", self.handover)
        self.assertIn("PRODUCTION-DESTRUCTIVE", self.handover)
        self.assertIn("ephemeral GitHub-hosted runner", self.handover)

    def test_cloudflare_runbook_references_shared_backup_helper(self) -> None:
        self.assertIn("scripts/portainer_backup.py", self.cf_runbook)


if __name__ == "__main__":
    unittest.main()
