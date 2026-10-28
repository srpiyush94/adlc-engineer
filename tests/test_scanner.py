import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer.scanner import scan_repository


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestScanner(unittest.TestCase):
    def test_detects_python_language_and_loc(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, "app.py"), "x = 1\ny = 2\n\nz = 3\n")
            evidence = scan_repository(repo, repo)
            self.assertEqual(evidence["languages"]["Python"], {"files": 1, "loc": 3})

    def test_flags_missing_deployment_and_tests(self):
        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, "tests"))
            evidence = scan_repository(repo, repo)
            self.assertFalse(evidence["deployment"]["found"]["Dockerfile"])
            self.assertTrue(any("Dockerfile" in gap for gap in evidence["deployment"]["gaps"]))
            self.assertEqual(evidence["tests"]["count"], 0)
            self.assertIn("gap", evidence["tests"])

    def test_detects_framework_and_dependency_signals(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, "requirements.txt"), "langgraph==1.2.11\n")
            _write(os.path.join(repo, "main.py"), "from langgraph.graph import StateGraph\n")
            evidence = scan_repository(repo, repo)
            self.assertIn("langgraph", evidence["frameworks"])
            self.assertIn("main.py:1", evidence["frameworks"]["langgraph"])
            self.assertIn("langgraph", evidence["dependencies"]["declared"])

    def test_hotspot_bare_except_and_todo(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(
                os.path.join(repo, "risky.py"),
                "try:\n    pass\nexcept:\n    pass\n# TODO: fix this\n",
            )
            evidence = scan_repository(repo, repo)
            self.assertGreaterEqual(evidence["hotspots"]["bare_except_count"], 1)
            self.assertGreaterEqual(evidence["hotspots"]["todo_fixme_count"], 1)

    def test_ignores_venv_directory(self):
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, ".venv", "lib", "fake_pkg.py"), "import langgraph\n")
            evidence = scan_repository(repo, repo)
            self.assertEqual(evidence["languages"], {})
            self.assertEqual(evidence["frameworks"], {})


class TestScannerAccuracy(unittest.TestCase):  # spec 0002
    def test_ignores_claude_directory_entirely(self):  # AC-1
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, "app.py"), "import langgraph\n")
            _write(os.path.join(repo, ".claude", "worktrees", "w1", "app.py"), "import langgraph\n# TODO: dup\n")
            _write(os.path.join(repo, ".claude", "worktrees", "w1", "tests", "test_a.py"), "x = 1\n")
            evidence = scan_repository(repo, repo)
            self.assertEqual(evidence["languages"]["Python"]["files"], 1)
            self.assertEqual(evidence["tests"]["count"], 0)
            self.assertEqual(evidence["hotspots"]["todo_fixme_count"], 0)
            self.assertNotIn(".claude", json.dumps(evidence))

    def _unimported(self, requirements, source):
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, "requirements.txt"), requirements)
            _write(os.path.join(repo, "main.py"), source)
            return scan_repository(repo, repo)["dependencies"]["declared_but_not_directly_imported"]

    def test_alias_package_counts_as_imported(self):  # AC-2
        self.assertEqual(
            self._unimported("python-dotenv\nPyYAML\nstreamlit-mermaid\n",
                             "from dotenv import load_dotenv\nimport yaml\nfrom streamlit_mermaid import st_mermaid\n"),
            [],
        )

    def test_genuinely_unused_package_still_reported(self):  # AC-3
        self.assertEqual(self._unimported("requests\nlangchain\n", "import requests\n"), ["langchain"])

    def test_non_framework_library_counts_as_imported(self):  # AC-4
        self.assertEqual(self._unimported("numpy>=1.0\n", "import numpy as np\n"), [])

    def _todo_count(self, source):
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, "a.py"), source)
            return scan_repository(repo, repo)["hotspots"]["todo_fixme_count"]

    def test_todo_in_comment_counts_but_not_in_string_or_docstring(self):  # AC-5
        self.assertEqual(self._todo_count("x = 1  # TODO: later\n# FIXME: also\n"), 2)
        self.assertEqual(self._todo_count('s = "TODO"\ndef f():\n    """FIXME in a docstring"""\n'), 0)

    def test_untokenizable_file_does_not_stop_other_files(self):  # AC-6
        with tempfile.TemporaryDirectory() as repo:
            _write(os.path.join(repo, "broken.py"), "def f(:\n    x = (\n# TODO: lost\n")
            _write(os.path.join(repo, "ok.py"), "# TODO: found\n")
            evidence = scan_repository(repo, repo)
            self.assertEqual(evidence["hotspots"]["todo_fixme_locations"], ["ok.py:1"])


if __name__ == "__main__":
    unittest.main()
