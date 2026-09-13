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

CHALLENGER = {
    "reviews": {
        "Security": {"has_objection": False, "severity": "none", "summary": "No security concerns found.",
                     "citations": ["integrations.database"]},
        "Scalability": {"has_objection": True, "severity": "medium",
                        "summary": "Scalability rating is asserted, not evidenced by coupling data.",
                        "citations": ["coupling"]},
        "Cost": {"has_objection": False, "severity": "none", "summary": "Cost rating matches repo size.",
                 "citations": ["languages.Python"]},
        "Reliability": {"has_objection": False, "severity": "none", "summary": "No reliability concerns.",
                        "citations": ["tests"]},
        "Implementation": {"has_objection": False, "severity": "none", "summary": "Roadmap looks feasible.",
                           "citations": ["languages.Python"]},
    },
    "has_objections": True,
    "objecting_personas": ["Scalability"],
}

SPECIFICATION = {
    "requirement_text": "System must support 10,000 concurrent requests with p95 latency under 300ms "
                         "and 99.9% availability.",
    "constraints": [
        {"description": "System must support 10,000 concurrent requests.", "citations": ["requirement_text"]},
        {"description": "p95 latency must be under 300ms.", "citations": ["requirement_text"]},
        {"description": "Availability must be at least 99.9%.", "citations": ["deployment.gaps"]},
    ],
    "acceptance_criteria": [
        {"id": "AC-1", "description": "Load test sustains 10,000 concurrent requests without error rate increase.",
         "citations": ["requirement_text"]},
        {"id": "AC-2", "description": "p95 latency stays under 300ms under the load in AC-1.",
         "citations": ["requirement_text"]},
        {"id": "AC-3", "description": "Deployment supports 99.9% availability via redundancy/rollback tooling.",
         "citations": ["deployment.gaps"]},
    ],
    "citation_warnings": [],
}

MODERNIZATION_WITH_COMPLIANCE = {
    **MODERNIZATION,
    "compliance_assessment": [
        {"criterion_id": "AC-1", "status": "not_satisfied",
         "reasoning": "No load-testing or horizontal scaling evidence exists today.", "citations": ["coupling"]},
        {"criterion_id": "AC-2", "status": "partial",
         "reasoning": "No latency instrumentation found to confirm.", "citations": ["languages.Python"]},
        {"criterion_id": "AC-3", "status": "not_satisfied",
         "reasoning": "No deployment infrastructure found.", "citations": ["deployment.gaps"]},
    ],
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


class TestReportTemplateChallenger(unittest.TestCase):
    def test_section_16_present_and_ordered_when_challenger_provided(self):
        report = render_report(EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION, "/tmp/repo", challenger=CHALLENGER)
        expected = EXPECTED_HEADERS[:-1] + [
            "## 16. Architecture Challenger Review", "## Appendix A: Evidence Data",
        ]
        positions = [report.index(h) for h in expected]
        self.assertEqual(positions, sorted(positions))

    def test_section_16_absent_by_default(self):
        report = render_report(EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION, "/tmp/repo")
        self.assertNotIn("Architecture Challenger Review", report)

    def test_revision_notes_appear_when_revised(self):
        revised = {**MODERNIZATION, "revised": True, "revision_notes": "Addressed the Scalability objection by..."}
        report = render_report(EVIDENCE, ARCHITECTURE_MODEL, revised, "/tmp/repo", challenger=CHALLENGER)
        self.assertIn("Addressed the Scalability objection", report)

    def test_all_five_personas_appear(self):
        report = render_report(EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION, "/tmp/repo", challenger=CHALLENGER)
        for persona in ["Security", "Scalability", "Cost", "Reliability", "Implementation"]:
            self.assertIn(f"### {persona}", report)


class TestReportTemplateSpecification(unittest.TestCase):
    def test_section_16_specification_when_only_specification_provided(self):
        report = render_report(
            EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION_WITH_COMPLIANCE, "/tmp/repo", specification=SPECIFICATION
        )
        expected = EXPECTED_HEADERS[:-1] + [
            "## 16. Specification & Acceptance Criteria", "## Appendix A: Evidence Data",
        ]
        positions = [report.index(h) for h in expected]
        self.assertEqual(positions, sorted(positions))

    def test_specification_then_challenger_numbered_16_and_17_when_both_provided(self):
        report = render_report(
            EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION_WITH_COMPLIANCE, "/tmp/repo",
            challenger=CHALLENGER, specification=SPECIFICATION,
        )
        expected = EXPECTED_HEADERS[:-1] + [
            "## 16. Specification & Acceptance Criteria",
            "## 17. Architecture Challenger Review",
            "## Appendix A: Evidence Data",
        ]
        positions = [report.index(h) for h in expected]
        self.assertEqual(positions, sorted(positions))

    def test_challenger_only_still_numbered_16_unchanged(self):
        report = render_report(EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION, "/tmp/repo", challenger=CHALLENGER)
        self.assertIn("## 16. Architecture Challenger Review", report)

    def test_neither_specification_nor_challenger_present_by_default(self):
        report = render_report(EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION, "/tmp/repo")
        self.assertNotIn("Specification & Acceptance Criteria", report)
        self.assertNotIn("Architecture Challenger Review", report)

    def test_acceptance_criteria_and_compliance_status_appear(self):
        report = render_report(
            EVIDENCE, ARCHITECTURE_MODEL, MODERNIZATION_WITH_COMPLIANCE, "/tmp/repo", specification=SPECIFICATION
        )
        self.assertIn("AC-1", report)
        self.assertIn("not_satisfied", report)


if __name__ == "__main__":
    unittest.main()
