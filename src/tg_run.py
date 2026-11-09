#!/usr/bin/env python3
"""Runs `terragrunt plan` or `apply` (env CMD) in the current unit directory.

Raw output -> /tmp/raw.txt, filtered output (for the PR comment) -> /tmp/out.txt.
Exits with terragrunt's exit code, after the output files are written.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# --log-level error + --tf-forward-stdout: raw tofu output only, no
# terragrunt INFO lines and no `tofu:` prefix.
QUIET = [
    "--no-color",
    "--log-level",
    "error",
    "--tf-forward-stdout",
    "--non-interactive",
]

PREAMBLE = re.compile(
    r'You may now begin|Try running "|for your infrastructure\.|should now work\.'
    r"|If you ever set or change|rerun this command to reinitialize"
    r"|commands will detect it and remind"
)
CHATTER = re.compile(
    r": (Refreshing state\.\.\.|Reading\.\.\.|Read complete |Still (reading|creating|modifying|destroying))"
)


def strip_output(text: str) -> str:
    """Drops the auto-init preamble and per-resource refresh chatter, so a PR comment
    shows only the plan/apply itself."""
    out, seen, body = [], False, False
    for line in text.split("\n"):
        if not seen:
            seen = "successfully initialized" in line
            continue
        if not body and (PREAMBLE.search(line) or not line.strip()):
            continue
        if CHATTER.search(line):
            continue
        body = True
        out.append(line)
    return "\n".join(out)


def main() -> int:
    if os.environ.get("CMD") == "apply":
        args = ["apply", *QUIET, "-auto-approve"]
    else:
        args = ["plan", *QUIET, "-lock=false", "-out=tf.plan"]
    # a failed run still gets its output files written, so the error reaches the PR
    p = subprocess.Popen(
        ["terragrunt", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    with open("/tmp/raw.txt", "w") as raw:
        for line in p.stdout:
            sys.stdout.write(line)
            raw.write(line)
    rc = p.wait()
    text = Path("/tmp/raw.txt").read_text()
    Path("/tmp/out.txt").write_text(strip_output(text) or text)
    return rc


if __name__ == "__main__":
    sys.exit(main())
