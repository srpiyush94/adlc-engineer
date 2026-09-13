import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer.graph import _NOT_FOUND, _resolve_dot_path, _sanitize_mermaid, check_citations


class TestSanitizeMermaid(unittest.TestCase):
    def test_rewrites_bare_reserved_word_node_id(self):
        code = "graph TD\ndashboard --> graph\ngraph --> llm"
        sanitized = _sanitize_mermaid(code)
        self.assertNotIn("--> graph\n", sanitized)
        self.assertNotIn("\ngraph -->", sanitized)
        self.assertIn("n_graph[graph]", sanitized)
        # every mention of the reserved word becomes the same synthetic id + label
        self.assertEqual(sanitized.count("n_graph[graph]"), 2)

    def test_leaves_safe_diagrams_untouched(self):
        code = "graph TD\ndashboard --> scanner\nscanner --> llm"
        self.assertEqual(_sanitize_mermaid(code), code)

    def test_leaves_diagram_type_declaration_line_alone(self):
        # "graph" in "graph TD" is the diagram type, not a node id -- must not be touched
        code = "graph TD\na --> b"
        self.assertTrue(_sanitize_mermaid(code).startswith("graph TD\n"))


class TestResolveDotPath(unittest.TestCase):
    EVIDENCE = {
        "frameworks": {"langgraph": ["main.py:1"]},
        "integrations": {"database": {}},
        "coupling": {"adlc_engineer/graph.py": ["llm", "scanner"]},
    }

    def test_resolves_simple_path(self):
        self.assertEqual(_resolve_dot_path(self.EVIDENCE, "frameworks.langgraph"), ["main.py:1"])

    def test_resolves_path_with_literal_dot_in_key(self):
        self.assertEqual(
            _resolve_dot_path(self.EVIDENCE, "coupling.adlc_engineer/graph.py"),
            ["llm", "scanner"],
        )

    def test_empty_dict_is_a_valid_resolution_not_not_found(self):
        self.assertEqual(_resolve_dot_path(self.EVIDENCE, "integrations.database"), {})

    def test_missing_path_returns_not_found(self):
        self.assertIs(_resolve_dot_path(self.EVIDENCE, "nonexistent.path"), _NOT_FOUND)


class TestCheckCitations(unittest.TestCase):
    EVIDENCE = {"integrations": {"database": {}}, "languages": {"Python": {"files": 1, "loc": 10}}}

    def test_empty_dict_citation_is_not_a_warning(self):
        warnings = check_citations(["integrations.database"], self.EVIDENCE, "/tmp/repo")
        self.assertEqual(warnings, [])

    def test_bogus_citation_is_a_warning(self):
        warnings = check_citations(["totally.made.up"], self.EVIDENCE, "/tmp/repo")
        self.assertEqual(len(warnings), 1)

    def test_no_citations_is_a_warning(self):
        warnings = check_citations([], self.EVIDENCE, "/tmp/repo")
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
