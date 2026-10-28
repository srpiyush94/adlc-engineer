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


if __name__ == "__main__":
    unittest.main()
