"""
Universal technology stack detector.
Inspects project manifests to determine languages, package managers, and frameworks.
"""
from pathlib import Path
from typing import Any, Dict, List
import json
from .base import BaseDetector


class StackDetector(BaseDetector):
    """Detects languages, frameworks, and tooling in a project-agnostic manner."""

    def detect(self, project_root: Path) -> Dict[str, Any]:
        languages: List[str] = []
        frameworks: List[str] = []
        package_managers: List[str] = []
        manifests_found: List[str] = []

        # Candidate directories to inspect (project root + immediate child directories)
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
            # 1. PHP / Composer
            composer_file = sdir / "composer.json"
            if composer_file.exists():
                languages.append("php")
                package_managers.append("composer")
                manifests_found.append(str(composer_file.relative_to(project_root)).replace("\\", "/"))
                try:
                    data = json.loads(composer_file.read_text(encoding="utf-8"))
                    deps = {**data.get("require", {}), **data.get("require-dev", {})}
                    if "laravel/framework" in deps:
                        frameworks.append("laravel")
                    if "symfony/framework-bundle" in deps or "symfony/symfony" in deps:
                        frameworks.append("symfony")
                except Exception:
                    pass

            # 2. Node / JavaScript / TypeScript
            pkg_file = sdir / "package.json"
            if pkg_file.exists():
                languages.append("javascript")
                manifests_found.append(str(pkg_file.relative_to(project_root)).replace("\\", "/"))
                if (sdir / "tsconfig.json").exists() or (project_root / "tsconfig.json").exists():
                    languages.append("typescript")
                if (sdir / "pnpm-lock.yaml").exists() or (project_root / "pnpm-lock.yaml").exists():
                    package_managers.append("pnpm")
                elif (sdir / "yarn.lock").exists() or (project_root / "yarn.lock").exists():
                    package_managers.append("yarn")
                elif (sdir / "bun.lockb").exists() or (project_root / "bun.lockb").exists():
                    package_managers.append("bun")
                else:
                    package_managers.append("npm")

                try:
                    data = json.loads(pkg_file.read_text(encoding="utf-8"))
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    for name, fw in [
                        ("next", "nextjs"),
                        ("react", "react"),
                        ("vue", "vue"),
                        ("svelte", "svelte"),
                        ("express", "express"),
                        ("fastify", "fastify"),
                        ("nest", "nestjs"),
                    ]:
                        if any(name in dep for dep in deps):
                            frameworks.append(fw)
                except Exception:
                    pass

            # 3. Python
            py_manifests = ["pyproject.toml", "requirements.txt", "Pipfile", "setup.py"]
            found_py_manifests = [m for m in py_manifests if (sdir / m).exists()]
            if found_py_manifests or list(sdir.glob("*.py")):
                languages.append("python")
                manifests_found.extend([str((sdir / m).relative_to(project_root)).replace("\\", "/") for m in found_py_manifests])
                if (sdir / "poetry.lock").exists():
                    package_managers.append("poetry")
                elif (sdir / "Pipfile.lock").exists():
                    package_managers.append("pipenv")
                else:
                    package_managers.append("pip")

                reqs_text = ""
                for mf in found_py_manifests:
                    try:
                        reqs_text += (sdir / mf).read_text(encoding="utf-8").lower() + "\n"
                    except Exception:
                        pass

                for sig, fw in [
                    ("fastapi", "fastapi"),
                    ("django", "django"),
                    ("flask", "flask"),
                    ("langgraph", "langgraph"),
                    ("langchain", "langchain"),
                ]:
                    if sig in reqs_text:
                        frameworks.append(fw)

            # 4. Rust
            cargo_file = sdir / "Cargo.toml"
            if cargo_file.exists():
                languages.append("rust")
                package_managers.append("cargo")
                manifests_found.append(str(cargo_file.relative_to(project_root)).replace("\\", "/"))

            # 5. Go
            go_mod = sdir / "go.mod"
            if go_mod.exists():
                languages.append("go")
                package_managers.append("go")
                manifests_found.append(str(go_mod.relative_to(project_root)).replace("\\", "/"))

        # 6. Container / Orchestration detection
        containers = []
        if (project_root / "Dockerfile").exists():
            containers.append("docker")
        if (project_root / "docker-compose.yml").exists() or (project_root / "docker-compose.yaml").exists():
            containers.append("docker-compose")

        primary_lang = "unknown"
        if "typescript" in languages:
            primary_lang = "typescript"
        elif "php" in languages:
            primary_lang = "php"
        elif languages:
            primary_lang = languages[0]

        return {
            "primary_language": primary_lang,
            "languages": list(dict.fromkeys(languages)),
            "frameworks": list(dict.fromkeys(frameworks)),
            "package_managers": list(dict.fromkeys(package_managers)),
            "manifests": list(dict.fromkeys(manifests_found)),
            "containers": containers,
        }
