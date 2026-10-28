import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adlc_engineer import adr_writer

MODERNIZATION = {
    "recommended_option": "Modernize monolith",
    "adr": "Context: small. Decision: modernize. Consequences: simple.",
    "options": [
        {
            "name": "Modernize monolith", "cost": "Low", "risk": "Low", "complexity": "Low",
            "scalability": "Moderate", "recommendation": "Strongly Recommended",
            "reasoning": "tiny repo", "citations": ["languages.Python"],
        },
        {
            "name": "Strangler", "cost": "High", "risk": "High", "complexity": "High",
            "scalability": "High", "recommendation": "Not Recommended",
            "reasoning": "overkill", "citations": [],
        },
    ],
    "risks": ["No tests"],
    "migration_roadmap": ["Add tests", "Add Dockerfile"],
}

README = """# Architecture Decision Records

| ADR | Title | Status |
|---|---|---|
| [0001](0001-first.md) | First | Accepted |

Trailing text.
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def make_repo(tmp, readme=True, existing=("0001-first.md",)):
    adr_dir = os.path.join(tmp, "docs", "adr")
    os.makedirs(adr_dir)
    for name in existing:
        with open(os.path.join(adr_dir, name), "w") as f:
            f.write("original")
    if readme:
        with open(os.path.join(adr_dir, "README.md"), "w") as f:
            f.write(README)
    return adr_dir


class TestNumbering(unittest.TestCase):
    def test_first_adr_when_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(adr_writer.next_adr_number(os.path.join(tmp, "nope")), 1)

    def test_next_is_max_plus_one_ignoring_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = make_repo(tmp, existing=("0001-a.md", "0007-b.md", "notes.md"))
            self.assertEqual(adr_writer.next_adr_number(adr_dir), 8)

    def test_slugify(self):
        self.assertEqual(adr_writer.slugify("Adopt Modernize monolith!"), "adopt-modernize-monolith")
        self.assertEqual(adr_writer.slugify("!!!"), "decision")


class TestWriteAdr(unittest.TestCase):
    def test_creates_proposed_adr_and_index_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = make_repo(tmp)
            path, indexed = adr_writer.write_adr(tmp, MODERNIZATION, today="2026-10-28")
            self.assertTrue(indexed)
            self.assertEqual(os.path.basename(path), "0002-adopt-modernize-monolith.md")
            content = read(path)
            self.assertTrue(content.startswith("# ADR 0002: Adopt Modernize monolith"))
            self.assertIn("**Status:** Proposed", content)
            self.assertIn("**Date:** 2026-10-28", content)
            self.assertIn("Decision: modernize", content)
            readme = read(os.path.join(adr_dir, "README.md"))
            self.assertIn("| [0002](0002-adopt-modernize-monolith.md) | Adopt Modernize monolith | Proposed |", readme)
            self.assertLess(readme.index("[0001]"), readme.index("[0002]"))
            self.assertIn("Trailing text.", readme)

    def test_existing_adr_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = make_repo(tmp)
            adr_writer.write_adr(tmp, MODERNIZATION)
            self.assertEqual(read(os.path.join(adr_dir, "0001-first.md")), "original")

    def test_never_overwrites_a_colliding_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = make_repo(tmp)
            first, _ = adr_writer.write_adr(tmp, MODERNIZATION)
            with open(first, "w") as f:
                f.write("edited by a human")
            second, _ = adr_writer.write_adr(tmp, MODERNIZATION)
            self.assertNotEqual(first, second)
            self.assertEqual(read(first), "edited by a human")
            self.assertTrue(os.path.basename(second).startswith("0003-"))

    def test_creates_dir_and_skips_index_when_no_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, indexed = adr_writer.write_adr(tmp, MODERNIZATION)
            self.assertFalse(indexed)
            self.assertEqual(os.path.basename(path), "0001-adopt-modernize-monolith.md")
            self.assertFalse(os.path.exists(os.path.join(tmp, "docs", "adr", "README.md")))

    def test_readme_without_index_table_reports_not_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = make_repo(tmp, readme=False)
            with open(os.path.join(adr_dir, "README.md"), "w") as f:
                f.write("# ADRs\n\nNo table yet.\n")
            _, indexed = adr_writer.write_adr(tmp, MODERNIZATION)
            self.assertFalse(indexed)

    def test_pipe_in_title_does_not_break_index_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            adr_dir = make_repo(tmp)
            adr_writer.write_adr(tmp, {**MODERNIZATION, "recommended_option": "A | B"})
            self.assertIn("Adopt A \\| B | Proposed |", read(os.path.join(adr_dir, "README.md")))


class TestRenderAdr(unittest.TestCase):
    def render(self, **kw):
        return adr_writer.render_adr(3, "Adopt Modernize monolith", MODERNIZATION, "2026-10-28", **kw)

    def test_follows_repo_adr_section_order(self):
        content = self.render()
        order = ["## Context", "## Decision Drivers", "## Options Considered", "## Decision\n",
                 "## Consequences", "## Follow-up Actions"]
        positions = [content.index(h) for h in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("### A. Modernize monolith — Strongly Recommended", content)
        self.assertIn("### B. Strangler — Not Recommended", content)
        self.assertIn("- [ ] Add tests", content)
        self.assertIn("- No tests", content)

    def test_no_challenger_note_by_default(self):
        self.assertNotIn("Challenger", self.render())

    def test_challenger_objection_is_flagged(self):
        content = self.render(challenger={"has_objections": True, "objecting_personas": ["Security", "Cost"]})
        self.assertIn("Challenger raised objections (Security, Cost)", content)

    def test_challenger_without_objections_adds_no_note(self):
        self.assertNotIn("Challenger", self.render(challenger={"has_objections": False, "objecting_personas": []}))


if __name__ == "__main__":
    unittest.main()
