"""Regression tests for registration of the DAG task-planning skill."""
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
from reconciler import ProjectReconciler


def test_dag_task_planning_skill_is_registered():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name":"dag-skill-test"}', encoding="utf-8")

        reconciler = ProjectReconciler(root)
        reconciler.reconcile()

        skills_json = root / ".agents" / "skills.json"
        assert skills_json.exists()
        config = json.loads(skills_json.read_text(encoding="utf-8"))
        paths = [entry.get("path", "") for entry in config.get("entries", [])]
        assert any(path.replace("\\", "/").endswith("/skills/dag-task-planning") for path in paths)
