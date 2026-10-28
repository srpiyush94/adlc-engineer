import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer import main as main_module

RESULT = {
    "report_markdown": "report",
    "evidence": {},
    "architecture_model": {},
    "modernization": {"recommended_option": "Modernize monolith"},
}


class FakeAgent:
    def invoke(self, *_args, **_kwargs):
        return RESULT


def run_main(argv):
    @contextlib.contextmanager
    def fake_resolve(_arg):
        yield "/nonexistent-repo", "demo"

    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(sys, "argv", ["main", *argv, "--output", os.path.join(tmp, "r.md")]), \
            mock.patch.object(main_module, "build_graph", return_value=FakeAgent()), \
            mock.patch.object(main_module.repo_source, "resolve_repo", fake_resolve), \
            mock.patch.object(main_module.adr_writer, "write_adr", return_value=("/x/0002.md", True)) as write, \
            contextlib.redirect_stdout(out):
        main_module.main()
    return out.getvalue(), write


class TestWriteAdrFlag(unittest.TestCase):
    def test_git_url_warns_before_the_run_and_writes_nothing(self):  # AC-9
        output, write = run_main(["--repo", "https://github.com/x/y.git", "--write-adr"])
        write.assert_not_called()
        self.assertIn("--write-adr ignored", output)
        self.assertLess(output.index("--write-adr ignored"), output.index("Analyzing repository"))

    def test_local_path_writes_adr(self):
        output, write = run_main(["--repo", "/some/local/path", "--write-adr"])
        write.assert_called_once()
        self.assertIn("ADR written to: /x/0002.md", output)

    def test_flag_off_never_writes(self):
        _, write = run_main(["--repo", "/some/local/path"])
        write.assert_not_called()

    def test_unindexed_adr_prints_warning(self):
        with mock.patch.object(main_module.adr_writer, "write_adr", return_value=("/x/0002.md", False)):
            out = io.StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(sys, "argv", ["main", "--repo", "/p", "--write-adr", "--output", f"{tmp}/r.md"]), \
                    mock.patch.object(main_module, "build_graph", return_value=FakeAgent()), \
                    mock.patch.object(main_module.repo_source, "resolve_repo",
                                      contextlib.contextmanager(lambda _a: (yield ("/p", "demo")))), \
                    contextlib.redirect_stdout(out):
                main_module.main()
        self.assertIn("no index table", out.getvalue())


class TestScanOnly(unittest.TestCase):  # spec 0004, AC-12
    def run_scan_only(self, repo, output):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["main", "--repo", repo, "--scan-only", "--output", output]), \
                mock.patch.object(main_module, "build_graph", side_effect=AssertionError("LLM graph built")), \
                mock.patch.object(main_module, "get_langfuse_handler", side_effect=AssertionError("tracing used")), \
                mock.patch("adlc_engineer.llm.build_llm", side_effect=AssertionError("LLM built")), \
                mock.patch.dict(os.environ, {}, clear=False), \
                contextlib.redirect_stdout(out):
            os.environ.pop("GOOGLE_API_KEY", None)
            main_module.main()
        return out.getvalue()

    def make_repo(self, root):
        with open(os.path.join(root, "requirements.txt"), "w") as f:
            f.write("bare\n")
        with open(os.path.join(root, "app.py"), "w") as f:
            f.write("import os\n")

    def test_writes_report_without_llm_or_api_key_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as out_dir:
            self.make_repo(repo)
            first, second = os.path.join(out_dir, "a.md"), os.path.join(out_dir, "b.md")
            stdout = self.run_scan_only(repo, first)
            self.run_scan_only(repo, second)
            with open(first, encoding="utf-8") as f1, open(second, encoding="utf-8") as f2:
                report, again = f1.read(), f2.read()
        self.assertEqual(report, again)
        self.assertIn("No LLM was used", report)
        self.assertIn("`bare`", report)
        self.assertIn("Unpinned dependencies: 1", stdout)
        self.assertIn("Unused imports: 1", stdout)

    def test_rejects_flags_that_need_an_llm(self):
        for extra in (["--plan"], ["--challenge"], ["--write-adr"], ["--requirement", "10k rps"]):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as repo:
                err = io.StringIO()
                with mock.patch.object(sys, "argv", ["main", "--repo", repo, "--scan-only", *extra]), \
                        contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                    main_module.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("cannot be combined with", err.getvalue())
                self.assertIn(extra[0], err.getvalue())


if __name__ == "__main__":
    unittest.main()


class TestFailOn(unittest.TestCase):  # spec 0005
    def invoke(self, repo, *extra, scan_only=True):
        argv = ["main", "--repo", repo, "--output", os.path.join(repo, "..", "out-" + os.path.basename(repo) + ".md")]
        argv += (["--scan-only"] if scan_only else []) + list(extra)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            try:
                main_module.main()
                code = 0
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue(), argv[4]

    def write(self, root, name, text):
        with open(os.path.join(root, name), "w") as f:
            f.write(text)

    def test_exits_1_naming_failing_categories_and_still_writes_report(self):  # AC-1, AC-4, AC-8
        with tempfile.TemporaryDirectory() as repo:
            self.write(repo, "requirements.txt", "bare\n")
            self.write(repo, "app.py", "import os\n")
            code, out, _, report = self.invoke(repo, "--fail-on", " unused-imports , unpinned,unpinned")
            self.assertTrue(os.path.exists(report))
            os.remove(report)
        self.assertEqual(code, 1)
        self.assertIn("FAILED (--fail-on): unpinned: 1, unused-imports: 1", out)

    def test_unselected_findings_do_not_fail(self):  # AC-5
        with tempfile.TemporaryDirectory() as repo:
            self.write(repo, "requirements.txt", "bare\n")
            code, _, _, report = self.invoke(repo, "--fail-on", "secrets")
            os.remove(report)
        self.assertEqual(code, 0)

    def test_clean_repo_passes(self):  # AC-6
        with tempfile.TemporaryDirectory() as repo:
            self.write(repo, "requirements.txt", "pinned==1.0\n")
            code, _, _, report = self.invoke(repo, "--fail-on", "secrets,unpinned,complexity")
            os.remove(report)
        self.assertEqual(code, 0)

    def test_without_fail_on_findings_still_exit_0(self):  # AC-7
        with tempfile.TemporaryDirectory() as repo:
            self.write(repo, "requirements.txt", "bare\n")
            code, _, _, report = self.invoke(repo)
            os.remove(report)
        self.assertEqual(code, 0)

    def test_unknown_category_is_a_usage_error(self):  # AC-2
        with tempfile.TemporaryDirectory() as repo:
            code, _, err, _ = self.invoke(repo, "--fail-on", "secrets,nonsense")
        self.assertEqual(code, 2)
        self.assertIn("nonsense", err)
        self.assertIn("unused-imports", err)

    def test_fail_on_requires_scan_only(self):  # AC-3
        with tempfile.TemporaryDirectory() as repo:
            code, _, err, _ = self.invoke(repo, "--fail-on", "secrets", scan_only=False)
        self.assertEqual(code, 2)
        self.assertIn("--scan-only", err)
