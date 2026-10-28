import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer.graph import check_citations
from adlc_engineer.plan import PlanModel, PlanTask, find_cycle, flagged_gap_paths, validate_plan
from adlc_engineer.report_template import _render_plan

EVIDENCE = {
    "deployment": {"gaps": ["No Dockerfile found"]},
    "tests": {"count": 0, "gap": "No test files found"},
    "dependencies": {"declared": [], "source_file": None},
}


def task(task_id, depends_on=(), gap_ref="tests.gap", citations=("tests.gap",), title="Add tests", **kw):
    return PlanTask(
        id=task_id,
        title=title,
        rationale="because",
        gap_ref=gap_ref,
        acceptance_check=kw.get("acceptance_check", "pytest passes"),
        depends_on=list(depends_on),
        effort="M",
        citations=list(citations),
        criteria_refs=kw.get("criteria_refs", []),
    )


def validate(plan, option="Modernize monolith", criterion_ids=()):
    return validate_plan(plan, EVIDENCE, option, list(criterion_ids), check_citations, "/nonexistent")


def full_plan(**overrides):
    tasks = [
        task("T-1", gap_ref="dependencies.source_file", citations=["dependencies.source_file"]),
        task("T-2", ["T-1"], gap_ref="tests.gap"),
        task("T-3", ["T-1"], gap_ref="deployment.gaps", citations=["deployment.gaps"], title="Add Dockerfile"),
    ]
    return PlanModel(tasks=overrides.get("tasks", tasks), not_addressed=overrides.get("not_addressed", []))


class TestFindCycle(unittest.TestCase):
    def test_acyclic(self):
        self.assertEqual(find_cycle([task("T-1"), task("T-2", ["T-1"])]), [])

    def test_two_node_cycle(self):
        cycle = find_cycle([task("T-1", ["T-2"]), task("T-2", ["T-1"])])
        self.assertEqual(cycle[0], cycle[-1])
        self.assertEqual(set(cycle), {"T-1", "T-2"})

    def test_self_loop(self):
        self.assertTrue(find_cycle([task("T-1", ["T-1"])]))

    def test_unknown_dependency_is_not_a_cycle(self):
        self.assertEqual(find_cycle([task("T-1", ["T-9"])]), [])


class TestFlaggedGaps(unittest.TestCase):
    def test_all_three_flagged(self):
        self.assertEqual(flagged_gap_paths(EVIDENCE), ["deployment.gaps", "tests.gap", "dependencies.source_file"])

    def test_clean_repo_flags_nothing(self):
        clean = {"deployment": {"gaps": []}, "tests": {"gap": None}, "dependencies": {"source_file": "requirements.txt"}}
        self.assertEqual(flagged_gap_paths(clean), [])


class TestValidatePlan(unittest.TestCase):
    def test_valid_plan_has_no_warnings(self):
        self.assertEqual(validate(full_plan()), [])

    def test_empty_plan(self):
        self.assertEqual(validate(PlanModel(tasks=[], not_addressed=[])), ["Plan contains no tasks."])

    def test_unknown_dependency_and_cycle_warn_not_raise(self):
        plan = full_plan(tasks=[task("T-1", ["T-2"]), task("T-2", ["T-1", "T-9"])])
        warnings = validate(plan)
        self.assertTrue(any("unknown task 'T-9'" in w for w in warnings))
        self.assertTrue(any("Dependency cycle" in w for w in warnings))

    def test_duplicate_ids(self):
        warnings = validate(full_plan(tasks=[task("T-1"), task("T-1")]))
        self.assertTrue(any("Duplicate task ids" in w for w in warnings))

    def test_missing_acceptance_check(self):
        warnings = validate(full_plan(tasks=[task("T-1", acceptance_check="  ")]))
        self.assertTrue(any("missing acceptance check" in w for w in warnings))

    def test_unresolved_citation(self):
        warnings = validate(full_plan(tasks=[task("T-1", citations=["no.such.path"])]))
        self.assertTrue(any("Unresolved citation" in w for w in warnings))

    def test_uncovered_gap_warns(self):
        warnings = validate(full_plan(tasks=[task("T-1")]))
        self.assertTrue(any("'deployment.gaps'" in w for w in warnings))
        self.assertTrue(any("'dependencies.source_file'" in w for w in warnings))

    def test_gap_listed_as_not_addressed_is_acknowledged(self):
        plan = full_plan(
            tasks=[task("T-1")],
            not_addressed=["deployment.gaps: demo project", "dependencies.source_file: out of scope"],
        )
        self.assertEqual(validate(plan), [])

    def test_decomposition_task_rejected_under_monolith(self):
        tasks = full_plan().tasks + [task("T-4", title="Split into microservices")]
        self.assertTrue(any("inconsistent" in w for w in validate(full_plan(tasks=tasks))))
        self.assertFalse(any("inconsistent" in w for w in validate(full_plan(tasks=tasks), option="Strangler")))

    def test_unknown_criterion_ref(self):
        plan = full_plan(tasks=[task("T-1", criteria_refs=["AC-9"])] + full_plan().tasks[1:])
        self.assertTrue(any("'AC-9'" in w for w in validate(plan, criterion_ids=["AC-1"])))


class TestRenderPlan(unittest.TestCase):
    def test_renders_table_with_dependencies(self):
        out = _render_plan({**full_plan().model_dump(), "citation_warnings": []}, 16)
        self.assertIn("## 16. Implementation Plan", out)
        self.assertIn("| T-2 |", out)
        self.assertIn("T-1", out)
        self.assertNotIn("| Criteria |", out)

    def test_criteria_column_only_when_used(self):
        tasks = [task("T-1", criteria_refs=["AC-1"])]
        out = _render_plan({"tasks": [t.model_dump() for t in tasks], "not_addressed": []}, 16)
        self.assertIn("Criteria", out)
        self.assertIn("AC-1", out)

    def test_pipe_in_text_is_escaped(self):
        t = task("T-1", acceptance_check="a | b")
        out = _render_plan({"tasks": [t.model_dump()], "not_addressed": []}, 16)
        self.assertIn("a \\| b", out)

    def test_warnings_and_not_addressed_rendered(self):
        out = _render_plan(
            {"tasks": [], "not_addressed": ["tests.gap: later"], "citation_warnings": ["boom"]}, 16
        )
        self.assertIn("_No tasks generated._", out)
        self.assertIn("tests.gap: later", out)
        self.assertIn("- boom", out)


if __name__ == "__main__":
    unittest.main()
