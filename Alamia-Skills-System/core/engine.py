"""Project state discovery and lifecycle health classification."""
from pathlib import Path
from typing import Any, Dict
import json
import subprocess

try:
    from .adapters import StackDetector, TestDetector, MemoryDetector, AgentDetector
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from adapters import StackDetector, TestDetector, MemoryDetector, AgentDetector

CORE_LIFECYCLE_GROUPS = [
    "bootstrap", "implement", "qa", "architecture-review", "session-end",
]
PROFILE_SCHEMA_VERSION = 1
SYSTEM_VERSION = "0.2.0"


class ProjectStateEngine:
    """Inspect a repository and classify its lifecycle infrastructure."""

    def __init__(self, project_root: Path = None):
        self.project_root = (project_root or Path.cwd()).resolve()
        self.stack_detector = StackDetector()
        self.test_detector = TestDetector()
        self.memory_detector = MemoryDetector()
        self.agent_detector = AgentDetector()

    def inspect(self) -> Dict[str, Any]:
        stack_info = self.stack_detector.detect(self.project_root)
        test_info = self.test_detector.detect(self.project_root)
        memory_info = self.memory_detector.detect(self.project_root)
        agent_info = self.agent_detector.detect(self.project_root)
        git_info = self._get_git_info()

        config_path = self.project_root / ".alamia" / "project.json"
        has_config = config_path.exists()
        configured_profile = None
        config_error = None
        if has_config:
            try:
                configured_profile = json.loads(config_path.read_text(encoding="utf-8"))
                if not isinstance(configured_profile, dict):
                    config_error = "Project profile must be a JSON object."
            except (OSError, json.JSONDecodeError) as exc:
                config_error = f"Project profile is unreadable or invalid JSON: {exc}"

        classification = self._classify_state(
            stack_info, agent_info, configured_profile, has_config, config_error
        )
        return {
            "project_name": self.project_root.name,
            "project_root": str(self.project_root).replace("\\", "/"),
            "case_classification": classification,
            "git": git_info,
            "stack": stack_info,
            "testing": test_info,
            "memory": memory_info,
            "agent_infrastructure": agent_info,
            "alamia_configured": has_config,
            "configured_profile": configured_profile,
            "profile_error": config_error,
            "missing_lifecycle_skills": [
                skill for skill in CORE_LIFECYCLE_GROUPS
                if skill not in agent_info["installed_skills"]
            ],
        }

    def _get_git_info(self) -> Dict[str, Any]:
        if not (self.project_root / ".git").exists():
            return {
                "is_git": False, "branch": None, "latest_commit": None,
                "is_dirty": False, "uncommitted_lines": 0,
            }
        try:
            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=self.project_root,
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()

            branch = git("branch", "--show-current")
            commit = git("log", "-1", "--oneline")
            status = git("status", "--porcelain")
            return {
                "is_git": True,
                "branch": branch or "HEAD detached",
                "latest_commit": commit or None,
                "is_dirty": bool(status),
                "uncommitted_lines": len(status.splitlines()) if status else 0,
            }
        except (OSError, subprocess.CalledProcessError):
            return {
                "is_git": True, "branch": "unknown", "latest_commit": "unknown",
                "is_dirty": False, "uncommitted_lines": 0,
            }

    def _classify_state(
        self, stack_info: Dict[str, Any], agent_info: Dict[str, Any],
        configured_profile: Any = None, has_config: bool = False,
        config_error: str = None,
    ) -> Dict[str, str]:
        installed = set(agent_info["installed_skills"])
        required = set(CORE_LIFECYCLE_GROUPS)
        is_fresh = not stack_info["manifests"] and not stack_info["languages"]

        if is_fresh and not installed:
            return {"case": "Case A", "description": "Fresh project with no existing code or agent infrastructure."}
        if not installed:
            return {"case": "Case B", "description": "Existing project with code but no lifecycle skill infrastructure."}

        missing = required - installed
        if missing:
            return {
                "case": "Case C",
                "description": f"Partially configured project (missing skills: {', '.join(sorted(missing))}).",
            }
        if not has_config:
            return {"case": "Case C", "description": "Lifecycle skills exist, but .alamia/project.json is missing."}
        if config_error:
            return {"case": "Case E", "description": f"Project profile needs repair: {config_error}"}

        if not isinstance(configured_profile, dict):
            return {"case": "Case E", "description": "Project profile is not a JSON object."}

        schema_version = configured_profile.get("schema_version")
        system_version = configured_profile.get("system_version")
        if schema_version != PROFILE_SCHEMA_VERSION or system_version != SYSTEM_VERSION:
            return {
                "case": "Case E",
                "description": (
                    "Project profile is outdated "
                    f"(schema {schema_version!r}, system {system_version!r}; "
                    f"expected schema {PROFILE_SCHEMA_VERSION}, system {SYSTEM_VERSION})."
                ),
            }

        lifecycle = configured_profile.get("lifecycle", {})
        configured_groups = set(lifecycle.get("groups", [])) if isinstance(lifecycle, dict) else set()
        if not required.issubset(configured_groups):
            return {"case": "Case E", "description": "Project profile lifecycle configuration is incomplete or inconsistent."}

        return {"case": "Case D", "description": "Configured project with current profile and required lifecycle skills."}


if __name__ == "__main__":
    print(json.dumps(ProjectStateEngine().inspect(), indent=2))
