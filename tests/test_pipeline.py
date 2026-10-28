"""End-to-end graph runs against a fake LLM: checks node wiring and LLM call counts."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer.graph import (
    MODERNIZATION_OPTION_NAMES,
    ArchitectureModel,
    ComponentCitation,
    ModernizationModel,
    ModernizationOption,
    ReviewFinding,
    build_graph,
)
from adlc_engineer.plan import PlanModel, PlanTask


def _modernization():
    options = [
        ModernizationOption(
            name=name, cost="Low", risk="Low", complexity="Low", scalability="Moderate",
            recommendation="Strongly Recommended" if name == "Modernize monolith" else "Not Recommended",
            reasoning="tiny repo", citations=["languages.Python"],
        )
        for name in MODERNIZATION_OPTION_NAMES
    ]
    return ModernizationModel(
        options=options, recommended_option="Modernize monolith", adr="ADR text",
        migration_roadmap=["step"], risks=["risk"], assumptions=["assumption"],
    )


def _task(task_id, gap, depends_on=()):
    return PlanTask(
        id=task_id, title=f"Close {gap}", rationale="why", gap_ref=gap,
        acceptance_check="it works", depends_on=list(depends_on), effort="S", citations=[gap],
        criteria_refs=[],
    )


def _plan():
    return PlanModel(
        tasks=[
            _task("T-1", "dependencies.source_file"),
            _task("T-2", "tests.gap", ["T-1"]),
            _task("T-3", "deployment.gaps", ["T-1"]),
        ],
        not_addressed=[],
    )


class FakeLLM:
    """Stands in for ChatGoogleGenerativeAI; counts invocations and returns canned models."""

    def __init__(self, objecting=False):
        self.calls = []
        self.objecting = objecting

    def with_structured_output(self, model):
        def invoke(_messages):
            self.calls.append(model.__name__)
            if model is ArchitectureModel:
                return ArchitectureModel(
                    narrative="n", mermaid="graph TD\nA-->B",
                    components=[ComponentCitation(name="A", grounded_in=["languages.Python"])],
                )
            if model is ModernizationModel:
                return _modernization()
            if model is PlanModel:
                return _plan()
            if model is ReviewFinding:
                return ReviewFinding(
                    has_objection=self.objecting, severity="high" if self.objecting else "none",
                    summary="s", citations=["languages.Python"],
                )
            raise AssertionError(f"unexpected model {model}")

        return mock.Mock(invoke=invoke)


def run(**state):
    llm = FakeLLM(objecting=state.pop("objecting", False))
    with tempfile.TemporaryDirectory() as repo, mock.patch("adlc_engineer.graph.build_llm", return_value=llm):
        with open(os.path.join(repo, "app.py"), "w") as f:
            f.write("print('hi')\n")
        result = build_graph().invoke({"repo_path": repo, "repo_display_name": "demo", **state})
    return result, llm.calls


class TestPipeline(unittest.TestCase):
    def test_default_run_unchanged_two_llm_calls_no_plan(self):  # AC-1
        result, calls = run()
        self.assertEqual(calls, ["ArchitectureModel", "ModernizationModel"])
        self.assertNotIn("plan", result)
        self.assertNotIn("Implementation Plan", result["report_markdown"])

    def test_plan_flag_adds_one_call_and_section(self):  # AC-2
        result, calls = run(run_plan=True)
        self.assertEqual(calls, ["ArchitectureModel", "ModernizationModel", "PlanModel"])
        self.assertIn("## 16. Implementation Plan", result["report_markdown"])
        self.assertEqual(result["plan"]["citation_warnings"], [])

    def test_plan_with_challenger_no_objections(self):  # AC-6
        result, calls = run(run_plan=True, run_challenger=True)
        self.assertEqual(len(calls), 8)
        self.assertEqual(calls[-1], "PlanModel")
        self.assertIn("Implementation Plan", result["report_markdown"])

    def test_plan_runs_after_revision(self):  # AC-6
        result, calls = run(run_plan=True, run_challenger=True, objecting=True)
        self.assertEqual(calls[-2:], ["ModernizationModel", "PlanModel"])
        self.assertEqual(len(calls), 9)
        self.assertTrue(result["modernization"]["revised"])

    def test_challenger_without_plan_has_no_plan_node(self):
        result, calls = run(run_challenger=True)
        self.assertNotIn("PlanModel", calls)
        self.assertNotIn("Implementation Plan", result["report_markdown"])


if __name__ == "__main__":
    unittest.main()
