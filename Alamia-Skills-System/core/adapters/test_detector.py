"""
Universal test runner detector.
Detects pytest, pest, phpunit, jest, vitest, cargo test, go test, etc.
"""
from pathlib import Path
from typing import Any, Dict, List
import json
from .base import BaseDetector


class TestDetector(BaseDetector):
    """Detects test runners, commands, and test suites."""

    def detect(self, project_root: Path) -> Dict[str, Any]:
        runner = "unknown"
        command = ""
        test_dirs: List[str] = []

        # 1. Look for test directories in root and subdirectories
        search_dirs = [project_root]
        try:
            for child in project_root.iterdir():
                if (
                    child.is_dir()
                    and not child.name.startswith(".")
                    and child.name not in ["vendor", "node_modules", "Alamia-Skills-System", "dist", "build", ".git"]
                ):
                    search_dirs.append(child)
        except Exception:
            pass

        for sdir in search_dirs:
            for d in ["tests", "test", "spec", "specs", "__tests__"]:
                td = sdir / d
                if td.is_dir():
                    test_dirs.append(str(td.relative_to(project_root)).replace("\\", "/"))

        # 2. Node E2E / Test Suite (e.g. tests/e2e/run-all.js or package.json scripts)
        if (project_root / "tests" / "e2e" / "run-all.js").exists():
            runner = "e2e-node"
            command = "node tests/e2e/run-all.js"

        # 3. PHP testing (Pest / PHPUnit)
        if runner == "unknown":
            for sdir in search_dirs:
                if (sdir / "composer.json").exists():
                    if (sdir / "tests" / "Pest.php").exists() or (sdir / "pest.php").exists():
                        runner = "pest"
                        command = f"cd {sdir.name} && ./vendor/bin/pest" if sdir != project_root else "./vendor/bin/pest"
                        break
                    elif (sdir / "phpunit.xml").exists() or (sdir / "phpunit.xml.dist").exists():
                        runner = "phpunit"
                        command = f"cd {sdir.name} && ./vendor/bin/phpunit" if sdir != project_root else "./vendor/bin/phpunit"
                        break

        # 4. Node testing (vitest, jest, playwright, npm test)
        if runner == "unknown":
            for sdir in search_dirs:
                pkg_file = sdir / "package.json"
                if pkg_file.exists():
                    try:
                        pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
                        scripts = pkg_data.get("scripts", {})
                        if "test" in scripts:
                            command = f"cd {sdir.name} && npm test" if sdir != project_root else "npm test"
                            test_script = scripts["test"].lower()
                            if "vitest" in test_script:
                                runner = "vitest"
                            elif "jest" in test_script:
                                runner = "jest"
                            elif "playwright" in test_script:
                                runner = "playwright"
                            else:
                                runner = "npm-test"
                            break
                    except Exception:
                        pass

        # 5. Python testing (pytest, unittest)
        if runner == "unknown":
            for sdir in search_dirs:
                py_test_indicators = [
                    sdir / "pytest.ini",
                    sdir / "conftest.py",
                    sdir / "tests" / "conftest.py",
                    sdir / "setup.cfg",
                    sdir / ".pytest_cache",
                ]
                if any(p.exists() for p in py_test_indicators):
                    runner = "pytest"
                    command = f"cd {sdir.name} && pytest" if sdir != project_root else "pytest"
                    break

        # 6. Rust testing
        if runner == "unknown":
            for sdir in search_dirs:
                if (sdir / "Cargo.toml").exists():
                    runner = "cargo"
                    command = f"cd {sdir.name} && cargo test" if sdir != project_root else "cargo test"
                    break

        # 7. Go testing
        if runner == "unknown":
            for sdir in search_dirs:
                if (sdir / "go.mod").exists():
                    runner = "go"
                    command = f"cd {sdir.name} && go test ./..." if sdir != project_root else "go test ./..."
                    break

        return {
            "runner": runner,
            "command": command,
            "test_dirs": list(dict.fromkeys(test_dirs)),
            "has_tests": len(test_dirs) > 0 or bool(command),
        }
