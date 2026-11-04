#!/usr/bin/env python3
"""Check that every non-merge commit in a range has a DCO sign-off.

Usage:
    python scripts/check_dco.py --base origin/main
    python scripts/check_dco.py --base HEAD~2
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

SIGNOFF = re.compile(r"(?im)^Signed-off-by:\s+.+<[^>\s]+@[^>\s]+>\s*$")
SEPARATOR = "@@DCO-COMMIT@@"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="base revision, e.g. origin/main or a SHA")
    args = parser.parse_args()

    raw = git(
        "log",
        "--no-merges",
        f"--format=%H%n%B%n{SEPARATOR}",
        f"{args.base}..HEAD",
    )
    commits = [chunk.strip() for chunk in raw.split(SEPARATOR) if chunk.strip()]

    missing: list[str] = []
    for chunk in commits:
        lines = chunk.splitlines()
        if not lines:
            continue
        sha = lines[0].strip()
        body = "\n".join(lines[1:])
        if not SIGNOFF.search(body):
            subject = next((line.strip() for line in lines[1:] if line.strip()), "")
            missing.append(f"{sha[:12]} {subject}")

    if missing:
        print("DCO check failed: missing Signed-off-by trailer in:")
        for item in missing:
            print(f"- {item}")
        print("\nUse `git commit -s` (or amend with a Signed-off-by trailer).")
        return 1

    print(f"DCO check passed ({len(commits)} commit(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
