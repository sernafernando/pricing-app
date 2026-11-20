#!/usr/bin/env python3
"""Deterministic file-level split of backend/tests into CI shards.

Two subcommands, both run from `backend/`:

  select --shards N --index I --durations FILE
      Prints the test files of shard I (1-based), one per line. Every shard
      job runs this over the same checkout and the same durations file, so
      the shards agree on the split without talking to each other: each test
      file lands in exactly one shard.

  durations JUNIT.xml [JUNIT.xml ...]
      Prints a durations file (JSON: test file -> seconds) built from the
      JUnit reports a CI run uploads (`junit-postgres*` artifacts). Refresh
      the committed file with it when the shards drift out of balance.

Balance: files with a known duration are placed largest first, each onto
the currently lightest shard (ties go to the lowest index). Files without
one (new files, or files with no test of this job's marker) are spread by
a stable hash of their path, so they cannot pile up on one shard. Neither
step looks at the clock, the runner or the environment: the same inputs
always give the same split.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TESTS_ROOT = Path("tests")


def discover(root: Path = TESTS_ROOT) -> list[str]:
    """Every file pytest collects by default under `root`, sorted."""
    files = {p for p in root.rglob("test_*.py")} | {p for p in root.rglob("*_test.py")}
    return sorted(p.as_posix() for p in files if p.is_file())


def split(files: list[str], durations: dict[str, float], shards: int) -> list[list[str]]:
    """Assigns every file to exactly one of `shards` buckets."""
    buckets: list[list[str]] = [[] for _ in range(shards)]
    loads = [0.0] * shards
    known = sorted((f for f in files if f in durations), key=lambda f: (-durations[f], f))
    for f in known:
        i = min(range(shards), key=lambda k: (loads[k], k))
        buckets[i].append(f)
        loads[i] += durations[f]
    for f in files:
        if f not in durations:
            digest = hashlib.sha256(f.encode()).hexdigest()
            buckets[int(digest, 16) % shards].append(f)
    return [sorted(b) for b in buckets]


def file_for(classname: str, root: Path = TESTS_ROOT.parent) -> str | None:
    """`tests.a.test_b.TestC` -> `tests/a/test_b.py` (strips class names)."""
    parts = classname.split(".")
    while parts:
        candidate = root / Path(*parts).with_suffix(".py")
        if candidate.is_file():
            return Path(*parts).with_suffix(".py").as_posix()
        parts.pop()
    return None


def durations_from_junit(paths: list[str]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for path in paths:
        for case in ET.parse(path).getroot().iter("testcase"):
            f = file_for(case.get("classname", ""))
            if f is not None:
                totals[f] = totals.get(f, 0.0) + float(case.get("time") or 0)
    return {f: round(t, 2) for f, t in sorted(totals.items())}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sel = sub.add_parser("select")
    sel.add_argument("--shards", type=int, required=True)
    sel.add_argument("--index", type=int, required=True)
    sel.add_argument("--durations", required=True)
    dur = sub.add_parser("durations")
    dur.add_argument("junit", nargs="+")
    args = parser.parse_args(argv)

    if args.cmd == "durations":
        json.dump(durations_from_junit(args.junit), sys.stdout, indent=1)
        sys.stdout.write("\n")
        return 0

    if not 1 <= args.index <= args.shards:
        parser.error(f"--index must be in 1..{args.shards}")
    durations = json.loads(Path(args.durations).read_text())
    files = discover()
    if not files:
        print(f"no test files under {TESTS_ROOT}/", file=sys.stderr)
        return 1
    buckets = split(files, durations, args.shards)
    mine = buckets[args.index - 1]
    est = sum(durations.get(f, 0.0) for f in mine)
    print(
        f"shard {args.index}/{args.shards}: {len(mine)} of {len(files)} files, ~{est:.0f} worker-s by the durations file",
        file=sys.stderr,
    )
    print("\n".join(mine))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
