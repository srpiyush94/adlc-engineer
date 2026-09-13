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


if __name__ == "__main__":
    unittest.main()
