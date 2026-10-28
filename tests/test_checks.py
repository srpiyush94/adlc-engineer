"""Spec 0004: deterministic code-health checks."""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer import checks
from adlc_engineer.report_template import _code_health_lines, render_scan_report
from adlc_engineer.scanner import EXCLUDED_DIRS, scan_repository

# Fake credentials are assembled at runtime so this file never contains a real-looking
# secret literal (the scanner is run on this repo and must report none, AC-14).
FAKE = {
    "AWS access key id": "AK" + "IA" + "IOSFODNN7ABCDEFG",
    "Google API key": "AI" + "za" + "A1b2C3d4" * 4 + "Zz1",
    "GitHub token": "gh" + "p_" + "A1b2C3d4E5f6" * 3,
    "Slack token": "xo" + "xb-" + "1234567890-abcdefghij",
    "Private key block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "Hard-coded credential": "api_key = " + repr("Zq9" + "x7Lm2Pa4Rt8"),
}


def write(root, rel, content):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def git_repo(root, files, ignore=""):
    subprocess.run(["git", "init", "-q", root], check=True)
    if ignore:
        write(root, ".gitignore", ignore)
    for rel, content in files.items():
        write(root, rel, content)
    subprocess.run(["git", "-C", root, "add", "-A"], check=True)


def scan_requirements(text, lockfile=None):
    with tempfile.TemporaryDirectory() as repo:
        write(repo, "requirements.txt", text)
        if lockfile:
            write(repo, lockfile, "")
        return scan_repository(repo, repo)["dependencies"]


class TestDependencyHygiene(unittest.TestCase):
    def test_unpinned_detected_pinned_and_options_ignored(self):  # AC-1
        deps = scan_requirements(
            "pinned==1.0\nranged>=1.0\nbare\nstar==1.*\n-r base.txt\n-e .\n--index-url https://x\n# comment\n"
            "marker==2.0; python_version<'3.9'\nextras[x]==1.0\n"
        )
        self.assertEqual(deps["unpinned"], ["bare", "ranged", "star"])
        self.assertEqual(deps["declared"], ["pinned", "ranged", "bare", "star", "marker", "extras"])

    def test_lockfile_detection(self):  # AC-2
        self.assertFalse(scan_requirements("a==1\n")["has_lockfile"])
        for name in ("poetry.lock", "Pipfile.lock", "uv.lock", "pdm.lock"):
            self.assertTrue(scan_requirements("a==1\n", lockfile=name)["has_lockfile"], name)


class TestSecrets(unittest.TestCase):
    def scan_text(self, text, name="app.py"):
        return checks.scan_text_for_secrets(name, text)

    def test_every_pattern_is_detected_with_path_line_and_kind(self):  # AC-3
        for kind, secret in FAKE.items():
            with self.subTest(kind=kind):
                findings = self.scan_text(f"first line\nvalue = {secret}\n" if kind != "Hard-coded credential"
                                          else f"first line\n{secret}\n")
                self.assertEqual([(f["path"], f["line"], f["kind"]) for f in findings], [("app.py", 2, kind)])

    def test_full_secret_never_appears_in_evidence(self):  # AC-4
        with tempfile.TemporaryDirectory() as repo:
            write(repo, "config.py", "\n".join(f"v{i} = {s}" for i, s in enumerate(FAKE.values())) + "\n")
            blob = json.dumps(scan_repository(repo, repo))
        for kind, secret in FAKE.items():
            raw = secret.split("= ", 1)[-1].strip("'")
            if kind != "Private key block":
                self.assertNotIn(raw, blob, kind)
        self.assertIn("chars)", blob)

    def test_placeholders_are_not_reported(self):  # AC-5
        text = "\n".join([
            "api_key = 'your_key_here'", "password = 'changeme12345'", "token = '${TOKEN_VALUE1}'",
            'secret = "<insert-secret-1>"', "api_key = 'xxxxxxxxxxxx1'", "password = 'my_function_name'",
            "token = 'EXAMPLE_TOKEN_123'", "aws = " + "AK" + "IA" + "IOSFODNN7EXAMPLE",
        ])
        self.assertEqual(self.scan_text(text), [])

    def test_sensitive_file_reported_only_when_git_tracks_it(self):  # AC-6
        files = {".env": "A=1\n", ".env.example": "A=\n", "server.pem": "x\n", "app.py": "x = 1\n"}
        with tempfile.TemporaryDirectory() as tracked_repo:
            git_repo(tracked_repo, files)
            found = scan_repository(tracked_repo, tracked_repo)["secrets"]["tracked_sensitive_files"]
        self.assertEqual(found, [".env", "server.pem"])
        with tempfile.TemporaryDirectory() as ignored_repo:
            git_repo(ignored_repo, files, ignore=".env\n*.pem\n")
            write(ignored_repo, ".env", "KEY=" + FAKE["Google API key"] + "\n")  # on disk, untracked
            secrets = scan_repository(ignored_repo, ignored_repo)["secrets"]
        self.assertEqual(secrets["tracked_sensitive_files"], [])
        self.assertEqual(secrets["count"], 0)

    def test_non_git_directory_reports_no_sensitive_files_but_still_scans_contents(self):  # AC-6
        with tempfile.TemporaryDirectory() as repo:
            write(repo, ".env", "KEY=" + FAKE["Google API key"] + "\n")
            secrets = scan_repository(repo, repo)["secrets"]
        self.assertEqual(secrets["tracked_sensitive_files"], [])
        self.assertEqual([f["kind"] for f in secrets["findings"]], ["Google API key"])

    def test_excluded_directories_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as repo:
            write(repo, ".venv/lib/x.py", "k = " + FAKE["GitHub token"] + "\n")
            self.assertEqual(scan_repository(repo, repo)["secrets"]["count"], 0)

    def test_results_sorted_and_capped(self):  # AC-10
        with tempfile.TemporaryDirectory() as repo:
            for i in range(30):
                write(repo, f"f{i:02d}.py", "k = " + FAKE["GitHub token"] + "\n")
            secrets = scan_repository(repo, repo)["secrets"]
        self.assertEqual(secrets["count"], 30)
        paths = [f["path"] for f in secrets["findings"]]
        self.assertEqual(len(paths), 20)
        self.assertEqual(paths, sorted(paths))


def funcs(source):
    return [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


class TestComplexity(unittest.TestCase):
    def cc(self, body, name="f"):
        return checks.cyclomatic_complexity(next(n for n in funcs(body) if n.name == name))

    def test_counts_each_construct(self):  # AC-7
        self.assertEqual(self.cc("def f():\n    return 1\n"), 1)
        self.assertEqual(self.cc("def f(a):\n    if a:\n        pass\n"), 2)
        self.assertEqual(self.cc("def f(a):\n    for i in a:\n        pass\n    while a:\n        pass\n"), 3)
        self.assertEqual(self.cc("def f():\n    try:\n        pass\n    except A:\n        pass\n    except B:\n        pass\n"), 3)
        self.assertEqual(self.cc("def f(a, b, c):\n    return a and b and c\n"), 3)
        self.assertEqual(self.cc("def f(a):\n    return 1 if a else 2\n"), 2)
        self.assertEqual(self.cc("def f(a):\n    return [x for x in a if x]\n"), 3)

    def test_nested_functions_are_measured_separately(self):  # AC-7
        src = "def outer(a):\n    def inner(b):\n        if b:\n            pass\n    return inner\n"
        self.assertEqual(self.cc(src, "outer"), 1)
        self.assertEqual(self.cc(src, "inner"), 2)

    def test_only_functions_at_or_above_threshold_listed_worst_first(self):  # AC-7
        body = "".join(f"    if a == {i}:\n        pass\n" for i in range(12))
        trees = {
            "b.py": ast.parse(f"def big(a):\n{body}"),
            "a.py": ast.parse(f"def big(a):\n{body}\ndef small(a):\n    return a\n"),
            "c.py": ast.parse(f"def bigger(a):\n{body}    if a:\n        pass\n"),
        }
        result = checks.find_complex_functions(trees, threshold=10)
        self.assertEqual(result["count"], 3)
        self.assertEqual([(f["path"], f["name"], f["complexity"]) for f in result["functions"]],
                         [("c.py", "bigger", 14), ("a.py", "big", 13), ("b.py", "big", 13)])
        self.assertEqual(checks.find_complex_functions(trees, threshold=50)["functions"], [])


class TestUntestedModules(unittest.TestCase):
    def untested(self, test_source):
        trees = {
            "pkg/__init__.py": ast.parse(""), "pkg/a.py": ast.parse("x = 1"), "pkg/b.py": ast.parse("x = 1"),
            "tools.py": ast.parse("x = 1"), "conftest.py": ast.parse(""),
            "tests/test_x.py": ast.parse(test_source),
        }
        return checks.find_untested_modules(trees)

    def test_listing_excludes_tests_and_init(self):  # AC-8
        result = self.untested("")
        self.assertEqual(result["modules"], ["pkg/a.py", "pkg/b.py", "tools.py"])
        self.assertEqual(result["source_modules"], 3)

    def test_each_import_form_marks_the_module_tested(self):  # AC-8
        for source in ("import pkg.a", "from pkg import a", "from pkg.a import thing", "import pkg.a as alias"):
            with self.subTest(source=source):
                self.assertNotIn("pkg/a.py", self.untested(source)["modules"])
                self.assertIn("pkg/b.py", self.untested(source)["modules"])

    def test_top_level_script_tested_by_plain_import(self):  # AC-8
        self.assertNotIn("tools.py", self.untested("import tools")["modules"])

    def test_importing_only_the_package_does_not_mark_submodules(self):  # AC-8
        self.assertEqual(self.untested("import pkg")["count"], 3)

    def test_note_says_this_is_not_coverage(self):
        self.assertIn("not coverage", self.untested("")["note"])


class TestUnusedImports(unittest.TestCase):
    def unused(self, source, path="m.py"):
        return checks.find_unused_imports(path, ast.parse(source), source)

    def test_unused_listed_used_not(self):  # AC-9
        src = "import os\nimport sys\nfrom a import b, c\nimport x.y\nprint(sys.argv, b, x.y.z)\n"
        self.assertEqual(self.unused(src), [(1, "os"), (3, "c")])

    def test_aliases(self):  # AC-9
        self.assertEqual(self.unused("import numpy as np\nfrom a import b as c\nprint(c)\n"), [(1, "np")])

    def test_exemptions(self):  # AC-9
        self.assertEqual(self.unused("from __future__ import annotations\n"), [])
        self.assertEqual(self.unused("import os  # noqa: F401\n"), [])
        self.assertEqual(self.unused("from a import (\n    b,\n    c,  # noqa\n)\n"), [])
        self.assertEqual(self.unused("import os\n", path="pkg/__init__.py"), [])
        self.assertEqual(self.unused("from a import *\n"), [])
        self.assertEqual(self.unused("from a import b\n__all__ = ['b']\n"), [])
        self.assertEqual(self.unused("try:\n    import fast\nexcept ImportError:\n    fast = None\n"), [])

    def test_unused_inside_try_without_importerror_is_reported(self):
        self.assertEqual(self.unused("try:\n    import os\nexcept ValueError:\n    pass\n"), [(2, "os")])

    def test_capped_and_sorted(self):  # AC-10
        src = {f"m{i:02d}.py": "import os\n" for i in range(30)}
        trees = {p: ast.parse(s) for p, s in src.items()}
        result = checks.find_all_unused_imports(trees, src)
        self.assertEqual(result["count"], 30)
        self.assertEqual(len(result["items"]), 20)
        self.assertEqual(result["items"], sorted(result["items"]))
        self.assertEqual(result["items"][0], "m00.py:1 os")


class TestDeterminismAndReport(unittest.TestCase):
    def make_repo(self, root):
        write(root, "requirements.txt", "bare\n")
        write(root, "app.py", "import os\n\ndef f(a):\n" + "".join(f"    if a == {i}:\n        pass\n" for i in range(11)))
        write(root, "leak.py", "k = " + FAKE["GitHub token"] + "\n")

    def test_scan_is_identical_across_runs(self):  # AC-10
        with tempfile.TemporaryDirectory() as repo:
            self.make_repo(repo)
            first, second = scan_repository(repo, repo), scan_repository(repo, repo)
        self.assertEqual(json.dumps(first), json.dumps(second))

    def test_findings_rendered_with_locations_and_masked_values(self):  # AC-11
        with tempfile.TemporaryDirectory() as repo:
            self.make_repo(repo)
            out = "\n".join(_code_health_lines(scan_repository(repo, repo)))
        self.assertIn("**Unpinned dependencies:** 1 of 1", out)
        self.assertIn("`bare`", out)
        self.assertIn("`leak.py:1` — GitHub token", out)
        self.assertNotIn(FAKE["GitHub token"], out)
        self.assertIn("`app.py:3` `f` — complexity 12", out)
        self.assertIn("`app.py:1 os`", out)
        self.assertIn("not coverage", out)

    def test_clean_checks_say_none_found(self):  # AC-11
        with tempfile.TemporaryDirectory() as repo:
            write(repo, "requirements.txt", "a==1\n")
            write(repo, "m.py", "x = 1\n")
            write(repo, "tests/test_m.py", "import m\n\nassert m.x\n")
            out = "\n".join(_code_health_lines(scan_repository(repo, repo)))
        for expected in ("**Unpinned dependencies:** none", "**Secrets:** none found.", "no function at or above complexity 10",
                         "every source module is imported by a test", "**Unused imports:** none found."):
            self.assertIn(expected, out)

    def test_checks_absent_from_older_evidence_are_skipped(self):  # AC-11
        self.assertEqual(_code_health_lines({"dependencies": {"declared": ["a"], "source_file": "requirements.txt"}}), [])

    def test_scan_report_is_deterministic_and_says_no_llm(self):  # AC-12
        with tempfile.TemporaryDirectory() as repo:
            self.make_repo(repo)
            evidence = scan_repository(repo, repo)
        first, second = render_scan_report(evidence, "demo"), render_scan_report(evidence, "demo")
        self.assertEqual(first, second)
        self.assertIn("No LLM was used", first)
        self.assertIn("| Potential secrets | 1 |", first)
        self.assertIn("## 2. Dependency Map", first)
        self.assertIn("## 3. Architectural Problems", first)


class TestSelfScan(unittest.TestCase):
    def test_this_repository_has_no_secrets(self):  # AC-14
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertEqual(scan_repository(root, root)["secrets"]["findings"], [])


if __name__ == "__main__":
    unittest.main()
