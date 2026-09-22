"""Keep test inputs and outputs inside an explicitly labelled verification run."""
import os
import tempfile
import unittest
from pathlib import Path


class PreservedTestCase(unittest.TestCase):
    def setUp(self):
        run = os.environ.get("PLASMIDSAURUS_TEST_ROOT")
        if not run or not (Path(run) / "RUN.txt").is_file():
            raise RuntimeError("Set PLASMIDSAURUS_TEST_ROOT to a run directory containing RUN.txt; see SETUP.md")
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=run))
