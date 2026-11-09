#!/usr/bin/env python3
"""Renders `tofu show <plan>` text of one unit (stdin) as a ```diff block: change markers
(+ - ~ -/+) move to column 0 so GitHub colours them, and helm_release `metadata.values`
(a jsonencode(...) diff of the whole values document, or "(known after apply)") is dropped.
"""

import re
import sys

RESOURCE = re.compile(r'resource "([a-z0-9_]+)" "')
META = re.compile(r"^\s+[-+~]? *metadata += [{]$")
VALUES = re.compile(r"^\s+[-+~]? *values += ")
MARKER = re.compile(r"^\s+(-/\+|\+/-|[-+~])\s")
CLOSER = re.compile(r"^\s*[\])}]")


def col(line: str) -> int:
    """1-based column of the first non-space character."""
    return len(line) - len(line.lstrip()) + 1


def shift(line: str) -> str:
    """'  + res' -> '+   res': marker to column 0, alignment kept."""
    if line.startswith(("-/+ ", "+/- ")):
        return "!  " + line[3:]
    if not MARKER.match(line):
        return line
    rest = line.lstrip()
    ind = line[: len(line) - len(rest)]
    mk = rest.split(None, 1)[0]
    c = mk if mk in "+-" and len(mk) == 1 else "!"
    return c + ind[1:] + " " * len(mk) + rest[len(mk) :]


def render(text: str) -> str:
    out = ["```diff"]
    rtype, meta_col, skip_col = "", 0, 0
    for line in text.split("\n"):
        if skip_col and line.startswith("  # "):
            skip_col = 0
        if skip_col:
            if col(line) == skip_col and CLOSER.match(line):
                skip_col = 0
            continue
        if m := RESOURCE.search(line):
            rtype = m.group(1)
        if rtype == "helm_release" and META.match(line):
            meta_col = line.index("metadata") + 1
        if rtype == "helm_release" and meta_col and VALUES.match(line):
            if line.endswith(("[", "{", "(")):
                skip_col = line.index("values") + 1
            continue
        if meta_col and col(line) == meta_col and re.match(r"^\s*}", line):
            meta_col = 0
        out.append(shift(line))
    out.append("```")
    return "\n".join(out)


if __name__ == "__main__":
    print(render(sys.stdin.read().rstrip("\n")))
