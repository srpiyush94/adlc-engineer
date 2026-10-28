import os
import re
import unittest

REQUIREMENTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt")
PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==\d+(\.\d+)*$")


class TestRequirementsPinned(unittest.TestCase):
    def test_every_requirement_is_pinned_exactly(self):
        with open(REQUIREMENTS, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
        self.assertTrue(lines)
        unpinned = [line for line in lines if not PINNED.match(line)]
        self.assertEqual(unpinned, [], "pin with name==x.y.z so deploys are reproducible")


if __name__ == "__main__":
    unittest.main()
