"""Deterministic, evidence-only repository scanner. No LLM calls here.

Everything returned is plain, JSON-serializable Python so it can be dropped
straight into an LLM prompt and rendered into the report appendix. File
paths are always recorded relative to the scanned repo root.
"""

import ast
import json
import os
import re

EXCLUDED_DIRS = {
    ".git", ".venv", "venv", ".idea", "__pycache__", "node_modules",
    ".pytest_cache", "dist", "build", ".mypy_cache",
    "reports",  # this tool's own generated output — never treat it as source evidence
}

LANGUAGE_BY_EXT = {
    ".py": "Python", ".md": "Markdown", ".txt": "Text",
    ".toml": "Config", ".cfg": "Config", ".ini": "Config",
    ".yml": "YAML", ".yaml": "YAML", ".json": "JSON", ".sh": "Shell",
    ".js": "JavaScript", ".ts": "TypeScript", ".java": "Java",
    ".go": "Go", ".rb": "Ruby",
}

FRAMEWORK_MARKERS = {
    "langgraph", "langchain", "langchain_core", "langchain_google_genai",
    "langfuse", "dotenv", "flask", "django", "fastapi", "streamlit",
}

INTEGRATION_MARKERS = {
    "database": {"sqlite3", "psycopg2", "sqlalchemy", "pymongo", "redis"},
    "external_sdks": {"langchain_google_genai", "langfuse", "openai", "anthropic"},
    "http_clients": {"requests", "httpx"},
}

DEPLOYMENT_CHECKS = [
    ("Dockerfile", "Dockerfile"),
    ("Procfile", "Procfile"),
    ("render.yaml", "render.yaml"),
]
DOCKER_COMPOSE_FILENAMES = ["docker-compose.yml", "docker-compose.yaml"]


def _iter_files(repo_path: str):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for name in files:
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, repo_path)
            yield rel_path, abs_path


def _read_text(abs_path: str):
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _scan_languages_and_content(repo_path: str, parse_errors: list):
    """Single pass: language/LOC stats, plus cached (rel_path, content) for .py files."""
    languages = {}
    loc_by_file = {}
    py_sources = {}

    for rel_path, abs_path in _iter_files(repo_path):
        ext = os.path.splitext(rel_path)[1].lower()
        language = LANGUAGE_BY_EXT.get(ext)
        if language is None:
            continue
        content = _read_text(abs_path)
        if content is None:
            parse_errors.append(f"Could not read file: {rel_path}")
            continue
        loc = sum(1 for line in content.splitlines() if line.strip())
        bucket = languages.setdefault(language, {"files": 0, "loc": 0})
        bucket["files"] += 1
        bucket["loc"] += loc
        loc_by_file[rel_path] = loc
        if ext == ".py":
            py_sources[rel_path] = content

    return languages, loc_by_file, py_sources


def _parse_python_imports(py_sources: dict, parse_errors: list):
    """Returns {rel_path: [(module_name, lineno), ...]} and per-file ast.Try node lists."""
    imports_by_file = {}
    trees_by_file = {}
    for rel_path, content in py_sources.items():
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError as exc:
            parse_errors.append(f"Could not parse Python file {rel_path}: {exc}")
            continue
        trees_by_file[rel_path] = tree
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    hits.append((alias.name.split(".")[0], node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module:
                hits.append((node.module.split(".")[0], node.lineno))
        imports_by_file[rel_path] = hits
    return imports_by_file, trees_by_file


def _detect_frameworks(imports_by_file: dict):
    frameworks = {}
    for rel_path, hits in imports_by_file.items():
        for module_name, lineno in hits:
            if module_name in FRAMEWORK_MARKERS:
                frameworks.setdefault(module_name, []).append(f"{rel_path}:{lineno}")
    return frameworks


def _detect_integrations(imports_by_file: dict):
    integrations = {category: {} for category in INTEGRATION_MARKERS}
    for rel_path, hits in imports_by_file.items():
        for module_name, lineno in hits:
            for category, markers in INTEGRATION_MARKERS.items():
                if module_name in markers:
                    integrations[category].setdefault(module_name, []).append(f"{rel_path}:{lineno}")
    return integrations


def _detect_dependencies(repo_path: str, frameworks: dict):
    declared = []
    source_file = None
    requirements_path = os.path.join(repo_path, "requirements.txt")
    if os.path.isfile(requirements_path):
        source_file = "requirements.txt"
        with open(requirements_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name = re.split(r"[<>=!~\[]", line)[0].strip()
                if name:
                    declared.append(name)

    normalized_declared = {name.lower().replace("-", "_") for name in declared}
    declared_but_not_directly_imported = sorted(
        name for name in declared
        if name.lower().replace("-", "_") not in frameworks
    )

    return {
        "declared": declared,
        "source_file": source_file,
        "declared_but_not_directly_imported": declared_but_not_directly_imported,
    }


def _detect_deployment(repo_path: str):
    found = {}
    gaps = []
    for filename, label in DEPLOYMENT_CHECKS:
        exists = os.path.isfile(os.path.join(repo_path, filename))
        found[filename] = exists
        if not exists:
            gaps.append(f"No {label} found")

    docker_compose_exists = any(
        os.path.isfile(os.path.join(repo_path, filename)) for filename in DOCKER_COMPOSE_FILENAMES
    )
    for filename in DOCKER_COMPOSE_FILENAMES:
        found[filename] = os.path.isfile(os.path.join(repo_path, filename))
    if not docker_compose_exists:
        gaps.append("No docker-compose file found")

    workflows_dir = os.path.join(repo_path, ".github", "workflows")
    has_workflows = os.path.isdir(workflows_dir) and any(os.scandir(workflows_dir))
    found[".github/workflows"] = has_workflows
    if not has_workflows:
        gaps.append("No CI/CD workflow found under .github/workflows")

    return {"found": found, "gaps": gaps}


def _detect_tests(repo_path: str):
    test_files = []
    for rel_path, _abs_path in _iter_files(repo_path):
        base = os.path.basename(rel_path)
        if base.startswith("test_") and base.endswith(".py"):
            test_files.append(rel_path)
        elif base.endswith("_test.py"):
            test_files.append(rel_path)

    result = {"test_files": test_files, "count": len(test_files)}
    if not test_files:
        result["gap"] = "No test files found (tests/ directory, if present, contains no test files)"
    return result


def _detect_hotspots(loc_by_file: dict, py_sources: dict, trees_by_file: dict):
    largest_files = sorted(
        ({"path": path, "loc": loc} for path, loc in loc_by_file.items()),
        key=lambda entry: entry["loc"],
        reverse=True,
    )[:5]

    todo_fixme_hits = []
    for rel_path, content in py_sources.items():
        for lineno, line in enumerate(content.splitlines(), start=1):
            if "TODO" in line or "FIXME" in line:
                todo_fixme_hits.append(f"{rel_path}:{lineno}")

    bare_except_hits = []
    for rel_path, tree in trees_by_file.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.type is None:
                        bare_except_hits.append(f"{rel_path}:{handler.lineno}")

    return {
        "largest_files": largest_files,
        "todo_fixme_count": len(todo_fixme_hits),
        "todo_fixme_locations": todo_fixme_hits,
        "bare_except_count": len(bare_except_hits),
        "bare_except_locations": bare_except_hits,
    }


def _local_packages(repo_path: str):
    """Top-level directories that are real Python packages (contain __init__.py)."""
    packages = set()
    for entry in os.scandir(repo_path):
        if entry.is_dir() and entry.name not in EXCLUDED_DIRS:
            if os.path.isfile(os.path.join(entry.path, "__init__.py")):
                packages.add(entry.name)
    return packages


def _coupling_candidates(tree, local_packages: set):
    """Candidate local module names referenced by a file's imports.

    Only follows dotted segments/alias names into a local package (e.g.
    "adlc_engineer.llm" -> "llm") — third-party dotted imports (e.g.
    "langgraph.graph") are never expanded, so a local module can't be
    falsely matched just because a third-party submodule shares its name.
    """
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            segments = node.module.split(".")
            if segments[0] in local_packages:
                candidates.extend(segments[1:])
                candidates.extend(alias.name for alias in node.names)
            elif len(segments) == 1:
                candidates.append(segments[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                segments = alias.name.split(".")
                if segments[0] in local_packages:
                    candidates.extend(segments[1:])
                elif len(segments) == 1:
                    candidates.append(segments[0])
    return candidates


def _detect_coupling(trees_by_file: dict, py_sources: dict, repo_path: str):
    local_modules = {
        os.path.splitext(os.path.basename(path))[0] for path in py_sources
    }
    local_packages = _local_packages(repo_path)
    edges = {}
    for rel_path, tree in trees_by_file.items():
        own_name = os.path.splitext(os.path.basename(rel_path))[0]
        targets = {
            name for name in _coupling_candidates(tree, local_packages)
            if name in local_modules and name != own_name
        }
        if targets:
            edges[rel_path] = sorted(targets)
    return edges


def _detect_architecture_pattern(frameworks: dict, py_sources: dict):
    if "langgraph" in frameworks:
        for rel_path, content in py_sources.items():
            if "StateGraph(" in content:
                return {
                    "pattern": "graph-orchestrated agent workflow",
                    "evidence": ["frameworks.langgraph", f"{rel_path} (StateGraph usage)"],
                }
    if "flask" in frameworks or "fastapi" in frameworks or "django" in frameworks:
        return {"pattern": "web service", "evidence": ["frameworks"]}
    return {"pattern": "undetermined from evidence", "evidence": []}


def scan_repository(repo_path: str, display_name: str) -> dict:
    parse_errors = []

    languages, loc_by_file, py_sources = _scan_languages_and_content(repo_path, parse_errors)
    imports_by_file, trees_by_file = _parse_python_imports(py_sources, parse_errors)

    frameworks = _detect_frameworks(imports_by_file)
    integrations = _detect_integrations(imports_by_file)
    dependencies = _detect_dependencies(repo_path, frameworks)
    deployment = _detect_deployment(repo_path)
    tests = _detect_tests(repo_path)
    hotspots = _detect_hotspots(loc_by_file, py_sources, trees_by_file)
    coupling = _detect_coupling(trees_by_file, py_sources, repo_path)
    architecture_pattern_guess = _detect_architecture_pattern(frameworks, py_sources)

    evidence = {
        "repo_meta": {
            "source": display_name,
            "type": "git_url" if display_name != repo_path else "local_path",
        },
        "languages": languages,
        "frameworks": frameworks,
        "dependencies": dependencies,
        "deployment": deployment,
        "integrations": integrations,
        "tests": tests,
        "hotspots": hotspots,
        "coupling": coupling,
        "architecture_pattern_guess": architecture_pattern_guess,
        "parse_errors": parse_errors,
    }

    json.dumps(evidence)  # fail fast here if anything isn't JSON-serializable
    return evidence
