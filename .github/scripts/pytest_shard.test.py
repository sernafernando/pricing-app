#!/usr/bin/env python3
"""Tests for pytest_shard.py. Run: python3 .github/scripts/pytest_shard.test.py"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "pytest_shard.py"
spec = importlib.util.spec_from_file_location("pytest_shard", SCRIPT)
shard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shard)


class SplitTest(unittest.TestCase):
    FILES: ClassVar[list[str]] = [f"tests/t{i:02d}/test_x.py" for i in range(40)]

    def test_every_file_lands_in_exactly_one_shard(self):
        durations = {f: float(i % 7 + 1) for i, f in enumerate(self.FILES[:25])}
        for n in (1, 2, 3, 5):
            buckets = shard.split(self.FILES, durations, n)
            flat = [f for b in buckets for f in b]
            self.assertEqual(sorted(flat), sorted(self.FILES), n)
            self.assertEqual(len(flat), len(set(flat)), n)

    def test_the_split_is_deterministic_and_order_independent(self):
        durations = {f: float(i) for i, f in enumerate(self.FILES[:30])}
        a = shard.split(self.FILES, durations, 3)
        b = shard.split(list(reversed(self.FILES)), dict(reversed(list(durations.items()))), 3)
        self.assertEqual(a, b)

    def test_known_durations_are_balanced(self):
        durations = {"tests/big.py": 100.0, "tests/a.py": 50.0, "tests/b.py": 50.0}
        buckets = shard.split(sorted(durations), durations, 2)
        self.assertEqual(buckets, [["tests/big.py"], ["tests/a.py", "tests/b.py"]])

    def test_unknown_files_spread_instead_of_piling_up(self):
        buckets = shard.split(self.FILES, {}, 3)
        self.assertTrue(all(len(b) >= 8 for b in buckets), [len(b) for b in buckets])


class CliTest(unittest.TestCase):
    def run_cli(self, cwd: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args], check=False, cwd=cwd, capture_output=True, text=True
        )

    def test_select_and_durations_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            for rel in ("tests/test_a.py", "tests/sub/test_b.py", "tests/sub/c_test.py", "tests/helper.py"):
                p = Path(d, rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("")
            Path(d, "junit.xml").write_text(
                "<testsuites><testsuite>"
                '<testcase classname="tests.test_a" name="t1" time="5.0"/>'
                '<testcase classname="tests.sub.test_b.TestK" name="t2" time="2.5"/>'
                '<testcase classname="tests.sub.test_b.TestK" name="t3" time="0.5"/>'
                "</testsuite></testsuites>"
            )
            out = self.run_cli(d, "durations", "junit.xml")
            self.assertEqual(out.returncode, 0, out.stderr)
            Path(d, "dur.json").write_text(out.stdout)
            self.assertIn('"tests/sub/test_b.py": 3.0', out.stdout)
            self.assertIn('"tests/test_a.py": 5.0', out.stdout)

            got = []
            for i in (1, 2):
                r = self.run_cli(d, "select", "--shards", "2", "--index", str(i), "--durations", "dur.json")
                self.assertEqual(r.returncode, 0, r.stderr)
                got += r.stdout.split()
            self.assertEqual(sorted(got), ["tests/sub/c_test.py", "tests/sub/test_b.py", "tests/test_a.py"])

            bad = self.run_cli(d, "select", "--shards", "2", "--index", "3", "--durations", "dur.json")
            self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    os.chdir(HERE)
    unittest.main(verbosity=1)
