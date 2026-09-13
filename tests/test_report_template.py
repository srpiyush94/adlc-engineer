import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer.report_template import render_report

EVIDENCE = {
    "repo_meta": {"source": "/tmp/repo", "type": "local_path"},
    "languages": {"Python": {"files": 1, "loc": 10}},
    "frameworks": {"langgraph": ["main.py:1"]},
    "dependencies": {"declared": ["langgraph"], "source_file": "requirements.txt",
                      "declared_but_not_directly_imported": []},
    "deployment": {"found": {"Dockerfile": False}, "gaps": ["No Dockerfile found"]},
    "integrations": {"database": {}, "external_sdks": {}, "http_clients": {}},
    "tests": {"test_files": [], "count": 0, "gap": "No test files found"},
    "hotspots": {"largest_files": [{"path": "main.py", "loc": 10}], "todo_fixme_count": 0,
                 "todo_fixme_locations": [], "bare_except_count": 0, "bare_except_locations": []},
    "coupling": {},
    "architecture_pattern_guess": {"pattern": "graph-orchestrated agent workflow", "evidence": ["frameworks.langgraph"]},
    "parse_errors": [],
}

ARCHITECTURE_MODEL = {
    "narrative": "A simple graph-based Python app.",
    "mermaid": "graph TD; App --> LangGraph;",
    "components": [{"name": "LangGraph Workflow", "grounded_in": ["frameworks.langgraph"]}],
    "citation_warnings": [],
}

MODERNIZATION = {
    "options": [
        {"name": "Modernize monolith", "cost": "Low", "risk": "Low", "complexity": "Low",
         "scalability": "Medium", "recommendation": "Recommended", "reasoning": "Small codebase.",
         "citations": ["languages.Python"]},
        {"name": "Modular monolith", "cost": "Medium", "risk": "Low", "complexity": "Medium",
         "scalability": "Medium", "recommendation": "Viable", "reasoning": "Could help later.",
         "citations": ["languages.Python"]},
        {"name": "Strangler", "cost": "Medium", "risk": "Medium", "complexity": "Medium",
         "scalability": "High", "recommendation": "Not recommended", "reasoning": "Overkill.",
         "citations": ["languages.Python"]},
        {"name": "Selective microservices", "cost": "High", "risk": "High", "complexity": "High",
         "scalability": "High", "recommendation": "Not recommended", "reasoning": "Overkill for size.",
         "citations": ["languages.Python"]},
        {"name": "Event-driven decomposition", "cost": "High", "risk": "High", "complexity": "High",
         "scalability": "Very High", "recommendation": "Not recommended", "reasoning": "Not needed.",
         "citations": ["languages.Python"]},
    ],
    "recommended_option": "Modernize monolith",
    "adr": "Context...\nDecision...\nConsequences...",
    "migration_roadmap": ["Add tests", "Add CI"],
    "risks": ["Low test coverage"],
    "assumptions": ["Repo evolves slowly"],
    "citation_warnings": [],
}

EXPECTED_HEADERS = [
    "## 1. Executive Summary",
    "## 2. Current Architecture",
    "## 3. System Components",
    "## 4. Dependency Map",
    "## 5. Architectural Problems",
    "## 6. Business/Technical Constraints",
    "## 7. Non-Functional Requirements",
    "## 8. Modernization Options",
    "## 9. Recommended Architecture",
    "## 10. Architecture Decision Record (ADR)",
    "## 11. Migration Roadmap",
    "## 12. Risks",
    "## 13. Assumptions",
    "## 14. Validation Plan",
    "## 15. Traceability (Evidence -> Architecture Claim -> Modernization Option)",
    "## Appendix A: Evidence Data",
]


class TestReportTemplate(unittest.TestCase):
    def setUp(self):
        self.report = render_report(EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION, "/tmp/repo")

    def test_all_section_headers_present_in_order(self):
        positions = [self.report.index(h) for h in EXPECTED_HEADERS]
        self.assertEqual(positions, sorted(positions))

    def test_mermaid_block_present(self):
        self.assertIn("```mermaid\ngraph TD; App --> LangGraph;\n```", self.report)

    def test_modernization_table_has_five_rows_in_order(self):
        expected_order = [
            "Modernize monolith", "Modular monolith", "Strangler",
            "Selective microservices", "Event-driven decomposition",
        ]
        positions = [self.report.index(f"| {name} |") for name in expected_order]
        self.assertEqual(positions, sorted(positions))

    def test_citation_round_trips_into_traceability(self):
        traceability_section = self.report[self.report.index("## 15."):]
        self.assertIn("frameworks.langgraph", traceability_section)


if __name__ == "__main__":
    unittest.main()
