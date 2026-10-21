"""
Portability and Project-Agnostic Verification Tests for Alamia-Skills-System.
Validates detection and reconciliation across Laravel, Node, Fresh, and Python stacks.
"""
import tempfile
import json
from pathlib import Path
import sys

# Add core to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from engine import ProjectStateEngine
from reconciler import ProjectReconciler


def test_laravel_discovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create mock Laravel project
        composer_data = {
            "name": "company/laravel-app",
            "require": {"php": "^8.2", "laravel/framework": "^11.0"},
            "require-dev": {"pestphp/pest": "^3.0"}
        }
        (root / "composer.json").write_text(json.dumps(composer_data), encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "Pest.php").write_text("<?php // pest test", encoding="utf-8")
        (root / "docs").mkdir()
        (root / "docs" / "handoffs").mkdir()
        (root / "docs" / "handoffs" / "01-sprint-handoff.md").write_text(
            "# Sprint 01 Handoff\n\n## Next Session Objectives\n- [ ] Migrate Auth to Sanctum\n",
            encoding="utf-8"
        )

        engine = ProjectStateEngine(root)
        state = engine.inspect()

        assert state["stack"]["primary_language"] == "php"
        assert "laravel" in state["stack"]["frameworks"]
        assert state["stack"]["package_managers"] == ["composer"]
        assert state["testing"]["runner"] == "pest"
        assert state["testing"]["command"] == "./vendor/bin/pest"
        assert state["memory"]["has_memory_system"] is True
        assert state["memory"]["handoff_dir"] == "docs/handoffs"
        assert "Migrate Auth to Sanctum" in state["memory"]["latest_handoff"]["pending_items"][0]
        print("[PASS] Laravel project discovery verified successfully!")


def test_node_nextjs_discovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create mock Next.js / TypeScript project
        pkg_data = {
            "name": "my-web-app",
            "scripts": {"test": "vitest run"},
            "dependencies": {"next": "^14.0.0", "react": "^18.0.0"},
            "devDependencies": {"vitest": "^1.0.0"}
        }
        (root / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")
        (root / "tsconfig.json").write_text("{}", encoding="utf-8")
        (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")

        engine = ProjectStateEngine(root)
        state = engine.inspect()

        assert "typescript" in state["stack"]["languages"]
        assert "nextjs" in state["stack"]["frameworks"]
        assert "pnpm" in state["stack"]["package_managers"]
        assert state["testing"]["runner"] == "vitest"
        assert state["testing"]["command"] == "npm test"
        print("[PASS] Next.js / TypeScript discovery verified successfully!")


def test_fresh_project_case_a():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        engine = ProjectStateEngine(root)
        state = engine.inspect()

        assert state["case_classification"]["case"] == "Case A"
        print("[PASS] Fresh project (Case A) verified successfully!")


def test_reconciler_idempotency():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

        reconciler = ProjectReconciler(root)
        res1 = reconciler.reconcile()
        assert res1["final_case"]["case"] == "Case D"
        assert (root / ".alamia" / "project.json").exists()

        # Run second time
        res2 = reconciler.reconcile()
        assert res2["final_case"]["case"] == "Case D"
        assert ".alamia/project.json is already up to date." in res2["actions_taken"]
        print("[PASS] Reconciler idempotency verified successfully!")


def test_monorepo_discovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        backend = root / "backend"
        backend.mkdir()
        composer_data = {
            "name": "company/backend-api",
            "require": {"php": "^8.2", "laravel/framework": "^11.0"}
        }
        (backend / "composer.json").write_text(json.dumps(composer_data), encoding="utf-8")
        (backend / "phpunit.xml").write_text("<phpunit></phpunit>", encoding="utf-8")

        frontend = root / "frontend"
        frontend.mkdir()
        pkg_data = {
            "name": "frontend-ui",
            "dependencies": {"next": "^14.0.0", "react": "^18.0.0"}
        }
        (frontend / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")
        (frontend / "tsconfig.json").write_text("{}", encoding="utf-8")

        engine = ProjectStateEngine(root)
        state = engine.inspect()

        assert "php" in state["stack"]["languages"]
        assert "typescript" in state["stack"]["languages"]
        assert "laravel" in state["stack"]["frameworks"]
        assert "nextjs" in state["stack"]["frameworks"]
        assert "composer" in state["stack"]["package_managers"]
        assert "npm" in state["stack"]["package_managers"]
        assert state["testing"]["runner"] == "phpunit"
        print("[PASS] Monorepo / multi-directory project discovery verified successfully!")


def test_agent_pm_skills_registration():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name": "test-app"}', encoding="utf-8")

        reconciler = ProjectReconciler(root)
        reconciler.reconcile()

        skills_json = root / ".agents" / "skills.json"
        assert skills_json.exists()
        cfg = json.loads(skills_json.read_text(encoding="utf-8"))
        paths = [e["path"] for e in cfg.get("entries", [])]
        assert any("agent-pm" in p for p in paths)
        print("[PASS] Vendored agent-pm registration in skills.json verified successfully!")



def test_persistent_operational_tooling_skill_registration():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name": "tooling-skill-test"}', encoding="utf-8")

        reconciler = ProjectReconciler(root)
        reconciler.reconcile()

        skills_json = root / ".agents" / "skills.json"
        assert skills_json.exists()
        cfg = json.loads(skills_json.read_text(encoding="utf-8"))
        paths = [e["path"] for e in cfg.get("entries", [])]
        assert any("persistent-operational-tooling" in p for p in paths)
        assert any("dag-task-planning" in p for p in paths)
        assert {"path": "local/custom-skill"} not in cfg.get("entries", [])
        print("[PASS] Persistent operational tooling skill registration verified successfully!")


def test_reconciler_preserves_custom_project_settings_and_skill_entries():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name":"custom-app"}', encoding="utf-8")
        alamia = root / ".alamia"
        alamia.mkdir()
        (alamia / "project.json").write_text(json.dumps({
            "custom_setting": {"keep": True},
            "memory": {"custom_handoff_policy": "manual"},
            "lifecycle": {"custom_group": "preserve"},
        }), encoding="utf-8")
        agents = root / ".agents"
        agents.mkdir()
        (agents / "skills.json").write_text(json.dumps({
            "custom_metadata": "preserve",
            "entries": [{"path": "local/custom-skill"}],
        }), encoding="utf-8")

        ProjectReconciler(root).reconcile()
        profile = json.loads((alamia / "project.json").read_text(encoding="utf-8"))
        skills = json.loads((agents / "skills.json").read_text(encoding="utf-8"))

        assert profile["custom_setting"] == {"keep": True}
        assert profile["memory"]["custom_handoff_policy"] == "manual"
        assert profile["lifecycle"]["custom_group"] == "preserve"
        assert skills["custom_metadata"] == "preserve"
        assert {"path": "local/custom-skill"} in skills["entries"]


def test_invalid_project_profile_is_backed_up_before_repair():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name":"repair-app"}', encoding="utf-8")
        alamia = root / ".alamia"
        alamia.mkdir()
        original = "{invalid json"
        (alamia / "project.json").write_text(original, encoding="utf-8")

        ProjectReconciler(root).reconcile()

        assert (alamia / "project.json.bak").read_text(encoding="utf-8") == original
        repaired = json.loads((alamia / "project.json").read_text(encoding="utf-8"))
        assert repaired["schema_version"] == 1
        assert repaired["system_version"] == "0.2.0"


def test_state_engine_classifies_outdated_profile_as_case_e():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name":"outdated-app"}', encoding="utf-8")
        agents_skills = root / ".agents" / "skills"
        for name in ["bootstrap", "implement", "qa", "architecture-review", "session-end"]:
            skill_dir = agents_skills / name
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"---\\nname: {name}\\n---\\n", encoding="utf-8")
        alamia = root / ".alamia"
        alamia.mkdir()
        (alamia / "project.json").write_text(json.dumps({
            "schema_version": 0,
            "system_version": "0.1.0",
            "lifecycle": {"groups": ["bootstrap", "implement", "qa", "architecture-review", "session-end"]},
        }), encoding="utf-8")

        state = ProjectStateEngine(root).inspect()
        assert state["case_classification"]["case"] == "Case E"
        assert "outdated" in state["case_classification"]["description"].lower()


if __name__ == "__main__":
    test_laravel_discovery()
    test_node_nextjs_discovery()
    test_fresh_project_case_a()
    test_monorepo_discovery()
    test_reconciler_idempotency()
    test_agent_pm_skills_registration()
    test_persistent_operational_tooling_skill_registration()
    test_reconciler_preserves_custom_project_settings_and_skill_entries()
    test_invalid_project_profile_is_backed_up_before_repair()
    test_state_engine_classifies_outdated_profile_as_case_e()
    print("\nALL PORTABILITY TESTS PASSED!")
