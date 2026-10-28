"""Deterministic code-health checks (spec 0004). No LLM, no network.

Pure functions over data the scanner has already gathered, except `tracked_files`
and `find_tracked_sensitive_files`, which ask git. Every result is sorted and size-bounded
so two runs on an unchanged repository produce identical evidence.
"""

import ast
import os
import re
import subprocess

COMPLEXITY_THRESHOLD = 10
MAX_LISTED = {"secrets": 20, "complexity": 10, "untested": 30, "unused_imports": 20}

LOCKFILES = ("poetry.lock", "Pipfile.lock", "uv.lock", "pdm.lock", "requirements.lock")

# ---------------------------------------------------------------- dependencies


def is_requirement_line(line: str) -> bool:
    """A real requirement: not blank, not a comment, not an option such as -r/-e/--index-url."""
    line = line.strip()
    return bool(line) and not line.startswith(("#", "-"))


def requirement_name(line: str) -> str:
    return re.split(r"[<>=!~\[;@\s]", line.strip(), maxsplit=1)[0]


def is_pinned(line: str) -> bool:
    """Pinned means an exact `==` version; `==1.*` and ranges are not."""
    spec = line.split("#", 1)[0].split(";", 1)[0]
    return "==" in spec and "*" not in spec


def has_lockfile(repo_path: str) -> bool:
    return any(os.path.isfile(os.path.join(repo_path, name)) for name in LOCKFILES)


# --------------------------------------------------------------------- secrets

# (kind, pattern). Only formats specific enough to be credible without context, plus one
# quoted-assignment pattern that is filtered further below.
SECRET_PATTERNS = [
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
]
ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)\b(?:api[_-]?key|secret(?:[_-]?key)?|token|passw(?:or)?d)\b\s*[:=]\s*(['"])([^'"\s]{12,})\1"""
)
PLACEHOLDER_MARKERS = (
    "your", "example", "changeme", "placeholder", "xxxx", "****", "<", "${", "{{", "todo",
    "dummy", "sample", "redacted",
)
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
SENSITIVE_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json"}
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
MAX_SCAN_BYTES = 1_000_000


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


def _mask(value: str) -> str:
    """Never keep a whole secret: first four characters and the length only."""
    return f"{value[:4]}… ({len(value)} chars)"


def scan_text_for_secrets(rel_path: str, content: str) -> list:
    findings = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if kind != "Private key block" and _is_placeholder(value):
                    continue
                preview = "-----BEGIN … PRIVATE KEY-----" if kind == "Private key block" else _mask(value)
                findings.append({"path": rel_path, "line": lineno, "kind": kind, "preview": preview})
        for match in ASSIGNMENT_PATTERN.finditer(line):
            value = match.group(2)
            # Mixed letters and digits: skips prose and identifiers like "my_function_name".
            if _is_placeholder(value) or not (any(c.isdigit() for c in value) and any(c.isalpha() for c in value)):
                continue
            findings.append({"path": rel_path, "line": lineno, "kind": "Hard-coded credential",
                             "preview": _mask(value)})
    return findings


def tracked_files(repo_path: str):
    """Relative paths git tracks, or None when repo_path is not a git repository."""
    if not os.path.exists(os.path.join(repo_path, ".git")):
        return None
    try:
        out = subprocess.run(["git", "-C", repo_path, "ls-files", "-z"],
                             check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return {os.path.normpath(p) for p in out.decode("utf-8", "replace").split("\0") if p}


def is_sensitive_filename(rel_path: str) -> bool:
    base = os.path.basename(rel_path)
    if base == ".env" or (base.startswith(".env.") and not base.endswith(ENV_TEMPLATE_SUFFIXES)):
        return True
    return base in SENSITIVE_NAMES or base.endswith(SENSITIVE_SUFFIXES)


def find_secrets(files, read_text, tracked, excluded_dirs) -> dict:
    """files: iterable of (rel_path, abs_path). When `tracked` is a set, only tracked
    files are scanned and only tracked sensitive filenames are reported; otherwise
    (a plain directory) every non-excluded file is scanned."""
    findings, sensitive = [], []
    for rel_path, abs_path in files:
        if set(rel_path.split(os.sep)) & excluded_dirs:
            continue
        if tracked is not None and os.path.normpath(rel_path) not in tracked:
            continue
        if is_sensitive_filename(rel_path) and tracked is not None:
            sensitive.append(rel_path)
        try:
            if os.path.getsize(abs_path) > MAX_SCAN_BYTES:
                continue
        except OSError:
            continue
        content = read_text(abs_path)
        if content is not None:
            findings.extend(scan_text_for_secrets(rel_path, content))
    findings.sort(key=lambda f: (f["path"], f["line"], f["kind"]))
    limit = MAX_LISTED["secrets"]
    return {
        "count": len(findings) + len(sensitive),
        "findings": findings[:limit],
        "tracked_sensitive_files": sorted(sensitive),
    }


# ------------------------------------------------------------------ complexity

_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_BRANCHES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler)


def cyclomatic_complexity(func) -> int:
    count = 1
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, _NESTED_SCOPES):
            continue  # measured on its own
        if isinstance(node, _BRANCHES):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            count += 1 + len(node.ifs)
        elif isinstance(node, getattr(ast, "match_case", ())):
            count += 1
        stack.extend(ast.iter_child_nodes(node))
    return count


def find_complex_functions(trees_by_file: dict, threshold: int = COMPLEXITY_THRESHOLD) -> dict:
    found = []
    for rel_path, tree in trees_by_file.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = cyclomatic_complexity(node)
                if complexity >= threshold:
                    found.append({
                        "path": rel_path, "name": node.name, "line": node.lineno,
                        "complexity": complexity, "lines": node.end_lineno - node.lineno + 1,
                    })
    found.sort(key=lambda f: (-f["complexity"], f["path"], f["line"]))
    return {"threshold": threshold, "count": len(found), "functions": found[:MAX_LISTED["complexity"]]}


# ------------------------------------------------------------ untested modules


def is_test_path(rel_path: str) -> bool:
    base = os.path.basename(rel_path)
    in_tests_dir = bool({"tests", "test"} & set(rel_path.split(os.sep)[:-1]))
    return in_tests_dir or (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py")


def _dotted(rel_path: str) -> str:
    return os.path.splitext(rel_path)[0].replace(os.sep, ".")


def _imported_dotted_names(tree) -> set:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def find_untested_modules(trees_by_file: dict) -> dict:
    """Static heuristic: source modules that no test file imports directly. Not coverage."""
    tested = set()
    for rel_path, tree in trees_by_file.items():
        if is_test_path(rel_path):
            tested |= _imported_dotted_names(tree)

    sources = [
        p for p in trees_by_file
        if not is_test_path(p) and os.path.basename(p) not in ("__init__.py", "conftest.py", "setup.py")
    ]
    untested = sorted(
        p for p in sources
        if not any(_dotted(p) == c or _dotted(p).endswith("." + c) for c in tested)
    )
    return {
        "count": len(untested),
        "source_modules": len(sources),
        "modules": untested[:MAX_LISTED["untested"]],
        "note": "Static heuristic: no test file imports the module directly. This is not coverage.",
    }


# -------------------------------------------------------------- unused imports


def _used_names(tree) -> set:
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for node in ast.walk(tree):  # names re-exported through __all__
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            used |= {e.value for e in ast.walk(node.value) if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return used


def _optional_import_nodes(tree) -> set:
    """Imports inside `try: ... except ImportError`: unused-by-design feature detection."""
    skip = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
            isinstance(h.type, ast.Name) and h.type.id in ("ImportError", "ModuleNotFoundError")
            for h in node.handlers
        ):
            for stmt in node.body:
                skip.update(id(n) for n in ast.walk(stmt))
    return skip


def find_unused_imports(rel_path: str, tree, source: str) -> list:
    if os.path.basename(rel_path) == "__init__.py":
        return []
    lines = source.splitlines()
    used, optional = _used_names(tree), _optional_import_nodes(tree)
    unused = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in optional:
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        end = getattr(node, "end_lineno", node.lineno)
        if any("noqa" in lines[i - 1] for i in range(node.lineno, end + 1) if 0 < i <= len(lines)):
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or (alias.name if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0])
            if bound not in used:
                unused.append((node.lineno, bound))
    return sorted(set(unused))


def find_all_unused_imports(trees_by_file: dict, py_sources: dict) -> dict:
    items = []
    for rel_path in sorted(trees_by_file):
        items.extend(f"{rel_path}:{lineno} {name}"
                     for lineno, name in find_unused_imports(rel_path, trees_by_file[rel_path], py_sources[rel_path]))
    return {"count": len(items), "items": items[:MAX_LISTED["unused_imports"]]}
